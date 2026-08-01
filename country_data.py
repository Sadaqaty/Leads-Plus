import re
from urllib.parse import urlparse

# 1. Comprehensive ccTLD mapping including 250+ country code top-level domains and common second-level domains
ALL_CCTLD_MAP = {
    # Second-level country TLDs
    'co.uk': 'GB', 'org.uk': 'GB', 'gov.uk': 'GB', 'me.uk': 'GB', 'ltd.uk': 'GB', 'plc.uk': 'GB',
    'com.au': 'AU', 'net.au': 'AU', 'org.au': 'AU', 'edu.au': 'AU', 'gov.au': 'AU',
    'co.nz': 'NZ', 'net.nz': 'NZ', 'org.nz': 'NZ',
    'com.pk': 'PK', 'org.pk': 'PK', 'net.pk': 'PK', 'edu.pk': 'PK', 'gov.pk': 'PK',
    'co.in': 'IN', 'net.in': 'IN', 'org.in': 'IN', 'firm.in': 'IN', 'ind.in': 'IN',
    'com.br': 'BR', 'net.br': 'BR', 'org.br': 'BR',
    'co.za': 'ZA', 'org.za': 'ZA', 'web.za': 'ZA',
    'com.mx': 'MX', 'org.mx': 'MX',
    'co.jp': 'JP', 'ne.jp': 'JP', 'or.jp': 'JP',
    'com.sg': 'SG', 'edu.sg': 'SG',
    'com.my': 'MY', 'edu.my': 'MY',
    'co.id': 'ID', 'web.id': 'ID',
    'com.ng': 'NG', 'gov.ng': 'NG',
    'co.ke': 'KE', 'or.ke': 'KE',
    'com.eg': 'EG', 'edu.eg': 'EG',
    'com.tr': 'TR', 'org.tr': 'TR',
    'co.th': 'TH', 'in.th': 'TH',
    'com.vn': 'VN', 'edu.vn': 'VN',
    'com.ph': 'PH', 'gov.ph': 'PH',
    'com.sa': 'SA', 'med.sa': 'SA',
    'com.ae': 'AE', 'net.ae': 'AE',
    'com.ar': 'AR', 'net.ar': 'AR',
    'com.co': 'CO', 'net.co': 'CO',
    'com.ua': 'UA', 'net.ua': 'UA',

    # Primary Country Code Top-Level Domains (ccTLDs)
    'ac': 'AC', 'ad': 'AD', 'ae': 'AE', 'af': 'AF', 'ag': 'AG', 'ai': 'AI', 'al': 'AL', 'am': 'AM',
    'ao': 'AO', 'aq': 'AQ', 'ar': 'AR', 'as': 'AS', 'at': 'AT', 'au': 'AU', 'aw': 'AW', 'ax': 'AX',
    'az': 'AZ', 'ba': 'BA', 'bb': 'BB', 'bd': 'BD', 'be': 'BE', 'bf': 'BF', 'bg': 'BG', 'bh': 'BH',
    'bi': 'BI', 'bj': 'BJ', 'bm': 'BM', 'bn': 'BN', 'bo': 'BO', 'br': 'BR', 'bs': 'BS', 'bt': 'BT',
    'bw': 'BW', 'by': 'BY', 'bz': 'BZ', 'ca': 'CA', 'cc': 'CC', 'cd': 'CD', 'cf': 'CF', 'cg': 'CG',
    'ch': 'CH', 'ci': 'CI', 'ck': 'CK', 'cl': 'CL', 'cm': 'CM', 'cn': 'CN', 'co': 'CO', 'cr': 'CR',
    'cu': 'CU', 'cv': 'CV', 'cw': 'CW', 'cx': 'CX', 'cy': 'CY', 'cz': 'CZ', 'de': 'DE', 'dj': 'DJ',
    'dk': 'DK', 'dm': 'DM', 'do': 'DO', 'dz': 'DZ', 'ec': 'EC', 'ee': 'EE', 'eg': 'EG', 'er': 'ER',
    'es': 'ES', 'et': 'ET', 'fi': 'FI', 'fj': 'FJ', 'fk': 'FK', 'fm': 'FM', 'fo': 'FO', 'fr': 'FR',
    'ga': 'GA', 'gb': 'GB', 'gd': 'GD', 'ge': 'GE', 'gf': 'GF', 'gg': 'GG', 'gh': 'GH', 'gi': 'GI',
    'gl': 'GL', 'gm': 'GM', 'gn': 'GN', 'gp': 'GP', 'gq': 'GQ', 'gr': 'GR', 'gt': 'GT', 'gu': 'GU',
    'gw': 'GW', 'gy': 'GY', 'hk': 'HK', 'hn': 'HN', 'hr': 'HR', 'ht': 'HT', 'hu': 'HU', 'id': 'ID',
    'ie': 'IE', 'il': 'IL', 'im': 'IM', 'in': 'IN', 'io': 'IO', 'iq': 'IQ', 'ir': 'IR', 'is': 'IS',
    'it': 'IT', 'je': 'JE', 'jm': 'JM', 'jo': 'JO', 'jp': 'JP', 'ke': 'KE', 'kg': 'KG', 'kh': 'KH',
    'ki': 'KI', 'km': 'KM', 'kn': 'KN', 'kp': 'KP', 'kr': 'KR', 'kw': 'KW', 'ky': 'KY', 'kz': 'KZ',
    'la': 'LA', 'lb': 'LB', 'lc': 'LC', 'li': 'LI', 'lk': 'LK', 'lr': 'LR', 'ls': 'LS', 'lt': 'LT',
    'lu': 'LU', 'lv': 'LV', 'ly': 'LY', 'ma': 'MA', 'mc': 'MC', 'md': 'MD', 'me': 'ME', 'mg': 'MG',
    'mh': 'MH', 'mk': 'MK', 'ml': 'ML', 'mm': 'MM', 'mn': 'MN', 'mo': 'MO', 'mp': 'MP', 'mq': 'MQ',
    'mr': 'MR', 'ms': 'MS', 'mt': 'MT', 'mu': 'MU', 'mv': 'MV', 'mw': 'MW', 'mx': 'MX', 'my': 'MY',
    'mz': 'MZ', 'na': 'NA', 'nc': 'NC', 'ne': 'NE', 'nf': 'NF', 'ng': 'NG', 'ni': 'NI', 'nl': 'NL',
    'no': 'NO', 'np': 'NP', 'nr': 'NR', 'nu': 'NU', 'nz': 'NZ', 'om': 'OM', 'pa': 'PA', 'pe': 'PE',
    'pf': 'PF', 'pg': 'PG', 'ph': 'PH', 'pk': 'PK', 'pl': 'PL', 'pm': 'PM', 'pn': 'PN', 'pr': 'PR',
    'ps': 'PS', 'pt': 'PT', 'pw': 'PW', 'py': 'PY', 'qa': 'QA', 're': 'RE', 'ro': 'RO', 'rs': 'RS',
    'ru': 'RU', 'rw': 'RW', 'sa': 'SA', 'sb': 'SB', 'sc': 'SC', 'sd': 'SD', 'se': 'SE', 'sg': 'SG',
    'sh': 'SH', 'si': 'SI', 'sk': 'SK', 'sl': 'SL', 'sm': 'SM', 'sn': 'SN', 'so': 'SO', 'sr': 'SR',
    'ss': 'SS', 'st': 'ST', 'sv': 'SV', 'sx': 'SX', 'sy': 'SY', 'sz': 'SZ', 'tc': 'TC', 'td': 'TD',
    'tf': 'TF', 'tg': 'TG', 'th': 'TH', 'tj': 'TJ', 'tk': 'TK', 'tl': 'TL', 'tm': 'TM', 'tn': 'TN',
    'to': 'TO', 'tr': 'TR', 'tt': 'TT', 'tv': 'TV', 'tw': 'TW', 'tz': 'TZ', 'ua': 'UA', 'ug': 'UG',
    'uk': 'GB', 'us': 'US', 'uy': 'UY', 'uz': 'UZ', 'va': 'VA', 'vc': 'VC', 've': 'VE', 'vg': 'VG',
    'vi': 'VI', 'vn': 'VN', 'vu': 'VU', 'wf': 'WF', 'ws': 'WS', 'ye': 'YE', 'yt': 'YT', 'za': 'ZA',
    'zm': 'ZM', 'zw': 'ZW'
}

# 2. Comprehensive Country Name, Alternate Name, State & City mapping
COUNTRY_NAME_MAP = {
    # PAKISTAN & Cities
    'pakistan': 'PK', 'islamabad': 'PK', 'karachi': 'PK', 'lahore': 'PK', 'rawalpindi': 'PK',
    'faisalabad': 'PK', 'multan': 'PK', 'peshawar': 'PK', 'quetta': 'PK', 'sialkot': 'PK',
    'gujranwala': 'PK', 'hyderabad': 'PK', 'abbottabad': 'PK', 'nathiagali': 'PK', 'murree': 'PK',
    'bahawalpur': 'PK', 'sargodha': 'PK', 'sukkur': 'PK', 'larkana': 'PK', 'sheikhupura': 'PK',
    'jhang': 'PK', 'rahim yar khan': 'PK', 'gujrat': 'PK', 'kasur': 'PK', 'mardan': 'PK',

    # UNITED KINGDOM & Cities
    'united kingdom': 'GB', 'uk': 'GB', 'great britain': 'GB', 'england': 'GB', 'scotland': 'GB', 'wales': 'GB',
    'northern ireland': 'GB', 'london': 'GB', 'manchester': 'GB', 'birmingham': 'GB', 'leeds': 'GB',
    'glasgow': 'GB', 'liverpool': 'GB', 'bristol': 'GB', 'sheffield': 'GB', 'edinburgh': 'GB',
    'cardiff': 'GB', 'belfast': 'GB', 'nottingham': 'GB', 'newcastle': 'GB', 'southampton': 'GB',
    'brighton': 'GB', 'leicester': 'GB', 'coventry': 'GB', 'hull': 'GB', 'stoke': 'GB',
    'plymouth': 'GB', 'derby': 'GB', 'reading': 'GB', 'wolverhampton': 'GB', 'didsbury': 'GB',

    # UNITED STATES & Major Cities / States
    'united states': 'US', 'usa': 'US', 'us': 'US', 'america': 'US', 'new york': 'US', 'los angeles': 'US',
    'chicago': 'US', 'houston': 'US', 'phoenix': 'US', 'philadelphia': 'US', 'san antonio': 'US',
    'san diego': 'US', 'dallas': 'US', 'san jose': 'US', 'austin': 'US', 'jacksonville': 'US',
    'fort worth': 'US', 'columbus': 'US', 'san francisco': 'US', 'charlotte': 'US', 'indianapolis': 'US',
    'seattle': 'US', 'denver': 'US', 'washington': 'US', 'boston': 'US', 'el paso': 'US',
    'nashville': 'US', 'detroit': 'US', 'oklahoma city': 'US', 'portland': 'US', 'las vegas': 'US',
    'memphis': 'US', 'louisville': 'US', 'baltimore': 'US', 'milwaukee': 'US', 'albuquerque': 'US',
    'tucson': 'US', 'fresno': 'US', 'sacramento': 'US', 'mesa': 'US', 'kansas city': 'US',
    'atlanta': 'US', 'miami': 'US', 'colorado': 'US', 'california': 'US', 'texas': 'US', 'florida': 'US',

    # CANADA & Cities / Provinces
    'canada': 'CA', 'toronto': 'CA', 'montreal': 'CA', 'vancouver': 'CA', 'calgary': 'CA',
    'edmonton': 'CA', 'ottawa': 'CA', 'winnipeg': 'CA', 'quebec': 'CA', 'hamilton': 'CA',
    'kitchener': 'CA', 'london ontario': 'CA', 'victoria': 'CA', 'halifax': 'CA', 'ontario': 'CA',

    # AUSTRALIA & Cities / States
    'australia': 'AU', 'sydney': 'AU', 'melbourne': 'AU', 'brisbane': 'AU', 'perth': 'AU',
    'adelaide': 'AU', 'gold coast': 'AU', 'canberra': 'AU', 'newcastle au': 'AU', 'sunshine coast': 'AU',
    'wollongong': 'AU', 'hobart': 'AU', 'geelong': 'AU', 'townsville': 'AU', 'cairns': 'AU',

    # INDIA & Cities
    'india': 'IN', 'mumbai': 'IN', 'delhi': 'IN', 'bangalore': 'IN', 'bengaluru': 'IN',
    'hyderabad in': 'IN', 'ahmedabad': 'IN', 'chennai': 'IN', 'kolkata': 'IN', 'surat': 'IN',
    'pune': 'IN', 'jaipur': 'IN', 'lucknow': 'IN', 'kanpur': 'IN', 'nagpur': 'IN',
    'indore': 'IN', 'thane': 'IN', 'bhopal': 'IN', 'visakhapatnam': 'IN', 'patna': 'IN',

    # GERMANY & Cities
    'germany': 'DE', 'deutschland': 'DE', 'berlin': 'DE', 'munich': 'DE', 'münchen': 'DE',
    'hamburg': 'DE', 'frankfurt': 'DE', 'cologne': 'DE', 'köln': 'DE', 'stuttgart': 'DE',
    'düsseldorf': 'DE', 'dortmund': 'DE', 'essen': 'DE', 'leipzig': 'DE', 'bremen': 'DE',

    # FRANCE & Cities
    'france': 'FR', 'paris': 'FR', 'marseille': 'FR', 'lyon': 'FR', 'toulouse': 'FR',
    'nice': 'FR', 'nantes': 'FR', 'montpellier': 'FR', 'strasbourg': 'FR', 'bordeaux': 'FR',

    # SPAIN & Cities
    'spain': 'ES', 'españa': 'ES', 'madrid': 'ES', 'barcelona': 'ES', 'valencia': 'ES',
    'seville': 'ES', 'sevilla': 'ES', 'zaragoza': 'ES', 'malaga': 'ES', 'málaga': 'ES', 'murcia': 'ES',

    # ITALY & Cities
    'italy': 'IT', 'italia': 'IT', 'rome': 'IT', 'roma': 'IT', 'milan': 'IT', 'milano': 'IT',
    'naples': 'IT', 'napoli': 'IT', 'turin': 'IT', 'torino': 'IT', 'palermo': 'IT', 'florence': 'IT', 'firenze': 'IT',

    # UNITED ARAB EMIRATES & Cities
    'united arab emirates': 'AE', 'uae': 'AE', 'dubai': 'AE', 'abu dhabi': 'AE', 'sharjah': 'AE',
    'al ain': 'AE', 'ajman': 'AE', 'ras al khaimah': 'AE', 'fujairah': 'AE',

    # SAUDI ARABIA & Cities
    'saudi arabia': 'SA', 'ksa': 'SA', 'riyadh': 'SA', 'jeddah': 'SA', 'mecca': 'SA',
    'medina': 'SA', 'dammam': 'SA', 'khobar': 'SA', 'tabuk': 'SA',

    # TURKEY / TÜRKİYE & Cities
    'turkey': 'TR', 'türkiye': 'TR', 'istanbul': 'TR', 'ankara': 'TR', 'izmir': 'TR',
    'bursa': 'TR', 'antalya': 'TR', 'adana': 'TR', 'gaziantep': 'TR',

    # NETHERLANDS & Cities
    'netherlands': 'NL', 'holland': 'NL', 'amsterdam': 'NL', 'rotterdam': 'NL', 'the hague': 'NL',
    'utrecht': 'NL', 'eindhoven': 'NL', 'groningen': 'NL',

    # BRAZIL & Cities
    'brazil': 'BR', 'brasil': 'BR', 'são paulo': 'BR', 'sao paulo': 'BR', 'rio de janeiro': 'BR',
    'brasilia': 'BR', 'salvador': 'BR', 'fortaleza': 'BR', 'belo horizonte': 'BR',

    # MEXICO & Cities
    'mexico': 'MX', 'méxico': 'MX', 'mexico city': 'MX', 'guadalajara': 'MX', 'monterrey': 'MX',
    'puebla': 'MX', 'tijuana': 'MX', 'cancun': 'MX', 'cancún': 'MX',

    # JAPAN & Cities
    'japan': 'JP', 'tokyo': 'JP', 'yokohama': 'JP', 'osaka': 'JP', 'nagoya': 'JP',
    'sapporo': 'JP', 'kobe': 'JP', 'kyoto': 'JP', 'fukuoka': 'JP',

    # CHINA & Cities
    'china': 'CN', 'beijing': 'CN', 'shanghai': 'CN', 'guangzhou': 'CN', 'shenzhen': 'CN',
    'chengdu': 'CN', 'wuhan': 'CN', 'hangzhou': 'CN', 'chongqing': 'CN',

    # OTHER MAJOR COUNTRIES
    'singapore': 'SG',
    'malaysia': 'MY', 'kuala lumpur': 'MY',
    'thailand': 'TH', 'bangkok': 'TH',
    'vietnam': 'VN', 'ho chi minh': 'VN', 'hanoi': 'VN',
    'indonesia': 'ID', 'jakarta': 'ID', 'bali': 'ID',
    'philippines': 'PH', 'manila': 'PH',
    'south korea': 'KR', 'korea': 'KR', 'seoul': 'KR',
    'south africa': 'ZA', 'johannesburg': 'ZA', 'cape town': 'ZA', 'durban': 'ZA',
    'egypt': 'EG', 'cairo': 'EG', 'alexandria': 'EG',
    'nigeria': 'NG', 'lagos': 'NG', 'abuja': 'NG',
    'kenya': 'KE', 'nairobi': 'KE',
    'new zealand': 'NZ', 'auckland': 'NZ', 'wellington': 'NZ', 'christchurch': 'NZ',
    'ireland': 'IE', 'dublin': 'IE', 'cork': 'IE',
    'switzerland': 'CH', 'zurich': 'CH', 'geneva': 'CH',
    'austria': 'AT', 'vienna': 'AT',
    'sweden': 'SE', 'stockholm': 'SE',
    'norway': 'NO', 'oslo': 'NO',
    'denmark': 'DK', 'copenhagen': 'DK',
    'finland': 'FI', 'helsinki': 'FI', 'tampere': 'FI',
    'poland': 'PL', 'warsaw': 'PL', 'krakow': 'PL',
    'portugal': 'PT', 'lisbon': 'PT', 'porto': 'PT',
    'greece': 'GR', 'athens': 'GR',
    'russia': 'RU', 'moscow': 'RU', 'saint petersburg': 'RU',
    'argentina': 'AR', 'buenos aires': 'AR',
    'chile': 'CL', 'santiago': 'CL',
    'colombia': 'CO', 'bogota': 'CO',
    'peru': 'PE', 'lima': 'PE',
    'qatar': 'QA', 'doha': 'QA',
    'kuwait': 'KW', 'kuwait city': 'KW',
    'oman': 'OM', 'muscat': 'OM', 'bahrain': 'BH', 'manama': 'BH'
}

def infer_country_code(address="N/A", query="N/A", site_url=None):
    """
    Infer 2-letter ISO country code from Google Maps address, website TLD, or search query.
    """
    # 1. Check Google Maps address text
    if address and address != "N/A":
        addr_lower = address.lower()
        for k, cc in COUNTRY_NAME_MAP.items():
            if re.search(r'\b' + re.escape(k) + r'\b', addr_lower):
                return cc

    # 2. Check website domain TLD (e.g. .co.uk, .com.au, .pk)
    if site_url:
        try:
            domain = urlparse(site_url).netloc.lower()
            # Try 2-part TLD first e.g. co.uk, com.au
            parts = domain.split('.')
            if len(parts) >= 2:
                two_part_tld = f"{parts[-2]}.{parts[-1]}"
                if two_part_tld in ALL_CCTLD_MAP:
                    return ALL_CCTLD_MAP[two_part_tld]
            
            # Single part TLD e.g. .pk, .de
            single_tld = parts[-1]
            if single_tld in ALL_CCTLD_MAP:
                return ALL_CCTLD_MAP[single_tld]
        except Exception:
            pass

    # 3. Check search query string
    if query and query != "N/A":
        q_lower = query.lower()
        for k, cc in COUNTRY_NAME_MAP.items():
            if re.search(r'\b' + re.escape(k) + r'\b', q_lower):
                return cc

    return "US"

import phonenumbers

def format_and_validate_phone(raw_phone, default_country="US", site_url=None, address=None, query=None):
    """
    Parse, validate, and format phone numbers into international standard format using phonenumbers library.
    Returns formatted phone string if valid, otherwise None.
    """
    if not raw_phone or not isinstance(raw_phone, str):
        return None

    clean_raw = raw_phone.strip()
    country_code = infer_country_code(address=address, query=query, site_url=site_url) or default_country.upper()

    try:
        parsed = phonenumbers.parse(clean_raw, country_code)
        if phonenumbers.is_possible_number(parsed) and phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    except Exception:
        pass

    digit_count = len(re.sub(r'[^\d]', '', clean_raw))
    if clean_raw.startswith('+') and 9 <= digit_count <= 15:
        return clean_raw

    return None
