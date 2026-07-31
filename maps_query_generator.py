#!/usr/bin/env python3
"""
Google Maps Query Generator (Python + OSMnx)
--------------------------------------------
Generates location‑specific search queries (e.g., "coffee shop in Brooklyn")
by combining a business type with every sub‑area (neighbourhood, suburb, district)
of a given city. Uses OpenStreetMap data via OSMnx – no API keys required.
"""

import os
import sys
import argparse
import json
from pathlib import Path

try:
    import osmnx as ox
    import geopandas as gpd
except ImportError:
    print("ERROR: Missing required libraries. Install with:")
    print("  pip install osmnx geopandas shapely matplotlib")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────
# 1.  AREA FETCHER  (OSMnx)
# ──────────────────────────────────────────────────────────────

def get_city_areas(city: str, state: str = None, country: str = None,
                   fallback_to_preset: bool = True) -> list:
    """
    Retrieve a list of unique sub‑area names (neighbourhoods, suburbs, quarters)
    within the given city using OpenStreetMap data.

    Uses `features_from_place` which handles city polygons automatically.
    """
    # Build a geocoding query string
    query_parts = [city]
    if state:
        query_parts.append(state)
    if country:
        query_parts.append(country)
    query = ", ".join(query_parts)

    print(f"🌍 Querying OSM for: '{query}' ...")

    # Define OSM tags for sub‑areas (adjustable)
    tags = {"place": ["neighbourhood", "suburb", "quarter", "city_block", "hamlet"]}

    try:
        # Directly get features from the place name
        features = ox.features_from_place(query, tags=tags)
    except Exception as e:
        print(f"⚠️  OSM feature download failed: {e}")
        return _fallback_areas(city) if fallback_to_preset else []

    if features.empty:
        print("⚠️  No sub‑areas found in OSM for this city.")
        return _fallback_areas(city) if fallback_to_preset else []

    # Extract unique names, dropping None/empty
    names = features["name"].dropna().unique().tolist()
    # Filter out very short or generic names
    names = [n.strip() for n in names if isinstance(n, str) and len(n) > 2]
    # Remove duplicates and sort
    unique_names = sorted(set(names))
    print(f"✅ Found {len(unique_names)} sub‑areas.")
    return unique_names

# ──────────────────────────────────────────────────────────────
# 2.  FALLBACK PRESETS (for offline / reliability)
# ──────────────────────────────────────────────────────────────

def _fallback_areas(city: str) -> list:
    """Hardcoded fallback for major cities when OSM fails."""
    presets = {
        "new york": [
            "Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island",
            "Harlem", "SoHo", "East Village", "Greenwich Village", "Chelsea",
            "Upper East Side", "Upper West Side", "Midtown", "Financial District",
            "Williamsburg", "Park Slope", "DUMBO", "Long Island City", "Astoria"
        ],
        "los angeles": [
            "Downtown LA", "Hollywood", "Santa Monica", "Venice", "Beverly Hills",
            "West Hollywood", "Silver Lake", "Echo Park", "Pasadena", "Glendale",
            "Burbank", "Long Beach", "Anaheim", "Irvine", "Santa Ana"
        ],
        "chicago": [
            "Loop", "River North", "West Loop", "Lincoln Park", "Lakeview",
            "Wicker Park", "Bucktown", "Logan Square", "Hyde Park", "South Loop",
            "Gold Coast", "Old Town", "Edgewater", "Rogers Park", "Pilsen"
        ],
        "san francisco": [
            "Downtown", "SoMa", "Mission District", "Haight-Ashbury", "Castro",
            "Noe Valley", "Bernal Heights", "Pacific Heights", "Marina District",
            "North Beach", "Chinatown", "Financial District", "Richmond District",
            "Sunset District", "Presidio"
        ],
        "london": [
            "Westminster", "Camden", "Islington", "Kensington", "Chelsea",
            "Mayfair", "Soho", "Covent Garden", "Shoreditch", "Hoxton",
            "Brixton", "Peckham", "Notting Hill", "Hampstead", "Greenwich"
        ],
        "paris": [
            "Le Marais", "Saint-Germain-des-Prés", "Latin Quarter", "Montmartre",
            "Belleville", "Canal Saint-Martin", "Oberkampf", "Bastille",
            "Champs-Élysées", "Trocadéro", "Eiffel Tower area", "République"
        ],
        "berlin": [
            "Mitte", "Kreuzberg", "Friedrichshain", "Prenzlauer Berg",
            "Neukölln", "Schöneberg", "Charlottenburg", "Wilmersdorf",
            "Tempelhof", "Treptow", "Köpenick", "Spandau"
        ],
        "tokyo": [
            "Shinjuku", "Shibuya", "Harajuku", "Akihabara", "Roppongi",
            "Ginza", "Asakusa", "Ueno", "Ikebukuro", "Ebisu",
            "Meguro", "Nakameguro", "Kichijoji", "Shimokitazawa", "Daikanyama"
        ],
        "sydney": [
            "CBD", "Surry Hills", "Newtown", "Paddington", "Bondi",
            "Coogee", "Manly", "Mosman", "North Sydney", "Chatswood",
            "Parramatta", "Blacktown", "Bankstown", "Hurstville", "Rhodes"
        ],
        "toronto": [
            "Downtown", "Yorkville", "Kensington Market", "Queen West",
            "King West", "Liberty Village", "The Annex", "Bloor West",
            "High Park", "Roncesvalles", "East York", "North York",
            "Scarborough", "Etobicoke", "York"
        ],
        "mumbai": [
            "South Mumbai", "Colaba", "Bandra", "Andheri", "Juhu",
            "Powai", "Goregaon", "Malad", "Kandivali", "Borivali",
            "Dadar", "Worli", "Lower Parel", "Kamala Mills", "BKC"
        ],
        "singapore": [
            "Marina Bay", "Orchard Road", "Chinatown", "Little India",
            "Kampong Glam", "Bugis", "Raffles Place", "Tanjong Pagar",
            "Sentosa", "Clarke Quay", "Robertson Quay", "East Coast"
        ],
        "dubai": [
            "Downtown Dubai", "Dubai Marina", "Jumeirah", "Palm Jumeirah",
            "Business Bay", "Deira", "Bur Dubai", "Al Barsha",
            "Jebel Ali", "Mirdif", "Al Qusais", "Al Nahda"
        ],
        "istanbul": [
            "Fatih", "Beyoğlu", "Beşiktaş", "Kadıköy", "Üsküdar",
            "Şişli", "Beylikdüzü", "Esenyurt", "Başakşehir", "Büyükçekmece",
            "Küçükçekmece", "Avcılar", "Zeytinburnu", "Eyüpsultan", "Gaziosmanpaşa",
            "Sarıyer", "Kağıthane", "Güngören", "Bakırköy", "Maltepe",
            "Pendik", "Tuzla", "Sancaktepe", "Sultanbeyli", "Arnavutköy"
        ]
    }
    key = city.lower().strip()
    # Exact match
    if key in presets:
        print(f"ℹ️  Using fallback preset for '{city}'.")
        return presets[key]
    # Partial match
    for known in presets:
        if known in key or key in known:
            print(f"ℹ️  Using fallback preset for '{known}' (matched from '{city}').")
            return presets[known]
    print(f"⚠️  No fallback available for '{city}'. Returning empty list.")
    return []

# ──────────────────────────────────────────────────────────────
# 3.  QUERY GENERATOR
# ──────────────────────────────────────────────────────────────

def generate_queries(business: str, areas: list) -> list:
    """
    Create a list of search queries: "business in area" for each area.
    Filters out empty business/area and deduplicates.
    """
    business = business.strip()
    if not business:
        return []
    queries = []
    seen = set()
    for area in areas:
        area = area.strip()
        if not area:
            continue
        q = f"{business} in {area}"
        if q not in seen:
            queries.append(q)
            seen.add(q)
    return queries

# ──────────────────────────────────────────────────────────────
# 4.  COMMAND‑LINE INTERFACE (CLI)
# ──────────────────────────────────────────────────────────────

def main_cli():
    parser = argparse.ArgumentParser(
        description="Generate Google Maps search queries for every sub‑area of a city."
    )
    parser.add_argument("business", help="Business type (e.g., 'coffee shop')")
    parser.add_argument("city", help="City name (e.g., 'New York')")
    parser.add_argument("--state", help="State or province (e.g., 'NY')", default=None)
    parser.add_argument("--country", help="Country name (e.g., 'USA')", default=None)
    parser.add_argument("--output", help="Output file (default: queries.txt)", default="queries.txt")
    parser.add_argument("--no-fallback", action="store_true",
                        help="Disable fallback presets if OSM data is missing")
    parser.add_argument("--gui", action="store_true", help="Launch graphical UI instead")

    args = parser.parse_args()

    if args.gui:
        main_gui()
        return

    # Fetch areas
    areas = get_city_areas(args.city, args.state, args.country,
                           fallback_to_preset=not args.no_fallback)
    if not areas:
        print("❌ No sub‑areas found. Exiting.")
        sys.exit(1)

    # Generate queries
    queries = generate_queries(args.business, areas)
    if not queries:
        print("❌ No queries generated (missing business or areas).")
        sys.exit(1)

    # Write output
    output_path = Path(args.output)
    output_path.write_text("\n".join(queries), encoding="utf-8")
    print(f"✅ {len(queries)} queries written to '{output_path}'")

# ──────────────────────────────────────────────────────────────
# 5.  TKINTER GUI (optional)
# ──────────────────────────────────────────────────────────────

def main_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, scrolledtext, messagebox
    except ImportError:
        print("Tkinter not available. Please install python3-tk or run in CLI mode.")
        return

    root = tk.Tk()
    root.title("Maps Query Generator")
    root.geometry("600x550")
    root.resizable(True, True)

    # Variables
    business_var = tk.StringVar(value="coffee shop")
    city_var = tk.StringVar(value="New York")
    state_var = tk.StringVar()
    country_var = tk.StringVar(value="USA")
    output_var = tk.StringVar(value="queries.txt")
    areas_list = []

    # Widgets
    frame = ttk.Frame(root, padding=10)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Business type:").grid(row=0, column=0, sticky="w", pady=2)
    ttk.Entry(frame, textvariable=business_var, width=40).grid(row=0, column=1, sticky="w", pady=2)

    ttk.Label(frame, text="City:").grid(row=1, column=0, sticky="w", pady=2)
    ttk.Entry(frame, textvariable=city_var, width=40).grid(row=1, column=1, sticky="w", pady=2)

    ttk.Label(frame, text="State (optional):").grid(row=2, column=0, sticky="w", pady=2)
    ttk.Entry(frame, textvariable=state_var, width=40).grid(row=2, column=1, sticky="w", pady=2)

    ttk.Label(frame, text="Country (optional):").grid(row=3, column=0, sticky="w", pady=2)
    ttk.Entry(frame, textvariable=country_var, width=40).grid(row=3, column=1, sticky="w", pady=2)

    ttk.Label(frame, text="Output file:").grid(row=4, column=0, sticky="w", pady=2)
    ttk.Entry(frame, textvariable=output_var, width=40).grid(row=4, column=1, sticky="w", pady=2)

    # Buttons
    btn_frame = ttk.Frame(frame)
    btn_frame.grid(row=5, column=0, columnspan=2, pady=10)

    def fetch_areas():
        nonlocal areas_list
        city = city_var.get().strip()
        if not city:
            messagebox.showerror("Error", "City is required.")
            return
        state = state_var.get().strip() or None
        country = country_var.get().strip() or None
        try:
            areas = get_city_areas(city, state, country, fallback_to_preset=True)
            areas_list = areas
            area_label.config(text=f"Areas loaded: {len(areas)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to fetch areas:\n{e}")
            areas_list = []

    def generate():
        business = business_var.get().strip()
        if not business:
            messagebox.showerror("Error", "Business type is required.")
            return
        if not areas_list:
            messagebox.showerror("Error", "No areas loaded. Click 'Fetch Areas' first.")
            return
        queries = generate_queries(business, areas_list)
        if not queries:
            messagebox.showerror("Error", "No queries generated.")
            return
        output_text.delete(1.0, tk.END)
        output_text.insert(tk.END, "\n".join(queries))
        output_text.config(state="normal")
        query_count_label.config(text=f"Queries: {len(queries)}")

    def save():
        content = output_text.get(1.0, tk.END).strip()
        if not content:
            messagebox.showerror("Error", "No content to save. Generate first.")
            return
        outfile = output_var.get().strip() or "queries.txt"
        try:
            Path(outfile).write_text(content, encoding="utf-8")
            messagebox.showinfo("Saved", f"Saved to '{outfile}'")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save: {e}")

    ttk.Button(btn_frame, text="Fetch Areas", command=fetch_areas).pack(side="left", padx=5)
    ttk.Button(btn_frame, text="Generate Queries", command=generate).pack(side="left", padx=5)
    ttk.Button(btn_frame, text="Save to File", command=save).pack(side="left", padx=5)

    # Info labels
    area_label = ttk.Label(frame, text="Areas loaded: 0")
    area_label.grid(row=6, column=0, columnspan=2, pady=2)

    query_count_label = ttk.Label(frame, text="Queries: 0")
    query_count_label.grid(row=7, column=0, columnspan=2, pady=2)

    # Output text area
    output_text = scrolledtext.ScrolledText(frame, height=12, wrap="word")
    output_text.grid(row=8, column=0, columnspan=2, pady=10, sticky="nsew")
    output_text.config(state="normal")

    # Configure grid weights
    frame.columnconfigure(1, weight=1)
    frame.rowconfigure(8, weight=1)

    root.mainloop()

# ──────────────────────────────────────────────────────────────
# 6.  ENTRY POINT
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) == 1:
        # No arguments -> launch GUI
        main_gui()
    else:
        main_cli()