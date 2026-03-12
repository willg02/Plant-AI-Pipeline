"""
AI Query Engine — translates natural-language questions into SQL,
runs the query against the local plant database, and returns a
conversational answer grounded in the results.
"""

import json
import re

import anthropic
from sqlalchemy.orm import Session
from sqlalchemy import text

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from database.schema import Plant


# ── System prompt that teaches Claude about our schema ────────────────────
SYSTEM_PROMPT = """You are a helpful plant advisor. You ONLY answer questions using the local plant database provided.
You must NEVER recommend plants that are not in this database. If no plants match, say so honestly.

You have access to a SQLite database with a single table called "plants". Here is the schema:

TABLE plants (
    id                    INTEGER PRIMARY KEY,
    common_name           TEXT     -- e.g. "Knockout Rose"
    scientific_name       TEXT     -- e.g. "Rosa × 'Knock Out'"
    plant_type            TEXT     -- one of: shrub, tree, perennial, annual, grass, groundcover, vine, succulent, bulb, fern, palm
    mature_height_min_ft  REAL     -- minimum mature height in feet
    mature_height_max_ft  REAL     -- maximum mature height in feet
    mature_width_min_ft   REAL     -- minimum mature spread/width in feet
    mature_width_max_ft   REAL     -- maximum mature spread/width in feet
    sun_exposure          TEXT     -- "full_sun", "partial_sun", "partial_shade", "full_shade" (can be comma-separated)
    water_needs           TEXT     -- "low", "moderate", "high"
    drought_tolerant      BOOLEAN  -- 1=yes, 0=no
    blooms                BOOLEAN  -- 1=yes, 0=no
    bloom_color           TEXT     -- e.g. "pink", "white, pink"
    bloom_season          TEXT     -- "spring", "summer", "fall", "winter" (can be comma-separated)
    fragrant              BOOLEAN  -- 1=yes, 0=no
    evergreen             BOOLEAN  -- 1=yes, 0=no (False = deciduous)
    foliage_color         TEXT     -- e.g. "green", "blue-green"
    fall_color            TEXT     -- e.g. "red", "orange"
    growth_rate           TEXT     -- "slow", "moderate", "fast"
    hardiness_zone_min    INTEGER
    hardiness_zone_max    INTEGER
    deer_resistant        BOOLEAN  -- 1=yes, 0=no
    landscape_use         TEXT     -- comma-separated: "border, hedge, accent, foundation, container, mass planting"
    native_region         TEXT
    description           TEXT     -- short narrative description
);

INSTRUCTIONS FOR GENERATING QUERIES:
1. When the user asks a question, respond with a JSON object containing:
   - "sql": a SELECT query against the plants table that answers the question
   - "explanation": a brief explanation of what you're searching for
2. Use LIKE with wildcards for text matching (e.g., sun_exposure LIKE '%full_sun%').
3. For size questions, use the max columns for "stays under" and min columns for "at least".
4. When the user says "about 3 feet" use a reasonable range (e.g., max <= 4).
5. Always SELECT * so we get full plant details.
6. ONLY output the JSON object, nothing else. No markdown, no extra text.

Example:
User: "What plants bloom in spring and can handle shade?"
{"sql": "SELECT * FROM plants WHERE blooms = 1 AND bloom_season LIKE '%spring%' AND (sun_exposure LIKE '%shade%')", "explanation": "Looking for spring-blooming plants that tolerate shade"}"""


ANSWER_PROMPT = """You are a friendly, knowledgeable plant advisor for a local plant supplier.
Using ONLY the plant data provided below, answer the user's question in a conversational, helpful way.

RULES:
- ONLY mention plants that appear in the data below. NEVER make up or suggest plants not in this list.
- If no plants match, say something like "We don't currently carry anything that matches that exactly, but here's the closest we have..." and suggest the nearest matches from the data.
- Include relevant details (size, sun, bloom color, etc.) that relate to the question.
- Keep it concise but informative — like a knowledgeable nursery worker would talk.
- If there are many matches, highlight the top 3-5 best fits and mention how many total matched.
- Format plant names in bold.

PLANT DATA:
{plant_data}

USER QUESTION: {question}"""


class QueryEngine:
    """Translates natural language → SQL → conversational answer."""

    def __init__(self, db: Session):
        self.db = db
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def ask(self, question: str) -> dict:
        """
        Full pipeline: question → SQL → results → natural language answer.
        Returns dict with keys: answer, sql, result_count
        """
        # Step 1: Generate SQL from the question
        sql_response = self._generate_sql(question)
        sql_query = sql_response.get("sql", "")
        explanation = sql_response.get("explanation", "")

        # Step 2: Execute the SQL
        results = self._execute_query(sql_query)

        # Step 3: Generate a natural language answer from the results
        answer = self._generate_answer(question, results)

        return {
            "answer": answer,
            "sql": sql_query,
            "explanation": explanation,
            "result_count": len(results),
        }

    def _generate_sql(self, question: str) -> dict:
        """Ask Claude to translate the question into SQL."""
        response = self.client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": question}],
        )
        raw = response.content[0].text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Fallback: search for JSON in the response
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {"sql": "SELECT * FROM plants", "explanation": "Showing all plants (query parse failed)"}

    def _execute_query(self, sql_query: str) -> list[dict]:
        """Run the SQL and return results as list of dicts."""
        # Safety: only allow SELECT statements
        if not sql_query.strip().upper().startswith("SELECT"):
            return []

        try:
            result = self.db.execute(text(sql_query))
            columns = result.keys()
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
            return rows
        except Exception as e:
            print(f"SQL execution error: {e}")
            # Fallback: return all plants
            try:
                result = self.db.execute(text("SELECT * FROM plants"))
                columns = result.keys()
                rows = [dict(zip(columns, row)) for row in result.fetchall()]
                return rows
            except Exception:
                return []

    def _generate_answer(self, question: str, results: list[dict]) -> str:
        """Ask Claude to craft a conversational answer from the query results."""
        if not results:
            plant_data = "No plants matched the query."
        else:
            # Format results for the prompt
            plant_data = json.dumps(results, indent=2, default=str)

        response = self.client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": ANSWER_PROMPT.format(plant_data=plant_data, question=question),
                }
            ],
        )
        return response.content[0].text.strip()

    def get_all_plants(self) -> list[dict]:
        """Return all plants in the database as a list of dicts."""
        plants = self.db.query(Plant).all()
        return [p.to_dict() for p in plants]

    def get_plant_count(self) -> int:
        """Return the total number of plants in the database."""
        return self.db.query(Plant).count()
