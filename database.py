import os
import sys
import sqlite3
import logging
import traceback
from supabase import create_client, Client

logger = logging.getLogger(__name__)

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
                logger.info("Successfully connected to Supabase Cloud Database.")
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
            "is_temporarily_closed", "address", "review_keywords", "link",
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
                    logger.info(f"Stored new lead in Supabase: {lead_data.get('name')}")
            except Exception as e:
                logger.error(f"Supabase lead insert failed: {e}. Falling back to local SQL.")

        # 2. Always persist locally
        return self._insert_lead_local(lead_data, fields, place_id)

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
        fields = ["lead_place_id", "name", "role", "email", "phone", "linkedin"]
        
        # Supabase push
        if self.is_supabase_connected:
            try:
                clean_contact = {f: contact_data.get(f, "N/A") for f in fields}
                self.supabase.table("contacts").insert(clean_contact).execute()
            except Exception as e:
                logger.error(f"Supabase contact insert failed: {e}")

        # Local SQLite
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                placeholders = ", ".join(["?"] * len(fields))
                columns = ", ".join(fields)
                values = tuple(contact_data.get(field, "N/A") for field in fields)
                cursor.execute(f"INSERT INTO contacts ({columns}) VALUES ({placeholders})", values)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Local contact insert failed: {e}")
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
