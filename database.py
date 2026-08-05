import os
import sys
import sqlite3
import logging
import traceback
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# Suppress verbose HTTP request logs from httpx and httpcore
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

class DatabaseManager:
    """
    Supabase Database Manager for LeadPulse Enterprise.
    Supports both remote Supabase cloud storage (primary) and local SQLite fallback.
    """
    def __init__(self, db_path=None):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.db_path = os.path.abspath(db_path) if db_path else os.path.join(base_dir, "leads.db")
        
        # Load Supabase credentials from env or config file
        self.supabase_url = os.getenv("SUPABASE_URL", "")
        self.supabase_key = os.getenv("SUPABASE_KEY", "")
        
        possible_config_paths = [
            os.path.join(base_dir, "config.env"),
            os.path.join(os.getcwd(), "config.env"),
            os.path.expanduser("~/config.env")
        ]
        if hasattr(sys, '_MEIPASS'):
            possible_config_paths.append(os.path.join(sys._MEIPASS, "config.env"))

        for config_path in possible_config_paths:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            if k.strip() == "SUPABASE_URL" and not self.supabase_url:
                                self.supabase_url = v.strip()
                            elif k.strip() == "SUPABASE_KEY" and not self.supabase_key:
                                self.supabase_key = v.strip()
                if self.supabase_url and self.supabase_key:
                    break

        self.supabase: Client = None
        self.is_supabase_connected = False
        
        # Try initializing Supabase client
        if self.supabase_url and self.supabase_key and "your-project-id" not in self.supabase_url:
            try:
                self.supabase = create_client(self.supabase_url, self.supabase_key)
                self.is_supabase_connected = True
                logger.info("Connected to Supabase Cloud Database.")
            except Exception as e:
                logger.warning(f"Supabase connection failed: {e}. Falling back to SQLite.")
                self.is_supabase_connected = False

        # Always initialize local SQLite database as fallback/cache
        self._init_local_db()

    def _init_local_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS leads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        place_id TEXT UNIQUE,
                        name TEXT,
                        query TEXT,
                        is_spending_on_ads TEXT,
                        reviews TEXT,
                        rating TEXT,
                        first_review TEXT,
                        website TEXT,
                        phone TEXT,
                        can_claim TEXT,
                        email TEXT,
                        linkedin TEXT,
                        twitter TEXT,
                        facebook TEXT,
                        youtube TEXT,
                        instagram TEXT,
                        owner_name TEXT,
                        main_category TEXT,
                        workday_timing TEXT,
                        is_temporarily_closed TEXT,
                        address TEXT,
                        latitude TEXT,
                        longitude TEXT,
                        review_keywords TEXT,
                        link TEXT,
                        contacts_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS contacts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        lead_place_id TEXT,
                        name TEXT,
                        role TEXT,
                        email TEXT,
                        phone TEXT,
                        linkedin TEXT,
                        FOREIGN KEY (lead_place_id) REFERENCES leads (place_id)
                    )
                """)
                
                # Auto-migrate: ensure any newly added columns exist in SQLite leads table
                cursor.execute("PRAGMA table_info(leads)")
                existing_cols = {c[1] for c in cursor.fetchall()}
                expected_cols = {
                    "place_id": "TEXT", "name": "TEXT", "query": "TEXT",
                    "is_spending_on_ads": "TEXT", "reviews": "TEXT", "rating": "TEXT",
                    "first_review": "TEXT", "website": "TEXT", "phone": "TEXT",
                    "can_claim": "TEXT", "email": "TEXT", "linkedin": "TEXT",
                    "twitter": "TEXT", "facebook": "TEXT", "youtube": "TEXT",
                    "instagram": "TEXT", "owner_name": "TEXT", "main_category": "TEXT",
                    "workday_timing": "TEXT", "is_temporarily_closed": "TEXT",
                    "address": "TEXT", "latitude": "TEXT", "longitude": "TEXT",
                    "review_keywords": "TEXT", "link": "TEXT", "contacts_count": "INTEGER DEFAULT 0",
                    "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                }
                for col, col_type in expected_cols.items():
                    if col not in existing_cols:
                        logger.info(f"Auto-migrating SQLite leads table: adding missing column '{col}'")
                        cursor.execute(f"ALTER TABLE leads ADD COLUMN {col} {col_type}")

                conn.commit()
        except Exception as e:
            logger.error(f"Local SQLite initialization failed: {e}")

    def insert_lead(self, lead_data):
        place_id = lead_data.get("place_id", "N/A")
        if not place_id or place_id == "N/A":
            logger.warning(f"Skipping lead with no place_id: {lead_data.get('name')}")
            return False

        fields = [
            "place_id", "name", "query", "is_spending_on_ads", "reviews", 
            "rating", "first_review", "website", "phone", "can_claim", 
            "email", "linkedin", "twitter", "facebook", "youtube", 
            "instagram", "owner_name", "main_category", "workday_timing", 
            "is_temporarily_closed", "address", "latitude", "longitude", "review_keywords", "link",
            "contacts_count"
        ]

        # 1. Push to Supabase if connected
        if self.is_supabase_connected:
            try:
                res = self.supabase.table("leads").select("*").eq("place_id", place_id).execute()
                existing = res.data[0] if res.data else None
                
                if existing:
                    merged = {}
                    for f in fields:
                        new_val = lead_data.get(f, "N/A")
                        old_val = existing.get(f, "N/A")
                        if f == "email":
                            new_emails = [e.strip() for e in str(new_val).split(',') if e.strip() and e.strip() != "N/A"]
                            old_emails = [e.strip() for e in str(old_val).split(',') if e.strip() and e.strip() != "N/A"]
                            combined = list(dict.fromkeys(old_emails + new_emails))
                            merged["email"] = ", ".join(combined) if combined else "N/A"
                        elif str(new_val).strip() in ["N/A", "", "None", "0"] and str(old_val).strip() not in ["N/A", "", "None", "0"]:
                            merged[f] = old_val
                        else:
                            merged[f] = new_val
                    
                    try:
                        merged["contacts_count"] = int(merged["contacts_count"]) if str(merged.get("contacts_count")).strip() not in ["N/A", "", "None"] else 0
                    except (ValueError, TypeError):
                        merged["contacts_count"] = 0

                    self.supabase.table("leads").update(merged).eq("place_id", place_id).execute()
                    logger.info(f"Merged lead in Supabase: {lead_data.get('name')}")
                else:
                    clean_lead = {}
                    for f in fields:
                        val = lead_data.get(f, "N/A")
                        if f == "contacts_count":
                            try:
                                clean_lead[f] = int(val) if str(val).strip() not in ["N/A", "", "None"] else 0
                            except (ValueError, TypeError):
                                clean_lead[f] = 0
                        else:
                            clean_lead[f] = val

                    self.supabase.table("leads").insert(clean_lead).execute()
                    logger.info(f"Stored lead: {lead_data.get('name')}")
            except Exception as e:
                logger.error(f"lead insert failed: {e}. Falling back to local SQL.")

        # 2. Always persist locally
        return self._insert_lead_local(lead_data, fields, place_id)

    def get_existing_place_ids(self) -> set:
        """Fetch set of all place_ids already present in Supabase or local SQLite DB."""
        place_ids = set()
        if self.is_supabase_connected:
            try:
                start = 0
                step = 1000
                while True:
                    res = self.supabase.table("leads").select("place_id").range(start, start + step - 1).execute()
                    if not res or not res.data:
                        break
                    for row in res.data:
                        pid = row.get("place_id")
                        if pid and pid != "N/A":
                            place_ids.add(pid)
                    if len(res.data) < step:
                        break
                    start += step
            except Exception as e:
                logger.warning(f"Error fetching existing place_ids from Supabase: {e}")

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT place_id FROM leads WHERE place_id IS NOT NULL AND place_id != 'N/A'")
                rows = cursor.fetchall()
                for r in rows:
                    if r[0]:
                        place_ids.add(r[0])
        except Exception as e:
            logger.warning(f"Error fetching existing place_ids from local SQLite: {e}")

        return place_ids

    def _insert_lead_local(self, lead_data, fields, place_id):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM leads WHERE place_id = ?", (place_id,))
                existing = cursor.fetchone()

                if existing:
                    cursor.execute("PRAGMA table_info(leads)")
                    cols = [c[1] for c in cursor.fetchall()]
                    existing_dict = dict(zip(cols, existing))
                    merged_data = {}
                    for field in fields:
                        new_val = lead_data.get(field, "N/A")
                        old_val = existing_dict.get(field, "N/A")
                        if field == "email":
                            new_emails = [e.strip() for e in str(new_val).split(',') if e.strip() and e.strip() != "N/A"]
                            old_emails = [e.strip() for e in str(old_val).split(',') if e.strip() and e.strip() != "N/A"]
                            combined = list(dict.fromkeys(old_emails + new_emails))
                            merged_data["email"] = ", ".join(combined) if combined else "N/A"
                        elif str(new_val).strip() in ["N/A", "", "None", "0"] and str(old_val).strip() not in ["N/A", "", "None", "0"]:
                            merged_data[field] = old_val
                        else:
                            merged_data[field] = new_val
                    set_clause = ", ".join([f"{f} = ?" for f in fields])
                    query = f"UPDATE leads SET {set_clause} WHERE place_id = ?"
                    params = tuple(merged_data[f] for f in fields) + (place_id,)
                    cursor.execute(query, params)
                else:
                    placeholders = ", ".join(["?"] * len(fields))
                    columns = ", ".join(fields)
                    values = tuple(lead_data.get(field, "N/A") for field in fields)
                    cursor.execute(f"INSERT INTO leads ({columns}) VALUES ({placeholders})", values)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Local SQL insert failed: {e}")
            return False

    def insert_contact(self, contact_data):
        return self.insert_contacts([contact_data])

    def insert_contacts(self, contacts_list):
        """Bulk insert contacts into Supabase (single HTTP request) and local SQLite."""
        if not contacts_list:
            return True
            
        fields = ["lead_place_id", "name", "role", "email", "phone", "linkedin"]
        valid_contacts = []
        for c in contacts_list:
            lead_place_id = str(c.get("lead_place_id", "N/A")).strip()
            if lead_place_id and lead_place_id not in ["N/A", "", "None"]:
                clean = {f: c.get(f, "N/A") for f in fields}
                clean["lead_place_id"] = lead_place_id
                valid_contacts.append(clean)
                
        if not valid_contacts:
            return True

        if self.is_supabase_connected:
            try:
                self.supabase.table("contacts").insert(valid_contacts).execute()
            except Exception as e:
                logger.error(f"contacts bulk insert failed: {e}")

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                placeholders = ", ".join(["?"] * len(fields))
                columns = ", ".join(fields)
                tuples_list = [tuple(c[f] for f in fields) for c in valid_contacts]
                cursor.executemany(f"INSERT INTO contacts ({columns}) VALUES ({placeholders})", tuples_list)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Local contacts bulk insert failed: {e}")
            return False

    def get_stats(self):
        if self.is_supabase_connected:
            try:
                total_leads = self.supabase.table("leads").select("id", count="exact").execute().count or 0
                with_email = self.supabase.table("leads").select("id", count="exact").neq("email", "N/A").execute().count or 0
                with_phone = self.supabase.table("leads").select("id", count="exact").neq("phone", "N/A").execute().count or 0
                total_contacts = self.supabase.table("contacts").select("id", count="exact").execute().count or 0
                return {
                    "total_leads": total_leads,
                    "with_email": with_email,
                    "with_phone": with_phone,
                    "total_contacts": total_contacts
                }
            except Exception as e:
                logger.error(f"Supabase stats query failed: {e}")

        # SQLite Fallback
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM leads")
                total_leads = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM leads WHERE email IS NOT NULL AND email != 'N/A' AND email != ''")
                with_email = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM leads WHERE phone IS NOT NULL AND phone != 'N/A' AND phone != ''")
                with_phone = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM contacts")
                total_contacts = cursor.fetchone()[0]
                return {
                    "total_leads": total_leads,
                    "with_email": with_email,
                    "with_phone": with_phone,
                    "total_contacts": total_contacts
                }
        except Exception:
            return {"total_leads": 0, "with_email": 0, "with_phone": 0, "total_contacts": 0}

    def export_to_csv(self, filepath):
        """Export all leads stored in local SQLite database to CSV."""
        import csv
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM leads ORDER BY id DESC")
                rows = cursor.fetchall()
                if rows:
                    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
                    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                        writer = csv.writer(f)
                        headers = list(rows[0].keys())
                        writer.writerow(headers)
                        for r in rows:
                            writer.writerow(list(r))
                    logger.info(f"Exported {len(rows)} leads to CSV: {filepath}")
                    return True
        except Exception as e:
            logger.error(f"Failed to export CSV: {e}")
        return False

