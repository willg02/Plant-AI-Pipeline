"""
Plant addition utility — parses pasted text, checks for duplicates,
enriches new plants via Claude, and streams SSE progress events.
"""

import json
import re
import time
from typing import Generator

import anthropic
from sqlalchemy.orm import Session

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from database.schema import Plant

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


def parse_plant_names_from_text(text: str) -> list[str]:
    """Parse plant names from pasted text, supporting Category: header groups."""
    names = []
    current_category = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":"):
            current_category = line[:-1].strip()
        else:
            names.append(f"{current_category} {line}" if current_category else line)
    return names


def _enrich_one(client: anthropic.Anthropic, plant_name: str) -> dict | None:
    """Call Claude to get structured attributes for one plant name."""
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": ENRICHMENT_PROMPT.replace("{plant_name}", plant_name)}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        return json.loads(raw)
    except Exception:
        return None


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def add_plants_stream(text: str, db: Session) -> Generator[str, None, None]:
    """
    Full pipeline: parse → deduplicate → enrich → insert.
    Yields SSE-formatted strings for real-time browser progress.
    """
    names = parse_plant_names_from_text(text)

    if not names:
        yield _sse({"type": "error", "message": "No plant names found. Use one per line with optional Category: headers."})
        return

    yield _sse({"type": "start", "total": len(names)})

    # Lowercase set of every common_name already in the DB
    existing: set[str] = {
        (p.common_name or "").lower()
        for p in db.query(Plant.common_name).all()
    }

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    added = skipped = errors = 0

    for i, name in enumerate(names, 1):
        # Fast duplicate check on the raw input name
        if name.lower() in existing:
            skipped += 1
            yield _sse({"type": "progress", "index": i, "total": len(names),
                        "name": name, "status": "skipped", "reason": "already in database"})
            continue

        data = _enrich_one(client, name)

        if data is None:
            errors += 1
            yield _sse({"type": "progress", "index": i, "total": len(names),
                        "name": name, "status": "error", "reason": "enrichment failed"})
            continue

        # Double-check using the name Claude returned
        claude_name = (data.get("common_name") or "").lower()
        if claude_name and claude_name in existing:
            skipped += 1
            yield _sse({"type": "progress", "index": i, "total": len(names),
                        "name": data.get("common_name", name), "status": "skipped",
                        "reason": "already in database"})
            continue

        db.add(Plant(**data))
        db.commit()
        if claude_name:
            existing.add(claude_name)
        added += 1

        yield _sse({"type": "progress", "index": i, "total": len(names),
                    "name": data.get("common_name", name), "status": "added"})

        if i < len(names):
            time.sleep(0.3)

    yield _sse({"type": "done", "added": added, "skipped": skipped,
                "errors": errors, "total": len(names)})
