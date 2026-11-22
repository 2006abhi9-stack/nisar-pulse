from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# --- Health & Diagnostics ---
class HealthResponse(BaseModel):
    status: str
    database_connected: bool
    earthdata_configured: bool
    gemini_configured: bool
    storage_writable: bool
    timestamp: datetime


# --- Granule & Search Schemas ---
class GranuleSearchRequest(BaseModel):
    wkt_polygon: str = Field(..., description="WKT polygon string representing AOI")
    dataset: str = Field("NISAR", description="NISAR or SENTINEL-1")
    start_date: str | None = Field(None, description="ISO start date")
    end_date: str | None = Field(None, description="ISO end date")
    processing_level: str | None = Field(None, description="e.g. GCOV, GUNW, GRD")
    max_results: int = Field(25, ge=1, le=100)


class GranuleResponse(BaseModel):
    id: str
    granule_name: str
    platform: str
    processing_level: str | None
    data_maturity: str | None
    polarization: str | None
    acquisition_time: datetime | None
    footprint_geojson: dict[str, Any] | None
    download_url: str | None
    browse_url: str | None


class GranuleSearchResponse(BaseModel):
    search_id: str
    total_count: int
    granules: list[GranuleResponse]
    message: str | None = None


# --- Change Detection Analysis Schemas ---
class AnalyzeASFRequest(BaseModel):
    before_granule_id: str
    after_granule_id: str
    threshold_db: float = Field(-3.0, description="Negative change threshold in dB")
    speckle_filter: bool = Field(True, description="Enable spatial speckle suppression")
    aoi_wkt: str | None = Field(None, description="Optional WKT polygon representing target AOI")


class AnalyzeCachedPairRequest(BaseModel):
    before_provider: str = Field(..., description="Provider: ISRO_BHOONIDHI or NASA_ASF")
    before_item_id: str = Field(..., description="Item ID / granule name for BEFORE observation")
    before_collection: str | None = Field(None, description="Optional collection name")
    after_provider: str = Field(..., description="Provider: ISRO_BHOONIDHI or NASA_ASF")
    after_item_id: str = Field(..., description="Item ID / granule name for AFTER observation")
    after_collection: str | None = Field(None, description="Optional collection name")
    aoi_wkt: str | None = Field(None, description="Target AOI WKT polygon string")
    threshold_db: float = Field(-3.0, description="Negative change threshold in dB")
    speckle_filter: bool = Field(True, description="Enable spatial speckle suppression")
    speckle_kernel_size: int = Field(7, description="Speckle filter kernel size")


class HistogramBin(BaseModel):
    bin: str
    count: int
    is_change: bool = False


class AnalysisResultResponse(BaseModel):
    analysis_id: str
    source_type: str
    before_granule_id: str | None = None
    after_granule_id: str | None = None
    before_date: datetime | None = None
    after_date: datetime | None = None
    before_platform: str | None = None
    after_platform: str | None = None
    threshold_db: float
    speckle_filter: bool
    impacted_km2: float
    mean_db_drop: float
    severity_tier: str
    mask_image_url: str | None
    mask_geojson: dict[str, Any] | None
    bounds: list[list[float]] | None
    histogram: list[HistogramBin]
    total_scene_km2: float | None = None
    valid_pixels: int | None = None
    crs: str | None = None
    change_type: str | None = None
    scientific_qualification: str | None = None
    created_at: datetime


# --- AI Briefing Schemas ---
class BriefingRequest(BaseModel):
    operational_focus: str | None = Field(
        None, description="Custom operational context or focus area"
    )


class AIBriefingOutput(BaseModel):
    risk_level: str = Field(
        ..., description="CRITICAL, ELEVATED, MODERATE, or NOMINAL"
    )
    summary_text: str = Field(..., description="Executive operational summary")
    primary_driver: str = Field(
        ..., description="Most probable physical driver (e.g. Surface Water Inundation, Landslide)"
    )
    recommended_actions: list[str] = Field(
        ..., description="List of concrete, prioritized field response actions"
    )


class AIBriefingResponse(BaseModel):
    id: str
    analysis_id: str
    model_name: str
    risk_level: str
    summary_text: str
    primary_driver: str
    recommended_actions: list[str]
    created_at: datetime


# --- History Listing ---
class HistoryItemResponse(BaseModel):
    id: str
    source_type: str
    threshold_db: float
    impacted_km2: float
    mean_db_drop: float
    severity_tier: str
    has_briefing: bool
    created_at: datetime


# --- Road Network Impact Assessment Schemas ---
class RoadImpactRequest(BaseModel):
    analysis_id: str | None = Field(None, description="ID of existing SAR analysis run")
    aoi_wkt: str | None = Field(None, description="AOI polygon WKT")
    bounds: list[list[float]] | None = Field(None, description="[[south, west], [north, east]]")
    proximity_meters: float = Field(50.0, description="Proximity threshold in meters for nearby road classification")
    mask_geojson: dict[str, Any] | None = Field(None, description="Optional direct/override mask GeoJSON")
    is_demo: bool = Field(False, description="Flag indicating isolated demonstration mode")
    verifications: dict[str, Any] | None = Field(None, description="Active client verifications")


class RoadImpactResponse(BaseModel):
    assessment_id: str
    analysis_id: str | None = None
    status: str = Field(..., description="COMPLETED, NO_CHANGE_DETECTED, or OSM_UNAVAILABLE")
    proximity_threshold_meters: float
    total_roads_assessed: int
    impacted_count: int
    nearby_count: int
    no_intersection_count: int
    unverified_count: int
    road_geojson: dict[str, Any]
    message: str | None = None
    scientific_qualification: str
    created_at: datetime


# --- Field Verification Schemas ---
class RoadVerificationCreate(BaseModel):
    osm_id: str = Field(..., description="OSM road identifier, e.g. '8916048' or 'way/8916048'")
    status: str = Field(..., description="UNVERIFIED, VERIFIED_PASSABLE, VERIFIED_BLOCKED, or RESTRICTED")
    verified_by: str = Field(..., description="Operator or Field Team Identifier")
    notes: str | None = Field(None, description="Optional field notes and observations")
    location_lat: float | None = Field(None, description="Optional GPS verification latitude")
    location_lon: float | None = Field(None, description="Optional GPS verification longitude")


class RoadVerificationResponse(BaseModel):
    id: str
    osm_id: str
    status: str
    verified_by: str
    notes: str | None = None
    location_lat: float | None = None
    location_lon: float | None = None
    created_at: datetime


# --- Preliminary Route Planning Schemas ---
class RoutePlanRequest(BaseModel):
    start_lat: float
    start_lon: float
    dest_lat: float
    dest_lon: float
    routing_mode: str = Field("CONSERVATIVE", description="'CONSERVATIVE' or 'EXPLORATORY'")
    permit_restricted: bool = Field(False, description="Whether restricted roads may be traversed")
    proximity_meters: float = Field(50.0, description="SAR proximity buffer")
    analysis_id: str | None = None
    mask_geojson: dict[str, Any] | None = None
    aoi_wkt: str | None = None
    bounds: list[list[float]] | None = None
    is_demo: bool = False
    verifications: dict[str, Any] | None = None


class RouteSegmentDetail(BaseModel):
    osm_id: str
    name: str
    highway: str
    length_meters: float
    sar_classification: str
    field_status: str
    is_unverified: bool
    notes: str | None = None


class RoutePlanResponse(BaseModel):
    route_id: str
    status: str
    routing_mode: str
    total_distance_km: float
    passable_segments_count: int
    unverified_segments_count: int
    restricted_segments_count: int
    route_geojson: dict[str, Any] | None = None
    warnings: list[str]
    candidate_label: str
    scientific_qualification: str
    message: str | None = None
    created_at: datetime


# --- Demonstration Scenario Schemas ---
class DemoFloodScenarioResponse(BaseModel):
    status: str = Field("SUCCESS", description="Execution status")
    sar_result: AnalysisResultResponse
    road_assessment: RoadImpactResponse
    demo_banner: str = Field(
        "DEMO MODE — SYNTHETIC SATELLITE AND ROAD DATA",
        description="Persistent demonstration warning banner",
    )
    simulated_label: str = Field(
        "SIMULATED CHANGE — NOT REAL FLOOD OBSERVATION",
        description="Simulated overlay qualification label",
    )
    scientific_qualification: str = Field(
        "[DEMO MODE] Isolated synthetic demonstration dataset for interface and map verification. "
        "Not a real satellite observation, real flooding, or real operational road conditions.",
        description="Scientific integrity qualification",
    )


# --- Bhoonidhi ISRO S-Band Schemas ---
class BhoonidhiProviderStatus(str):
    ONLINE = "ONLINE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    ERROR = "ERROR"


class BhoonidhiProductQualification(str):
    DOWNLOADABLE_CANDIDATE = "DOWNLOADABLE_CANDIDATE"
    CATALOGUE_ONLY = "CATALOGUE_ONLY"
    UNSUPPORTED_PRODUCT = "UNSUPPORTED_PRODUCT"
    INVALID_METADATA = "INVALID_METADATA"


class BhoonidhiProduct(BaseModel):
    item_id: str
    collection_id: str
    provider: str = "ISRO / Bhoonidhi"
    platform: str = "NISAR"
    sensor_band: str = "S-band"
    product_type: str | None = None
    processing_level: str | None = None
    acquisition_time: datetime | None = None
    polarization: str | None = None
    orbit_direction: str | None = None
    look_direction: str | None = None
    footprint_geojson: dict[str, Any] | None = None
    is_online: bool = False
    download_url: str | None = None
    assets: dict[str, Any] = Field(default_factory=dict)
    qualification: str  # DOWNLOADABLE_CANDIDATE, CATALOGUE_ONLY, UNSUPPORTED_PRODUCT, INVALID_METADATA
    qualification_reason: str


class BhoonidhiSearchRequest(BaseModel):
    wkt_polygon: str | None = Field(None, description="AOI WKT polygon string")
    geojson_polygon: dict[str, Any] | None = Field(None, description="AOI GeoJSON geometry dictionary")
    start_date: str | None = Field(None, description="ISO start date (YYYY-MM-DD)")
    end_date: str | None = Field(None, description="ISO end date (YYYY-MM-DD)")
    collection: str = Field("NISAR_SSAR_GCOV", description="STAC collection ID")
    max_results: int = Field(25, ge=1, le=500, description="Max results (1-500)")


class BhoonidhiSearchResponse(BaseModel):
    provider_status: str
    collection_searched: str
    total_count: int
    products: list[BhoonidhiProduct]
    has_more: bool = False
    message: str | None = None
    warning: str | None = None


# --- Observation Pairing & Compatibility Schemas ---
class CommonObservation(BaseModel):
    provider: str  # "NASA_ASF" or "ISRO_BHOONIDHI"
    original_id: str
    collection_id: str
    platform: str
    instrument: str  # "C-SAR", "LSAR", "SSAR"
    frequency_band: str  # "C-band", "L-band", "S-band"
    product_type: str | None = None  # "GRD", "GCOV", "GUNW", etc.
    processing_level: str | None = None
    polarization: str | None = None
    acquisition_time: datetime | None = None
    orbit_direction: str | None = None
    track_or_orbit: str | None = None
    incidence_angle: float | None = None
    footprint_geojson: dict[str, Any] | None = None
    spatial_resolution: float | None = None
    is_online: bool = False
    download_url: str | None = None
    qualification: str = "COMPATIBLE_CANDIDATE"
    warnings: list[str] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class ObservationPair(BaseModel):
    pair_id: str
    before_observation: CommonObservation
    after_observation: CommonObservation
    is_compatible: bool
    status: str  # COMPATIBLE_CANDIDATE, INSUFFICIENT_METADATA, INCOMPATIBLE, UNSUPPORTED_PRODUCT, DOWNLOAD_REQUIRED
    compatibility_reasons: list[str]
    rejection_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    ranking_score: float
    ranking_explanation: str
    aoi_coverage_percent: float
    temporal_delta_days: float


class ObservationPairSearchRequest(BaseModel):
    wkt_polygon: str = Field(..., description="Target AOI WKT polygon string")
    start_date: str | None = Field(None, description="Baseline search start date (YYYY-MM-DD)")
    end_date: str | None = Field(None, description="Event search end date (YYYY-MM-DD)")
    provider_preference: str = Field("ALL", description="'ALL', 'NASA_ASF', or 'ISRO_BHOONIDHI'")
    dataset_preference: str = Field("ALL", description="'ALL', 'NISAR', or 'SENTINEL-1'")
    max_candidates: int = Field(25, ge=2, le=100)


class ObservationPairSearchResponse(BaseModel):
    search_id: str
    total_observations_found: int
    total_compatible_pairs: int
    recommended_pair: ObservationPair | None = None
    alternative_pairs: list[ObservationPair] = Field(default_factory=list)
    status: str  # SUCCESS, NO_COMPATIBLE_PAIR, NOT_CONFIGURED, ERROR
    message: str | None = None
    warnings: list[str] = Field(default_factory=list)


# --- Satellite Product Download & Caching Schemas ---
class ProductDownloadResult(BaseModel):
    provider: str  # ISRO_BHOONIDHI or NASA_ASF
    collection_id: str | None = None
    item_id: str
    status: str  # SUCCESS, CACHED, OFFLINE, FAILED, UNSUPPORTED, NOT_CONFIGURED
    local_path: str | None = None
    file_size_bytes: int | None = None
    sha256: str | None = None
    is_cached: bool = False
    validation_error: str | None = None
    sar_preflight_ok: bool = False
    sar_preflight_details: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class PairDownloadRequest(BaseModel):
    before_provider: str
    before_item_id: str
    before_collection: str | None = None
    before_download_url: str | None = None
    after_provider: str
    after_item_id: str
    after_collection: str | None = None
    after_download_url: str | None = None
    aoi_wkt: str | None = None


class PairDownloadResponse(BaseModel):
    pair_status: str  # PAIR_READY_FOR_ANALYSIS, PARTIAL, DOWNLOAD_FAILED, PAIR_UNSUPPORTED
    before_product: ProductDownloadResult
    after_product: ProductDownloadResult
    message: str | None = None
    warnings: list[str] = Field(default_factory=list)


