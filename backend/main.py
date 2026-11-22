import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asf_search as asf
import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service import generate_ai_briefing
from bhoonidhi_client import get_bhoonidhi_client
from database import get_db, init_db
from models import AIBriefing, AnalysisRun, AOISearch, RoadVerification, SARGranule
from observation_pairing import ObservationPairingService
from product_downloader import ProductCacheManager, ProductDownloader, compute_file_sha256
from road_network import (
    OSMUnavailableError,
    assess_road_impacts,
    calculate_candidate_route,
    fetch_osm_roads,
    generate_demo_flood_scenario,
    generate_demo_roads,
)
from sar_engine import compute_sar_change
from schemas import (
    AIBriefingResponse,
    AnalysisResultResponse,
    AnalyzeASFRequest,
    AnalyzeCachedPairRequest,
    BhoonidhiSearchRequest,
    BhoonidhiSearchResponse,
    BriefingRequest,
    DemoFloodScenarioResponse,
    GranuleResponse,
    GranuleSearchRequest,
    GranuleSearchResponse,
    HealthResponse,
    HistogramBin,
    HistoryItemResponse,
    ObservationPairSearchRequest,
    ObservationPairSearchResponse,
    PairDownloadRequest,
    PairDownloadResponse,
    RoadImpactRequest,
    RoadImpactResponse,
    RoadVerificationCreate,
    RoadVerificationResponse,
    RoutePlanRequest,
    RoutePlanResponse,
)

# Load environment configuration
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger("nisar_pulse.main")

# Resolve storage directory for mask outputs
raw_storage = os.getenv("STORAGE_DIR", "../storage/masks")
storage_path = Path(raw_storage)
if not storage_path.is_absolute():
    STORAGE_DIR = (Path(__file__).resolve().parent / storage_path).resolve()
else:
    STORAGE_DIR = storage_path.resolve()
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB schema on startup
    await init_db()
    yield


app = FastAPI(
    title="NISAR-Pulse API",
    description="Real-data SAR Surface Change & Disaster Tracking Engine",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS origin restrictions (supports local dev, Render onrender.com domains, and custom env origins)
cors_env = os.getenv("CORS_ORIGINS", "")
allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
if cors_env:
    allowed_origins.extend([o.strip() for o in cors_env.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if cors_env == "*" else allowed_origins,
    allow_origin_regex=r"https://.*\.onrender\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static masks directory
app.mount("/masks", StaticFiles(directory=str(STORAGE_DIR)), name="masks")


# --- Endpoint 1: Health & Diagnostics ---
@app.get("/api/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    earthdata_token = os.getenv("EARTHDATA_TOKEN", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()

    db_ok = False
    try:
        await db.execute(select(1))
        db_ok = True
    except Exception:
        db_ok = False

    storage_writable = False
    try:
        test_file = STORAGE_DIR / ".write_test"
        test_file.write_text("ok")
        test_file.unlink()
        storage_writable = True
    except Exception:
        storage_writable = False

    return HealthResponse(
        status="healthy" if db_ok and storage_writable else "degraded",
        database_connected=db_ok,
        earthdata_configured=bool(earthdata_token),
        gemini_configured=bool(gemini_key),
        storage_writable=storage_writable,
        timestamp=datetime.now(timezone.utc),
    )


# --- Endpoint 2: Live NASA ASF Satellite Search ---
@app.post("/api/search/granules", response_model=GranuleSearchResponse)
async def search_granules(payload: GranuleSearchRequest, db: AsyncSession = Depends(get_db)):
    search_id = str(uuid.uuid4())
    granule_responses: list[GranuleResponse] = []

    try:
        # Build ASF search query
        opts: dict[str, Any] = {
            "intersectsWith": payload.wkt_polygon,
            "maxResults": payload.max_results,
        }

        if payload.dataset.upper() == "NISAR":
            opts["dataset"] = "NISAR"
        elif payload.dataset.upper() in ["SENTINEL-1", "SENTINEL1"]:
            opts["platform"] = asf.PLATFORM.SENTINEL1

        if payload.start_date:
            opts["start"] = payload.start_date
        if payload.end_date:
            opts["end"] = payload.end_date
        if payload.processing_level:
            opts["processingLevel"] = payload.processing_level

        # Run live search against NASA ASF API
        results = asf.search(**opts)
        results_list = list(results)
    except Exception as e:
        results_list = []
        error_msg = f"NASA ASF live query notice: {str(e)[:180]}"
        # Record search attempt in database
        search_rec = AOISearch(
            id=search_id,
            wkt_polygon=payload.wkt_polygon,
            dataset=payload.dataset,
            results_count=0,
        )
        db.add(search_rec)
        await db.commit()
        return GranuleSearchResponse(
            search_id=search_id,
            total_count=0,
            granules=[],
            message=error_msg,
        )

    # Persist search record
    search_rec = AOISearch(
        id=search_id,
        wkt_polygon=payload.wkt_polygon,
        dataset=payload.dataset,
        results_count=len(results_list),
    )
    db.add(search_rec)

    seen_in_batch: set[str] = set()
    for item in results_list:
        props = getattr(item, "properties", {})
        geom = getattr(item, "geojson", lambda: None)() or {}
        raw_footprint = geom.get("geometry") if isinstance(geom, dict) else None

        # Sanitize footprint: ensure footprint conforms to valid GeoJSON specification
        footprint = None
        if raw_footprint and isinstance(raw_footprint, dict):
            coords = raw_footprint.get("coordinates")
            geom_type = raw_footprint.get("type")
            if coords and isinstance(coords, list) and len(coords) > 0:
                if geom_type == "Polygon":
                    if isinstance(coords[0], list) and len(coords[0]) >= 3:
                        footprint = raw_footprint
                elif geom_type == "MultiPolygon":
                    if isinstance(coords[0], list) and len(coords[0]) > 0 and isinstance(coords[0][0], list) and len(coords[0][0]) >= 3:
                        footprint = raw_footprint
                elif geom_type in ("Point", "LineString", "MultiLineString"):
                    footprint = raw_footprint

        granule_name = props.get("fileID") or props.get("sceneName") or str(uuid.uuid4())
        if granule_name in seen_in_batch:
            continue
        seen_in_batch.add(granule_name)

        platform = props.get("platform") or payload.dataset
        processing_level = props.get("processingLevel")
        data_maturity = props.get("dataMaturity", "PROVISIONAL" if "NISAR" in platform else "VALIDATED")
        raw_pol = props.get("polarization")
        if isinstance(raw_pol, list):
            polarization = "+".join(str(p) for p in raw_pol)
        elif raw_pol:
            polarization = str(raw_pol)
        else:
            polarization = None
        # Normalize browse and download URLs (ASF can return list or string)
        raw_browse = props.get("browse") or props.get("url")
        browse_url = (
            raw_browse[0] if isinstance(raw_browse, list) and raw_browse else (
                str(raw_browse) if raw_browse else None
            )
        )

        raw_dl = props.get("url")
        download_url = (
            raw_dl[0] if isinstance(raw_dl, list) and raw_dl else (
                str(raw_dl) if raw_dl else None
            )
        )

        # Parse acquisition time safely
        acq_time = None
        raw_start = props.get("startTime")
        if raw_start:
            try:
                acq_time = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
            except Exception:
                acq_time = None

        granule_id = str(uuid.uuid4())
        # Check if already indexed
        existing = await db.execute(
            select(SARGranule).where(SARGranule.granule_name == granule_name)
        )
        granule_model = existing.scalar_one_or_none()

        if not granule_model:
            granule_model = SARGranule(
                id=granule_id,
                search_id=search_id,
                granule_name=granule_name,
                platform=platform,
                processing_level=processing_level,
                data_maturity=data_maturity,
                polarization=polarization,
                acquisition_time=acq_time,
                footprint_geojson=footprint,
                download_url=download_url,
                browse_url=browse_url,
            )
            db.add(granule_model)
        else:
            granule_id = granule_model.id
            granule_model.footprint_geojson = footprint

        granule_responses.append(
            GranuleResponse(
                id=granule_id,
                granule_name=granule_name,
                platform=platform,
                processing_level=processing_level,
                data_maturity=data_maturity,
                polarization=polarization,
                acquisition_time=acq_time,
                footprint_geojson=footprint,
                download_url=download_url,
                browse_url=browse_url,
            )
        )

    await db.commit()

    msg = None
    if len(granule_responses) == 0:
        msg = "0 granules found in NASA ASF for this exact AOI and temporal range. Expand your date window or bounding polygon."

    return GranuleSearchResponse(
        search_id=search_id,
        total_count=len(granule_responses),
        granules=granule_responses,
        message=msg,
    )


# --- Endpoint 2b: Bhoonidhi ISRO S-Band Satellite Search ---
@app.post("/api/search/bhoonidhi", response_model=BhoonidhiSearchResponse)
async def search_bhoonidhi(payload: BhoonidhiSearchRequest):
    client = get_bhoonidhi_client()
    return await client.search_products(payload)


# --- Endpoint 2c: Automatic Observation Pair Selection & Compatibility Engine ---
@app.post("/api/search/observation-pairs", response_model=ObservationPairSearchResponse)
async def search_observation_pairs(payload: ObservationPairSearchRequest):
    return await ObservationPairingService.find_pairs(payload)


# --- Endpoint 3: Change Detection on User Uploaded Files ---
@app.post("/api/analyze/upload", response_model=AnalysisResultResponse)
async def analyze_upload(
    before_file: UploadFile = File(...),
    after_file: UploadFile = File(...),
    threshold_db: float = Form(-3.0),
    speckle_filter: bool = Form(True),
    bounds: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    analysis_id = str(uuid.uuid4())

    # Validate allowed file extensions
    allowed_extensions = {".h5", ".hdf5", ".tif", ".tiff", ".png"}
    before_ext = Path(before_file.filename or "").suffix.lower()
    after_ext = Path(after_file.filename or "").suffix.lower()
    if before_ext not in allowed_extensions or after_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file extension. Allowed formats: {', '.join(sorted(allowed_extensions))}",
        )

    # Save incoming files to temporary paths
    temp_dir = STORAGE_DIR / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    before_tmp = temp_dir / f"{uuid.uuid4()}_{before_file.filename}"
    after_tmp = temp_dir / f"{uuid.uuid4()}_{after_file.filename}"

    try:
        content_before = await before_file.read()
        content_after = await after_file.read()

        if len(content_before) > 50 * 1024 * 1024 or len(content_after) > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Uploaded file exceeds 50 MB limit.")

        before_tmp.write_bytes(content_before)
        after_tmp.write_bytes(content_after)

        mask_png_name = f"{analysis_id}.png"
        mask_png_path = str(STORAGE_DIR / mask_png_name)

        parsed_bounds = None
        if bounds:
            try:
                parsed_bounds = json.loads(bounds)
            except Exception:
                parsed_bounds = None

        # Run SAR Engine
        try:
            results = compute_sar_change(
                before_path=str(before_tmp),
                after_path=str(after_tmp),
                threshold_db=threshold_db,
                speckle_filter=speckle_filter,
                output_mask_path=mask_png_path,
                default_bounds=parsed_bounds,
            )
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve)) from None
        except Exception as pe:
            logger.error(f"SAR processing error: {pe}")
            raise HTTPException(status_code=500, detail=f"SAR processing failed: {str(pe)}") from None

        # Persist analysis run
        run_record = AnalysisRun(
            id=analysis_id,
            source_type="USER_UPLOAD",
            threshold_db=threshold_db,
            speckle_filter=speckle_filter,
            impacted_km2=results["impacted_km2"],
            mean_db_drop=results["mean_db_drop"],
            severity_tier=results["severity_tier"],
            mask_image_path=f"/masks/{mask_png_name}",
            mask_geojson=results["mask_geojson"],
            histogram_json=results["histogram"],
            bounds_json=results["bounds"],
            created_at=datetime.now(timezone.utc),
        )
        db.add(run_record)
        await db.commit()

        return AnalysisResultResponse(
            analysis_id=analysis_id,
            source_type="USER_UPLOAD",
            threshold_db=threshold_db,
            speckle_filter=speckle_filter,
            impacted_km2=results["impacted_km2"],
            mean_db_drop=results["mean_db_drop"],
            severity_tier=results["severity_tier"],
            mask_image_url=f"/masks/{mask_png_name}",
            mask_geojson=results["mask_geojson"],
            bounds=results["bounds"],
            histogram=results["histogram"],
            total_scene_km2=results.get("total_scene_km2"),
            valid_pixels=results.get("valid_pixels"),
            crs=results.get("crs"),
            change_type=results.get("change_type"),
            scientific_qualification=results.get("scientific_qualification"),
            created_at=run_record.created_at,
        )
    finally:
        # Clean up temporary uploaded input files
        if before_tmp.exists():
            before_tmp.unlink()
        if after_tmp.exists():
            after_tmp.unlink()


# --- Endpoint 4: Change Detection on Indexed ASF Granules ---
@app.post("/api/analyze/asf", response_model=AnalysisResultResponse)
async def analyze_asf(payload: AnalyzeASFRequest, db: AsyncSession = Depends(get_db)):
    # Retrieve before and after granules from DB
    res_before = await db.execute(select(SARGranule).where(SARGranule.id == payload.before_granule_id))
    g_before = res_before.scalar_one_or_none()
    res_after = await db.execute(select(SARGranule).where(SARGranule.id == payload.after_granule_id))
    g_after = res_after.scalar_one_or_none()

    if not g_before or not g_after:
        raise HTTPException(status_code=404, detail="One or both selected granules not found in database.")

    # 1. Validate platform/sensor compatibility
    is_s1_both = ("Sentinel" in g_before.platform or "S1" in g_before.platform) and \
                 ("Sentinel" in g_after.platform or "S1" in g_after.platform)
    is_nisar_both = "NISAR" in g_before.platform and "NISAR" in g_after.platform
    if not (is_s1_both or is_nisar_both or g_before.platform == g_after.platform):
        raise HTTPException(
            status_code=400,
            detail=f"Incompatible satellite sensors: Cannot compare {g_before.platform} with {g_after.platform}. Both observations must belong to the same radar sensor constellation.",
        )

    # 2. Validate product processing level (Reject slant-range SLC)
    if (g_before.processing_level and "SLC" in g_before.processing_level.upper()) or \
       (g_after.processing_level and "SLC" in g_after.processing_level.upper()):
        raise HTTPException(
            status_code=400,
            detail="Level-1 SLC slant-range complex products are unsupported for direct 2D change detection. Level-2 geocoded products (GCOV, GUNW) or terrain-corrected GRD are required.",
        )

    # 3. Validate AOI coverage if aoi_wkt is supplied
    bounds = None
    if payload.aoi_wkt:
        try:
            from shapely import wkt as shapely_wkt
            from shapely.geometry import shape as shapely_shape

            aoi_geom = shapely_wkt.loads(payload.aoi_wkt)

            if g_before.footprint_geojson:
                geom_b = shapely_shape(g_before.footprint_geojson)
                if not geom_b.intersects(aoi_geom):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Pre-event observation ({g_before.granule_name}) does not cover the selected AOI region.",
                    )
            if g_after.footprint_geojson:
                geom_a = shapely_shape(g_after.footprint_geojson)
                if not geom_a.intersects(aoi_geom):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Post-event observation ({g_after.granule_name}) does not cover the selected AOI region.",
                    )

            minx, miny, maxx, maxy = aoi_geom.bounds
            bounds = [[float(miny), float(minx)], [float(maxy), float(maxx)]]
        except HTTPException:
            raise
        except Exception as err:
            logger.warning(f"Could not parse aoi_wkt: {err}")

    # Fallback to granule footprint bounds if AOI bounds not established
    if not bounds and g_before.footprint_geojson:
        coords = g_before.footprint_geojson.get("coordinates")
        if coords and isinstance(coords, list) and len(coords) > 0 and isinstance(coords[0], list):
            ring = coords[0]
            lons = [c[0] for c in ring if isinstance(c, (list, tuple)) and len(c) >= 2]
            lats = [c[1] for c in ring if isinstance(c, (list, tuple)) and len(c) >= 2]
            if lons and lats:
                bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

    analysis_id = str(uuid.uuid4())
    temp_dir = STORAGE_DIR / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    before_tmp = temp_dir / f"{uuid.uuid4()}_before.png"
    after_tmp = temp_dir / f"{uuid.uuid4()}_after.png"

    try:
        # Download real browse thumbnails or imagery
        # Earthdata token or public browse fallback
        headers = {}
        token = os.getenv("EARTHDATA_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        url_before = g_before.browse_url or g_before.download_url
        url_after = g_after.browse_url or g_after.download_url

        if not url_before or not url_after:
            raise HTTPException(
                status_code=400,
                detail=f"Selected observations missing downloadable browse/data URLs. Before: {bool(url_before)}, After: {bool(url_after)}",
            )

        resp_b = requests.get(url_before, headers=headers, timeout=30)
        resp_a = requests.get(url_after, headers=headers, timeout=30)

        if resp_b.status_code != 200 or resp_a.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch imagery from NASA servers (Status: {resp_b.status_code}/{resp_a.status_code}). Configure EARTHDATA_TOKEN in .env.",
            )

        before_tmp.write_bytes(resp_b.content)
        after_tmp.write_bytes(resp_a.content)

        mask_png_name = f"{analysis_id}.png"
        mask_png_path = str(STORAGE_DIR / mask_png_name)

        # Run SAR Engine
        try:
            results = compute_sar_change(
                before_path=str(before_tmp),
                after_path=str(after_tmp),
                threshold_db=payload.threshold_db,
                speckle_filter=payload.speckle_filter,
                output_mask_path=mask_png_path,
                default_bounds=bounds,
            )
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve)) from None
        except Exception as pe:
            logger.error(f"SAR processing error: {pe}")
            raise HTTPException(status_code=500, detail=f"SAR processing failed: {str(pe)}") from None

        run_record = AnalysisRun(
            id=analysis_id,
            before_granule_id=g_before.id,
            after_granule_id=g_after.id,
            source_type="ASF_LIVE",
            threshold_db=payload.threshold_db,
            speckle_filter=payload.speckle_filter,
            impacted_km2=results["impacted_km2"],
            mean_db_drop=results["mean_db_drop"],
            severity_tier=results["severity_tier"],
            mask_image_path=f"/masks/{mask_png_name}",
            mask_geojson=results["mask_geojson"],
            histogram_json=results["histogram"],
            bounds_json=results["bounds"],
            created_at=datetime.now(timezone.utc),
        )
        db.add(run_record)
        await db.commit()

        return AnalysisResultResponse(
            analysis_id=analysis_id,
            source_type="ASF_LIVE",
            before_granule_id=g_before.id,
            after_granule_id=g_after.id,
            before_date=g_before.acquisition_time,
            after_date=g_after.acquisition_time,
            before_platform=g_before.platform,
            after_platform=g_after.platform,
            threshold_db=payload.threshold_db,
            speckle_filter=payload.speckle_filter,
            impacted_km2=results["impacted_km2"],
            mean_db_drop=results["mean_db_drop"],
            severity_tier=results["severity_tier"],
            mask_image_url=f"/masks/{mask_png_name}",
            mask_geojson=results["mask_geojson"],
            bounds=results["bounds"],
            histogram=results["histogram"],
            total_scene_km2=results.get("total_scene_km2"),
            valid_pixels=results.get("valid_pixels"),
            crs=results.get("crs"),
            change_type=results.get("change_type"),
            scientific_qualification=results.get("scientific_qualification"),
            created_at=run_record.created_at,
        )
    finally:
        if before_tmp.exists():
            before_tmp.unlink()
        if after_tmp.exists():
            after_tmp.unlink()


# --- Endpoint 5: Structured Gemini AI Briefing ---
@app.post("/api/briefing/{analysis_id}", response_model=AIBriefingResponse)
async def create_briefing(
    analysis_id: str,
    payload: BriefingRequest = BriefingRequest(),
    db: AsyncSession = Depends(get_db),
):
    if analysis_id == "demo-flood-scenario" or analysis_id.startswith("demo"):
        analysis_dict = {
            "id": analysis_id,
            "source_type": "DEMO_SYNTHETIC",
            "impacted_km2": 8.7999,
            "mean_db_drop": -9.52,
            "threshold_db": -3.0,
            "severity_tier": "CRITICAL",
        }
        briefing_data = await generate_ai_briefing(
            analysis_record=analysis_dict,
            operational_focus=payload.operational_focus,
        )
        briefing_id = f"demo-briefing-{uuid.uuid4()}"
        return AIBriefingResponse(
            id=briefing_id,
            analysis_id=analysis_id,
            model_name=briefing_data.get("model_name", "gemini-2.5-flash"),
            risk_level=briefing_data.get("risk_level", "CRITICAL"),
            summary_text=briefing_data.get("summary_text", ""),
            primary_driver=briefing_data.get("primary_driver", "Radar Backscatter Loss / Inundation"),
            recommended_actions=briefing_data.get("recommended_actions", []),
            created_at=datetime.now(timezone.utc),
        )

    res = await db.execute(select(AnalysisRun).where(AnalysisRun.id == analysis_id))
    run = res.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found.")

    analysis_dict = {
        "id": run.id,
        "source_type": run.source_type,
        "impacted_km2": run.impacted_km2,
        "mean_db_drop": run.mean_db_drop,
        "threshold_db": run.threshold_db,
        "severity_tier": run.severity_tier,
    }

    briefing_data = await generate_ai_briefing(
        analysis_record=analysis_dict,
        operational_focus=payload.operational_focus,
    )

    briefing_id = str(uuid.uuid4())
    briefing_model = AIBriefing(
        id=briefing_id,
        analysis_id=run.id,
        model_name=briefing_data.get("model_name", "gemini-2.5-flash"),
        risk_level=briefing_data.get("risk_level", run.severity_tier),
        summary_text=briefing_data.get("summary_text", ""),
        recommended_actions_json=briefing_data.get("recommended_actions", []),
        created_at=datetime.now(timezone.utc),
    )
    db.add(briefing_model)
    await db.commit()

    return AIBriefingResponse(
        id=briefing_id,
        analysis_id=run.id,
        model_name=briefing_model.model_name,
        risk_level=briefing_model.risk_level,
        summary_text=briefing_model.summary_text,
        primary_driver=briefing_data.get("primary_driver", "Radar Backscatter Loss"),
        recommended_actions=briefing_data.get("recommended_actions", []),
        created_at=briefing_model.created_at,
    )


# --- Endpoint 6: History Archive & Item Retrieval ---
@app.get("/api/history", response_model=list[HistoryItemResponse])
async def get_history(db: AsyncSession = Depends(get_db)):
    query = select(AnalysisRun).order_by(desc(AnalysisRun.created_at)).limit(50)
    result = await db.execute(query)
    runs = result.scalars().all()

    items: list[HistoryItemResponse] = []
    for r in runs:
        # Check if briefing exists
        b_res = await db.execute(select(AIBriefing.id).where(AIBriefing.analysis_id == r.id))
        has_b = b_res.first() is not None
        items.append(
            HistoryItemResponse(
                id=r.id,
                source_type=r.source_type,
                threshold_db=r.threshold_db,
                impacted_km2=r.impacted_km2,
                mean_db_drop=r.mean_db_drop,
                severity_tier=r.severity_tier,
                has_briefing=has_b,
                created_at=r.created_at,
            )
        )
    return items


@app.get("/api/history/{analysis_id}", response_model=dict[str, Any])
async def get_history_detail(analysis_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(AnalysisRun).where(AnalysisRun.id == analysis_id))
    run = res.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found.")

    b_res = await db.execute(
        select(AIBriefing).where(AIBriefing.analysis_id == analysis_id).order_by(desc(AIBriefing.created_at))
    )
    briefing = b_res.scalars().first()

    return {
        "id": run.id,
        "analysis_id": run.id,
        "source_type": run.source_type,
        "before_granule_id": run.before_granule_id,
        "after_granule_id": run.after_granule_id,
        "threshold_db": run.threshold_db,
        "speckle_filter": run.speckle_filter,
        "impacted_km2": run.impacted_km2,
        "mean_db_drop": run.mean_db_drop,
        "severity_tier": run.severity_tier,
        "mask_image_url": run.mask_image_path,
        "mask_geojson": run.mask_geojson,
        "bounds": run.bounds_json,
        "histogram": run.histogram_json,
        "created_at": run.created_at,
        "briefing": {
            "id": briefing.id,
            "model_name": briefing.model_name,
            "risk_level": briefing.risk_level,
            "summary_text": briefing.summary_text,
            "recommended_actions": briefing.recommended_actions_json,
            "created_at": briefing.created_at,
        }
        if briefing
        else None,
    }


@app.delete("/api/history/{analysis_id}")
async def delete_history_item(analysis_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(AnalysisRun).where(AnalysisRun.id == analysis_id))
    run = res.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found.")

    if run.mask_image_path:
        mask_file = STORAGE_DIR / Path(run.mask_image_path).name
        if mask_file.exists():
            mask_file.unlink()

    await db.delete(run)
    await db.commit()
    return {"deleted": True, "analysis_id": analysis_id}


# --- Endpoint 7: Evidence-Based Road Network Impact Assessment ---
@app.post("/api/roads/impact", response_model=RoadImpactResponse)
async def assess_roads(payload: RoadImpactRequest, db: AsyncSession = Depends(get_db)):
    # 1. Resolve mask GeoJSON and geographic bounds
    mask_geojson = payload.mask_geojson
    bounds = payload.bounds
    aoi_polygon = None

    if payload.aoi_wkt:
        try:
            from shapely import wkt as shapely_wkt
            aoi_polygon = shapely_wkt.loads(payload.aoi_wkt)
            minx, miny, maxx, maxy = aoi_polygon.bounds
            bounds = [[float(miny), float(minx)], [float(maxy), float(maxx)]]
        except Exception as err:
            logger.warning(f"Could not parse aoi_wkt in road assessment: {err}")

    if payload.analysis_id and (not mask_geojson or not bounds):
        res = await db.execute(select(AnalysisRun).where(AnalysisRun.id == payload.analysis_id))
        run = res.scalar_one_or_none()
        if run:
            if not mask_geojson:
                mask_geojson = run.mask_geojson
            if not bounds:
                bounds = run.bounds_json

    if not bounds and mask_geojson and "features" in mask_geojson and len(mask_geojson["features"]) > 0:
        try:
            from shapely.geometry import shape as shapely_shape
            from shapely.ops import unary_union
            geoms = [shapely_shape(f["geometry"]) for f in mask_geojson["features"] if f.get("geometry")]
            if geoms:
                u = unary_union(geoms)
                minx, miny, maxx, maxy = u.bounds
                bounds = [[float(miny), float(minx)], [float(maxy), float(maxx)]]
        except Exception as err:
            logger.warning(f"Could not derive bounds from mask features: {err}")

    if not bounds or len(bounds) != 2:
        raise HTTPException(
            status_code=400,
            detail="Geographic bounds or AOI polygon required for road network assessment.",
        )

    # 2. Retrieve active field verifications
    verif_res = await db.execute(select(RoadVerification).order_by(RoadVerification.created_at.asc()))
    verifs = verif_res.scalars().all()
    verif_map = {
        v.osm_id: {
            "status": v.status,
            "verified_by": v.verified_by,
            "notes": v.notes,
            "created_at": v.created_at,
        }
        for v in verifs
    }

    if payload.is_demo:
        demo_verifs = {
            "DEMO-990004": {
                "status": "VERIFIED_PASSABLE",
                "verified_by": "Demo Field Team Alpha",
                "notes": "High ground causeway clear. Spillway active.",
                "created_at": "2026-02-16T12:00:00Z",
            }
        }
        verif_map = {**demo_verifs, **verif_map}

    # Overlay active client verifications submitted during the mission
    client_verifs = getattr(payload, "verifications", None)
    if client_verifs:
        for osm_id, v_data in client_verifs.items():
            if isinstance(v_data, dict):
                verif_map[str(osm_id)] = {
                    "status": v_data.get("status", "UNVERIFIED"),
                    "verified_by": v_data.get("verified_by", "Field Operator"),
                    "notes": v_data.get("notes", ""),
                    "created_at": v_data.get("created_at") or datetime.now(timezone.utc),
                }
            elif isinstance(v_data, str):
                verif_map[str(osm_id)] = {
                    "status": v_data,
                    "verified_by": "Field Operator",
                    "notes": "",
                    "created_at": datetime.now(timezone.utc),
                }

    # 3. DEMO Mode Isolation (Strictly isolated synthetic benchmark roads)
    if payload.is_demo:
        roads = generate_demo_roads(bounds)
        results = assess_road_impacts(
            roads=roads,
            mask_geojson=mask_geojson,
            proximity_threshold_meters=payload.proximity_meters,
            bounds=bounds,
            verifications=verif_map,
        )
        return RoadImpactResponse(
            assessment_id=results["assessment_id"],
            analysis_id=payload.analysis_id,
            status="COMPLETED",
            proximity_threshold_meters=payload.proximity_meters,
            total_roads_assessed=results["total_roads_assessed"],
            impacted_count=results["impacted_count"],
            nearby_count=results["nearby_count"],
            no_intersection_count=results["no_intersection_count"],
            unverified_count=results["unverified_count"],
            road_geojson=results["road_geojson"],
            message="[DEMO MODE] Assessment completed using isolated synthetic benchmark road network.",
            scientific_qualification=(
                "[DEMO MODE] Synthetic benchmark assessment for interface verification. "
                "Not real road network or disaster impact observations."
            ),
            created_at=datetime.now(timezone.utc),
        )

    # 4. Retrieve Real Road Geometries from OpenStreetMap
    try:
        roads = fetch_osm_roads(bounds=bounds, aoi_polygon=aoi_polygon)
    except OSMUnavailableError as osm_err:
        logger.error(f"OpenStreetMap retrieval error: {osm_err}")
        return RoadImpactResponse(
            assessment_id=str(uuid.uuid4()),
            analysis_id=payload.analysis_id,
            status="OSM_UNAVAILABLE",
            proximity_threshold_meters=payload.proximity_meters,
            total_roads_assessed=0,
            impacted_count=0,
            nearby_count=0,
            no_intersection_count=0,
            unverified_count=0,
            road_geojson={"type": "FeatureCollection", "features": []},
            message=f"OpenStreetMap road network data is currently unavailable for this region: {str(osm_err)}",
            scientific_qualification="OpenStreetMap data could not be retrieved. NISAR-Pulse strictly prohibits substituting fabricated road networks.",
            created_at=datetime.now(timezone.utc),
        )

    if len(roads) == 0:
        return RoadImpactResponse(
            assessment_id=str(uuid.uuid4()),
            analysis_id=payload.analysis_id,
            status="COMPLETED" if mask_geojson is not None else "UNASSESSED_NEUTRAL",
            proximity_threshold_meters=payload.proximity_meters,
            total_roads_assessed=0,
            impacted_count=0,
            nearby_count=0,
            no_intersection_count=0,
            unverified_count=0,
            road_geojson={"type": "FeatureCollection", "features": []},
            message="No OpenStreetMap driveable road geometries found within the selected bounding box.",
            scientific_qualification="Zero road geometries found in the specified AOI bounds. NISAR-Pulse strictly prohibits substituting fabricated road networks.",
            created_at=datetime.now(timezone.utc),
        )

    # 5. Assess Spatial Impacts against SAR Radiometric Change Polygons
    results = assess_road_impacts(
        roads=roads,
        mask_geojson=mask_geojson,
        proximity_threshold_meters=payload.proximity_meters,
        bounds=bounds,
        verifications=verif_map,
    )

    return RoadImpactResponse(
        assessment_id=results["assessment_id"],
        analysis_id=payload.analysis_id,
        status=results["status"],
        proximity_threshold_meters=payload.proximity_meters,
        total_roads_assessed=results["total_roads_assessed"],
        impacted_count=results["impacted_count"],
        nearby_count=results["nearby_count"],
        no_intersection_count=results["no_intersection_count"],
        unverified_count=results["unverified_count"],
        road_geojson=results["road_geojson"],
        message=results["message"],
        scientific_qualification=results["scientific_qualification"],
        created_at=datetime.now(timezone.utc),
    )


# --- Endpoint 7B: Self-Contained Isolated DEMO Flood Scenario ---
@app.post("/api/demo/flood-scenario", response_model=DemoFloodScenarioResponse)
@app.get("/api/demo/flood-scenario", response_model=DemoFloodScenarioResponse)
async def demo_flood_scenario():
    """
    Self-contained, isolated synthetic demonstration scenario.
    Generates georeferenced before/after SAR rasters, executes real compute_sar_change(),
    evaluates demo road impacts with ground-truth verification, and returns the result.
    Does NOT persist any records to operational SQLite database tables.
    """
    raw = generate_demo_flood_scenario()
    sar_raw = raw["sar_result"]
    road_raw = raw["road_assessment"]

    sar_resp = AnalysisResultResponse(
        analysis_id="demo-flood-scenario",
        source_type="DEMO_SYNTHETIC",
        before_granule_id="DEMO_SYNTH_PRE_20260201",
        after_granule_id="DEMO_SYNTH_POST_20260215",
        before_date=datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc),
        after_date=datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc),
        before_platform="DEMO-SYNTHETIC-SAR",
        after_platform="DEMO-SYNTHETIC-SAR",
        threshold_db=sar_raw["threshold_db"],
        speckle_filter=sar_raw["speckle_filter"],
        impacted_km2=sar_raw["impacted_km2"],
        mean_db_drop=sar_raw["mean_db_drop"],
        severity_tier=sar_raw["severity_tier"],
        mask_image_url=sar_raw.get("mask_image_url"),
        mask_geojson=sar_raw["mask_geojson"],
        bounds=sar_raw["bounds"],
        histogram=[HistogramBin(**b) for b in sar_raw["histogram"]],
        total_scene_km2=sar_raw.get("total_scene_km2"),
        valid_pixels=sar_raw.get("valid_pixels"),
        crs=sar_raw.get("crs"),
        change_type="[DEMO MODE] Simulated Flood Inundation",
        scientific_qualification=raw["scientific_qualification"],
        created_at=datetime.now(timezone.utc),
    )

    road_resp = RoadImpactResponse(
        assessment_id=road_raw["assessment_id"],
        analysis_id="demo-flood-scenario",
        status=road_raw["status"],
        proximity_threshold_meters=road_raw["proximity_threshold_meters"],
        total_roads_assessed=road_raw["total_roads_assessed"],
        impacted_count=road_raw["impacted_count"],
        nearby_count=road_raw["nearby_count"],
        no_intersection_count=road_raw["no_intersection_count"],
        unverified_count=road_raw["unverified_count"],
        road_geojson=road_raw["road_geojson"],
        message=road_raw.get("message") or "[DEMO MODE] Assessment completed using isolated synthetic flood scenario.",
        scientific_qualification=road_raw["scientific_qualification"],
        created_at=datetime.now(timezone.utc),
    )

    return DemoFloodScenarioResponse(
        status="SUCCESS",
        sar_result=sar_resp,
        road_assessment=road_resp,
        demo_banner=raw["demo_banner"],
        simulated_label=raw["simulated_label"],
        scientific_qualification=raw["scientific_qualification"],
    )


# --- Endpoint 8: Ground-Truth Field Verification Workflow ---
@app.post("/api/roads/verify", response_model=RoadVerificationResponse)
async def create_road_verification(
    payload: RoadVerificationCreate, db: AsyncSession = Depends(get_db)
):
    valid_statuses = {"UNVERIFIED", "VERIFIED_PASSABLE", "VERIFIED_BLOCKED", "RESTRICTED"}
    norm_status = payload.status.upper().strip()
    if norm_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid verification status '{payload.status}'. Allowed: {', '.join(sorted(valid_statuses))}",
        )

    if payload.osm_id.strip().startswith("DEMO"):
        # Isolated demo verification - do not persist to operational database
        return RoadVerificationResponse(
            id=f"demo-verif-{uuid.uuid4()}",
            osm_id=payload.osm_id.strip(),
            status=norm_status,
            verified_by=payload.verified_by.strip() or "Demo Field Team Alpha",
            notes=payload.notes or "Demo field verification",
            location_lat=payload.location_lat,
            location_lon=payload.location_lon,
            created_at=datetime.now(timezone.utc),
        )

    verif_id = str(uuid.uuid4())
    record = RoadVerification(
        id=verif_id,
        osm_id=payload.osm_id.strip(),
        status=norm_status,
        verified_by=payload.verified_by.strip(),
        notes=payload.notes,
        location_lat=payload.location_lat,
        location_lon=payload.location_lon,
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    await db.commit()

    return RoadVerificationResponse(
        id=record.id,
        osm_id=record.osm_id,
        status=record.status,
        verified_by=record.verified_by,
        notes=record.notes,
        location_lat=record.location_lat,
        location_lon=record.location_lon,
        created_at=record.created_at,
    )


@app.get("/api/roads/verifications", response_model=list[RoadVerificationResponse])
async def list_road_verifications(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(RoadVerification).order_by(desc(RoadVerification.created_at)).limit(200))
    records = res.scalars().all()
    return [
        RoadVerificationResponse(
            id=r.id,
            osm_id=r.osm_id,
            status=r.status,
            verified_by=r.verified_by,
            notes=r.notes,
            location_lat=r.location_lat,
            location_lon=r.location_lon,
            created_at=r.created_at,
        )
        for r in records
    ]


# --- Endpoint 9: Preliminary Evidence-Based Route Planning ---
@app.post("/api/roads/route", response_model=RoutePlanResponse)
async def plan_route(payload: RoutePlanRequest, db: AsyncSession = Depends(get_db)):
    # 1. Resolve mask GeoJSON and bounds
    mask_geojson = payload.mask_geojson
    bounds = payload.bounds
    aoi_polygon = None

    if payload.aoi_wkt:
        try:
            from shapely import wkt as shapely_wkt
            aoi_polygon = shapely_wkt.loads(payload.aoi_wkt)
            minx, miny, maxx, maxy = aoi_polygon.bounds
            bounds = [[float(miny), float(minx)], [float(maxy), float(maxx)]]
        except Exception as err:
            logger.warning(f"Could not parse aoi_wkt in route planning: {err}")

    if payload.analysis_id and (not mask_geojson or not bounds):
        res = await db.execute(select(AnalysisRun).where(AnalysisRun.id == payload.analysis_id))
        run = res.scalar_one_or_none()
        if run:
            if not mask_geojson:
                mask_geojson = run.mask_geojson
            if not bounds:
                bounds = run.bounds_json

    if not bounds:
        min_lat = min(payload.start_lat, payload.dest_lat) - 0.05
        max_lat = max(payload.start_lat, payload.dest_lat) + 0.05
        min_lon = min(payload.start_lon, payload.dest_lon) - 0.05
        max_lon = max(payload.start_lon, payload.dest_lon) + 0.05
        bounds = [[min_lat, min_lon], [max_lat, max_lon]]

    # 2. Retrieve persistent field verifications
    verif_res = await db.execute(select(RoadVerification).order_by(RoadVerification.created_at.asc()))
    verifs = verif_res.scalars().all()
    verif_map = {
        v.osm_id: {
            "status": v.status,
            "verified_by": v.verified_by,
            "notes": v.notes,
            "created_at": v.created_at,
        }
        for v in verifs
    }

    if payload.is_demo:
        demo_verifs = {
            "DEMO-990004": {
                "status": "VERIFIED_PASSABLE",
                "verified_by": "Demo Field Team Alpha",
                "notes": "High ground causeway clear. Spillway active.",
                "created_at": "2026-02-16T12:00:00Z",
            }
        }
        verif_map = {**demo_verifs, **verif_map}

    # Overlay active client verifications submitted during the mission
    client_verifs = getattr(payload, "verifications", None)
    if client_verifs:
        for osm_id, v_data in client_verifs.items():
            if isinstance(v_data, dict):
                verif_map[str(osm_id)] = {
                    "status": v_data.get("status", "UNVERIFIED"),
                    "verified_by": v_data.get("verified_by", "Field Operator"),
                    "notes": v_data.get("notes", ""),
                    "created_at": v_data.get("created_at") or datetime.now(timezone.utc),
                }
            elif isinstance(v_data, str):
                verif_map[str(osm_id)] = {
                    "status": v_data,
                    "verified_by": "Field Operator",
                    "notes": "",
                    "created_at": datetime.now(timezone.utc),
                }

    # 3. Retrieve road geometries (demo or live OSM)
    if payload.is_demo:
        roads = generate_demo_roads(bounds)
    else:
        try:
            roads = fetch_osm_roads(bounds=bounds, aoi_polygon=aoi_polygon)
        except OSMUnavailableError as osm_err:
            return RoutePlanResponse(
                route_id=str(uuid.uuid4()),
                status="ROUTING_UNAVAILABLE",
                routing_mode=payload.routing_mode.upper(),
                total_distance_km=0.0,
                passable_segments_count=0,
                unverified_segments_count=0,
                restricted_segments_count=0,
                route_geojson=None,
                warnings=["OpenStreetMap road network data is currently unavailable for route computation."],
                candidate_label="Candidate Route — Ground Verification Required",
                scientific_qualification="Routing unavailable due to missing road network data.",
                message=f"OSM data retrieval failed: {str(osm_err)}",
                created_at=datetime.now(timezone.utc),
            )

    # 4. Assess SAR impacts against current change polygons
    assess_road_impacts(
        roads=roads,
        mask_geojson=mask_geojson,
        proximity_threshold_meters=payload.proximity_meters,
        bounds=bounds,
        verifications=verif_map,
    )

    # 5. Compute topological route
    route_result = calculate_candidate_route(
        roads=roads,
        start_lat=payload.start_lat,
        start_lon=payload.start_lon,
        dest_lat=payload.dest_lat,
        dest_lon=payload.dest_lon,
        routing_mode=payload.routing_mode,
        permit_restricted=payload.permit_restricted,
        bounds=bounds,
    )

    return RoutePlanResponse(
        route_id=route_result["route_id"],
        status=route_result["status"],
        routing_mode=route_result["routing_mode"],
        total_distance_km=route_result["total_distance_km"],
        passable_segments_count=route_result["passable_segments_count"],
        unverified_segments_count=route_result["unverified_segments_count"],
        restricted_segments_count=route_result["restricted_segments_count"],
        route_geojson=route_result["route_geojson"],
        warnings=route_result["warnings"],
        candidate_label=route_result["candidate_label"],
        scientific_qualification=route_result["scientific_qualification"],
        message=route_result["message"],
        created_at=datetime.now(timezone.utc),
    )


# --- Endpoint: Automatic Satellite Product Pair Download ---
@app.post("/api/products/download-pair", response_model=PairDownloadResponse)
async def download_satellite_pair(payload: PairDownloadRequest):
    """
    Downloads, validates, extracts, and caches the operator-selected BEFORE and AFTER
    satellite products directly from Bhoonidhi or NASA ASF without manual upload.
    """
    downloader = ProductDownloader()
    return await downloader.download_pair(payload)


# --- Endpoint: Automatic SAR Change Detection from Validated Cached Satellite Products ---
@app.post("/api/analyze/cached-pair", response_model=AnalysisResultResponse)
async def analyze_cached_pair(
    payload: AnalyzeCachedPairRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Executes automated SAR change detection directly from validated local cache products.
    Resolves products strictly through the trusted manifest index.
    Verifies disk existence, recalculates SHA-256 hashes, and re-validates pair compatibility.
    """
    cache_mgr = ProductCacheManager()

    # 1. Resolve BEFORE product from cache
    cached_before = await cache_mgr.get_cached(payload.before_item_id)
    if not cached_before:
        raise HTTPException(
            status_code=400,
            detail=f"BEFORE product '{payload.before_item_id}' is not cached or manifest is missing. Please download the product first.",
        )

    # 2. Resolve AFTER product from cache
    cached_after = await cache_mgr.get_cached(payload.after_item_id)
    if not cached_after:
        raise HTTPException(
            status_code=400,
            detail=f"AFTER product '{payload.after_item_id}' is not cached or manifest is missing. Please download the product first.",
        )

    before_path = Path(cached_before.get("local_path", ""))
    after_path = Path(cached_after.get("local_path", ""))

    # 3. Confirm both files exist on disk
    if not before_path.exists():
        raise HTTPException(status_code=400, detail=f"BEFORE product file missing on disk: {before_path.name}")
    if not after_path.exists():
        raise HTTPException(status_code=400, detail=f"AFTER product file missing on disk: {after_path.name}")

    # 4. Recalculate and verify SHA-256 digests
    try:
        actual_before_sha = compute_file_sha256(before_path)
        expected_before_sha = cached_before.get("sha256")
        if expected_before_sha and actual_before_sha.lower() != expected_before_sha.lower():
            raise HTTPException(
                status_code=400,
                detail=f"Cache integrity verification failed for BEFORE product ({before_path.name}): SHA-256 digest mismatch. File on disk may be corrupted.",
            )

        actual_after_sha = compute_file_sha256(after_path)
        expected_after_sha = cached_after.get("sha256")
        if expected_after_sha and actual_after_sha.lower() != expected_after_sha.lower():
            raise HTTPException(
                status_code=400,
                detail=f"Cache integrity verification failed for AFTER product ({after_path.name}): SHA-256 digest mismatch. File on disk may be corrupted.",
            )
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Failed to calculate SHA-256 for cached products: {ex}")

    # 5. Verify stored validation and SAR preflight status
    if not cached_before.get("sar_preflight_ok", False):
        err = cached_before.get("sar_preflight_details", {}).get("error", "Unknown preflight failure")
        raise HTTPException(
            status_code=400,
            detail=f"BEFORE product failed SAR Engine preflight verification: {err}",
        )
    if not cached_after.get("sar_preflight_ok", False):
        err = cached_after.get("sar_preflight_details", {}).get("error", "Unknown preflight failure")
        raise HTTPException(
            status_code=400,
            detail=f"AFTER product failed SAR Engine preflight verification: {err}",
        )

    # 6. Re-run Hard Pair Compatibility Checks
    b_pt = (cached_before.get("collection_id") or payload.before_collection or "").upper()
    a_pt = (cached_after.get("collection_id") or payload.after_collection or "").upper()
    b_id = payload.before_item_id.upper()
    a_id = payload.after_item_id.upper()

    # Reject RSLC / Level-1 SLC
    unsupported_formats = {"RSLC", "SLC", "RAW", "RIFG", "L1"}
    if any(u in b_id or u in b_pt for u in unsupported_formats) or any(u in a_id or u in a_pt for u in unsupported_formats):
        raise HTTPException(
            status_code=400,
            detail="Unsupported product format: Level-1 slant-range complex products (RSLC/SLC) require geometric terrain correction and are unsupported for direct 2D backscatter change detection.",
        )

    # Reject InSAR GUNW
    if "GUNW" in b_id or "GUNW" in b_pt or "GUNW" in a_id or "GUNW" in a_pt:
        raise HTTPException(
            status_code=400,
            detail="Unsupported product format: GUNW (Geocoded Unwrapped Interferogram) products contain interferometric phase/coherence and cannot be used for radiometric backscatter change detection.",
        )

    # Cross-family check
    is_b_gcov = "GCOV" in b_id or "GCOV" in b_pt
    is_a_gcov = "GCOV" in a_id or "GCOV" in a_pt
    is_b_grd = "GRD" in b_id or "GRD" in b_pt
    is_a_grd = "GRD" in a_id or "GRD" in a_pt

    if (is_b_gcov and not is_a_gcov) or (is_a_gcov and not is_b_gcov) or (is_b_grd and not is_a_grd) or (is_a_grd and not is_b_grd):
        raise HTTPException(
            status_code=400,
            detail="Product family mismatch: Radiometric change detection requires matching product families (e.g. GCOV to GCOV, or GRD to GRD). Cannot compare GCOV with GRD.",
        )

    # Cross-sensor / frequency band check
    b_prov = payload.before_provider.upper()
    a_prov = payload.after_provider.upper()
    is_b_s1 = "SENTINEL" in b_id or "S1" in b_id or ("ASF" in b_prov and "GRD" in b_id)
    is_a_s1 = "SENTINEL" in a_id or "S1" in a_id or ("ASF" in a_prov and "GRD" in a_id)
    is_b_nisar = "NISAR" in b_id or "SSAR" in b_pt or "LSAR" in b_pt or "BHOONIDHI" in b_prov
    is_a_nisar = "NISAR" in a_id or "SSAR" in a_pt or "LSAR" in a_pt or "BHOONIDHI" in a_prov

    if (is_b_s1 and is_a_nisar) or (is_b_nisar and is_a_s1):
        raise HTTPException(
            status_code=400,
            detail="Incompatible satellite sensors / radar frequency bands: Cannot compare Sentinel-1 (C-band) with NISAR (S-band/L-band). Observations must operate in the exact same radar frequency band.",
        )

    # 7. AOI Validation & Coverage
    bounds = None
    if payload.aoi_wkt:
        try:
            from shapely import wkt as shapely_wkt
            from shapely.geometry import box as shapely_box

            aoi_geom = shapely_wkt.loads(payload.aoi_wkt)
            if not aoi_geom.is_valid:
                aoi_geom = aoi_geom.buffer(0)

            minx, miny, maxx, maxy = aoi_geom.bounds
            bounds = [[float(miny), float(minx)], [float(maxy), float(maxx)]]

            # Verify AOI overlap with raster bounds
            b_bounds = cached_before.get("sar_preflight_details", {}).get("bounds_wgs84")
            a_bounds = cached_after.get("sar_preflight_details", {}).get("bounds_wgs84")
            if b_bounds and a_bounds:
                b_box = shapely_box(b_bounds[0][1], b_bounds[0][0], b_bounds[1][1], b_bounds[1][0])
                a_box = shapely_box(a_bounds[0][1], a_bounds[0][0], a_bounds[1][1], a_bounds[1][0])
                if not b_box.intersects(aoi_geom):
                    raise HTTPException(
                        status_code=400,
                        detail=f"BEFORE product '{payload.before_item_id}' does not geographically cover the selected AOI.",
                    )
                if not a_box.intersects(aoi_geom):
                    raise HTTPException(
                        status_code=400,
                        detail=f"AFTER product '{payload.after_item_id}' does not geographically cover the selected AOI.",
                    )
        except HTTPException:
            raise
        except Exception as ex:
            logger.warning(f"Failed to parse AOI WKT geometry: {ex}")

    # Fallback bounds from preflight if AOI bounds not established
    if not bounds:
        bounds = cached_before.get("sar_preflight_details", {}).get("bounds_wgs84")

    # 8. Execute SAR Engine
    analysis_id = str(uuid.uuid4())
    mask_png_name = f"{analysis_id}.png"
    mask_png_path = str(STORAGE_DIR / mask_png_name)

    try:
        results = compute_sar_change(
            before_path=str(before_path),
            after_path=str(after_path),
            threshold_db=payload.threshold_db,
            speckle_filter=payload.speckle_filter,
            output_mask_path=mask_png_path,
            default_bounds=bounds,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from None
    except Exception as pe:
        logger.error(f"SAR processing error on cached products: {pe}")
        raise HTTPException(status_code=500, detail=f"SAR processing failed: {str(pe)}") from None

    # 9. Persist analysis run
    run_record = AnalysisRun(
        id=analysis_id,
        source_type="CACHED_SATELLITE_PAIR",
        threshold_db=payload.threshold_db,
        speckle_filter=payload.speckle_filter,
        impacted_km2=results["impacted_km2"],
        mean_db_drop=results["mean_db_drop"],
        severity_tier=results["severity_tier"],
        mask_image_path=f"/masks/{mask_png_name}",
        mask_geojson=results["mask_geojson"],
        histogram_json=results["histogram"],
        bounds_json=results["bounds"],
        created_at=datetime.now(timezone.utc),
    )
    db.add(run_record)
    await db.commit()

    return AnalysisResultResponse(
        analysis_id=analysis_id,
        source_type="CACHED_SATELLITE_PAIR",
        before_granule_id=payload.before_item_id,
        after_granule_id=payload.after_item_id,
        threshold_db=payload.threshold_db,
        speckle_filter=payload.speckle_filter,
        impacted_km2=results["impacted_km2"],
        mean_db_drop=results["mean_db_drop"],
        severity_tier=results["severity_tier"],
        mask_image_url=f"/masks/{mask_png_name}",
        mask_geojson=results["mask_geojson"],
        bounds=results["bounds"],
        histogram=results["histogram"],
        total_scene_km2=results.get("total_scene_km2"),
        valid_pixels=results.get("valid_pixels"),
        crs=results.get("crs"),
        change_type=results.get("change_type"),
        scientific_qualification=results.get("scientific_qualification"),
        created_at=run_record.created_at,
    )


# --- Frontend Static SPA Mounting ---
FRONTEND_DIST = (Path(__file__).resolve().parent.parent / "frontend" / "dist").resolve()
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="frontend_assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(FRONTEND_DIST / "index.html"))

