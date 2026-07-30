import os
import glob
import csv
import logging
import argparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CombineCSVs")

# Standardized superset of all CSV columns
STANDARD_COLUMNS = [
    "place_id", "name", "query", "is_spending_on_ads", "reviews", "rating", 
    "first_review", "website", "phone", "can_claim", "email", "contacts_count", 
    "linkedin", "twitter", "facebook", "youtube", "instagram", "owner_name", 
    "owner_profile_link", "main_category", "categories", "workday_timing", 
    "is_temporarily_closed", "address", "review_keywords", "link"
]

def combine_csvs(directory=None, output_filename="mega_combined_leads.csv"):
    """
    Finds all CSV files in the target directory, merges them, removes duplicate entries
    by place_id and composite name+address, and writes a clean mega CSV.
    """
    base_dir = os.path.abspath(directory) if directory else os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(base_dir, output_filename)

    csv_pattern = os.path.join(base_dir, "*.csv")
    all_csv_files = [f for f in glob.glob(csv_pattern) if os.path.abspath(f) != output_path]

    if not all_csv_files:
        logger.error(f"No CSV files found in directory: {base_dir}")
        return False

    logger.info(f"Found {len(all_csv_files)} CSV files to merge from: {base_dir}")

    seen_place_ids = set()
    seen_name_address = set()
    combined_rows = []
    total_processed = 0
    duplicate_count = 0

    for filepath in sorted(all_csv_files):
        filename = os.path.basename(filepath)
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as fp:
                reader = csv.DictReader(fp)
                file_count = 0
                file_dups = 0

                for row in reader:
                    total_processed += 1
                    file_count += 1
                    
                    place_id = str(row.get("place_id", "")).strip()
                    name = str(row.get("name", "")).strip()
                    address = str(row.get("address", "")).strip()

                    # Deduplication logic
                    is_dup = False
                    if place_id and place_id != "N/A":
                        if place_id in seen_place_ids:
                            is_dup = True
                        else:
                            seen_place_ids.add(place_id)
                    
                    if not is_dup and name and name != "N/A" and address and address != "N/A":
                        name_addr_key = (name.lower(), address.lower())
                        if name_addr_key in seen_name_address:
                            is_dup = True
                        else:
                            seen_name_address.add(name_addr_key)

                    if is_dup:
                        duplicate_count += 1
                        file_dups += 1
                        continue

                    # Standardize row keys against STANDARD_COLUMNS
                    clean_row = {}
                    for col in STANDARD_COLUMNS:
                        val = row.get(col, "N/A")
                        clean_row[col] = val if val is not None and str(val).strip() != "" else "N/A"

                    combined_rows.append(clean_row)

                logger.info(f"Merged {filename}: {file_count - file_dups} unique leads added ({file_dups} duplicates skipped).")
        except Exception as e:
            logger.error(f"Error reading {filename}: {e}")

    # Write output mega CSV
    logger.info(f"Writing {len(combined_rows)} unique records to mega CSV: {output_path}")
    try:
        with open(output_path, "w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=STANDARD_COLUMNS)
            writer.writeheader()
            writer.writerows(combined_rows)
        
        logger.info("\n" + "="*50)
        logger.info("🎉 MEGA CSV COMBINATION COMPLETE!")
        logger.info(f"Total Source Rows Scanned : {total_processed}")
        logger.info(f"Total Duplicates Removed   : {duplicate_count}")
        logger.info(f"Final Unique Records       : {len(combined_rows)}")
        logger.info(f"Output Saved To            : {output_path}")
        logger.info("="*50)
        return True
    except Exception as e:
        logger.error(f"Failed to write output CSV: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Combine all CSV files in a folder into a deduplicated mega CSV.")
    parser.add_argument("--dir", type=str, default=None, help="Directory containing CSV files (default: project root)")
    parser.add_argument("--out", type=str, default="mega_combined_leads.csv", help="Output filename (default: mega_combined_leads.csv)")
    args = parser.parse_args()

    combine_csvs(args.dir, args.out)
