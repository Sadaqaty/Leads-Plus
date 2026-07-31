import asyncio
from playwright.async_api import async_playwright
import json
import logging
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DeepCrawler:
    def __init__(self, browser):
        self.browser = browser
        self.junk_patterns = [
            r'sentry.*\.io', r'wixpress\.com', r'example\.com', r'domain\.com', r'yourdomain\.com',
            r'schema\.org', r'bootstrap', r'jquery', r'wordpress', r'github', r'gravatar',
            r'\.png$', r'\.jpg$', r'\.jpeg$', r'\.gif$', r'\.svg$', r'\.webp$', r'2x-',
            r'noreply', r'no-reply', r'donotreply', r'^test@', r'^demo@', r'^user@', r'^you@',
            r'^youremail@', r'^name@', r'settlement', r'facebook\.com', r'instagram\.com',
            r'developers\.facebook', r'privacy', r'policy', r'terms'
        ]

    async def crawl_site(self, base_url, stop_event=None):
        found_contacts = []
        found_emails = set()
        found_phones = set()
        socials = {}
        
        if stop_event and stop_event.is_set():
            return found_contacts, found_emails, found_phones, socials

        page = None
        try:
            # 1. Discover key URLs
            page = await self.browser.new_page()
            # Resolve redirects
            await page.goto(base_url, timeout=20000, wait_until="domcontentloaded")
            
            # Step 1: Scroll home page
            await self._scroll_page(page)
            resolved_url = page.url
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            # Discover URLs & Socials
            urls_to_crawl = {resolved_url}
            socials = self._extract_socials(soup, resolved_url)
            
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
                    await self._scroll_page(sub_page)
                    
                    html = await sub_page.content()
                    page_soup = BeautifulSoup(html, 'html.parser')
                    
                    found_emails.update(self._extract_emails(html))
                    found_phones.update(self._extract_phones(page_soup.get_text()))
                    socials.update(self._extract_socials(page_soup, url))
                    found_contacts.extend(self._extract_team_members(page_soup, url))
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
        except:
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

    def _extract_emails(self, html):
        matches = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', html)
        valid_emails = []
        seen = set()
        for m in matches:
            m = m.lower().strip()
            if m in seen:
                continue
            if not any(re.search(jp, m) for jp in self.junk_patterns):
                if len(re.findall(r'[0-9]{5,}', m)) < 2 and len(m) < 60:
                    seen.add(m)
                    valid_emails.append(m)
        return valid_emails

    def _extract_phones(self, text):
        if not text:
            return set()
        # Clean multiline spacing first
        text = re.sub(r'\s+', ' ', text)
        phone_matches = re.findall(r'\+?[0-9][0-9\s.-]{8,15}', text)
        cleaned = set()
        for p in phone_matches:
            p_clean = re.sub(r'\s+', ' ', p).strip()
            digit_count = len(re.sub(r'[^\d]', '', p_clean))
            if 9 <= digit_count <= 15:
                cleaned.add(p_clean)
        return cleaned

    def _extract_team_members(self, soup, url):
        members = []
        # Heuristic: look for containers that might hold person info
        person_containers = soup.find_all(['div', 'article', 'section', 'li'], 
                                         class_=re.compile(r'member|team|person|staff|leadership|profile|employee', re.I))
        
        for container in person_containers:
            name_el = container.find(['h2', 'h3', 'h4', 'h5', 'strong', 'span'], 
                                     class_=re.compile(r'name|title|header', re.I))
            if not name_el:
                # Try finding capitalized text that doesn't look like general UI
                text = container.get_text(separator=' ').strip()
                name_match = re.search(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', text)
                name = name_match.group(1) if name_match else None
            else:
                name = name_el.get_text().strip()

            if name and len(name.split()) >= 2 and len(name) < 40:
                role_el = container.find(['p', 'span', 'div'], class_=re.compile(r'role|position|job|desc', re.I))
                role = role_el.get_text().strip() if role_el else "N/A"
                
                # Check for LinkedIn
                linkedin_el = container.find('a', href=re.compile(r'linkedin\.com', re.I))
                linkedin = linkedin_el['href'] if linkedin_el else "N/A"
                
                # Check for direct email/phone in container
                email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', container.get_text())
                email = email_match.group(0) if email_match else "N/A"
                
                phone_match = re.search(r'\+?[0-9][0-9\s.-]{8,15}', container.get_text())
                phone = phone_match.group(0) if phone_match else "N/A"

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
        return unique_members

class MapsScraper:
    def __init__(self):
        self.results = []
        self.db = DatabaseManager()

    async def scrape_maps(self, queries, total_results=10, callback=None, stop_event=None, headless=True):
        if isinstance(queries, str):
            queries = [queries]

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            total_queries = len(queries)
            global_seen_ids = set()
            global_seen_names = set()
            
            for query_idx, query in enumerate(queries, 1):
                if stop_event and stop_event.is_set(): break
                
                logger.info(f"Processing query [{query_idx}/{total_queries}]: {query}")
                try:
                    # Clear search before new query
                    clear_btn = await page.query_selector('button.gsst_a')
                    if clear_btn: await clear_btn.click()
                    
                    search_url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                    
                    # Wait for results or input
                    try:
                        await page.wait_for_selector('a.hfpxzc, a[href*="/maps/place/"], div[role="feed"]', timeout=12000)
                    except:
                        search_box = await page.wait_for_selector('input#searchboxinput, input[name="q"]', timeout=5000)
                        if search_box:
                            await search_box.click(click_count=3)
                            await page.keyboard.press("Backspace")
                            await search_box.fill(query)
                            await page.keyboard.press("Enter")
                            await page.wait_for_selector('a.hfpxzc, a[href*="/maps/place/"], div[role="feed"]', timeout=12000)
                except Exception as e:
                    logger.error(f"Search failed for {query}: {e}")
                    continue

                extracted_count = 0
                consecutive_no_new = 0
                
                while extracted_count < total_results:
                    if stop_event and stop_event.is_set(): break
                    
                    # Scroll to load more items
                    await self._scroll_list(page)
                    items = await page.query_selector_all('a.hfpxzc, a[href*="/maps/place/"]')
                    
                    if not items:
                        # Try one more scroll if we don't see items immediately
                        await self._scroll_list(page)
                        items = await page.query_selector_all('a.hfpxzc, a[href*="/maps/place/"]')
                        if not items:
                            consecutive_no_new += 1
                            if consecutive_no_new > 8: break
                            continue

                    processed_any_new = False
                    for item in items:
                        if stop_event and stop_event.is_set(): break
                        if extracted_count >= total_results: break
                        
                        try:
                            name = await item.get_attribute('aria-label')
                            item_url = await item.get_attribute('href')
                            if not item_url: continue
                            place_id = self._extract_place_id(item_url)
                            
                            if not name: continue
                                
                            # Robust duplicate check (both ID and Name)
                            is_duplicate = (place_id != "N/A" and place_id in global_seen_ids) or (name in global_seen_names)
                            if is_duplicate:
                                continue

                            logger.info(f"Query {query_idx}/{total_queries} | item {extracted_count + 1}: {name}")
                            
                            # Detailed extraction in isolated page
                            detail_page = None
                            try:
                                detail_page = await context.new_page()
                                await detail_page.goto(item_url, wait_until="domcontentloaded", timeout=30000)
                                await detail_page.wait_for_selector('h1.DUwDvf', timeout=15000)
                                await asyncio.sleep(0.5) # Slight pause for rendering

                                details = self._extract_details_template(query, name, item_url, place_id)
                                
                                # Extract latitude and longitude from URL or page
                                current_url = detail_page.url
                                lat, lng = self._extract_coords(current_url)
                                
                                # Parallel attributes extraction
                                details.update({
                                    "latitude": lat,
                                    "longitude": lng,
                                    "reviews": await self._get_reviews_count(detail_page),
                                    "rating": await self._get_rating(detail_page),
                                    "first_review": await self._get_first_review(detail_page),
                                    "website": await self._get_attr(detail_page, 'a[data-item-id="authority"]', 'href'),
                                    "phone": self._clean_text(await self._get_text(detail_page, 'button[data-item-id^="phone:tel:"]')),
                                    "can_claim": await self._check_exists(detail_page, 'button:has-text("Claim this business")'),
                                    "phones": [self._clean_text(await self._get_text(detail_page, 'button[data-item-id^="phone:tel:"]'))],
                                    "linkedin": await self._find_social(detail_page, "linkedin.com"),
                                    "twitter": await self._find_social(detail_page, "twitter.com/"),
                                    "facebook": await self._find_social(detail_page, "facebook.com/"),
                                    "youtube": await self._find_social(detail_page, "youtube.com/"),
                                    "instagram": await self._find_social(detail_page, "instagram.com/"),
                                    "main_category": await self._get_text(detail_page, 'button.DkEaL'),
                                    "workday_timing": await self._get_timing(detail_page),
                                    "address": self._clean_text(await self._get_text(detail_page, 'button[data-item-id="address"]')),
                                    "review_keywords": await self._get_review_keywords(detail_page),
                                })

                                if details["website"] != "N/A" and not (stop_event and stop_event.is_set()):
                                    logger.info(f"Deep crawling website: {details['website']}")
                                    crawler = DeepCrawler(browser)
                                    contacts, emails, phones, socials = await crawler.crawl_site(details["website"], stop_event=stop_event)
                                    
                                    # Update leads table fields with aggregated data
                                    if emails:
                                        details["email"] = ", ".join(list(emails))
                                    if phones:
                                        details["phone"] = ", ".join(list(phones))
                                    
                                    # Update Socials from crawler if not found in Maps
                                    for platform, link in socials.items():
                                        if details.get(platform) == "N/A":
                                            details[platform] = link

                                    details["contacts_count"] = len(contacts)
                                    
                                    # Save contacts to specialized table
                                    for c in contacts:
                                        c["lead_place_id"] = place_id
                                        self.db.insert_contact(c)
                                        # Also try to set owner_name if found
                                        if any(x in c["role"].lower() for x in ['founder', 'owner', 'ceo', 'director', 'principal']):
                                            details["owner_name"] = c["name"]

                                # Save to DB real-time
                                self.db.insert_lead(details)
                                
                                self.results.append(details)
                                if place_id != "N/A": global_seen_ids.add(place_id)
                                global_seen_names.add(name)
                                
                                extracted_count += 1
                                processed_any_new = True
                                logger.info(f"Successfully extracted [{extracted_count}/{total_results}]: {name}")
                                
                                if callback:
                                    await callback(details, {
                                        "query_idx": query_idx,
                                        "total_queries": total_queries,
                                        "query_name": query,
                                        "current_count": extracted_count,
                                        "total_results": total_results
                                    })
                                        
                            except Exception as e:
                                logger.warning(f"Error processing {name}: {e}")
                            finally:
                                if detail_page: await detail_page.close()
                                    
                        except Exception as item_err:
                            logger.error(f"Outer loop item error: {item_err}")
                            continue

                    if processed_any_new:
                        consecutive_no_new = 0
                    else:
                        consecutive_no_new += 1
                        # Break faster if stuck on duplicates or empty
                        if consecutive_no_new >= 6:
                            logger.info(f"Stuck on stale results for query: {query}. Moving on.")
                            break
                
            await browser.close()
            return self.results

    async def _scroll_list(self, page):
        feed = await page.query_selector('div[role="feed"]')
        if feed:
            await feed.evaluate('element => element.scrollBy(0, 2000)')
            await asyncio.sleep(2)
        else:
            await page.mouse.wheel(0, 2000)
            await asyncio.sleep(2)

    def _extract_details_template(self, query, name, url, place_id):
        return {
            "place_id": place_id, "name": name, "query": query, "link": url,
            "latitude": "N/A", "longitude": "N/A",
            "is_spending_on_ads": "No", "reviews": "0", "rating": "N/A",
            "first_review": "N/A", "website": "N/A", "phone": "N/A",
            "can_claim": "No", "email": "N/A", "phones": [],
            "linkedin": "N/A", "twitter": "N/A", "facebook": "N/A",
            "youtube": "N/A", "instagram": "N/A", "owner_name": "N/A",
            "owner_profile_link": "N/A", "featured_image": "N/A",
            "main_category": "N/A", "categories": "N/A", "workday_timing": "N/A",
            "is_temporarily_closed": "No", "closed_on": "N/A", "address": "N/A",
            "review_keywords": "N/A", "contacts_count": 0
        }

    def _extract_coords(self, url):
        if not url: return "N/A", "N/A"
        # Method 1: @lat,lng
        match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
        if match:
            return match.group(1), match.group(2)
        # Method 2: !3dLAT!4dLNG
        match_3d = re.search(r'!3d(-?\d+\.\d+).*?!4d(-?\d+\.\d+)', url)
        if match_3d:
            return match_3d.group(1), match_3d.group(2)
        return "N/A", "N/A"

    def _extract_place_id(self, url):
        match = re.search(r'!1s(0x[a-fA-F0-9]+:[a-fA-F0-9]+)', url)
        return match.group(1) if match else "N/A"

    async def _get_text(self, page, selector):
        try:
            el = await page.wait_for_selector(selector, timeout=3000)
            return await el.inner_text() if el else "N/A"
        except: return "N/A"

    async def _get_attr(self, page, selector, attr):
        try:
            el = await page.wait_for_selector(selector, timeout=3000)
            return await el.get_attribute(attr) if el else "N/A"
        except: return "N/A"

    async def _check_exists(self, page, selector):
        try:
            el = await page.query_selector(selector)
            return "Yes" if el else "No"
        except: return "No"

    def _clean_text(self, text):
        if not text or text == "N/A": return "N/A"
        return text.replace("\ue0b0", "").replace("\ue0c8", "").replace("\n", " ").strip()

    async def _get_rating(self, page):
        try:
            el = await page.wait_for_selector('span.ceNzRbc, .F7nice span[aria-hidden="true"]', timeout=3000)
            text = await el.inner_text() if el else "N/A"
            match = re.search(r'(\d\.\d)', text)
            return match.group(1) if match else text
        except: return "N/A"

    async def _get_reviews_count(self, page):
        try:
            # Modern Google Maps DOM selectors for review counts
            selectors = [
                'button.HHrUfc',
                'button[aria-label*="reviews"]',
                'span[aria-label*="reviews"]',
                'div.F7nice span:last-child',
                'button:has-text("reviews")',
                'button:has-text("review")'
            ]
            for sel in selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        text = await el.inner_text()
                        if text:
                            # Extract numbers enclosed in parenthesis, e.g. "(1,250)" or "1,250 reviews"
                            match = re.search(r'\(?([\d,.]+)\)?\s*(?:reviews|review)?', text, re.I)
                            if match:
                                digits_only = re.sub(r'[^\d]', '', match.group(1))
                                if digits_only:
                                    return digits_only
                except:
                    continue
            
            # Full text fallback on page header area
            header_text = await page.evaluate('''() => {
                const el = document.querySelector('div.F7nice') || document.querySelector('h1.DUwDvf')?.parentElement;
                return el ? el.innerText : '';
            }''')
            if header_text:
                nums = re.findall(r'\(?([\d,]{1,8})\)?\s*(?:reviews|review)?', header_text, re.I)
                clean_nums = [int(re.sub(r'[^\d]', '', n)) for n in nums if re.sub(r'[^\d]', '', n)]
                if clean_nums:
                    return str(max(clean_nums))
            return "0"
        except:
            return "0"

    async def _get_first_review(self, page):
        try:
            # More aggressive scroll to trigger review load
            side_pane = await page.query_selector('div[role="main"]')
            if side_pane: 
                await side_pane.evaluate('el => el.scrollBy(0, 800)')
                await asyncio.sleep(1) # Wait for potential lazy loading
            
            # primary modern selector: .wiI7pd
            # fallback: .wiL7W, .jANv8b
            review_el = await page.wait_for_selector('span.wiI7pd, div.MyEned span.wiL7W, .jANv8b span', timeout=5000)
            if review_el:
                return self._clean_text(await review_el.inner_text())
            return "N/A"
        except: return "N/A"

    async def _find_social(self, page, domain):
        try:
            links = await page.query_selector_all(f'a[href*="{domain}"]')
            if links: return await links[0].get_attribute('href')
            profiles_header = await page.query_selector('div:has-text("Profiles")')
            if profiles_header:
                parent = await profiles_header.evaluate_handle('el => el.parentElement')
                social_link = await parent.query_selector(f'a[href*="{domain}"]')
                if social_link: return await social_link.get_attribute('href')
            return "N/A"
        except: return "N/A"

    async def _get_timing(self, page):
        try:
            expand_btn = await page.wait_for_selector('div.t39Bqc', timeout=1000)
            if expand_btn:
                await expand_btn.click()
                await asyncio.sleep(0.5)
                table = await page.query_selector('table.fontBodyMedium')
                if table: return await table.inner_text()
            return await self._get_text(page, 'div.t39Bqc')
        except: return "N/A"

    async def _get_review_keywords(self, page):
        try:
            keywords = await page.query_selector_all('span.K70EDP')
            return ", ".join([await k.inner_text() for k in keywords]) if keywords else "N/A"
        except: return "N/A"

if __name__ == "__main__":
    scraper = MapsScraper()
    async def main():
        # Headless test run
        results = await scraper.scrape_maps(["Coffee Tokyo"], total_results=2)
        print(json.dumps(results, indent=2))
    asyncio.run(main())
