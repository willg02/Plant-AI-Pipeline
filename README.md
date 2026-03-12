# 🌿 Plant AI Advisor

A local plant database with an AI-powered natural language interface. Ask questions about your plant selection in plain English and get answers pulled from **your specific inventory** — not the entire internet.

---

## How It Works

1. **You provide plant names** → paste them into `data/plants_input.txt`
2. **AI enriches them** → Claude fills in sun, size, bloom, water needs, and 20+ other attributes
3. **Data goes into SQLite** → structured, queryable, no server needed
4. **Users ask questions in plain English** → "What blooms in summer and handles shade?"
5. **AI queries your local DB only** → translates to SQL, runs it, returns a friendly answer

---

## Quick Start

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up Your API Key

Copy the example env file and add your Anthropic API key:

```bash
copy .env.example .env
```

Edit `.env` and replace `your-api-key-here` with your actual Anthropic API key.  
Get one at: https://console.anthropic.com/

### 3. Add Your Plant Names

Open `data/plants_input.txt` and paste your plant names, one per line:

```
Knockout Rose
Japanese Maple
Blue Rug Juniper
Endless Summer Hydrangea
Dwarf Yaupon Holly
```

### 4. Enrich Plants (AI fills in all the details)

```bash
python -m enrichment.enrich_plants
```

This reads each plant name, asks Claude for structured attributes (sun, size, bloom color, water needs, etc.), and saves everything to the SQLite database at `data/plants.db`.

**Optional:** Preview without writing to DB:
```bash
python -m enrichment.enrich_plants --dry-run
```

### 5. Start the Server

```bash
uvicorn api.main:app --reload
```

Then open **http://localhost:8000** in your browser.

---

## Asking Questions

Just type naturally. Examples:

- "Which plants take full sun and stay under 4 feet?"
- "What do you have that blooms pink in spring?"
- "Show me evergreen shrubs that are deer resistant"
- "I need something drought tolerant for a border"
- "What's the fastest growing tree you carry?"

The AI **only** answers from your local database — it won't hallucinate plants you don't carry.

---

## Updating Your Plant List

To add new plants later:

1. Add the new names to `data/plants_input.txt`
2. Run `python -m enrichment.enrich_plants` again (it will skip/update existing plants by name)

---

## Project Structure

```
Plant-AI-Pipeline/
├── .env                    # Your API key (not committed)
├── .env.example            # Template
├── config.py               # Settings
├── requirements.txt        # Python dependencies
│
├── data/
│   ├── plants_input.txt    # Your plant names go here
│   └── plants.db           # SQLite database (auto-created)
│
├── database/
│   ├── schema.py           # Plant table definition (25+ columns)
│   └── connection.py       # DB connection setup
│
├── enrichment/
│   └── enrich_plants.py    # AI enrichment script
│
├── api/
│   ├── main.py             # FastAPI server
│   └── query_engine.py     # NL → SQL → Answer engine
│
└── static/
    └── index.html          # Chat web interface
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/ask` | Ask a natural language question |
| GET | `/api/plants` | List all plants in the database |
| GET | `/api/status` | Health check + plant count |
| GET | `/` | Web chat interface |

---

## Tech Stack

- **Database:** SQLite (via SQLAlchemy)
- **AI:** Anthropic Claude (for enrichment + queries)
- **Backend:** Python / FastAPI
- **Frontend:** Vanilla HTML/CSS/JS chat interface
