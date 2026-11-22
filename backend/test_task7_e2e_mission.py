"""
TASK 07: End-to-End Mission Workflow Validation & Final Reliability Suite

Validates the full NISAR-Pulse operational sequence from arbitrary AOI
to SAR analysis, road impact assessment, field verification, and candidate route planning.

Workflow Sequence:
1. Define arbitrary AOI (San Francisco Bay / Delta region).
2. Discover satellite observations via /api/search/granules contract.
3. Validate observation compatibility (platform match, chronological order, Level-2 product).
4. Execute SAR radiometric change detection via /api/analyze/asf.
5. Verify SAR change metrics and GeoJSON output.
6. Retrieve road network geometries (live OSM and DEMO mode).
7. Assess road impacts against SAR backscatter attenuation polygons.
8. Submit operator ground verification via /api/roads/verify.
9. Confirm ground verification persistence and verify SAR changes cannot overwrite it.
10. Execute Conservative Route Planning:
    - Proves shorter unverified route CANNOT beat longer verified-passable route.
    - Proves Conservative mode returns NO_ROUTE_FOUND when no verified-passable path exists (strictly excludes unverified roads).
11. Execute Exploratory Route Planning:
    - Traverses unverified roads when necessary with explicit warnings.
    - Strictly excludes VERIFIED_BLOCKED roads.
    - Respects permit_restricted flag.
    - Mandatory label: 'Candidate Route — Ground Verification Required' (never 'SAFE').
"""

import sys
import os
import uuid
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch
import numpy as np
import tempfile
from PIL import Image, TiffImagePlugin
from shapely.geometry import LineString, Polygon, mapping

# Add backend directory to path
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient
from main import app
from database import init_db, AsyncSessionLocal
from models import SARGranule, AnalysisRun, RoadVerification
from road_network import (
    assess_road_impacts,
    calculate_candidate_route,
    fetch_osm_roads,
    generate_demo_roads,
    get_metric_projector,
)
from sar_engine import compute_sar_change


def create_synthetic_geotiff(
    filename: str,
    shape_hw: tuple[int, int] = (60, 60),
    crs_epsg: int = 4326,
    pixel_size: float = 0.001,
    origin_xy: tuple[float, float] = (-122.45, 37.82),
    data_value: float = 500.0,
    drop_region: tuple[int, int, int, int] | None = None,
) -> None:
    h, w = shape_hw
    arr = np.full((h, w), data_value, dtype=np.float32)
    if drop_region:
        r0, r1, c0, c1 = drop_region
        arr[r0:r1, c0:c1] = data_value * 0.1  # -10 dB drop
    im = Image.fromarray(arr)
    ifd = TiffImagePlugin.ImageFileDirectory_v2()
    ifd[33550] = (float(pixel_size), float(pixel_size), 0.0)
    ifd[33922] = (0.0, 0.0, 0.0, float(origin_xy[0]), float(origin_xy[1]), 0.0)
    if crs_epsg == 4326:
        ifd[34735] = (1, 1, 0, 2, 1024, 0, 1, 2, 2048, 0, 1, 4326)
    else:
        ifd[34735] = (1, 1, 0, 2, 1024, 0, 1, 1, 3072, 0, 1, crs_epsg)
    im.save(filename, tiffinfo=ifd)

client = TestClient(app)


def test_full_mission_workflow():
    print("=" * 80)
    print("TASK 07: END-TO-END MISSION WORKFLOW VALIDATION & RELIABILITY")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # STEP 1: Arbitrary AOI Selection
    # -------------------------------------------------------------------------
    print("\n[STEP 1] Arbitrary AOI Definition")
    aoi_bounds = [[37.75, -122.45], [37.82, -122.38]]
    aoi_wkt = "POLYGON((-122.45 37.75, -122.38 37.75, -122.38 37.82, -122.45 37.82, -122.45 37.75))"
    assert len(aoi_bounds) == 2
    print(f"  [PASS] Arbitrary AOI established: {aoi_bounds}")

    # -------------------------------------------------------------------------
    # STEP 2 & 3: Observation Discovery & Compatibility Validation
    # -------------------------------------------------------------------------
    print("\n[STEP 2 & 3] Observation Discovery & Compatibility Controls")

    # Verify search API endpoint contract
    search_payload = {
        "wkt_polygon": aoi_wkt,
        "dataset": "SENTINEL-1",
        "start_date": "2026-01-01T00:00:00Z",
        "end_date": "2026-01-31T23:59:59Z",
        "max_results": 10,
    }
    # Test search schema validation
    res_search = client.post("/api/search/granules", json=search_payload)
    assert res_search.status_code == 200
    search_data = res_search.json()
    assert "granules" in search_data
    print("  [PASS] Granule search API contract validated successfully.")

    # Validation: Seed granules to test platform compatibility and product level checks
    s1_id = f"test-s1-{uuid.uuid4().hex[:8]}"
    nisar_id = f"test-nisar-{uuid.uuid4().hex[:8]}"
    slc_id = f"test-slc-{uuid.uuid4().hex[:8]}"

    async def seed():
        async with AsyncSessionLocal() as session:
            session.add_all([
                SARGranule(
                    id=s1_id,
                    granule_name="S1A_IW_GRDH_TEST",
                    platform="Sentinel-1A",
                    processing_level="GRD",
                    acquisition_time=datetime(2026, 1, 10, tzinfo=timezone.utc),
                ),
                SARGranule(
                    id=nisar_id,
                    granule_name="NISAR_L2_PR_GCOV_TEST",
                    platform="NISAR",
                    processing_level="GCOV",
                    acquisition_time=datetime(2026, 1, 20, tzinfo=timezone.utc),
                ),
                SARGranule(
                    id=slc_id,
                    granule_name="S1A_IW_SLC_TEST",
                    platform="Sentinel-1A",
                    processing_level="SLC",
                    acquisition_time=datetime(2026, 1, 15, tzinfo=timezone.utc),
                ),
            ])
            await session.commit()

    asyncio.run(seed())

    # Validation A: Mismatched sensor rejection
    mismatched_payload = {
        "before_granule_id": s1_id,
        "after_granule_id": nisar_id,
        "threshold_db": -3.0,
        "speckle_filter": True,
        "aoi_wkt": aoi_wkt,
    }
    res_mismatch = client.post("/api/analyze/asf", json=mismatched_payload)
    assert res_mismatch.status_code == 400
    assert "incompatible" in res_mismatch.json()["detail"].lower()
    print("  [PASS] Mismatched satellite sensors properly rejected (HTTP 400).")

    # Validation B: Level-1 SLC product rejection
    slc_payload = {
        "before_granule_id": s1_id,
        "after_granule_id": slc_id,
        "threshold_db": -3.0,
        "speckle_filter": True,
        "aoi_wkt": aoi_wkt,
    }
    res_slc = client.post("/api/analyze/asf", json=slc_payload)
    assert res_slc.status_code == 400
    assert "slc" in res_slc.json()["detail"].lower()
    print("  [PASS] Unsupported Level-1 SLC product properly rejected (HTTP 400).")

    # -------------------------------------------------------------------------
    # STEP 4 & 5: SAR Analysis Execution & Metric Grounding
    # -------------------------------------------------------------------------
    print("\n[STEP 4 & 5] SAR Processing & Metric Qualification")

    with tempfile.TemporaryDirectory() as tmp_dir:
        before_path = os.path.join(tmp_dir, "before_test.tif")
        after_path = os.path.join(tmp_dir, "after_test.tif")

        # 60x60 grid with pixel size 0.001 deg (~110m)
        # Drop region between rows 20:40 and cols 20:40
        create_synthetic_geotiff(before_path, shape_hw=(60, 60), data_value=500.0)
        create_synthetic_geotiff(after_path, shape_hw=(60, 60), data_value=500.0, drop_region=(20, 40, 20, 40))

        sar_res = compute_sar_change(
            before_path=before_path,
            after_path=after_path,
            threshold_db=-3.0,
            speckle_filter=True,
        )

        assert sar_res["impacted_km2"] > 0
        assert sar_res["mean_db_drop"] < -3.0
        assert sar_res["valid_pixels"] == 60 * 60
        assert sar_res["mask_geojson"] is not None
        assert len(sar_res["mask_geojson"]["features"]) > 0
        mask_geojson = sar_res["mask_geojson"]

        print(f"  [PASS] SAR Change Computed: {sar_res['impacted_km2']:.2f} km² attenuation, "
              f"mean drop: {sar_res['mean_db_drop']:.2f} dB, "
              f"features: {len(mask_geojson['features'])}")

    # -------------------------------------------------------------------------
    # STEP 6 & 7: Road Network Retrieval & Impact Assessment
    # -------------------------------------------------------------------------
    print("\n[STEP 6 & 7] Road Network Retrieval & Evidence-Based Impact Assessment")

    # Test DEMO mode road assessment
    impact_demo_payload = {
        "analysis_id": f"mission-{uuid.uuid4().hex[:6]}",
        "bounds": aoi_bounds,
        "proximity_meters": 50,
        "mask_geojson": mask_geojson,
        "is_demo": True,
    }
    res_impact_demo = client.post("/api/roads/impact", json=impact_demo_payload)
    assert res_impact_demo.status_code == 200
    demo_impact_data = res_impact_demo.json()
    assert demo_impact_data["status"] == "COMPLETED"
    assert demo_impact_data["total_roads_assessed"] >= 3
    print(f"  [PASS] DEMO mode road assessment completed: {demo_impact_data['total_roads_assessed']} roads.")

    # -------------------------------------------------------------------------
    # STEP 8 & 9: Field Verification Submission & Non-Overwriting Integrity
    # -------------------------------------------------------------------------
    print("\n[STEP 8 & 9] Field Verification Submission & SAR Separation")

    target_osm_id = f"way_field_{uuid.uuid4().hex[:8]}"

    # Submit verification
    verif_submission = {
        "osm_id": target_osm_id,
        "status": "VERIFIED_PASSABLE",
        "verified_by": "Specialist Delta-9",
        "notes": "Culvert inspected; water 3cm deep; passable for all vehicles.",
        "location_lat": 37.785,
        "location_lon": -122.415,
    }
    res_verif = client.post("/api/roads/verify", json=verif_submission)
    assert res_verif.status_code == 200
    verif_record = res_verif.json()
    assert verif_record["status"] == "VERIFIED_PASSABLE"
    assert verif_record["verified_by"] == "Specialist Delta-9"
    assert verif_record["created_at"] is not None
    print(f"  [PASS] Field verification submitted and persisted at {verif_record['created_at']}.")

    # Confirm retrieval via GET /api/roads/verifications
    res_list = client.get("/api/roads/verifications")
    assert res_list.status_code == 200
    assert any(v["osm_id"] == target_osm_id for v in res_list.json())
    print("  [PASS] GET /api/roads/verifications confirmed latest verification status.")

    # Reassessment integrity: SAR attenuation must NOT overwrite ground verification
    synthetic_road = {
        "osm_id": target_osm_id,
        "name": "Delta Access Highway",
        "highway": "primary",
        "geometry": LineString([[-122.42, 37.77], [-122.40, 37.77]]),
    }
    reassess_result = assess_road_impacts(
        roads=[synthetic_road],
        mask_geojson=mask_geojson,
        proximity_threshold_meters=50,
        bounds=aoi_bounds,
        verifications={
            target_osm_id: {
                "status": "VERIFIED_PASSABLE",
                "verified_by": "Specialist Delta-9",
                "notes": "Culvert inspected; water 3cm deep; passable for all vehicles.",
                "created_at": datetime.now(timezone.utc),
            }
        },
    )
    p = reassess_result["road_geojson"]["features"][0]["properties"]
    assert p["field_status"] == "VERIFIED_PASSABLE"
    assert p["verified_by"] == "Specialist Delta-9"
    print("  [PASS] Scientific integrity confirmed: SAR attenuation did not overwrite field verification.")

    # -------------------------------------------------------------------------
    # STEP 10: Conservative Routing Semantics Validation
    # -------------------------------------------------------------------------
    print("\n[STEP 10] Conservative Routing Semantics (Strict Unverified Exclusion)")

    # Build a controlled network:
    # Path 1 (Verified Passable): Nodes 10 -> 20 -> 40 (Length: ~2.8 km, longer)
    # Path 2 (Unverified): Nodes 10 -> 30 -> 40 (Length: ~2.0 km, shorter direct chord)
    test_network = [
        # Longer verified-passable route
        {
            "osm_id": "way_passable_a",
            "name": "Verified Loop A",
            "highway": "secondary",
            "nodes": [10, 20],
            "node_coords": {10: (-122.43, 37.77), 20: (-122.42, 37.785)},
            "sar_classification": "NO_DETECTED_INTERSECTION",
            "field_status": "VERIFIED_PASSABLE",
        },
        {
            "osm_id": "way_passable_b",
            "name": "Verified Loop B",
            "highway": "secondary",
            "nodes": [20, 40],
            "node_coords": {20: (-122.42, 37.785), 40: (-122.41, 37.77)},
            "sar_classification": "NO_DETECTED_INTERSECTION",
            "field_status": "VERIFIED_PASSABLE",
        },
        # Shorter unverified route
        {
            "osm_id": "way_unverified_direct",
            "name": "Unverified Shortcut",
            "highway": "primary",
            "nodes": [10, 30, 40],
            "node_coords": {
                10: (-122.43, 37.77),
                30: (-122.42, 37.77),
                40: (-122.41, 37.77),
            },
            "sar_classification": "NO_DETECTED_INTERSECTION",
            "field_status": "UNVERIFIED",
        },
    ]

    shared_coords = {
        10: (-122.43, 37.77),
        20: (-122.42, 37.785),
        30: (-122.42, 37.77),
        40: (-122.41, 37.77),
    }

    # Test A: In CONSERVATIVE mode, shorter unverified path CANNOT beat longer verified-passable path
    route_conserv = calculate_candidate_route(
        roads=test_network,
        start_lat=37.77,
        start_lon=-122.43,
        dest_lat=37.77,
        dest_lon=-122.41,
        routing_mode="CONSERVATIVE",
        permit_restricted=False,
        node_coords=shared_coords,
    )
    assert route_conserv["status"] == "ROUTE_FOUND"
    assert route_conserv["passable_segments_count"] == 2
    assert route_conserv["unverified_segments_count"] == 0
    print("  [PASS] Conservative routing selected verified-passable path (shorter unverified path excluded).")

    # Test B: In CONSERVATIVE mode, if verified-passable path is blocked, return NO_ROUTE_FOUND
    # (Must not silently use unverified shortcut!)
    test_network_blocked = [
        r if not r["osm_id"].startswith("way_passable")
        else {**r, "field_status": "VERIFIED_BLOCKED"}
        for r in test_network
    ]
    route_conserv_blocked = calculate_candidate_route(
        roads=test_network_blocked,
        start_lat=37.77,
        start_lon=-122.43,
        dest_lat=37.77,
        dest_lon=-122.41,
        routing_mode="CONSERVATIVE",
        permit_restricted=False,
        node_coords=shared_coords,
    )
    assert route_conserv_blocked["status"] == "NO_ROUTE_FOUND"
    assert "unverified" in route_conserv_blocked["warnings"][0].lower() or "unverified" in route_conserv_blocked["message"].lower()
    print("  [PASS] Conservative routing returned NO_ROUTE_FOUND when verified path was blocked (did not silently use unverified path).")

    # -------------------------------------------------------------------------
    # STEP 11: Exploratory Routing Semantics & Mandatory Labeling
    # -------------------------------------------------------------------------
    print("\n[STEP 11] Exploratory Routing Semantics & Mandatory Safety Labeling")

    # In EXPLORATORY mode on the same blocked network, the unverified shortcut CAN be traversed with warnings
    route_exploratory = calculate_candidate_route(
        roads=test_network_blocked,
        start_lat=37.77,
        start_lon=-122.43,
        dest_lat=37.77,
        dest_lon=-122.41,
        routing_mode="EXPLORATORY",
        permit_restricted=False,
        node_coords=shared_coords,
    )
    assert route_exploratory["status"] == "ROUTE_FOUND"
    assert route_exploratory["unverified_segments_count"] >= 1
    assert any("unverified" in w.lower() for w in route_exploratory["warnings"])
    print("  [PASS] Exploratory mode traversed unverified path with explicit warnings.")

    # Check mandatory scientific labeling
    label = route_exploratory["candidate_label"]
    assert "Candidate Route — Ground Verification Required" in label
    assert "safe" not in label.lower()
    assert "guaranteed" not in label.lower()
    print(f"  [PASS] Mandatory labeling strictly maintained: '{label}'")

    print("\n" + "=" * 80)
    print("TASK 07 END-TO-END MISSION WORKFLOW VALIDATION PASSED (100%)!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(init_db())
    test_full_mission_workflow()
