from sqlalchemy import Column, Integer, String, Float, Boolean, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Plant(Base):
    __tablename__ = "plants"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Identity ──────────────────────────────────────────────
    common_name = Column(String(200), nullable=False, index=True)
    scientific_name = Column(String(200), nullable=True)
    plant_type = Column(
        String(50), nullable=True, index=True,
        comment="e.g. shrub, tree, perennial, annual, grass, groundcover, vine, succulent"
    )

    # ── Size ──────────────────────────────────────────────────
    mature_height_min_ft = Column(Float, nullable=True, comment="Minimum mature height in feet")
    mature_height_max_ft = Column(Float, nullable=True, comment="Maximum mature height in feet")
    mature_width_min_ft = Column(Float, nullable=True, comment="Minimum mature spread in feet")
    mature_width_max_ft = Column(Float, nullable=True, comment="Maximum mature spread in feet")

    # ── Sun & Water ───────────────────────────────────────────
    sun_exposure = Column(
        String(50), nullable=True, index=True,
        comment="full_sun, partial_sun, partial_shade, full_shade"
    )
    water_needs = Column(
        String(50), nullable=True,
        comment="low, moderate, high"
    )
    drought_tolerant = Column(Boolean, nullable=True)

    # ── Flowering ─────────────────────────────────────────────
    blooms = Column(Boolean, nullable=True, index=True)
    bloom_color = Column(String(100), nullable=True)
    bloom_season = Column(
        String(100), nullable=True,
        comment="spring, summer, fall, winter — can be comma-separated"
    )
    fragrant = Column(Boolean, nullable=True)

    # ── Foliage ───────────────────────────────────────────────
    evergreen = Column(Boolean, nullable=True, comment="True=evergreen, False=deciduous")
    foliage_color = Column(String(100), nullable=True)
    fall_color = Column(String(100), nullable=True)

    # ── Growth & Care ─────────────────────────────────────────
    growth_rate = Column(String(30), nullable=True, comment="slow, moderate, fast")
    hardiness_zone_min = Column(Integer, nullable=True)
    hardiness_zone_max = Column(Integer, nullable=True)
    deer_resistant = Column(Boolean, nullable=True)

    # ── Use & Notes ───────────────────────────────────────────
    landscape_use = Column(
        Text, nullable=True,
        comment="e.g. border, hedge, accent, foundation, container, mass planting"
    )
    native_region = Column(String(200), nullable=True)
    description = Column(Text, nullable=True, comment="Short narrative description")

    def to_dict(self) -> dict:
        """Return a plain dictionary of all columns for AI context."""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    def __repr__(self):
        return f"<Plant id={self.id} common_name='{self.common_name}'>"
