import os
import sys
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

    # Fetch leads where latitude is null, empty, or 'N/A'
    res = supabase.table("leads").select("place_id, address, name").execute()
    all_leads = res.data if res.data else []

    missing_coords = [
        lead for lead in all_leads 
        if lead.get("address") and lead.get("address") != "N/A" and 
        (not lead.get("latitude") or str(lead.get("latitude")).strip() in ["N/A", "", "None"])
    ]

    total = len(missing_coords)
    logger.info(f"Found {total} leads in Supabase needing geocoding enrichment.")

    for idx, lead in enumerate(missing_coords, 1):
        place_id = lead.get("place_id")
        address = lead.get("address")
        name = lead.get("name")

        try:
            logger.info(f"[{idx}/{total}] Geocoding: {name} | Address: {address}")
            location = geolocator.geocode(address, timeout=10)
            
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
                logger.warning(f" Could not resolve coordinates for address: {address}")

            # Sleep 1s to respect Nominatim API rate usage guidelines
            time.sleep(1)

        except Exception as e:
            logger.error(f"Failed to geocode {name} ({place_id}): {e}")
            time.sleep(1)

    logger.info("Batch Supabase geocoding enrichment completed!")

if __name__ == "__main__":
    geocode_supabase_leads()
