"""
Fetch plant images from Wikipedia using scientific name, then common name as fallback.
Stores the best image URL in the image_url column of each plant record.

Usage:
    python -m enrichment.fetch_images            # all plants missing images
    python -m enrichment.fetch_images --all      # re-fetch everything (overwrite)
    python -m enrichment.fetch_images --id 42    # single plant by id
"""

import re
import sys
import time
import argparse
import requests

# Must run from project root
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database.connection import SessionLocal
from database.schema import Plant

HEADERS = {"User-Agent": "PlantAdvisor/1.0 (educational plant database)"}
DELAY = 0.5  # seconds between requests — respectful to Wikipedia


def _wiki_summary_image(page_title: str) -> str | None:
    """Fetch the thumbnail image from a Wikipedia page summary."""
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(page_title.replace(' ', '_'))}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return None
        data = r.json()
        thumb = data.get("thumbnail", {}).get("source")
        if not thumb:
            return None
        # Upsize thumbnail: change /80px- or /220px- to /500px- for decent quality
        large = re.sub(r'/\d+px-', '/500px-', thumb)
        return large
    except Exception:
        return None


def _wiki_search_image(query: str) -> str | None:
    """Search Wikipedia for the query and fetch the image from the top result."""
    search_url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": 3,
        "format": "json",
    }
    try:
        r = requests.get(search_url, params=params, headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return None
        results = r.json().get("query", {}).get("search", [])
        for hit in results:
            title = hit["title"]
            img = _wiki_summary_image(title)
            if img:
                return img
            time.sleep(DELAY)
    except Exception:
        return None
    return None


def fetch_image_for_plant(plant: Plant) -> str | None:
    """
    Try multiple strategies to find a Wikipedia image for this plant.
    Returns the image URL or None.
    """
    candidates = []

    # Strategy 1: scientific name direct lookup (most reliable)
    if plant.scientific_name:
        sci = plant.scientific_name.strip()
        candidates.append(sci)
        # Also try just the first two words (genus + species, drop cultivar suffix)
        parts = sci.split()
        if len(parts) >= 2:
            genus_species = f"{parts[0]} {parts[1]}"
            if genus_species != sci:
                candidates.append(genus_species)

    # Strategy 2: common name direct lookup
    if plant.common_name:
        candidates.append(plant.common_name.strip())

    for candidate in candidates:
        img = _wiki_summary_image(candidate)
        time.sleep(DELAY)
        if img:
            return img

    # Strategy 3: search fallback using "plant_name plant"
    if plant.scientific_name:
        img = _wiki_search_image(plant.scientific_name + " plant")
        time.sleep(DELAY)
        if img:
            return img

    if plant.common_name:
        img = _wiki_search_image(plant.common_name + " plant")
        time.sleep(DELAY)
        if img:
            return img

    return None


def run(overwrite: bool = False, plant_id: int | None = None):
    db = SessionLocal()
    try:
        if plant_id is not None:
            plants = db.query(Plant).filter(Plant.id == plant_id).all()
        elif overwrite:
            plants = db.query(Plant).order_by(Plant.common_name).all()
        else:
            plants = db.query(Plant).filter(Plant.image_url.is_(None)).order_by(Plant.common_name).all()

        total = len(plants)
        print(f"Fetching images for {total} plant(s)...\n")

        found = 0
        not_found = 0

        for i, plant in enumerate(plants, 1):
            label = plant.common_name or plant.scientific_name or f"id={plant.id}"
            print(f"[{i}/{total}] {label}", end=" ... ", flush=True)

            url = fetch_image_for_plant(plant)

            if url:
                plant.image_url = url
                db.commit()
                found += 1
                print(f"✓")
            else:
                not_found += 1
                print("✗ not found")

        print(f"\nDone — {found} images found, {not_found} not found.")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch plant images from Wikipedia")
    parser.add_argument("--all",  action="store_true", help="Re-fetch all plants (overwrite existing)")
    parser.add_argument("--id",   type=int,            help="Fetch image for a single plant by ID")
    args = parser.parse_args()
    run(overwrite=args.all, plant_id=args.id)
