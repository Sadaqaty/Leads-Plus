import os
import sys
import re
import time
import logging
from geopy.geocoders import Nominatim
from database import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def geocode_supabase_leads():
    # Initialize DatabaseManager to automatically connect to Supabase
    db_manager = DatabaseManager()
    
    if not db_manager.is_supabase_connected:
        logger.error("Could not connect to Supabase Cloud Database. Check config.env credentials.")
        return

    supabase = db_manager.supabase
    geolocator = Nominatim(user_agent="map_the_map_geocoder")

    logger.info("Fetching leads missing latitude/longitude from Supabase...")

    # Fetch ALL leads using Supabase range pagination (Supabase caps single queries at 1,000)
    all_leads = []
    page_size = 1000
    start = 0

    while True:
        res = supabase.table("leads").select("place_id, address, name, latitude").range(start, start + page_size - 1).execute()
        data = res.data if res.data else []
        all_leads.extend(data)
        if len(data) < page_size:
            break
        start += page_size

    missing_coords = [
        lead for lead in all_leads 
        if lead.get("address") and lead.get("address") != "N/A" and 
        (not lead.get("latitude") or str(lead.get("latitude")).strip() in ["N/A", "", "None"])
    ]

    total = len(missing_coords)
    logger.info(f"Found {total} leads out of {len(all_leads)} total records in Supabase needing geocoding enrichment.")

    def clean_address_for_geocoding(raw_addr):
        if not raw_addr or raw_addr == "N/A":
            return ""
        # Remove unit/shop numbers at start (e.g. "shop 57/156 Inala Ave" -> "156 Inala Ave", "1/2281 Sandgate Rd" -> "2281 Sandgate Rd")
        addr = re.sub(r'^(?:Unit|Shop|Level|Suite)?\s*\d+[a-zA-Z]?\s*[/,-]\s*', '', raw_addr, flags=re.I)
        # Remove complex building prefix descriptions (e.g. "and walk past Ca-Phin to the end...")
        if " - " in addr:
            parts = addr.split(" - ")
            # Keep last 2-3 location components (street/city/country) which OSM understands
            addr = ", ".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
        return addr.strip()

    for idx, lead in enumerate(missing_coords, 1):
        place_id = lead.get("place_id")
        raw_address = lead.get("address")
        name = lead.get("name")
        cleaned_address = clean_address_for_geocoding(raw_address)

        try:
            logger.info(f"[{idx}/{total}] Geocoding: {name} | Search: {cleaned_address or raw_address}")
            
            # Try 1: Geocode cleaned address
            location = geolocator.geocode(cleaned_address, timeout=10) if cleaned_address else None
            
            # Try 2: Fallback to raw address
            if not location and cleaned_address != raw_address:
                location = geolocator.geocode(raw_address, timeout=10)
                
            # Try 3: Fallback to Name + City/Country from raw address
            if not location and "," in raw_address:
                city_part = ", ".join(raw_address.split(",")[-2:])
                location = geolocator.geocode(f"{name}, {city_part}", timeout=10)
            
            if location:
                lat_str = str(location.latitude)
                lng_str = str(location.longitude)
                
                # Directly update Supabase record
                supabase.table("leads").update({
                    "latitude": lat_str,
                    "longitude": lng_str
                }).eq("place_id", place_id).execute()

                logger.info(f" Successfully enriched {name} in Supabase -> Lat: {lat_str}, Lng: {lng_str}")
            else:
                logger.warning(f" Could not resolve coordinates for address: {raw_address}")

            # Sleep 1s to respect Nominatim API rate limits
            time.sleep(1)

        except Exception as e:
            logger.error(f"Failed to geocode {name} ({place_id}): {e}")
            time.sleep(1)

    logger.info("Batch Supabase geocoding enrichment completed!")

if __name__ == "__main__":
    geocode_supabase_leads()
