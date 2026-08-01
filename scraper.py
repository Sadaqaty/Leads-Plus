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
            socials = self._extract_socials(soup, resolved_url)
            found_contacts.extend(self._extract_team_members(soup, resolved_url, address=address, query=query))

            # Discover internal contact/about URLs & social links
            urls_to_crawl = {resolved_url}
            for a in soup.find_all('a', href=True):
                href = a['href']
                abs_url = urljoin(resolved_url, href)
                if urlparse(abs_url).netloc == urlparse(resolved_url).netloc:
                    if any(x in href.lower() for x in ['about', 'team', 'staff', 'people', 'leadership', 'contact', 'careers']):
                        urls_to_crawl.add(abs_url)
                elif any(x in abs_url.lower() for x in ['facebook.com', 'instagram.com', 'linkedin.com', 'twitter.com', 'youtube.com']):
                    socials.update(self._extract_socials(BeautifulSoup(f'<a href="{abs_url}"></a>', 'html.parser'), resolved_url))
            
            await page.close()
            page = None # Prevent double close

            # 2. Crawl discovery URLs (limit to 5)
            for url in list(urls_to_crawl)[:5]:
                if stop_event and stop_event.is_set(): break
                sub_page = None
                try:
                    sub_page = await self.browser.new_page()
                    await sub_page.goto(url, timeout=15000, wait_until="domcontentloaded")
                    try:
                        await sub_page.wait_for_load_state("networkidle", timeout=3000)
                    except Exception:
                        pass
                    await asyncio.sleep(1)
                    await self._scroll_page(sub_page)
                    
                    html = await sub_page.content()
                    page_soup = BeautifulSoup(html, 'html.parser')
                    
                    found_emails.update(self._extract_emails(html, page_soup))
                    found_phones.update(self._extract_phones(page_soup.get_text(), page_soup, site_url=url, address=address, query=query))
                    socials.update(self._extract_socials(page_soup, url))
                    found_contacts.extend(self._extract_team_members(page_soup, url, address=address, query=query))
                except Exception as e:
                    logger.warning(f"Failed to crawl subpage {url}: {e}")
                finally:
                    if sub_page: await sub_page.close()

        except Exception as e:
            logger.error(f"Crawling failed for {base_url}: {e}")
        finally:
            if page: await page.close()
            
        return found_contacts, found_emails, found_phones, socials

    async def _scroll_page(self, page):
        """Scroll down the page to trigger lazy loading."""
        try:
            await page.evaluate("""async () => {
                await new Promise((resolve) => {
                    let totalHeight = 0;
                    let distance = 100;
                    let timer = setInterval(() => {
                        let scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        if(totalHeight >= scrollHeight || totalHeight > 5000){
                            clearInterval(timer);
                            resolve();
                        }
                    }, 100);
                });
            }""")
            await asyncio.sleep(1)
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

    def _extract_socials(self, soup, base_url):
        socials = {}
        platforms = {
            'facebook': [r'facebook\.com'],
            'instagram': [r'instagram\.com'],
            'linkedin': [r'linkedin\.com'],
            'twitter': [r'twitter\.com', r'x\.com'],
            'youtube': [r'youtube\.com']
        }
        
        for a in soup.find_all('a', href=True):
            href = a['href']
            abs_url = urljoin(base_url, href)
            for platform, patterns in platforms.items():
                if platform not in socials:
                    if any(re.search(pat, abs_url, re.I) for pat in patterns):
                        cleaned = self._clean_social_link(abs_url)
                        if cleaned != "N/A":
                            socials[platform] = cleaned
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

class MapsScraper:
    def __init__(self):
        self.results = []
        self.db = DatabaseManager()

    async def scrape_maps(self, queries, total_results=10, callback=None, stop_event=None, headless=True):
        if isinstance(queries, str):
            queries = [queries]

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=headless)
            except Exception as launch_err:
                logger.warning(f"Initial browser launch failed ({launch_err}). Auto-installing Playwright Chromium binaries...")
                ensure_playwright_browsers()
                browser = await p.chromium.launch(headless=headless)

            self.browser = browser

            for q_idx, query in enumerate(queries, 1):
                if stop_event and stop_event.is_set():
                    break
                    
                logger.info(f"Processing query [{q_idx}/{len(queries)}]: {query}")
                page = await browser.new_page()
                
                try:
                    search_url = f"https://www.google.com/maps/search/{quote(query)}"
                    await page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(2500)

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

                    while scraped_count < total_results:
                        if stop_event and stop_event.is_set():
                            break

                        # Find place links in results list
                        elements = await page.query_selector_all('a[href*="/maps/place/"]')
                        
                        for elem in elements:
                            if scraped_count >= total_results:
                                break
                            if stop_event and stop_event.is_set():
                                break

                            try:
                                place_url = await elem.get_attribute("href")
                                if not place_url:
                                    continue

                                # Open place detail view
                                detail_page = await browser.new_page()
                                await detail_page.goto(place_url, timeout=20000, wait_until="domcontentloaded")
                                await detail_page.wait_for_timeout(1500)

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

                                    # Save Lead to Supabase & SQLite
                                    self.db.insert_lead(item)

                                    # Save discovered Contacts in a single bulk operation
                                    if contacts:
                                        for c in contacts:
                                            c["lead_place_id"] = item["place_id"]
                                        self.db.insert_contacts(contacts)

                                    scraped_count += 1
                                    logger.info(f"Successfully extracted [{scraped_count}/{total_results}]: {item.get('name')}")

                                    if callback:
                                        meta = {
                                            "query_idx": q_idx,
                                            "total_queries": len(queries),
                                            "query_name": query,
                                            "current_count": scraped_count,
                                            "max_results": total_results
                                        }
                                        await callback(item, meta)

                            except Exception as elem_err:
                                logger.warning(f"Error parsing place item: {elem_err}")
                                continue

                        # Scroll feed to load more places
                        feed = await page.query_selector('div[role="feed"]')
                        if feed:
                            current_height = await feed.evaluate("node => node.scrollHeight")
                            await feed.evaluate("node => node.scrollBy(0, 1000)")
                            await page.wait_for_timeout(2000)

                            if current_height == previous_height:
                                stuck_counter += 1
                                if stuck_counter >= 3:
                                    logger.info(f"Stuck on stale results for query: {query}. Moving on.")
                                    break
                            else:
                                stuck_counter = 0
                            previous_height = current_height

                except Exception as query_err:
                    logger.error(f"Error executing query '{query}': {query_err}")
                finally:
                    await page.close()

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
                'button[data-tab-index="1"], div.fontBodyMedium span'
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
                    m_rev = re.search(r'([0-9,]+)\s*reviews?', combined, re.I)
                    if not m_rev:
                        m_rev = re.search(r'\(([0-9,]+)\)', combined)
                    if m_rev:
                        item["reviews"] = m_rev.group(1).replace(",", "")

            # 2. Rating & Reviews Count - Full HTML Fallback if missing
            if item["reviews"] == "0" or item["rating"] == "0.0":
                content = await page.content()
                if item["rating"] == "0.0":
                    m_rat = re.search(r'aria-label=[\"\']([0-5]\.[0-9])\s*stars?', content, re.I) or re.search(r'([0-5]\.[0-9])\s*stars?', content, re.I)
                    if m_rat:
                        item["rating"] = m_rat.group(1)
                        
                if item["reviews"] == "0":
                    m_rev = (
                        re.search(r'aria-label=[\"\'][^\"\']*?([0-9,]+)\s+reviews?[\"\']', content, re.I) or
                        re.search(r'([0-9,]+)\s+reviews', content, re.I) or
                        re.search(r'\(([0-9,]+)\)\s*<', content)
                    )
                    if m_rev:
                        item["reviews"] = m_rev.group(1).replace(",", "")

            # 3. First Review Snippet Extraction
            snippet_els = await page.query_selector_all(
                'div.My44vd, span.wi3wfd, div.jftiEf, div[data-review-id], '
                'div[class*="review"] span, div.fontBodyMedium span, blockquote, div.K712bc'
            )
            for s_el in snippet_els:
                stxt = (await s_el.inner_text()).strip()
                if (
                    len(stxt) > 20 and 
                    not stxt.startswith("http") and 
                    not any(k in stxt.lower() for k in ["google", "directions", "share", "save", "claim this", "add a photo", "open 24 hours", "hours", "price"])
                ):
                    item["first_review"] = re.sub(r'\s+', ' ', stxt)[:250]
                    break

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
