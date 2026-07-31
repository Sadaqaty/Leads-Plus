import os
import csv
import sqlite3
import logging
import argparse
from database import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MigrateToSupabase")

def migrate_to_supabase(csv_file=None, db_file=None, batch_size=25):
    """
    Import leads and contacts into Supabase Cloud Database.
    Prevents duplicates using UNIQUE constraints and Smart Merging:
    - If entry exists: Retains old data and enriches missing fields (e.g. emails, phones, socials).
    - If entry is new: Inserts clean record.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_manager = DatabaseManager()
    
    if not db_manager.is_supabase_connected:
        logger.error("Supabase connection is NOT active. Please configure SUPABASE_URL and SUPABASE_KEY in config.env first!")
        return False

    lead_fields = [
        "place_id", "name", "query", "is_spending_on_ads", "reviews", 
        "rating", "first_review", "website", "phone", "can_claim", 
        "email", "linkedin", "twitter", "facebook", "youtube", 
        "instagram", "owner_name", "main_category", "workday_timing", 
        "is_temporarily_closed", "address", "review_keywords", "link",
        "contacts_count"
    ]

    total_inserted = 0
    total_updated = 0
    total_skipped = 0

    # 1. Import from Mega CSV if provided
    csv_path = os.path.abspath(csv_file) if csv_file else os.path.join(base_dir, "mega_combined_leads.csv")
    if os.path.exists(csv_path):
        logger.info(f"Reading mega CSV file: {csv_path}")
        with open(csv_path, "r", encoding="utf-8", errors="ignore") as fp:
            reader = csv.DictReader(fp)
            rows = list(reader)
            logger.info(f"Found {len(rows)} records in mega CSV. Starting Smart-Merge Import to Supabase...")

            for i, row in enumerate(rows, 1):
                place_id = str(row.get("place_id", "")).strip()
                if not place_id or place_id == "N/A":
                    total_skipped += 1
                    continue

                try:
                    # Query existing entry in Supabase
                    res = db_manager.supabase.table("leads").select("*").eq("place_id", place_id).execute()
                    existing = res.data[0] if res.data else None

                    if existing:
                        # Smart Merge: Keep existing valid info and append new info where missing
                        merged = {}
                        has_changes = False
                        for field in lead_fields:
                            new_val = str(row.get(field, "N/A")).strip()
                            old_val = str(existing.get(field, "N/A")).strip()

                            if field == "email":
                                new_emails = [e.strip() for e in new_val.split(',') if e.strip() and e.strip() != "N/A"]
                                old_emails = [e.strip() for e in old_val.split(',') if e.strip() and e.strip() != "N/A"]
                                combined = list(dict.fromkeys(old_emails + new_emails))
                                merged["email"] = ", ".join(combined) if combined else "N/A"
                                if merged["email"] != old_val:
                                    has_changes = True
                            elif new_val not in ["N/A", "", "None", "0"] and old_val in ["N/A", "", "None", "0"]:
                                merged[field] = new_val
                                has_changes = True
                            else:
                                merged[field] = old_val

                        if has_changes:
                            if "contacts_count" in merged:
                                try:
                                    merged["contacts_count"] = int(merged["contacts_count"]) if str(merged["contacts_count"]).strip() not in ["N/A", "", "None"] else 0
                                except ValueError:
                                    merged["contacts_count"] = 0
                            db_manager.supabase.table("leads").update(merged).eq("place_id", place_id).execute()
                            total_updated += 1
                        else:
                            total_skipped += 1
                    else:
                        # Clean new entry insert
                        clean_row = {}
                        for f in lead_fields:
                            val = str(row.get(f, "N/A")).strip()
                            if f == "contacts_count":
                                try:
                                    clean_row[f] = int(val) if val not in ["N/A", "", "None"] else 0
                                except ValueError:
                                    clean_row[f] = 0
                            else:
                                clean_row[f] = val

                        db_manager.supabase.table("leads").insert(clean_row).execute()
                        total_inserted += 1

                    if i % batch_size == 0 or i == len(rows):
                        logger.info(f"Processed [{i}/{len(rows)}] CSV records (Inserted: {total_inserted}, Merged: {total_updated}, Skipped: {total_skipped})...")

                except Exception as e:
                    logger.warning(f"Error processing place_id '{place_id}': {e}")

    # 2. Also sync local SQLite contacts table if available
    sqlite_file = os.path.abspath(db_file) if db_file else os.path.join(base_dir, "leads.db")
    if os.path.exists(sqlite_file):
        try:
            conn = sqlite3.connect(sqlite_file)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM contacts")
            contacts_rows = cursor.fetchall()
            cursor.execute("PRAGMA table_info(contacts)")
            contact_cols = [c[1] for c in cursor.fetchall()]

            logger.info(f"Syncing {len(contacts_rows)} contacts from local DB to Supabase...")
            contact_fields = ["lead_place_id", "name", "role", "email", "phone", "linkedin"]

            for row in contacts_rows:
                row_dict = dict(zip(contact_cols, row))
                clean_contact = {f: str(row_dict.get(f, "N/A")).strip() for f in contact_fields}
                lead_place_id = clean_contact.get("lead_place_id", "N/A")
                if not lead_place_id or lead_place_id in ["N/A", "", "None"]:
                    continue
                try:
                    db_manager.supabase.table("contacts").insert(clean_contact).execute()
                except Exception as e:
                    logger.warning(f"Contact migration skipped for place_id '{lead_place_id}': {e}")
            conn.close()
        except Exception as e:
            logger.warning(f"Contacts sync warning: {e}")

    logger.info("\n" + "="*50)
    logger.info("🎉 SUPABASE SMART IMPORT & ENRICHMENT COMPLETE!")
    logger.info(f"New Leads Inserted : {total_inserted}")
    logger.info(f"Existing Leads Enriched: {total_updated}")
    logger.info(f"Duplicates Skipped  : {total_skipped}")
    logger.info("="*50)
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smart Import mega_combined_leads.csv into Supabase Cloud")
    parser.add_argument("--csv", type=str, default=None, help="Path to mega CSV file")
    parser.add_argument("--db", type=str, default=None, help="Path to local leads.db file")
    args = parser.parse_args()

    migrate_to_supabase(args.csv, args.db)
