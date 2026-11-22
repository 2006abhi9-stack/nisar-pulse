import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


class AOISearch(Base):
    __tablename__ = "aoi_searches"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=True)
    wkt_polygon = Column(Text, nullable=False)
    dataset = Column(String(64), nullable=False)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    results_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)

    granules = relationship("SARGranule", back_populates="search", cascade="all, delete-orphan")


class SARGranule(Base):
    __tablename__ = "sar_granules"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    search_id = Column(String(36), ForeignKey("aoi_searches.id", ondelete="CASCADE"), nullable=True)
    granule_name = Column(String(255), index=True, nullable=False)
    platform = Column(String(32), nullable=False)
    processing_level = Column(String(32), nullable=True)
    data_maturity = Column(String(32), nullable=True)
    polarization = Column(String(32), nullable=True)
    acquisition_time = Column(DateTime, nullable=True)
    footprint_geojson = Column(JSON, nullable=True)
    download_url = Column(Text, nullable=True)
    browse_url = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    search = relationship("AOISearch", back_populates="granules")


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    before_granule_id = Column(
        String(36), ForeignKey("sar_granules.id", ondelete="SET NULL"), nullable=True
    )
    after_granule_id = Column(
        String(36), ForeignKey("sar_granules.id", ondelete="SET NULL"), nullable=True
    )
    source_type = Column(String(32), nullable=False)  # 'ASF_LIVE' or 'USER_UPLOAD'
    threshold_db = Column(Float, nullable=False, default=-3.0)
    speckle_filter = Column(Boolean, default=True)
    impacted_km2 = Column(Float, nullable=False, default=0.0)
    mean_db_drop = Column(Float, nullable=False, default=0.0)
    severity_tier = Column(String(32), nullable=False, default="NOMINAL")
    mask_image_path = Column(String(512), nullable=True)
    mask_geojson = Column(JSON, nullable=True)
    histogram_json = Column(JSON, nullable=True)
    bounds_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    briefings = relationship("AIBriefing", back_populates="analysis", cascade="all, delete-orphan")


class AIBriefing(Base):
    __tablename__ = "ai_briefings"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    analysis_id = Column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    model_name = Column(String(64), nullable=False, default="gemini-2.5-flash")
    risk_level = Column(String(32), nullable=False, default="NOMINAL")
    summary_text = Column(Text, nullable=False)
    recommended_actions_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    analysis = relationship("AnalysisRun", back_populates="briefings")


class RoadVerification(Base):
    __tablename__ = "road_verifications"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    osm_id = Column(String(64), index=True, nullable=False)
    status = Column(String(32), nullable=False)  # UNVERIFIED, VERIFIED_PASSABLE, VERIFIED_BLOCKED, RESTRICTED
    verified_by = Column(String(128), nullable=False)
    notes = Column(Text, nullable=True)
    location_lat = Column(Float, nullable=True)
    location_lon = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utc_now)

