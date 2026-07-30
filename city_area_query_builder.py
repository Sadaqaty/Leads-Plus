#!/usr/bin/env python3
"""
Auto-get suburbs/neighbourhoods for a city using:
1) Nominatim (geocode city -> OSM boundary id)
2) Overpass (pull place=suburb|neighbourhood|locality inside that boundary)
3) Combine with your base queries file

Install: pip install requests
Run:
  python3 city_area_query_builder.py --city "Brisbane" --country "Australia" --queries queries.txt
"""

from __future__ import annotations
import argparse, csv, time
from pathlib import Path
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

def dedupe_keep_order(items: list[str]) -> list[str]:
    seen, out = set(), []
    for x in items:
        k = x.casefold()
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out

def read_lines(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(" ".join(s.split()))
    return lines

def overpass(query: str, timeout: int = 180) -> dict:
    r = requests.post(OVERPASS_URL, data={"data": query}, timeout=timeout, headers={
        "User-Agent": "CityAreaQueryBuilder/1.0 (contact: local-script)"
    })
    r.raise_for_status()
    return r.json()

def nominatim_lookup(city: str, country: str | None) -> dict:
    params = {
        "q": f"{city}, {country}" if country else city,
        "format": "jsonv2",
        "limit": 10,
        "polygon_geojson": 0,
        "addressdetails": 1,
    }
    r = requests.get(NOMINATIM_URL, params=params, timeout=60, headers={
        "User-Agent": "CityAreaQueryBuilder/1.0 (contact: local-script)"
    })
    r.raise_for_status()
    data = r.json()
    if not data:
        raise SystemExit("Nominatim found nothing. Try a different city string.")
    return data

def pick_best_boundary(results: list[dict]) -> dict:
    """
    Prefer administrative boundaries (relation) like city/LGA.
    If not found, take best ranked result.
    """
    def score(item: dict) -> tuple:
        cls = item.get("class", "")
        typ = item.get("type", "")
        osm_type = item.get("osm_type", "")
        imp = float(item.get("importance", 0.0))
        # lower is better
        prefer_admin = 0 if (cls == "boundary" and typ == "administrative" and osm_type == "relation") else 1
        prefer_relation = 0 if osm_type == "relation" else 1
        return (prefer_admin, prefer_relation, -imp)

    results_sorted = sorted(results, key=score)
    return results_sorted[0]

def to_overpass_area_id(osm_type: str, osm_id: int) -> int:
    """
    Overpass area id rules:
    - relation: 3600000000 + id
    - way:      2400000000 + id
    Nodes are not supported as areas in the same way for this use.
    """
    if osm_type == "relation":
        return 3600000000 + osm_id
    if osm_type == "way":
        return 2400000000 + osm_id
    raise SystemExit(f"Unsupported OSM type for boundary: {osm_type}. Try another city result.")

def find_places_within(area_id: int) -> list[str]:
    q = f"""
    [out:json][timeout:180];
    area({area_id})->.a;
    (
      node["place"~"suburb|neighbourhood|locality"](area.a);
      way["place"~"suburb|neighbourhood|locality"](area.a);
      relation["place"~"suburb|neighbourhood|locality"](area.a);
    );
    out tags;
    """
    data = overpass(q)
    names = []
    for e in data.get("elements", []):
        name = (e.get("tags") or {}).get("name")
        if name:
            names.append(" ".join(name.split()))
    names = dedupe_keep_order(sorted(set(names), key=lambda x: x.casefold()))
    return names

def build_rows(city_label: str, areas: list[str], base_queries: list[str]) -> list[dict]:
    rows = []
    for area in areas:
        for q in base_queries:
            rows.append({
                "city": city_label,
                "area": area,
                "base_query": q,
                "combined_query": f"{q} {area} {city_label}".strip()
            })
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", required=True, help='City name, example: "Brisbane"')
    ap.add_argument("--country", default=None, help='Optional, example: "Australia"')
    ap.add_argument("--queries", required=True, help="Path to queries.txt (one per line)")
    ap.add_argument("--outdir", default="output", help="Output folder")
    ap.add_argument("--max_areas", type=int, default=0, help="0 = no limit, else cap areas")
    args = ap.parse_args()

    city = " ".join(args.city.split())
    country = " ".join(args.country.split()) if args.country else None
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    base_queries = dedupe_keep_order(read_lines(Path(args.queries)))
    if not base_queries:
        raise SystemExit("queries file is empty")

    print("Geocoding city boundary (Nominatim)...")
    results = nominatim_lookup(city, country)
    best = pick_best_boundary(results)

    display_name = best.get("display_name", "")
    osm_type = best.get("osm_type")
    osm_id = int(best.get("osm_id"))

    print(f"Picked boundary: {display_name}")
    print(f"OSM: {osm_type} {osm_id}")

    area_id = to_overpass_area_id(osm_type, osm_id)

    time.sleep(1.0)  # be polite

    print("Fetching suburbs/neighbourhoods (Overpass)...")
    areas = find_places_within(area_id)
    if not areas:
        raise SystemExit("No areas found. Try using 'Brisbane City' as --city or add --country.")

    if args.max_areas and len(areas) > args.max_areas:
        areas = areas[:args.max_areas]

    (outdir / "areas.txt").write_text("\n".join(areas) + "\n", encoding="utf-8")

    city_label = city if not country else f"{city}, {country}"
    rows = build_rows(city_label, areas, base_queries)

    (outdir / "combined_queries.txt").write_text(
        "\n".join(r["combined_query"] for r in rows) + "\n",
        encoding="utf-8"
    )

    with (outdir / "combined_queries.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["city", "area", "base_query", "combined_query"])
        w.writeheader()
        w.writerows(rows)

    print("Done.")
    print(f"Areas found: {len(areas)}")
    print(f"Queries generated: {len(rows)}")
    print(f"Output folder: {outdir.resolve()}")

if __name__ == "__main__":
    main()
