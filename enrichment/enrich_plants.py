"""
Enrichment script — reads plant names from data/plants_input.txt,
uses Claude to fill in structured attributes, and inserts them into the database.

Usage:
    python -m enrichment.enrich_plants          # enrich all plants in the input file
    python -m enrichment.enrich_plants --dry-run  # preview without writing to DB
"""

import json
import sys
import time
import argparse
from pathlib import Path

import anthropic

# Allow running as `python -m enrichment.enrich_plants` from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from database.schema import Base, Plant
from database.connection import engine, SessionLocal

INPUT_FILE = Path("data/plants_input.txt")

# ── Prompt template for Claude to return structured plant data ────────────
ENRICHMENT_PROMPT = """You are a horticultural database assistant. Given a plant name, return a JSON object with the following fields filled in as accurately as possible. Use your expert knowledge.

RULES:
- Use the exact field names shown below.
- For numeric fields, use numbers (not strings). Use null if unknown.
- For boolean fields, use true/false/null.
- sun_exposure must be one of: "full_sun", "partial_sun", "partial_shade", "full_shade", or a comma-separated combination like "full_sun, partial_sun".
- water_needs must be one of: "low", "moderate", "high".
- growth_rate must be one of: "slow", "moderate", "fast".
- plant_type must be one of: "shrub", "tree", "perennial", "annual", "grass", "groundcover", "vine", "succulent", "bulb", "fern", "palm".
- Heights and widths are in FEET.
- bloom_season can be comma-separated: "spring", "summer", "fall", "winter".
- landscape_use is a comma-separated list, e.g. "border, hedge, accent".
- description should be 1-2 sentences summarizing the plant.

FIELDS:
{
    "common_name": "",
    "scientific_name": "",
    "plant_type": "",
    "mature_height_min_ft": 0,
    "mature_height_max_ft": 0,
    "mature_width_min_ft": 0,
    "mature_width_max_ft": 0,
    "sun_exposure": "",
    "water_needs": "",
    "drought_tolerant": false,
    "blooms": false,
    "bloom_color": "",
    "bloom_season": "",
    "fragrant": false,
    "evergreen": false,
    "foliage_color": "",
    "fall_color": "",
    "growth_rate": "",
    "hardiness_zone_min": 0,
    "hardiness_zone_max": 0,
    "deer_resistant": false,
    "landscape_use": "",
    "native_region": "",
    "description": ""
}

Plant name: {plant_name}

Return ONLY the JSON object, no markdown fences, no extra text."""


def load_plant_names() -> list[str]:
    """Read plant names from the input file, skipping blanks and comments.

    Supports a grouped format where a line ending with ':' is treated as a
    genus/category prefix that gets prepended to the cultivar names that follow:

        Distylium:
        Swing low        →  "Distylium Swing low"
        Coppertone       →  "Distylium Coppertone"

    Standalone lines (no active category) are used as-is:
        Mojo dwarf pittosporum  →  "Mojo dwarf pittosporum"
    """
    if not INPUT_FILE.exists():
        print(f"ERROR: Input file not found at {INPUT_FILE}")
        sys.exit(1)

    names = []
    current_category = ""
    for line in INPUT_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":"):
            # New category header — store it without the colon
            current_category = line[:-1].strip()
        else:
            # Plant entry
            if current_category:
                names.append(f"{current_category} {line}")
            else:
                names.append(line)
    return names


def enrich_one(client: anthropic.Anthropic, plant_name: str) -> dict | None:
    """Call Claude to get structured data for a single plant name."""
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[
                {"role": "user", "content": ENRICHMENT_PROMPT.replace("{plant_name}", plant_name)}
            ],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if Claude adds them anyway
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        data = json.loads(raw)
        return data
    except json.JSONDecodeError as e:
        print(f"  WARNING: Could not parse JSON for '{plant_name}': {e}")
        return None
    except anthropic.APIError as e:
        print(f"  WARNING: API error for '{plant_name}': {e}")
        return None


def upsert_plant(session, data: dict):
    """Insert or update a plant record based on common_name."""
    existing = session.query(Plant).filter_by(common_name=data["common_name"]).first()
    if existing:
        for key, value in data.items():
            if key != "id":
                setattr(existing, key, value)
        print(f"  UPDATED: {data['common_name']}")
    else:
        plant = Plant(**data)
        session.add(plant)
        print(f"  ADDED:   {data['common_name']}")


def main():
    parser = argparse.ArgumentParser(description="Enrich plant names with AI-generated attributes.")
    parser.add_argument("--dry-run", action="store_true", help="Preview enrichment without writing to DB")
    args = parser.parse_args()

    names = load_plant_names()
    if not names:
        print("No plant names found in", INPUT_FILE)
        return

    print(f"Found {len(names)} plant(s) to enrich.\n")

    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "your-api-key-here":
        print("ERROR: Set your ANTHROPIC_API_KEY in the .env file first.")
        sys.exit(1)

    # Create tables if they don't exist
    Base.metadata.create_all(engine)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    session = SessionLocal()

    try:
        for i, name in enumerate(names, 1):
            print(f"[{i}/{len(names)}] Enriching: {name}")
            data = enrich_one(client, name)

            if data is None:
                continue

            if args.dry_run:
                print(json.dumps(data, indent=2))
            else:
                upsert_plant(session, data)
                session.commit()

            # Small delay to be polite to the API
            if i < len(names):
                time.sleep(0.5)

        print("\nDone!")
        if not args.dry_run:
            count = session.query(Plant).count()
            print(f"Total plants in database: {count}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
