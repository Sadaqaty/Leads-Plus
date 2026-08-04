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
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        import subprocess
        driver_executable, _ = compute_driver_executable()
        env = get_driver_env()
        logger.info("Verifying/Installing Playwright Chromium browser binaries...")
        subprocess.run([driver_executable, "install", "chromium"], env=env, check=True)
        logger.info("Playwright Chromium browser is ready.")
        return True
    except Exception as e:
        logger.warning(f"Auto-installing Playwright Chromium failed: {e}")
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

class ProxyManager:
    """
    High-Performance Proxy Manager supporting HTTP, HTTPS, SOCKS4, and SOCKS5 proxies
    with format parsing, rotation, and automatic health monitoring.
    """
    def __init__(self, proxy_list=None, proxy_file=None):
        self.proxies = []
        self.current_idx = 0
        self.unhealthy_proxies = set()

        if proxy_list:
            if isinstance(proxy_list, str):
                proxy_list = [proxy_list]
            for p in proxy_list:
                parsed = self.parse_proxy(p)
                if parsed:
                    self.proxies.append(parsed)

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

        if self.proxies:
            logger.info(f"Loaded {len(self.proxies)} proxies into ProxyManager.")

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
    def __init__(self, proxy_list=None, proxy_file=None):
        self.results = []
        self.db = DatabaseManager()
        self.proxy_manager = ProxyManager(proxy_list=proxy_list, proxy_file=proxy_file)

    async def _stealth_delay(self, min_sec=1.2, max_sec=2.8):
        """Randomized humanized jitter delay to prevent rate-limiting."""
        await asyncio.sleep(random.uniform(min_sec, max_sec))

    async def _navigate_with_retry(self, page, url, max_retries=3, timeout=30000, current_proxy=None):
        """Navigate to URL with exponential backoff and proxy health tracking."""
        for attempt in range(1, max_retries + 1):
            try:
                response = await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
                return response
            except Exception as e:
                err_str = str(e)
                logger.warning(f"Navigation attempt {attempt}/{max_retries} failed for {url} ({err_str})")
                if current_proxy and ("net::ERR" in err_str or "PROXY" in err_str.upper() or "Timeout" in err_str):
                    self.proxy_manager.mark_unhealthy(current_proxy)
                if attempt == max_retries:
                    raise e
                await asyncio.sleep(attempt * 2.0)

    async def scrape_maps(self, queries, total_results=10, callback=None, stop_event=None, headless=True, proxy_list=None, proxy_file=None):
        if isinstance(queries, str):
            queries = [queries]

        if proxy_list or proxy_file:
            self.proxy_manager = ProxyManager(proxy_list=proxy_list, proxy_file=proxy_file)

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
                ensure_playwright_browsers()
                browser = await p.chromium.launch(headless=headless, args=chromium_args)

            self.browser = browser

            for q_idx, query in enumerate(queries, 1):
                if stop_event and stop_event.is_set():
                    break
                    
                logger.info(f"Processing query [{q_idx}/{len(queries)}]: {query}")
                
                # Fetch next active proxy from ProxyManager if configured
                current_proxy = self.proxy_manager.get_next_proxy()
                if current_proxy:
                    logger.info(f"🌐 Rotating stealth proxy: {current_proxy['server']}")

                # Rotate user agent and create stealth context
                ua = random.choice(USER_AGENTS)
                context_kwargs = {
                    "user_agent": ua,
                    "viewport": {"width": 1920, "height": 1080},
                    "locale": "en-US"
                }
                if current_proxy:
                    proxy_cfg = {"server": current_proxy["server"]}
                    if "username" in current_proxy and "password" in current_proxy:
                        proxy_cfg["username"] = current_proxy["username"]
                        proxy_cfg["password"] = current_proxy["password"]
                    context_kwargs["proxy"] = proxy_cfg

                context = await browser.new_context(**context_kwargs)
                await context.add_init_script(STEALTH_JS)
                page = await context.new_page()
                
                try:
                    search_url = f"https://www.google.com/maps/search/{quote(query)}"
                    await self._navigate_with_retry(page, search_url, max_retries=3, current_proxy=current_proxy)
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

                except Exception as query_err:
                    logger.error(f"Error executing query '{query}': {query_err}")
                finally:
                    await page.close()
                    await context.close()
                    # Trigger immediate RAM garbage collection to keep VPS memory footprint minimal
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
            # Wait briefly for detail header panel to render
            try:
                await page.wait_for_selector('h1', timeout=4000)
            except Exception:
                pass

            # Place ID from URL
            url = page.url
            if "!1s" in url:
                item["place_id"] = url.split("!1s")[1].split("!")[0]
            elif "place/" in url:
                item["place_id"] = url.split("place/")[1].split("/")[0]

            # Name
            h1 = await page.query_selector("h1")
            if h1:
                item["name"] = (await h1.inner_text()).strip()

            # Category
            cat_btn = await page.query_selector('button[data-item-id="address"] + button, button.DkCrMe')
            if cat_btn:
                item["main_category"] = (await cat_btn.inner_text()).strip()

            # 1. Rating & Reviews Count - DOM selectors
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
                    m_rat = re.search(r'([0-4]\.[0-9]|5\.0)', combined)
                    if m_rat:
                        item["rating"] = m_rat.group(1)

                if item["reviews"] == "0":
                    m_rev = re.search(r'([0-9,]+)\s*reviews?', combined, re.I) or re.search(r'\(([0-9,]+)\)', combined)
                    if m_rev:
                        item["reviews"] = m_rev.group(1).replace(",", "")

            # 2. Rating & Reviews Count - Full HTML Fallback if missing
            content = await page.content()
            if item["rating"] == "0.0":
                m_rat = (
                    re.search(r'class=[\"\']F7v25d[\"\'][^>]*?>\s*([0-5]\.[0-9])', content, re.I) or
                    re.search(r'aria-label=[\"\']([0-5]\.[0-9])\s*stars?', content, re.I) or
                    re.search(r'([0-5]\.[0-9])\s*stars?', content, re.I)
                )
                if m_rat:
                    item["rating"] = m_rat.group(1)

            if item["reviews"] == "0":
                m_rev = (
                    re.search(r'aria-label=[\"\'][^\"\']*?([0-9,]+)\s+reviews?[\"\']', content, re.I) or
                    re.search(r'([0-9,]+)\s+(?:Google\s*)?reviews', content, re.I) or
                    re.search(r'button[^>]*Dx2nRe[^>]*>.*?([0-9,]+)', content, re.I | re.DOTALL) or
                    re.search(r'\(([0-9,]+)\)\s*(?:<|\s)', content)
                )
                if m_rev:
                    item["reviews"] = m_rev.group(1).replace(",", "")

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
                    rev_tab = await page.query_selector('button[role="tab"][aria-label*="Reviews"], button[aria-label*="Reviews for"], button:has-text("Reviews")')
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

            # Website
            web_btn = await page.query_selector('a[data-item-id="authority"]')
            if web_btn:
                href = await web_btn.get_attribute("href")
                if href: item["website"] = href

            # Address
            addr_btn = await page.query_selector('button[data-item-id="address"]')
            if addr_btn:
                addr_aria = await addr_btn.get_attribute("aria-label")
                if addr_aria:
                    item["address"] = addr_aria.replace("Address:", "").strip()

            # Phone
            phone_btn = await page.query_selector('button[data-item-id^="phone:"]')
            if phone_btn:
                phone_aria = await phone_btn.get_attribute("aria-label")
                if phone_aria:
                    raw_ph = phone_aria.replace("Phone:", "").strip()
                    val_ph = format_and_validate_phone(raw_ph, site_url=item.get("website"), address=item.get("address"), query=query)
                    item["phone"] = val_ph if val_ph else raw_ph

            # Coordinates (latitude & longitude)
            coord_match = re.search(r'!3d(-?[0-9\.]+)!4d(-?[0-9\.]+)', url)
            if coord_match:
                item["latitude"] = coord_match.group(1)
                item["longitude"] = coord_match.group(2)
            else:
                ll_match = re.search(r'@(-?[0-9\.]+),(-?[0-9\.]+)', url)
                if ll_match:
                    item["latitude"] = ll_match.group(1)
                    item["longitude"] = ll_match.group(2)

        except Exception as e:
            logger.warning(f"Error parsing place fields: {e}")

        return item
