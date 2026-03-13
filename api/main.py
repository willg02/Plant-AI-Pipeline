"""
FastAPI backend — serves the chat interface and handles AI queries.
"""

from fastapi import FastAPI, Depends, Query, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, ADMIN_PASSWORD
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


@app.get("/api/plants/filter")
def filter_plants(
    db: Session = Depends(get_db),
    plant_type: Optional[str] = Query(None),
    sun_exposure: Optional[str] = Query(None),
    water_needs: Optional[str] = Query(None),
    blooms: Optional[bool] = Query(None),
    evergreen: Optional[bool] = Query(None),
    deer_resistant: Optional[bool] = Query(None),
    drought_tolerant: Optional[bool] = Query(None),
    max_height: Optional[float] = Query(None),
    min_height: Optional[float] = Query(None),
    max_width: Optional[float] = Query(None),
    bloom_season: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """Filter plants by any combination of attributes."""
    from database.schema import Plant
    from sqlalchemy import or_
    q = db.query(Plant)
    if plant_type:
        q = q.filter(Plant.plant_type.ilike(f"%{plant_type}%"))
    if sun_exposure:
        q = q.filter(Plant.sun_exposure.ilike(f"%{sun_exposure}%"))
    if water_needs:
        q = q.filter(Plant.water_needs.ilike(f"%{water_needs}%"))
    if blooms is not None:
        q = q.filter(Plant.blooms == blooms)
    if evergreen is not None:
        q = q.filter(Plant.evergreen == evergreen)
    if deer_resistant is not None:
        q = q.filter(Plant.deer_resistant == deer_resistant)
    if drought_tolerant is not None:
        q = q.filter(Plant.drought_tolerant == drought_tolerant)
    if max_height is not None:
        q = q.filter(Plant.mature_height_max_ft <= max_height)
    if min_height is not None:
        q = q.filter(Plant.mature_height_min_ft >= min_height)
    if max_width is not None:
        q = q.filter(Plant.mature_width_max_ft <= max_width)
    if bloom_season:
        q = q.filter(Plant.bloom_season.like(f"%{bloom_season}%"))
    if search:
        q = q.filter(or_(
            Plant.common_name.like(f"%{search}%"),
            Plant.scientific_name.like(f"%{search}%"),
            Plant.description.like(f"%{search}%"),
        ))
    plants = [p.to_dict() for p in q.order_by(Plant.common_name).all()]
    return {"total": len(plants), "plants": plants}


@app.get("/api/plants/{plant_id}")
def get_plant(plant_id: int, db: Session = Depends(get_db)):
    """Return full details for a single plant."""
    from database.schema import Plant
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Plant not found")
    return plant.to_dict()


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


# ── Admin helpers ─────────────────────────────────────────────────────────
def require_admin(x_admin_password: str = Header(...)):
    """Dependency that validates the admin password header."""
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin password")


class PlantUpdateRequest(BaseModel):
    fields: dict  # arbitrary {column: value} pairs to update


class ConfigRequest(BaseModel):
    value: str


@app.put("/api/admin/plants/{plant_id}")
def admin_update_plant(
    plant_id: int,
    req: PlantUpdateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Update any set of fields on a plant. Only known column names are applied."""
    from database.schema import Plant
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")
    allowed = {c.name for c in Plant.__table__.columns} - {"id"}
    updated = []
    for col, val in req.fields.items():
        if col in allowed:
            setattr(plant, col, val)
            updated.append(col)
    db.commit()
    db.refresh(plant)
    return {"updated": updated, "plant": plant.to_dict()}


@app.get("/api/admin/config")
def admin_get_config(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Return all admin config values."""
    from database.schema import AppConfig
    rows = db.query(AppConfig).all()
    return {r.key: r.value for r in rows}


@app.put("/api/admin/config/{key}")
def admin_set_config(
    key: str,
    req: ConfigRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Upsert a config value."""
    from database.schema import AppConfig
    row = db.query(AppConfig).filter(AppConfig.key == key).first()
    if row:
        row.value = req.value
    else:
        db.add(AppConfig(key=key, value=req.value))
    db.commit()
    return {"key": key, "saved": True}


# ── Serve the static chat UI ─────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_ui():
    return FileResponse("static/index.html")


@app.get("/admin")
def serve_admin():
    return FileResponse("static/admin.html")
