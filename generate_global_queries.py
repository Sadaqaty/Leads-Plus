#!/usr/bin/env python3
"""
Global Google Maps Query Generator
-----------------------------------
Generates a comprehensive queries.txt containing business search queries 
spanning all business categories across major cities and countries worldwide.

Usage:
  python generate_global_queries.py              # Generates full queries.txt
  python generate_global_queries.py --output my_queries.txt
"""

import os
import sys
import argparse

# ──────────────────────────────────────────────────────────────
# 1. EXHAUSTIVE BUSINESS TYPES & CATEGORIES (100+ Categories)
# ──────────────────────────────────────────────────────────────

BUSINESS_TYPES = [
    # Dental & Healthcare
    "Dentist", "Orthodontist", "Cosmetic Dentist", "Pediatric Dentist",
    "General Practitioner", "Dermatologist", "Pediatrician", "Optometrist",
    "Chiropractor", "Physiotherapist", "Veterinary Clinic", "Pharmacy",
    "Medical Clinic", "Urgent Care Center", "Cardiologist", "Psychiatrist",
    
    # Legal & Financial Services
    "Law Firm", "Criminal Defense Lawyer", "Family Lawyer", "Corporate Law Firm",
    "Personal Injury Lawyer", "Accountant", "Tax Consultant", "Financial Advisor",
    "Insurance Agency", "Mortgage Broker", "Auditing Firm", "Bookkeeping Service",
    
    # Home & Trade Services
    "Plumber", "Electrician", "HVAC Contractor", "Roofing Contractor",
    "Solar Panel Installer", "General Contractor", "Painter", "Pest Control",
    "Cleaning Service", "Locksmith", "Landscaping Service", "Tree Service",
    "Carpet Cleaning Service", "Appliance Repair Service", "Window Cleaning Service",
    
    # Real Estate & Property
    "Real Estate Agency", "Property Management Company", "Commercial Real Estate Agency",
    "Home Inspector", "Interior Designer", "Architecture Firm", "Surveyor",
    
    # Automotive
    "Auto Repair Shop", "Car Dealership", "Auto Detailing Service", "Car Body Shop",
    "Car Rental Agency", "Towing Service", "Auto Parts Store", "Tire Shop",
    
    # Personal Care & Beauty
    "Hair Salon", "Barber Shop", "Beauty Salon", "Nail Salon",
    "Spa & Wellness Center", "Massage Therapist", "Tattoo Parlor", "Laser Hair Removal Clinic",
    
    # Fitness & Leisure
    "Gym", "Yoga Studio", "Personal Trainer", "Martial Arts School",
    "Pilates Studio", "CrossFit Gym", "Dance Studio",
    
    # Hospitality & Food
    "Restaurant", "Cafe", "Bakery", "Catering Service", "Bar", "Pub",
    "Hotel", "Hostel", "Boutique Hotel", "Coffee Shop",
    
    # Technology & Business Services
    "Digital Marketing Agency", "Web Design Agency", "Software Development Company",
    "IT Support Company", "Printing Service", "Staffing Agency", "Security Guard Service",
    "Logistics Company", "Freight Forwarder", "Coworking Space", "Sign Shop",
    
    # Retail & Specialty Stores
    "Jewelry Store", "Furniture Store", "Clothing Store", "Pet Shop",
    "Flower Shop", "Electronics Store", "Bicycle Shop", "Hardware Store",
    
    # Education & Childcare
    "Private School", "Tutoring Center", "Driving School", "Daycare Center",
    "Language School", "Music School"
]

# ──────────────────────────────────────────────────────────────
# 2. GLOBAL CITIES & COUNTRIES COVERAGE (250+ Major World Hubs)
# ──────────────────────────────────────────────────────────────

GLOBAL_LOCATIONS = [
    # United States
    ("New York", "United States"), ("Los Angeles", "United States"), ("Chicago", "United States"),
    ("Houston", "United States"), ("Phoenix", "United States"), ("Philadelphia", "United States"),
    ("San Antonio", "United States"), ("San Diego", "United States"), ("Dallas", "United States"),
    ("San Jose", "United States"), ("Austin", "United States"), ("Jacksonville", "United States"),
    ("San Francisco", "United States"), ("Columbus", "United States"), ("Indianapolis", "United States"),
    ("Fort Worth", "United States"), ("Charlotte", "United States"), ("Seattle", "United States"),
    ("Denver", "United States"), ("Washington", "United States"), ("Boston", "United States"),
    ("El Paso", "United States"), ("Nashville", "United States"), ("Detroit", "United States"),
    ("Oklahoma City", "United States"), ("Portland", "United States"), ("Las Vegas", "United States"),
    ("Memphis", "United States"), ("Louisville", "United States"), ("Baltimore", "United States"),
    ("Milwaukee", "United States"), ("Albuquerque", "United States"), ("Tucson", "United States"),
    ("Fresno", "United States"), ("Sacramento", "United States"), ("Atlanta", "United States"),
    ("Miami", "United States"), ("Tampa", "United States"), ("Orlando", "United States"),
    ("Minneapolis", "United States"), ("Kansas City", "United States"), ("Raleigh", "United States"),
    
    # United Kingdom
    ("London", "United Kingdom"), ("Birmingham", "United Kingdom"), ("Glasgow", "United Kingdom"),
    ("Manchester", "United Kingdom"), ("Liverpool", "United Kingdom"), ("Bristol", "United Kingdom"),
    ("Edinburgh", "United Kingdom"), ("Leeds", "United Kingdom"), ("Sheffield", "United Kingdom"),
    ("Leicester", "United Kingdom"), ("Coventry", "United Kingdom"), ("Bradford", "United Kingdom"),
    ("Cardiff", "United Kingdom"), ("Belfast", "United Kingdom"), ("Nottingham", "United Kingdom"),
    ("Newcastle", "United Kingdom"), ("Hull", "United Kingdom"), ("Plymouth", "United Kingdom"),

    # Canada
    ("Toronto", "Canada"), ("Montreal", "Canada"), ("Vancouver", "Canada"),
    ("Calgary", "Canada"), ("Edmonton", "Canada"), ("Ottawa", "Canada"),
    ("Winnipeg", "Canada"), ("Quebec City", "Canada"), ("Hamilton", "Canada"),

    # Australia & New Zealand
    ("Sydney", "Australia"), ("Melbourne", "Australia"), ("Brisbane", "Australia"),
    ("Perth", "Australia"), ("Adelaide", "Australia"), ("Gold Coast", "Australia"),
    ("Canberra", "Australia"), ("Auckland", "New Zealand"), ("Wellington", "New Zealand"),

    # Germany
    ("Berlin", "Germany"), ("Hamburg", "Germany"), ("Munich", "Germany"),
    ("Cologne", "Germany"), ("Frankfurt", "Germany"), ("Stuttgart", "Germany"),
    ("Düsseldorf", "Germany"), ("Leipzig", "Germany"), ("Dortmund", "Germany"),

    # France
    ("Paris", "France"), ("Marseille", "France"), ("Lyon", "France"),
    ("Toulouse", "France"), ("Nice", "France"), ("Nantes", "France"),
    ("Montpellier", "France"), ("Strasbourg", "France"), ("Bordeaux", "France"),

    # Spain & Italy
    ("Madrid", "Spain"), ("Barcelona", "Spain"), ("Valencia", "Spain"),
    ("Seville", "Spain"), ("Malaga", "Spain"), ("Rome", "Italy"),
    ("Milan", "Italy"), ("Naples", "Italy"), ("Turin", "Italy"), ("Florence", "Italy"),

    # UAE & Middle East
    ("Dubai", "United Arab Emirates"), ("Abu Dhabi", "United Arab Emirates"),
    ("Sharjah", "United Arab Emirates"), ("Riyadh", "Saudi Arabia"),
    ("Jeddah", "Saudi Arabia"), ("Dammam", "Saudi Arabia"), ("Doha", "Qatar"),
    ("Kuwait City", "Kuwait"), ("Muscat", "Oman"), ("Manama", "Bahrain"),
    ("Istanbul", "Turkey"), ("Ankara", "Turkey"), ("Izmir", "Turkey"),
    ("Amman", "Jordan"), ("Beirut", "Lebanon"), ("Cairo", "Egypt"),

    # Pakistan & India & South Asia
    ("Karachi", "Pakistan"), ("Lahore", "Pakistan"), ("Islamabad", "Pakistan"),
    ("Rawalpindi", "Pakistan"), ("Peshawar", "Pakistan"), ("Faisalabad", "Pakistan"),
    ("Multan", "Pakistan"), ("Gujranwala", "Pakistan"), ("Sialkot", "Pakistan"),
    ("Mumbai", "India"), ("Delhi", "India"), ("Bangalore", "India"),
    ("Hyderabad", "India"), ("Ahmedabad", "India"), ("Chennai", "India"),
    ("Kolkata", "India"), ("Surat", "India"), ("Pune", "India"), ("Jaipur", "India"),
    ("Dhaka", "Bangladesh"), ("Chittagong", "Bangladesh"), ("Colombo", "Sri Lanka"),

    # East & Southeast Asia
    ("Tokyo", "Japan"), ("Yokohama", "Japan"), ("Osaka", "Japan"), ("Nagoya", "Japan"),
    ("Seoul", "South Korea"), ("Busan", "South Korea"), ("Singapore", "Singapore"),
    ("Hong Kong", "Hong Kong"), ("Taipei", "Taiwan"), ("Bangkok", "Thailand"),
    ("Jakarta", "Indonesia"), ("Kuala Lumpur", "Malaysia"), ("Manila", "Philippines"),
    ("Ho Chi Minh City", "Vietnam"), ("Hanoi", "Vietnam"),

    # Latin America
    ("Sao Paulo", "Brazil"), ("Rio de Janeiro", "Brazil"), ("Brasilia", "Brazil"),
    ("Mexico City", "Mexico"), ("Guadalajara", "Mexico"), ("Monterrey", "Mexico"),
    ("Buenos Aires", "Argentina"), ("Bogota", "Colombia"), ("Lima", "Peru"),
    ("Santiago", "Chile"), ("Caracas", "Venezuela"),

    # Africa & Other Regions
    ("Johannesburg", "South Africa"), ("Cape Town", "South Africa"), ("Durban", "South Africa"),
    ("Lagos", "Nigeria"), ("Abuja", "Nigeria"), ("Nairobi", "Kenya"),
    ("Casablanca", "Morocco"), ("Accra", "Ghana")
]

def generate_global_queries(output_file="queries.txt", max_queries=None):
    print(f"🌐 Generating global business search queries across {len(BUSINESS_TYPES)} categories and {len(GLOBAL_LOCATIONS)} global locations...")
    
    queries = []
    seen = set()

    for biz in BUSINESS_TYPES:
        for city, country in GLOBAL_LOCATIONS:
            query = f"{biz} in {city}, {country}"
            if query not in seen:
                seen.add(query)
                queries.append(query)
                if max_queries and len(queries) >= max_queries:
                    break
        if max_queries and len(queries) >= max_queries:
            break

    # Write queries to output file
    with open(output_file, "w", encoding="utf-8") as f:
        for q in queries:
            f.write(f"{q}\n")

    print("\n" + "=" * 70)
    print(f" ✅ Query Generation Complete!")
    print(f" 📊 Total Unique Queries Generated: {len(queries):,}")
    print(f" 📂 Saved to File: {os.path.abspath(output_file)}")
    print("=" * 70 + "\n")

def main():
    parser = argparse.ArgumentParser(description="Global Google Maps Search Query Generator")
    parser.add_argument("--output", "-o", default="queries.txt", help="Output file path (default: queries.txt)")
    parser.add_argument("--limit", "-l", type=int, default=None, help="Limit number of generated queries (optional)")
    args = parser.parse_args()

    generate_global_queries(output_file=args.output, max_queries=args.limit)

if __name__ == "__main__":
    main()
