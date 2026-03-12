"""
FastAPI backend — serves the chat interface and handles AI queries.
"""

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from database.connection import SessionLocal
from api.query_engine import QueryEngine
from api.plant_adder import add_plants_stream, parse_plant_names_from_text

# Create tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Plant AI Advisor", version="1.0.0")


# ── Request / Response models ─────────────────────────────────────────────
class QuestionRequest(BaseModel):
    question: str
    history: list[dict] = []


class AnswerResponse(BaseModel):
    answer: str
    sql: str
    explanation: str
    result_count: int


class PlantSummary(BaseModel):
    total_plants: int
    plants: list[dict]


class AddPlantsRequest(BaseModel):
    text: str


class PreviewResponse(BaseModel):
    count: int
    names: list[str]


# ── API Routes ────────────────────────────────────────────────────────────
@app.post("/api/ask", response_model=AnswerResponse)
def ask_question(req: QuestionRequest, db: Session = Depends(get_db)):
    """Main endpoint — takes a natural language question, returns an AI answer
    grounded in the local plant database."""
    engine = QueryEngine(db)
    result = engine.ask(req.question, req.history)
    return AnswerResponse(**result)


@app.get("/api/plants", response_model=PlantSummary)
def list_plants(db: Session = Depends(get_db)):
    """Return all plants currently in the database."""
    engine = QueryEngine(db)
    plants = engine.get_all_plants()
    return PlantSummary(total_plants=len(plants), plants=plants)


@app.get("/api/status")
def status(db: Session = Depends(get_db)):
    """Health check that also reports plant count."""
    engine = QueryEngine(db)
    count = engine.get_plant_count()
    return {"status": "ok", "plant_count": count}


@app.post("/api/preview-plants", response_model=PreviewResponse)
def preview_plants(req: AddPlantsRequest):
    """Parse pasted text and return the list of plant names that would be processed."""
    names = parse_plant_names_from_text(req.text)
    return PreviewResponse(count=len(names), names=names)


@app.post("/api/add-plants")
def add_plants(req: AddPlantsRequest):
    """Stream SSE progress as plants are enriched and added to the database."""
    db = SessionLocal()

    def generate():
        try:
            yield from add_plants_stream(req.text, db)
        finally:
            db.close()

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Serve the static chat UI ─────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_ui():
    return FileResponse("static/index.html")
