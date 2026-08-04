import os
import asyncio
from playwright.async_api import async_playwright
import json
import logging
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote, quote
from database import DatabaseManager
from email_validator import validate_email, EmailNotValidError
import phonenumbers
from country_data import ALL_CCTLD_MAP, COUNTRY_NAME_MAP, infer_country_code, format_and_validate_phone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DeepCrawler:
    def __init__(self, browser):
        self.browser = browser
        self.junk_patterns = [
            r'sentry.*\.io', r'wixpress\.com', r'example\.com', r'domain\.com', r'yourdomain\.com',
            r'mysite\.com', r'schema\.org', r'bootstrap', r'jquery', r'wordpress', r'github', r'gravatar',
            r'\.png$', r'\.jpg$', r'\.jpeg$', r'\.gif$', r'\.svg$', r'\.webp$', r'2x-',
            r'noreply', r'no-reply', r'donotreply', r'^test@', r'^demo@', r'^user@', r'^you@',
            r'^youremail@', r'^name@', r'settlement', r'facebook\.com', r'instagram\.com',
            r'developers\.facebook', r'privacy', r'policy', r'terms'
        ]

    def _is_valid_email(self, email):
        """Validate email syntax with email-validator and filter out placeholder/dummy emails."""
        if not email or not isinstance(email, str):
            return False
        email = email.lower().strip().rstrip('.')

        # 1. RFC syntax validation via email-validator library
        try:
            valid = validate_email(email, check_deliverability=False)
            email = valid.normalized
        except EmailNotValidError:
            return False

        # 2. Length check & obfuscated hash emails (e.g. Sentry/Wix hashes)
        if len(email) >= 60 or len(re.findall(r'[0-9]{5,}', email)) >= 2:
            return False

        # 3. Check for image/media extensions mistakenly captured as emails
        if re.search(r'\.(png|jpg|jpeg|gif|svg|webp|pdf|css|js|woff|ttf|eot)$', email, re.I):
            return False

        # 4. Check dummy domains
        try:
            local_part, domain_part = email.split('@', 1)
        except ValueError:
            return False

        dummy_domains = {
            'example.com', 'example.org', 'example.net', 'mysite.com', 'yourdomain.com',
            'domain.com', 'sample.com', 'placeholder.com', 'test.com', 'email.com',
            'site.com', 'sentry.io', 'wixpress.com', 'schema.org', 'bootstrap.com',
            'jquery.com', 'gravatar.com', 'wordpress.org', 'wordpress.com'
        }
        if domain_part in dummy_domains or any(domain_part.endswith('.' + d) for d in dummy_domains):
            return False

        # 5. Check dummy usernames
        dummy_users = {
            'demo', 'test', 'user', 'you', 'yourname', 'username',
            'noreply', 'no-reply', 'donotreply', 'sample', 'placeholder'
        }
        if local_part in dummy_users:
            return False

        # 6. Check regex junk patterns
        if any(re.search(jp, email) for jp in self.junk_patterns):
            return False

        return True

    async def crawl_site(self, base_url, stop_event=None, address=None, query=None):
        found_contacts = []
        found_emails = set()
        found_phones = set()
        socials = {}
        
        if stop_event and stop_event.is_set():
            return found_contacts, found_emails, found_phones, socials

        page = None
        try:
            # 1. Discover key URLs & load homepage
            page = await self.browser.new_page()
            await page.goto(base_url, timeout=20000, wait_until="domcontentloaded")
            
            # Wait for network idle or fallback delay for SPA/dynamic JavaScript rendering
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            await asyncio.sleep(1)

            # Scroll home page to trigger lazy loading
            await self._scroll_page(page)
            resolved_url = page.url
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            found_emails.update(self._extract_emails(content, soup))
            found_phones.update(self._extract_phones(soup.get_text(), soup, site_url=resolved_url, address=address, query=query))
            socials = self._extract_socials(soup, resolved_url, raw_html=content)
            found_contacts.extend(self._extract_team_members(soup, resolved_url, address=address, query=query))

            # Discover internal contact/about URLs & social links
            urls_to_crawl = {resolved_url}
            for a in soup.find_all('a', href=True):
                href = a['href']
                abs_url = urljoin(resolved_url, href)
                if urlparse(abs_url).netloc == urlparse(resolved_url).netloc:
                    if any(x in href.lower() for x in ['about', 'team', 'staff', 'people', 'leadership', 'contact', 'careers']):
                        urls_to_crawl.add(abs_url)
                elif any(x in abs_url.lower() for x in ['facebook.com', 'instagram.com', 'linkedin.com', 'twitter.com', 'youtube.com', 'tiktok.com', 'pinterest.com']):
                    socials.update(self._extract_socials(BeautifulSoup(f'<a href="{abs_url}"></a>', 'html.parser'), resolved_url, raw_html=abs_url))
            
            await page.close()
            page = None # Prevent double close

            # 2. Crawl key internal discovery URLs (limit to 2 most relevant: contact/about)
            sub_candidates = [
                u for u in urls_to_crawl if u != resolved_url and any(k in u.lower() for k in ['contact', 'about', 'team'])
            ]
            for url in sub_candidates[:2]:
                if stop_event and stop_event.is_set(): break
                sub_page = None
                try:
                    sub_page = await self.browser.new_page()
                    await sub_page.goto(url, timeout=8000, wait_until="domcontentloaded")
                    await asyncio.sleep(0.3)
                    await self._scroll_page(sub_page)
                    
                    html = await sub_page.content()
                    page_soup = BeautifulSoup(html, 'html.parser')
                    
                    found_emails.update(self._extract_emails(html, page_soup))
                    found_phones.update(self._extract_phones(page_soup.get_text(), page_soup, site_url=url, address=address, query=query))
                    socials.update(self._extract_socials(page_soup, url, raw_html=html))
                    found_contacts.extend(self._extract_team_members(page_soup, url, address=address, query=query))
                except Exception as e:
                    logger.debug(f"Subpage crawl note for {url}: {e}")
                finally:
                    if sub_page: await sub_page.close()

        except Exception as e:
            logger.warning(f"Crawling issue for {base_url}: {e}")
        finally:
            if page: await page.close()
            
        return found_contacts, found_emails, found_phones, socials

    async def _scroll_page(self, page):
        """Fast scroll down the page to trigger lazy loading."""
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2);")
            await asyncio.sleep(0.2)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            await asyncio.sleep(0.3)
        except Exception:
            pass

    def _clean_social_link(self, link):
        if not link or link == "N/A":
            return "N/A"
        # Unescape Facebook/Instagram tracking redirect URLs
        if "facebook.com/l.php?u=" in link or "l.facebook.com" in link:
            match = re.search(r'[?&]u=([^&]+)', link)
            if match:
                link = unquote(match.group(1))
        # Remove developer/doc links
        if "developers.facebook.com" in link:
            return "N/A"
        return link.strip()

    def _extract_socials(self, soup, base_url, raw_html=None):
        socials = {}
        platforms = {
            'facebook': [r'facebook\.com/(?:[a-zA-Z0-9_\-\.]+)', r'fb\.com'],
            'instagram': [r'instagram\.com/(?:[a-zA-Z0-9_\-\.]+)'],
            'linkedin': [r'linkedin\.com/(?:company|in|pub)/(?:[a-zA-Z0-9_\-\.]+)'],
            'twitter': [r'twitter\.com/(?:[a-zA-Z0-9_\-\.]+)', r'x\.com/(?:[a-zA-Z0-9_\-\.]+)'],
            'youtube': [r'youtube\.com/(?:c/|user/|channel/|@)?(?:[a-zA-Z0-9_\-\.]+)'],
            'tiktok': [r'tiktok\.com/@(?:[a-zA-Z0-9_\-\.]+)'],
            'pinterest': [r'pinterest\.com/(?:[a-zA-Z0-9_\-\.]+)', r'pin\.it']
        }
        
        # 1. Inspect <a> href tags
        if soup:
            for a in soup.find_all('a', href=True):
                href = a['href']
                abs_url = urljoin(base_url, href)
                for platform, patterns in platforms.items():
                    if platform not in socials:
                        if any(re.search(pat, abs_url, re.I) for pat in patterns):
                            cleaned = self._clean_social_link(abs_url)
                            if cleaned != "N/A":
                                socials[platform] = cleaned

            # 2. Inspect meta tags & JSON-LD scripts (sameAs)
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string or '')
                    same_as = []
                    if isinstance(data, dict):
                        sa = data.get('sameAs')
                        if isinstance(sa, list): same_as.extend(sa)
                        elif isinstance(sa, str): same_as.append(sa)
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                sa = item.get('sameAs')
                                if isinstance(sa, list): same_as.extend(sa)
                                elif isinstance(sa, str): same_as.append(sa)

                    for s_url in same_as:
                        if isinstance(s_url, str):
                            for platform, patterns in platforms.items():
                                if platform not in socials:
                                    if any(re.search(pat, s_url, re.I) for pat in patterns):
                                        cleaned = self._clean_social_link(s_url)
                                        if cleaned != "N/A":
                                            socials[platform] = cleaned
                except Exception:
                    pass

        # 3. Fallback raw HTML regex matching
        if raw_html:
            for platform, patterns in platforms.items():
                if platform not in socials:
                    for pat in patterns:
                        match = re.search(r'https?://(?:www\.)?' + pat, raw_html, re.I)
                        if match:
                            cleaned = self._clean_social_link(match.group(0))
                            if cleaned != "N/A":
                                socials[platform] = cleaned
                                break

        return socials

    def _clean_text(self, text):
        if not text or text == "N/A":
            return "N/A"
        # Flatten multiline whitespace and clean quotes
        cleaned = re.sub(r'\s+', ' ', text).strip()
        return cleaned if cleaned else "N/A"

    def _extract_emails(self, html, soup=None):
        extracted = set()

        # 1. Extract mailto: hrefs if BeautifulSoup soup provided
        if soup:
            for a in soup.find_all('a', href=re.compile(r'^mailto:', re.I)):
                href = a['href']
                email_part = href.split('mailto:')[-1].split('?')[0].strip()
                if self._is_valid_email(email_part):
                    extracted.add(email_part.lower())

        # 2. Extract JSON-LD script emails
        if soup:
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string or '')
                    if isinstance(data, dict):
                        em = data.get('email')
                        if em and isinstance(em, str) and self._is_valid_email(em):
                            extracted.add(em.lower())
                except Exception:
                    pass

        # 3. Unobfuscate [at] and (at) patterns
        unobfuscated_html = re.sub(r'\[at\]|\(at\)|\s+at\s+', '@', html, flags=re.I)
        unobfuscated_html = re.sub(r'\[dot\]|\(dot\)|\s+dot\s+', '.', unobfuscated_html, flags=re.I)

        # 4. Standard regex extraction
        matches = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', unobfuscated_html)
        for m in matches:
            if self._is_valid_email(m):
                extracted.add(m.lower())

        return list(extracted)

    def _extract_phones(self, text, soup=None, site_url=None, address=None, query=None):
        extracted = set()
        raw_candidates = set()

        # 1. Extract tel: hrefs if BeautifulSoup soup provided
        if soup:
            for a in soup.find_all('a', href=re.compile(r'^tel:', re.I)):
                href = a['href']
                phone_part = href.split('tel:')[-1].split('?')[0].strip()
                phone_part = re.sub(r'\s+', ' ', phone_part).strip()
                if phone_part:
                    raw_candidates.add(phone_part)

        # 2. Extract JSON-LD script telephones
        if soup:
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string or '')
                    if isinstance(data, dict):
                        ph = data.get('telephone')
                        if ph and isinstance(ph, str):
                            raw_candidates.add(ph.strip())
                except Exception:
                    pass

        # 3. Plain text regex matches
        if text:
            text_clean = re.sub(r'\s+', ' ', text)
            phone_matches = re.findall(r'\+?[0-9][0-9\s.-]{8,15}', text_clean)
            for p in phone_matches:
                p_clean = re.sub(r'\s+', ' ', p).strip()
                if p_clean:
                    raw_candidates.add(p_clean)

        for candidate in raw_candidates:
            validated = format_and_validate_phone(candidate, site_url=site_url, address=address, query=query)
            if validated:
                extracted.add(validated)

        return extracted

    def _extract_team_members(self, soup, url, address=None, query=None):
        members = []
        invalid_names = {
            'our team', 'meet the team', 'about us', 'contact us', 'read more', 
            'book appointment', 'home', 'services', 'dental clinic', 'emergency dentist',
            'opening hours', 'cookie policy', 'privacy policy', 'terms conditions'
        }
        
        person_containers = soup.find_all(['div', 'article', 'section', 'li'], 
                                         class_=re.compile(r'member|team|person|staff|leadership|profile|employee', re.I))
        
        for container in person_containers:
            name_el = container.find(['h2', 'h3', 'h4', 'h5', 'strong', 'span'], 
                                     class_=re.compile(r'name|title|header', re.I))
            if not name_el:
                text = container.get_text(separator=' ').strip()
                name_match = re.search(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', text)
                name = name_match.group(1) if name_match else None
            else:
                name = name_el.get_text().strip()

            if name and len(name.split()) >= 2 and len(name) < 40:
                if name.lower() in invalid_names:
                    continue

                role_el = container.find(['p', 'span', 'div'], class_=re.compile(r'role|position|job|desc', re.I))
                role = role_el.get_text().strip() if role_el else "N/A"
                
                # Check for LinkedIn
                linkedin_el = container.find('a', href=re.compile(r'linkedin\.com', re.I))
                linkedin = linkedin_el['href'] if linkedin_el else "N/A"
                
                # Check for direct email/phone in container
                email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', container.get_text())
                email = email_match.group(0) if email_match and self._is_valid_email(email_match.group(0)) else "N/A"
                
                phone_match = re.search(r'\+?[0-9][0-9\s.-]{8,15}', container.get_text())
                phone_val = format_and_validate_phone(phone_match.group(0), site_url=url, address=address, query=query) if phone_match else None
                phone = phone_val if phone_val else "N/A"

                # Require at least one valid detail or meaningful role
                if email != "N/A" or phone != "N/A" or linkedin != "N/A" or (role != "N/A" and len(role) < 50):
                    members.append({
                        "name": name,
                        "role": role,
                        "email": email,
                        "phone": phone,
                        "linkedin": linkedin
                    })
        
        # Deduplicate members by name
        seen_names = set()
        unique_members = []
        for m in members:
            if m["name"].lower() not in seen_names:
                seen_names.add(m["name"].lower())
                unique_members.append(m)
        return unique_members[:8]

def ensure_playwright_browsers():
    """Ensure Playwright Chromium browser binary is downloaded and installed."""
    import subprocess
    import sys
    import os
    
    logger.info("Verifying/Installing Playwright Chromium browser binaries...")

    # Clear PLAYWRIGHT_BROWSERS_PATH if it points to a non-existent or empty bundle dir
    pb_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if pb_path and (not os.path.exists(pb_path) or not any("chromium" in d for d in os.listdir(pb_path) if os.path.isdir(pb_path))):
        os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    
    # Method 1: PyInstaller bundled driver + package/cli.js
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        driver_executable, _ = compute_driver_executable()
        cli_js = os.path.join(os.path.dirname(driver_executable), "package", "cli.js")
        env = get_driver_env()
        if os.path.exists(driver_executable) and os.path.exists(cli_js):
            res = subprocess.run([driver_executable, cli_js, "install", "chromium"], env=env, check=False, capture_output=True, text=True)
            if res.returncode == 0:
                logger.info("Playwright Chromium browser installed successfully via bundled driver.")
                return True
    except Exception as e:
        logger.warning(f"Bundled driver install error: {e}")

    # Method 2: sys.executable -m playwright install chromium
    try:
        res = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False, capture_output=True, text=True)
        if res.returncode == 0:
            logger.info("Playwright Chromium browser is ready.")
            return True
    except Exception:
        pass

    # Method 3: System npx / playwright CLI fallback
    for cmd in [["npx", "playwright", "install", "chromium"], ["playwright", "install", "chromium"]]:
        try:
            res = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if res.returncode == 0:
                logger.info("Playwright Chromium browser installed via system CLI.")
                return True
        except Exception:
            pass

    return False

import gc
import random
from urllib.parse import urlparse

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
]

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: { OnInstalledReason: {}, OnRestartRequiredReason: {} } };
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Google Inc. (NVIDIA)';
    if (parameter === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)';
    return getParameter.apply(this, [parameter]);
};
"""

# Hardcoded High-Quality Fallback Proxies from ProxyScrape API
HARDCODED_FALLBACK_PROXIES = [
    "http://34.130.92.118:443",
    "http://195.26.224.135:80",
    "http://45.155.226.177:3128",
    "http://59.66.22.107:7898",
    "http://160.238.65.9:3128",
    "http://219.249.37.107:8380",
    "http://109.120.133.180:1443",
    "http://47.81.56.193:8888",
    "http://34.140.137.151:80",
    "http://119.188.131.55:17981",
    "http://77.239.112.19:35000",
    "http://103.15.222.192:10327",
    "http://159.65.245.255:80",
    "http://47.76.226.125:8118",
    "http://149.18.81.114:7890",
    "http://212.47.232.28:80",
    "http://89.207.72.188:8083",
    "http://34.162.25.75:443",
    "http://92.39.129.50:1256",
    "http://43.252.106.147:8080",
    "http://5.189.159.180:80",
    "http://183.110.216.128:8090",
    "http://66.163.119.55:10006",
    "http://123.138.24.113:9480",
    "http://149.86.151.202:8085",
    "http://122.246.3.210:17981",
    "http://114.236.137.41:21000",
    "http://219.65.73.80:80",
    "http://216.106.179.216:49503",
    "http://58.254.153.147:17981",
    "http://217.154.70.86:7777",
    "http://190.153.122.3:999",
    "http://129.226.127.245:18080",
    "http://185.125.18.5:3128",
    "http://20.210.76.175:8561",
    "http://65.109.65.238:28080",
    "http://38.76.9.0:999",
    "http://14.225.240.23:8562",
    "http://34.124.190.108:8080",
    "http://166.1.18.72:28015",
    "http://93.123.16.14:80",
    "http://45.26.30.144:8888",
    "http://147.78.0.81:9443",
    "http://8.219.97.248:80",
    "http://195.133.14.222:49152",
    "http://216.106.179.216:49380",
    "http://103.61.16.20:8780",
    "http://152.230.215.123:80",
    "http://103.111.225.210:9155",
    "http://46.203.233.116:3128",
    "http://175.143.76.177:8181",
    "http://85.214.107.177:80",
    "http://34.94.46.8:80",
    "http://102.132.201.202:80",
    "http://212.231.191.23:80",
    "http://200.8.121.121:8080",
    "http://45.146.163.31:80",
    "http://103.176.174.100:8080",
    "http://103.169.132.34:3128",
    "http://38.49.133.226:999",
    "http://113.249.102.192:18255",
    "http://167.99.124.118:80",
    "http://43.133.128.153:16012",
    "http://45.133.251.223:3128",
    "http://36.50.56.209:8818",
    "http://38.172.170.80:999",
    "http://143.198.85.218:3128",
    "http://103.156.17.158:8818",
    "http://219.93.101.63:80",
    "http://103.172.42.105:1111",
    "http://5.45.126.128:8080",
    "http://91.142.75.202:1080",
    "http://103.43.17.143:11111",
    "http://47.89.184.18:3128",
    "http://87.251.74.124:3128",
    "http://123.138.24.114:8800",
    "http://103.173.141.9:8080",
    "http://159.196.182.72:8080",
    "http://188.165.199.207:80",
    "http://103.88.91.14:8080",
    "http://104.129.192.156:11766",
    "http://103.158.97.83:8080",
    "http://212.68.59.254:8080",
    "http://143.208.84.57:8589",
    "http://195.87.182.10:9090",
    "http://186.250.202.104:8080",
    "http://36.91.148.36:8080",
    "http://187.190.58.152:80",
    "http://103.184.98.15:1991",
    "http://112.198.132.34:8082",
    "http://103.43.191.71:8888",
    "http://103.172.42.193:1111",
    "http://31.28.4.192:80",
    "http://114.111.19.228:3389",
    "http://144.31.75.120:11112",
    "http://179.60.191.19:8080",
    "http://101.66.194.115:8085",
    "http://38.75.82.42:999",
    "http://131.222.247.253:8080",
    "http://190.97.239.22:999",
    "http://103.1.224.34:18080",
    "http://123.138.24.113:9443",
    "http://102.68.135.147:8080",
    "http://217.177.33.53:3128",
    "http://102.38.7.110:1972",
    "http://159.194.228.40:8888",
    "http://113.160.132.26:8080",
    "http://188.129.8.242:81",
    "http://34.84.162.206:38080",
    "http://205.209.64.21:8080",
    "http://103.172.42.93:1111",
    "http://160.238.65.4:3128",
    "http://185.68.184.235:3128",
    "http://38.210.179.115:999",
    "http://61.186.243.6:9002",
    "http://153.80.240.37:8080",
    "http://222.252.14.70:8443",
    "http://85.234.100.149:1080",
    "http://203.177.139.11:8082",
    "http://174.137.134.182:2999",
    "http://103.151.17.201:8080",
    "http://103.15.222.192:10006",
    "http://104.154.186.48:80",
    "http://185.205.210.154:8095",
    "http://123.138.24.112:8800",
    "http://138.121.15.230:999",
    "http://190.142.231.46:999",
    "http://85.234.100.149:8080",
    "http://174.138.119.88:80",
    "http://135.87.39.23:443",
    "http://97.74.87.226:80",
    "http://41.209.14.123:8080",
    "http://103.3.59.208:8080",
    "http://176.111.37.5:39811",
    "http://190.14.240.133:999",
    "http://157.173.123.247:3128",
    "http://219.249.37.107:8382",
    "http://117.50.194.130:7890",
    "http://103.171.161.96:9090",
    "http://31.57.178.255:8181",
    "http://181.119.84.218:8080",
    "http://108.170.12.12:80",
    "http://113.249.102.27:18255",
    "http://175.29.125.242:8080",
    "http://103.210.35.182:8080",
    "http://160.238.65.5:3128",
    "http://191.102.107.235:999",
    "http://20.83.140.251:8080",
    "http://45.167.126.42:999",
    "http://103.69.96.15:9999",
    "http://181.204.81.179:999",
    "http://202.165.232.238:8080",
    "http://46.209.15.187:8080",
    "http://186.96.160.220:999",
    "http://64.227.123.197:3128",
    "http://182.160.124.83:50000",
    "http://103.46.8.85:8080",
    "http://220.154.128.91:21033",
    "http://103.178.42.23:8181",
    "http://167.249.29.218:999",
    "http://173.254.204.118:7890",
    "http://154.19.39.151:8090",
    "http://154.113.18.189:9779",
    "http://109.107.181.73:12198",
    "http://43.252.236.158:8080",
    "http://95.111.194.14:6045",
    "http://144.31.207.192:8888",
    "http://165.16.46.215:8080",
    "http://185.135.99.14:8080",
    "http://103.228.171.47:8118",
    "http://43.132.189.30:3128",
    "http://97.76.251.138:8080",
    "http://14.238.8.63:9090",
    "http://170.81.102.163:6666",
    "http://112.198.138.14:8082",
    "http://45.174.108.141:999",
    "http://103.186.193.135:8080",
    "http://103.189.249.196:1111",
    "http://177.184.195.168:8080",
    "http://103.178.23.6:8080",
    "http://45.70.236.194:999",
    "http://153.72.68.0:8080",
    "http://38.211.24.242:8080",
    "http://94.102.193.91:8080",
    "http://160.25.56.58:3125",
    "http://34.134.231.117:3129",
    "http://23.228.86.236:8081",
    "http://95.3.69.222:8080",
    "http://47.251.87.74:9098",
    "http://185.82.238.42:8888",
    "http://144.124.227.88:3128",
    "http://61.49.87.3:80",
    "http://195.133.2.113:3128",
    "http://103.13.192.76:8080",
    "http://175.136.239.174:8181",
    "http://192.236.242.201:2055",
    "http://103.149.42.14:3125",
    "http://8.213.128.6:9090",
    "http://178.212.144.7:80",
    "http://119.93.153.250:8082",
    "http://103.71.162.17:8080",
    "http://186.33.5.13:8080",
    "http://194.135.81.158:3128",
    "http://102.213.179.210:8080",
    "http://54.39.28.106:8082",
    "http://5.188.190.218:80",
    "http://91.98.86.26:8888",
    "http://43.255.159.94:3129",
    "http://181.209.122.115:999",
    "http://23.27.143.117:3080",
    "http://103.163.231.106:3127",
    "http://202.162.195.157:8080",
    "http://104.129.192.156:10121",
    "http://41.33.203.238:1975",
    "http://8.215.112.214:7777",
    "http://103.237.102.191:11111",
    "http://103.167.171.149:7778",
    "http://103.162.54.182:8090",
    "http://24.152.58.22:999",
    "http://176.88.166.163:8080",
    "http://46.39.252.111:8080",
    "http://181.119.111.59:999",
    "http://135.87.39.23:9443",
    "http://219.93.101.62:80",
    "http://181.191.14.5:8080",
    "http://104.129.192.156:10525",
    "http://43.229.254.221:8181",
    "http://182.160.114.106:12331",
    "http://103.162.16.45:8080",
    "http://202.182.96.178:10087",
    "http://27.185.218.213:17981",
    "http://108.170.12.10:80",
    "http://104.129.192.156:10174",
    "http://62.171.168.211:3128",
    "http://181.233.100.101:8080",
    "http://103.188.33.74:8085",
    "http://103.157.79.154:1818",
    "http://15.204.35.6:30017",
    "http://103.155.246.42:8080",
    "http://101.255.208.18:8090",
    "http://177.234.211.79:999",
    "http://125.209.110.83:39617",
    "http://38.51.221.17:999",
    "http://122.246.4.6:17981",
    "http://31.131.248.48:3129",
    "http://103.166.158.41:1080",
    "http://143.198.135.176:80",
    "http://103.156.75.41:8080",
    "socks4://116.203.19.71:9099",
    "socks5://94.19.248.31:1080",
    "socks5://195.201.111.97:12001",
    "socks5://3.129.27.9:17000",
    "socks4://189.202.204.53:1080",
    "socks5://144.24.47.42:1080",
    "socks5://130.49.187.61:1082",
    "socks4://89.237.33.126:51549",
    "socks4://37.193.125.68:1090",
    "socks5://212.77.75.25:1088",
    "socks5://117.50.194.130:7890",
    "socks4://68.71.247.130:4145",
    "socks5://184.182.240.12:4145",
    "socks5://216.22.13.244:1083",
    "socks4://139.28.240.202:1082",
    "socks4://176.88.166.190:5678",
    "socks5://213.199.47.140:1080",
    "socks4://47.239.140.6:80",
    "socks5://103.195.191.39:10800",
    "socks4://178.130.47.50:1082",
    "socks4://178.253.23.193:1080",
    "socks4://147.45.60.139:1082",
    "socks5://194.163.174.78:1082",
    "socks5://192.252.215.2:4145",
    "socks4://157.90.113.23:9052",
    "socks5://101.2.166.73:1080",
    "socks5://83.147.216.208:1080",
    "socks5://178.128.59.180:40001",
    "socks5://5.255.117.250:1080",
    "socks5://72.207.113.97:4145",
    "socks4://103.1.224.34:18080",
    "socks5://47.245.165.201:1080",
    "socks4://61.191.119.134:10800",
    "socks5://123.58.219.171:10808",
    "socks5://23.27.141.243:3080",
    "socks5://67.201.58.190:4145",
    "socks5://193.233.218.213:1080",
    "socks5://141.98.85.49:1080",
    "socks5://47.250.115.134:1080",
    "socks4://190.18.170.230:5678",
    "socks4://103.153.247.74:12",
    "socks5://203.25.208.163:1515",
    "socks4://125.26.4.197:4145",
    "socks4://103.81.114.182:4145",
    "socks4://192.111.139.163:19404",
    "socks5://103.118.85.146:1080",
    "socks4://78.31.93.76:1080",
    "socks5://184.181.217.206:4145",
    "socks5://117.175.168.195:1080",
    "socks4://78.111.112.118:4145",
    "socks4://184.182.240.211:4145",
    "socks4://69.55.49.177:38182",
    "socks5://199.66.182.243:4145",
    "socks5://174.77.111.197:4145",
    "socks4://185.190.90.2:4145",
    "socks4://149.62.186.244:1080",
    "socks5://147.45.60.124:1082",
    "socks5://103.191.218.119:69",
    "socks4://101.255.150.238:1080",
    "socks5://176.192.41.172:4444",
    "socks5://88.99.82.67:443",
    "socks5://119.28.13.138:1080",
    "socks5://202.79.26.242:1080",
    "socks5://208.102.51.6:58208",
    "socks4://116.203.19.71:9092",
    "socks5://123.0.24.154:9090",
    "socks5://144.91.121.61:1088",
    "socks4://1.179.172.45:31225",
    "socks4://105.30.248.241:1080",
    "socks4://195.201.111.97:12001",
    "socks4://144.31.11.24:4500",
    "socks4://81.18.90.43:4153",
    "socks5://45.133.16.88:1080",
    "socks4://203.160.59.253:4145",
    "socks4://103.146.42.181:8086",
    "socks4://91.142.75.202:1080",
    "socks4://159.195.61.240:1080",
    "socks4://117.50.194.130:7890",
    "socks4://200.8.235.10:4145",
    "socks5://193.25.215.182:22222",
    "socks4://216.68.128.121:4145",
    "socks5://190.89.4.185:1080",
    "socks4://199.66.183.226:4145",
    "socks4://184.182.240.12:4145",
    "socks5://152.32.219.123:10808",
    "socks5://45.137.43.0:1081",
    "socks5://193.108.115.81:10808",
    "socks5://216.68.128.121:4145",
    "socks5://192.252.214.17:4145",
    "socks4://147.15.122.136:1084",
    "socks5://141.148.158.143:1080",
    "socks5://66.163.119.55:10006",
    "socks4://95.140.118.34:1080",
    "socks4://147.15.122.136:1094",
    "socks5://68.71.252.38:4145",
    "socks4://98.188.47.132:4145",
    "socks4://147.45.60.136:1082",
    "socks5://43.160.255.142:7890",
    "socks4://24.37.245.42:51056",
    "socks4://185.5.202.203:1080",
    "socks4://176.241.82.149:5678",
    "socks5://47.238.210.231:1011",
    "socks4://8.215.25.3:2080",
    "socks4://189.39.118.210:5678",
    "socks4://66.163.119.55:10006",
    "socks5://47.85.37.60:1080",
    "socks4://190.89.104.48:5432",
    "socks4://103.10.99.110:5678",
    "socks4://70.166.167.55:57745",
    "socks4://77.239.112.19:35000",
    "socks4://72.195.34.41:4145",
    "socks5://184.182.240.211:4145",
    "socks4://190.54.100.74:5678",
    "socks5://95.105.28.76:1080",
    "socks4://43.160.255.142:7890",
    "socks4://66.42.224.229:41679",
    "socks4://105.214.87.237:5678",
    "socks5://98.170.57.249:4145",
    "socks5://152.32.203.130:10808",
    "socks5://144.31.222.106:7890",
    "socks5://38.49.210.79:40000",
    "socks5://115.127.53.114:1080",
    "socks5://93.90.232.32:1080",
    "socks4://209.182.234.151:40000",
    "socks5://213.176.113.24:50001",
    "socks5://138.124.26.19:1080",
    "socks4://77.238.246.43:17277",
    "socks5://78.63.115.20:8899",
    "socks5://104.234.124.3:1080",
    "socks4://147.45.60.124:1082",
    "socks4://216.106.179.216:49503",
    "socks5://195.133.65.238:10909",
    "socks5://109.199.107.68:1080",
    "socks4://107.173.153.119:2080",
    "socks4://177.128.81.10:81",
    "socks4://163.47.156.230:1080",
    "socks5://147.15.17.132:1084",
    "socks4://138.124.26.19:1080",
    "socks5://77.110.102.252:1080"
]

class ProxyManager:
    """
    High-Performance Proxy Manager supporting HTTP, HTTPS, SOCKS4, and SOCKS5 proxies
    with auto-fetching from ProxyScrape API, hardcoded fallbacks, rotation, and automatic health monitoring.
    """
    def __init__(self, proxy_list=None, proxy_file=None, fetch_live=True, no_proxy=False):
        self.proxies = []
        self.current_idx = 0
        self.unhealthy_proxies = set()
        self.no_proxy = no_proxy

        if no_proxy:
            logger.info("🌐 Running in DIRECT IP mode (--no-proxy). Bypassing proxy pool.")
            return

        # Load explicitly provided list
        if proxy_list:
            if isinstance(proxy_list, str):
                proxy_list = [proxy_list]
            for p in proxy_list:
                parsed = self.parse_proxy(p)
                if parsed:
                    self.proxies.append(parsed)

        # Load from file if provided
        if proxy_file and os.path.exists(proxy_file):
            try:
                with open(proxy_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            parsed = self.parse_proxy(line)
                            if parsed:
                                self.proxies.append(parsed)
            except Exception as e:
                logger.warning(f"Error reading proxy file '{proxy_file}': {e}")

        # Fallback to environment variables
        if not self.proxies:
            env_proxy = os.getenv("PROXIES", "") or os.getenv("HTTP_PROXY", "") or os.getenv("HTTPS_PROXY", "")
            if env_proxy:
                for p in env_proxy.split(","):
                    parsed = self.parse_proxy(p.strip())
                    if parsed:
                        self.proxies.append(parsed)
            
            env_file = os.getenv("PROXY_LIST_FILE", "")
            if env_file and os.path.exists(env_file):
                try:
                    with open(env_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                parsed = self.parse_proxy(line)
                                if parsed:
                                    self.proxies.append(parsed)
                except Exception:
                    pass

        # Live fetch from ProxyScrape API if enabled and no custom proxy supplied
        if not self.proxies and fetch_live:
            fetched = self._fetch_proxyscrape_api()
            if fetched:
                self.proxies.extend(fetched)

        # Final Fallback to Built-in High Quality Proxy List
        if not self.proxies:
            logger.info("Initializing ProxyManager with built-in high quality proxy pool...")
            for raw_p in HARDCODED_FALLBACK_PROXIES:
                parsed = self.parse_proxy(raw_p)
                if parsed:
                    self.proxies.append(parsed)

        if self.proxies:
            logger.info(f"Loaded {len(self.proxies)} functional proxies into ProxyManager pool.")

    def _fetch_proxyscrape_api(self):
        """Fetch fresh live proxies directly from ProxyScrape API v4 endpoint."""
        url = "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text"
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read().decode('utf-8')
                fetched_list = []
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        parsed = self.parse_proxy(line)
                        if parsed:
                            fetched_list.append(parsed)
                if fetched_list:
                    logger.info(f"Successfully fetched {len(fetched_list)} fresh proxies from ProxyScrape API.")
                    return fetched_list
        except Exception as e:
            logger.warning(f"Could not fetch live proxies from ProxyScrape API ({e}). Falling back to hardcoded pool...")
        return []

    @staticmethod
    def parse_proxy(proxy_str):
        if not proxy_str or not isinstance(proxy_str, str):
            return None
        proxy_str = proxy_str.strip()

        # Format: host:port:user:pass
        if not proxy_str.startswith(("http://", "https://", "socks5://", "socks4://")):
            parts = proxy_str.split(":")
            if len(parts) == 4:
                host, port, user, password = parts
                return {"server": f"http://{host}:{port}", "username": user, "password": password, "raw": proxy_str}
            elif len(parts) == 2:
                host, port = parts
                return {"server": f"http://{host}:{port}", "raw": proxy_str}
            else:
                proxy_str = f"http://{proxy_str}"

        try:
            parsed = urlparse(proxy_str)
            scheme = parsed.scheme or "http"
            netloc = parsed.netloc or parsed.path

            if "@" in netloc:
                auth, host_port = netloc.split("@", 1)
                user, password = auth.split(":", 1) if ":" in auth else (auth, "")
                return {"server": f"{scheme}://{host_port}", "username": user, "password": password, "raw": proxy_str}
            else:
                return {"server": f"{scheme}://{netloc}", "raw": proxy_str}
        except Exception as e:
            logger.warning(f"Could not parse proxy string '{proxy_str}': {e}")
            return None

    def get_next_proxy(self):
        if not self.proxies:
            return None

        healthy = [p for p in self.proxies if p["raw"] not in self.unhealthy_proxies]
        if not healthy:
            logger.warning("All proxies marked unhealthy! Resetting health status pool...")
            self.unhealthy_proxies.clear()
            healthy = self.proxies

        proxy = healthy[self.current_idx % len(healthy)]
        self.current_idx += 1
        return proxy

    def mark_unhealthy(self, proxy):
        if proxy and "raw" in proxy:
            self.unhealthy_proxies.add(proxy["raw"])
            logger.warning(f"Marked proxy as unhealthy: {proxy['server']}")

class MapsScraper:
    def __init__(self, proxy_list=None, proxy_file=None, no_proxy=False):
        self.results = []
        self.db = DatabaseManager()
        self.proxy_manager = ProxyManager(proxy_list=proxy_list, proxy_file=proxy_file, no_proxy=no_proxy)

    async def _stealth_delay(self, min_sec=1.2, max_sec=2.8):
        """Randomized humanized jitter delay to prevent rate-limiting."""
        await asyncio.sleep(random.uniform(min_sec, max_sec))

    async def _navigate_with_retry(self, page, url, max_retries=3, timeout=30000, current_proxy=None):
        """Navigate to URL with exponential backoff, CAPTCHA/Bot block detection, and proxy health tracking."""
        for attempt in range(1, max_retries + 1):
            try:
                response = await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
                
                # Check for Google anti-bot / CAPTCHA block page
                content = await page.content()
                if "Google Search - Unusual Traffic" in content or "recaptcha" in content.lower() or "sorry/index" in page.url:
                    logger.warning(f"⚠️ Google Bot/CAPTCHA block detected on proxy: {current_proxy['server'] if current_proxy else 'Direct IP'}")
                    if current_proxy:
                        self.proxy_manager.mark_unhealthy(current_proxy)
                    raise Exception("Google Bot/CAPTCHA Detection Blocked Access")

                return response
            except Exception as e:
                err_str = str(e)
                logger.warning(f"Navigation attempt {attempt}/{max_retries} failed for {url} ({err_str})")
                if current_proxy and ("net::ERR" in err_str or "PROXY" in err_str.upper() or "Timeout" in err_str or "CAPTCHA" in err_str):
                    self.proxy_manager.mark_unhealthy(current_proxy)
                if attempt == max_retries:
                    raise e
                await asyncio.sleep(attempt * 1.5)

    async def scrape_maps(self, queries, total_results=10, callback=None, stop_event=None, headless=True, proxy_list=None, proxy_file=None, no_proxy=False):
        if isinstance(queries, str):
            queries = [queries]

        if proxy_list or proxy_file or no_proxy:
            self.proxy_manager = ProxyManager(proxy_list=proxy_list, proxy_file=proxy_file, no_proxy=no_proxy)

        chromium_args = [
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-extensions',
            '--js-flags=--max-old-space-size=256',
            '--disable-blink-features=AutomationControlled'
        ]

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=headless, args=chromium_args)
            except Exception as launch_err:
                logger.warning(f"Initial browser launch failed ({launch_err}). Auto-installing Playwright Chromium binaries...")
                os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
                ensure_playwright_browsers()
                try:
                    browser = await p.chromium.launch(headless=headless, args=chromium_args)
                except Exception:
                    browser = await p.chromium.launch(headless=headless, args=chromium_args, channel="chromium")

            self.browser = browser

            for q_idx, query in enumerate(queries, 1):
                if stop_event and stop_event.is_set():
                    break
                    
                logger.info(f"Processing query [{q_idx}/{len(queries)}]: {query}")
                search_url = f"https://www.google.com/maps/search/{quote(query)}?hl=en"

                page = None
                context = None
                nav_success = False

                # Navigation retry loop with dynamic proxy fallback & Direct IP fallback
                for nav_attempt in range(1, 4):
                    current_proxy = self.proxy_manager.get_next_proxy() if nav_attempt < 3 else None
                    if current_proxy:
                        logger.info(f"🌐 Rotating stealth proxy (attempt {nav_attempt}/3): {current_proxy['server']}")
                    else:
                        logger.info(f"🌐 Using Direct IP Connection for query '{query}'...")

                    ua = random.choice(USER_AGENTS)
                    context_kwargs = {
                        "user_agent": ua,
                        "viewport": {"width": 1920, "height": 1080},
                        "locale": "en-US",
                        "extra_http_headers": {
                            "Accept-Language": "en-US,en;q=0.9"
                        }
                    }
                    if current_proxy:
                        proxy_cfg = {"server": current_proxy["server"]}
                        if "username" in current_proxy and "password" in current_proxy:
                            proxy_cfg["username"] = current_proxy["username"]
                            proxy_cfg["password"] = current_proxy["password"]
                        context_kwargs["proxy"] = proxy_cfg

                    try:
                        context = await browser.new_context(**context_kwargs)
                        await context.add_init_script(STEALTH_JS)
                        page = await context.new_page()
                        await self._navigate_with_retry(page, search_url, max_retries=1, timeout=20000, current_proxy=current_proxy)
                        nav_success = True
                        break
                    except Exception as e:
                        logger.warning(f"Query navigation attempt {nav_attempt} failed: {e}")
                        if context:
                            await context.close()
                            context = None

                if not nav_success or not page:
                    logger.error(f"Error executing query '{query}': All navigation attempts failed.")
                    continue

                await self._stealth_delay(1.5, 3.0)

                # Automatically dismiss Google cookie consent overlay if present
                try:
                    consent_btn = await page.query_selector('button[aria-label*="Accept all"], button[aria-label*="I agree"], form[action*="consent"] button, button[aria-label*="Reject all"]')
                    if consent_btn:
                        await consent_btn.click()
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass

                # Fallback fill search box if direct URL did not trigger search
                try:
                    search_input = await page.query_selector('input#searchboxinput, input.searchboxinput, input[name="q"], input[aria-label*="Search"]')
                    if search_input and not (await page.query_selector('div[role="feed"], a[href*="/maps/place/"]')):
                        await search_input.fill(query)
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(3000)
                except Exception:
                    pass

                # Wait for search result feed or place links
                try:
                    await page.wait_for_selector('div[role="feed"], a[href*="/maps/place/"]', timeout=15000)
                except Exception as wait_err:
                    logger.warning(f"Wait for feed selector timed out ({wait_err}), proceeding with DOM extraction...")

                scraped_count = 0
                previous_height = 0
                stuck_counter = 0
                seen_place_urls = set()
                target_limit = float('inf') if (total_results is None or total_results <= 0) else total_results
                display_limit = "UNLIMITED" if target_limit == float('inf') else target_limit

                while scraped_count < target_limit:
                    if stop_event and stop_event.is_set():
                        break

                    # Check for Google Maps "You've reached the end of the list" end banner
                    end_banner = await page.query_selector(
                        'span.Hvt42d, div.PbV8W, p.fontBodyMedium:has-text("end of the list"), '
                        'span:has-text("reached the end"), div:has-text("You\'ve reached the end of the list")'
                    )
                    if end_banner:
                        logger.info(f"🏁 Reached absolute end of Google Maps search results for query '{query}' ({scraped_count} leads total).")
                        break

                    # Find place links in results list
                    elements = await page.query_selector_all('a[href*="/maps/place/"]')
                    new_items_found = False

                    for elem in elements:
                        if scraped_count >= target_limit:
                            break
                        if stop_event and stop_event.is_set():
                            break

                        try:
                            place_url = await elem.get_attribute("href")
                            if not place_url or place_url in seen_place_urls:
                                continue

                            seen_place_urls.add(place_url)
                            new_items_found = True

                            # Force English parameter on place URL
                            if "hl=" in place_url:
                                place_url = re.sub(r'hl=[a-zA-Z\-]+', 'hl=en', place_url)
                            else:
                                place_url += "&hl=en" if "?" in place_url else "?hl=en"

                            # Open place detail view inside stealth context
                            detail_page = await context.new_page()
                            await self._navigate_with_retry(detail_page, place_url, max_retries=2, timeout=20000, current_proxy=current_proxy)
                            await self._stealth_delay(1.0, 2.2)

                            item = await self._parse_place_details(detail_page, query)
                            await detail_page.close()

                            if item and item.get("place_id") != "N/A":
                                # Deep web crawl if website is present
                                website = item.get("website", "N/A")
                                contacts = []
                                emails = set()
                                phones = set()
                                socials = {}

                                if website != "N/A" and website.startswith("http"):
                                    logger.info(f"Deep crawling website: {website}")
                                    crawler = DeepCrawler(browser)
                                    contacts, emails, phones, socials = await crawler.crawl_site(website, stop_event=stop_event, address=item.get("address"), query=query)

                                # Enrich item with deep crawl results
                                if emails:
                                    valid_email_list = list(emails)
                                    item["email"] = valid_email_list[0]
                                    item["contacts_count"] = len(valid_email_list)
                                if phones and item.get("phone") == "N/A":
                                    item["phone"] = list(phones)[0]
                                    
                                for s_name, s_url in socials.items():
                                    if item.get(s_name) == "N/A":
                                        item[s_name] = s_url

                                # Save Lead directly to Supabase & local SQLite
                                self.db.insert_lead(item)

                                # Save discovered Contacts in a single bulk operation
                                if contacts:
                                    for c in contacts:
                                        c["lead_place_id"] = item["place_id"]
                                    self.db.insert_contacts(contacts)

                                scraped_count += 1
                                logger.info(f"Successfully extracted [{scraped_count}/{display_limit}]: {item.get('name')}")

                                if callback:
                                    meta = {
                                        "query_idx": q_idx,
                                        "total_queries": len(queries),
                                        "query_name": query,
                                        "current_count": scraped_count,
                                        "max_results": display_limit
                                    }
                                    await callback(item, meta)

                                # Humanized jitter pause between extractions
                                await self._stealth_delay(0.8, 1.8)

                        except Exception as elem_err:
                            logger.warning(f"Error parsing place item: {elem_err}")
                            continue

                    # Scroll feed to load more places
                    feed = await page.query_selector('div[role="feed"]')
                    if feed:
                        current_height = await feed.evaluate("node => node.scrollHeight")
                        await feed.evaluate("node => node.scrollBy(0, 1000)")
                        await self._stealth_delay(1.5, 2.5)

                        if current_height == previous_height and not new_items_found:
                            stuck_counter += 1
                            if stuck_counter >= 4:
                                logger.info(f"End of feed reached or no new results for query '{query}'. Moving to next query.")
                                break
                        else:
                            stuck_counter = 0
                        previous_height = current_height

                if page:
                    await page.close()
                if context:
                    await context.close()
                gc.collect()

            await browser.close()

    async def _parse_place_details(self, page, query):
        item = {
            "place_id": "N/A", "name": "N/A", "query": query, "is_spending_on_ads": "No",
            "reviews": "0", "rating": "0.0", "first_review": "N/A", "website": "N/A",
            "phone": "N/A", "can_claim": "No", "email": "N/A", "contacts_count": 0,
            "linkedin": "N/A", "twitter": "N/A", "facebook": "N/A", "youtube": "N/A",
            "instagram": "N/A", "owner_name": "N/A", "main_category": "N/A",
            "workday_timing": "N/A", "is_temporarily_closed": "No", "address": "N/A",
            "latitude": "N/A", "longitude": "N/A", "review_keywords": "N/A", "link": page.url
        }

        try:
            # Wait for detail panel header AND info section to render
            try:
                await page.wait_for_selector('h1.DUwif, h1.fontHeadlineLarge, h1', timeout=5000)
            except Exception:
                pass

            try:
                await page.wait_for_selector('button[data-item-id="address"], button[data-item-id^="phone"], a[data-item-id="authority"], div.Io6YTe', timeout=5000)
            except Exception:
                await page.wait_for_timeout(2000)

            # Place ID from URL
            url = page.url
            if "!1s" in url:
                item["place_id"] = url.split("!1s")[1].split("!")[0]
            elif "place/" in url:
                item["place_id"] = url.split("place/")[1].split("/")[0]

            # Name Extraction with system banner filtering
            h1_elements = await page.query_selector_all("h1.DUwif, h1.fontHeadlineLarge, h1")
            for h1_el in h1_elements:
                h1_text = (await h1_el.inner_text()).strip()
                if h1_text and not any(err_word in h1_text.lower() for err_word in [
                    "google maps", "geen toegang", "no connection", "unusual traffic", 
                    "recaptcha", "something went wrong", "before you continue"
                ]):
                    item["name"] = h1_text
                    break

            # Category Extraction
            cat_el = await page.query_selector('button[jsaction*="category"], button.Dkftq, span.Dkftq, button.DkCrMe, button[data-item-id="category"], div.LBbeF button, button[data-item-id="address"] + button')
            if cat_el:
                cat_txt = (await cat_el.inner_text()).strip()
                if cat_txt and len(cat_txt) < 60 and not cat_txt.startswith("·"):
                    item["main_category"] = cat_txt

            # 1. Rating & Reviews Count - DOM selectors with Multilingual Support
            rev_elements = await page.query_selector_all(
                'span.ZkP5Je, div.F7v25d, span.ceNzKf, button[aria-label*="review"], '
                'button[aria-label*="star"], span[aria-label*="review"], span[aria-label*="star"], '
                'button[data-tab-index="1"], div.fontBodyMedium span, button.Dx2nRe span, span.UY7F9'
            )
            for el in rev_elements:
                aria = (await el.get_attribute("aria-label")) or ""
                txt = (await el.inner_text()).strip()
                combined = f"{aria} {txt}"
                
                if item["rating"] == "0.0":
                    m_rat = re.search(r'([0-5][\.,][0-9])', combined)
                    if m_rat:
                        item["rating"] = m_rat.group(1).replace(",", ".")

                if item["reviews"] == "0":
                    m_rev = re.search(r'([\d\.,\s]+)\s*(?:reviews|recensies|avis|bewertungen|opiniones|reseñas)', combined, re.I) or re.search(r'\(([\d\.,\s]+)\)', combined)
                    if m_rev:
                        cleaned = re.sub(r'[^\d]', '', m_rev.group(1))
                        if cleaned:
                            item["reviews"] = cleaned

            # 2. Rating & Reviews Count - Full HTML Fallback if missing
            content = await page.content()
            if item["rating"] == "0.0":
                m_rat = (
                    re.search(r'class=[\"\']F7v25d[\"\'][^>]*?>\s*([0-5][\.,][0-9])', content, re.I) or
                    re.search(r'aria-label=[\"\']([0-5][\.,][0-9])\s*(?:stars?|sterren)', content, re.I) or
                    re.search(r'([0-5][\.,][0-9])\s*(?:stars?|sterren)', content, re.I)
                )
                if m_rat:
                    item["rating"] = m_rat.group(1).replace(",", ".")

            if item["reviews"] == "0":
                m_rev = (
                    re.search(r'aria-label=[\"\'][^\"\']*?([\d\.,]+)\s+(?:reviews?|recensies|avis|bewertungen)[\"\']', content, re.I) or
                    re.search(r'([\d\.,]+)\s+(?:Google\s*)?(?:reviews?|recensies|avis)', content, re.I) or
                    re.search(r'button[^>]*Dx2nRe[^>]*>.*?([\d\.,]+)', content, re.I | re.DOTALL) or
                    re.search(r'\(([\d\.,]+)\)\s*(?:<|\s)', content)
                )
                if m_rev:
                    cleaned = re.sub(r'[^\d]', '', m_rev.group(1))
                    if cleaned:
                        item["reviews"] = cleaned

            # 3. First Review Snippet Extraction
            snippet_els = await page.query_selector_all(
                'div.My44vd, span.wi3wfd, div.jftiEf, div[data-review-id], '
                'div.K712bc, div.d4r55, div.HVZp2e, span.r75fW, blockquote'
            )
            for s_el in snippet_els:
                stxt = (await s_el.inner_text()).strip()
                stxt_clean = re.sub(r'\s+', ' ', stxt)
                stxt_lower = stxt_clean.lower()
                if (
                    len(stxt_clean) > 20 and 
                    not stxt_clean.startswith("·") and
                    not stxt_clean.startswith("http") and 
                    not any(k in stxt_lower for k in [
                        "google", "directions", "share", "save", "claim this", 
                        "add a photo", "open 24 hours", "hours", "price", "open ·", 
                        "closes", "closed", "website", "menu", "appointment", "located in",
                        "street", "st", "rd", "ave", "road", "plus code", "rating", "star",
                        "update results", "search this area", "keyboard", "map data"
                    ])
                ):
                    item["first_review"] = stxt_clean[:250]
                    break

            # Fallback: Click Reviews tab if first_review is still missing
            if item["first_review"] == "N/A":
                try:
                    rev_tab = await page.query_selector('button[role="tab"][aria-label*="Reviews"], button[role="tab"][aria-label*="Recensies"], button[aria-label*="Reviews for"], button:has-text("Reviews"), button:has-text("Recensies")')
                    if rev_tab:
                        await rev_tab.click()
                        await page.wait_for_timeout(1500)
                        
                        cards = await page.query_selector_all('div.jftiEf, div[data-review-id]')
                        for c in cards:
                            text_el = await c.query_selector('span.wi3wfd, div.My44vd, span.r75fW, div[class*="text"]')
                            if text_el:
                                ctxt = (await text_el.inner_text()).strip()
                                clean_c = re.sub(r'\s+', ' ', ctxt)
                                if len(clean_c) > 15:
                                    item["first_review"] = clean_c[:250]
                                    break
                            else:
                                ctxt = (await c.inner_text()).strip()
                                lines = [l.strip() for l in ctxt.split('\n') if len(l.strip()) > 20 and not any(k in l.lower() for k in ["star", "ago", "like", "share", "response", "owner"])]
                                if lines:
                                    item["first_review"] = lines[0][:250]
                                    break
                except Exception:
                    pass

            # Check social links directly on Google Maps place details page
            try:
                g_social_els = await page.query_selector_all('a[href*="facebook.com"], a[href*="instagram.com"], a[href*="linkedin.com"], a[href*="twitter.com"], a[href*="x.com"], a[href*="youtube.com"]')
                for g_s in g_social_els:
                    g_href = await g_s.get_attribute("href")
                    if g_href:
                        for p_name, p_pats in [
                            ('facebook', [r'facebook\.com']), ('instagram', [r'instagram\.com']),
                            ('linkedin', [r'linkedin\.com']), ('twitter', [r'twitter\.com', r'x\.com']),
                            ('youtube', [r'youtube\.com'])
                        ]:
                            if item.get(p_name, "N/A") == "N/A" and any(re.search(pat, g_href, re.I) for pat in p_pats):
                                item[p_name] = self._clean_social_link(g_href)
            except Exception:
                pass

            # --- WEBSITE EXTRACTION ---
            web_btn = await page.query_selector('a[data-item-id="authority"], a[aria-label*="Website"], a[aria-label*="website"], a[data-tooltip*="Website"], a[data-tooltip*="website"]')
            if web_btn:
                href = await web_btn.get_attribute("href")
                if href:
                    if "google.com/url?" in href or "google.com/url" in href:
                        m_url = re.search(r'q=([^&]+)', href)
                        if m_url:
                            href = unquote(m_url.group(1))
                    item["website"] = href

            if item["website"] == "N/A":
                all_links = await page.query_selector_all('a[href^="http"]')
                for l in all_links:
                    l_href = (await l.get_attribute("href")) or ""
                    l_aria = (await l.get_attribute("aria-label")) or ""
                    l_ttip = (await l.get_attribute("data-tooltip")) or ""
                    l_did = (await l.get_attribute("data-item-id")) or ""
                    if "google.com" not in l_href and "gstatic.com" not in l_href and "ggpht.com" not in l_href:
                        if "website" in l_aria.lower() or "website" in l_ttip.lower() or l_did == "authority":
                            item["website"] = l_href
                            break

            if item["website"] == "N/A":
                # HTML Content Fallback for Website
                m_web = re.search(r'data-item-id=[\"\']authority[\"\'][^>]*?href=[\"\']([^\"\'\s>]+)[\"\']', content, re.I) or re.search(r'href=[\"\'](https?://(?!www\.google|gstatic|ggpht|schema\.org)[^\"\'\s>]+)[\"\'][^>]*?data-tooltip=[\"\'](?:Open\s*)?website', content, re.I)
                if m_web:
                    href = m_web.group(1)
                    if "google.com/url?" in href:
                        m_u = re.search(r'q=([^&]+)', href)
                        if m_u:
                            href = unquote(m_u.group(1))
                    item["website"] = href

            # --- ADDRESS EXTRACTION ---
            addr_btn = await page.query_selector('button[data-item-id="address"], button[aria-label*="Address"], button[aria-label*="Adres"], button[aria-label*="Adresse"], button[data-tooltip*="address"], button[data-tooltip*="adres"]')
            if addr_btn:
                addr_aria = await addr_btn.get_attribute("aria-label")
                if addr_aria:
                    item["address"] = re.sub(r'^(Address:|Address\s*|Adres:|Adres\s*|Adresse:|Adresse\s*)', '', addr_aria, flags=re.I).strip()
                else:
                    addr_txt = (await addr_btn.inner_text()).strip()
                    if addr_txt and len(addr_txt) > 5:
                        item["address"] = addr_txt

            # --- PHONE EXTRACTION ---
            phone_btn = await page.query_selector('button[data-item-id^="phone"], button[aria-label*="Phone"], button[aria-label*="Telefoon"], button[aria-label*="Telefon"], button[data-tooltip*="phone"], button[data-tooltip*="telefoon"]')
            raw_ph = None
            if phone_btn:
                phone_aria = await phone_btn.get_attribute("aria-label")
                if phone_aria:
                    raw_ph = re.sub(r'^(Phone:|Phone\s*|Telefoon:|Telefoon\s*|Telefon:|Telefon\s*)', '', phone_aria, flags=re.I).strip()
                else:
                    raw_ph = (await phone_btn.inner_text()).strip()

            # --- UNIVERSAL INFO SECTION SCAN (div.Io6YTe / button.CsA25) for Address & Phone ---
            info_nodes = await page.query_selector_all('div.Io6YTe, button.CsA25, button.Io6YTe, div.fontBodyMedium')
            for node in info_nodes:
                node_text = (await node.inner_text()).strip()
                if not node_text or len(node_text) < 4:
                    continue

                # Phone Check
                if (not raw_ph or raw_ph == "N/A") and re.search(r'^\+?[0-9\s\-\(\)\.]{7,25}$', node_text):
                    if not any(c in node_text for c in ['@', 'http', ':', '$', ',']):
                        raw_ph = node_text

                # Address Check
                if item["address"] == "N/A":
                    if ("," in node_text or any(k in node_text for k in ["Street", " St", " Ave", " Rd", " Blvd", " Suite", " Suite", " Way", " Drive", " Dr"])) and len(node_text) > 8:
                        if not re.search(r'^\+?[0-9\s\-\(\)]+$', node_text) and not node_text.startswith("http") and not any(k in node_text.lower() for k in ["open", "closed", "hours", "reviews", "star", "claim"]):
                            item["address"] = node_text

            # HTML Regex Fallback for Phone
            if not raw_ph or raw_ph == "N/A":
                m_ph = re.search(r'data-item-id=[\"\']phone:tel:([^\"\'\s>]+)[\"\']', content, re.I) or re.search(r'href=[\"\']tel:([^\"\'\s>]+)[\"\']', content, re.I)
                if m_ph:
                    raw_ph = unquote(m_ph.group(1))

            if raw_ph and raw_ph != "N/A":
                val_ph = format_and_validate_phone(raw_ph, site_url=item.get("website"), address=item.get("address"), query=query)
                item["phone"] = val_ph if val_ph else raw_ph

            # --- COORDINATES (LATITUDE & LONGITUDE) EXTRACTION ---
            # 1. URL pattern: !3d<lat>!4d<lng>
            coord_match = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', url)
            if coord_match:
                item["latitude"] = coord_match.group(1)
                item["longitude"] = coord_match.group(2)
            else:
                # 2. URL pattern: @<lat>,<lng>
                ll_match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
                if ll_match:
                    item["latitude"] = ll_match.group(1)
                    item["longitude"] = ll_match.group(2)
                else:
                    # 3. URL pattern: ll=<lat>,<lng> or center=<lat>,<lng>
                    ll_param = re.search(r'[?&](?:ll|center|coordinates)=(-?\d+\.\d+)[,%2C](-?\d+\.\d+)', url, re.I)
                    if ll_param:
                        item["latitude"] = ll_param.group(1)
                        item["longitude"] = ll_param.group(2)

            # 4. DOM Directions link fallback (a[href*="/dir/"])
            if item["latitude"] == "N/A" or item["longitude"] == "N/A":
                try:
                    dir_btn = await page.query_selector('a[href*="/dir/"], a[aria-label*="Directions"], a[data-tooltip*="Directions"]')
                    if dir_btn:
                        dir_href = await dir_btn.get_attribute("href")
                        if dir_href:
                            dir_match = re.search(r'/dir/[^/]+/.*?@(-?\d+\.\d+),(-?\d+\.\d+)', dir_href) or re.search(r'destination=(-?\d+\.\d+)[,%2C](-?\d+\.\d+)', dir_href) or re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', dir_href)
                            if dir_match:
                                item["latitude"] = dir_match.group(1)
                                item["longitude"] = dir_match.group(2)
                except Exception:
                    pass

            # 5. HTML Meta tag / Static Map fallback scan
            if item["latitude"] == "N/A" or item["longitude"] == "N/A":
                try:
                    meta_lat = await page.query_selector('meta[itemprop="latitude"]')
                    meta_lng = await page.query_selector('meta[itemprop="longitude"]')
                    if meta_lat and meta_lng:
                        c_lat = await meta_lat.get_attribute("content")
                        c_lng = await meta_lng.get_attribute("content")
                        if c_lat and c_lng:
                            item["latitude"] = c_lat.strip()
                            item["longitude"] = c_lng.strip()
                except Exception:
                    pass

            # 6. Page Content HTML Regex Fallback for embedded Google Maps JS arrays
            if item["latitude"] == "N/A" or item["longitude"] == "N/A":
                try:
                    html_content = await page.content()
                    m_html = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', html_content) or re.search(r'center=(-?\d+\.\d+)%2C(-?\d+\.\d+)', html_content, re.I)
                    if m_html:
                        item["latitude"] = m_html.group(1)
                        item["longitude"] = m_html.group(2)
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"Error parsing place fields: {e}")

        return item
