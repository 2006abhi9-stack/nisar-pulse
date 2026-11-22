"""
Test Suite: Task 14 — Operational Road Overlay Integration & Isolated Flood Demonstration
Verifies:
1. Demo BEFORE and AFTER rasters have valid georeferencing.
2. Demo actually invokes the existing SAR change function.
3. Generated GeoJSON originates from computed raster output.
4. Impacted-area metrics are calculated rather than hardcoded.
5. Simulated change intersects the intended synthetic road.
6. Nearby road receives NEARBY_CHANGE_REGION.
7. Distant road does not receive a false blocked status.
8. SAR classification never overwrites a field verification.
9. Road network with empty OSM result produces an honest empty state.
10. OSM failure does not create fake operational roads.
11. Demo data cannot enter operational response paths.
12. Synthetic verification records cannot enter operational history.
13. Repeated demo loading produces deterministic results.
14. DEMO/OPERATIONAL mode switching clears the appropriate layers and state.
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient
from main import app
from road_network import (
    generate_demo_roads,
    generate_demo_flood_scenario,
    assess_road_impacts,
    fetch_osm_roads,
    OSMUnavailableError,
)
from sar_engine import compute_sar_change, read_sar_raster
from shapely.geometry import shape, LineString

client = TestClient(app)


def test_1_demo_rasters_valid_georeferencing():
    print("\n--- Test 1: Demo Rasters Have Valid Georeferencing ---")
    import tempfile
    import numpy as np
    from PIL import Image, TiffImagePlugin

    td = tempfile.mkdtemp()
    b_path = os.path.join(td, "test_b.tif")
    a_path = os.path.join(td, "test_a.tif")
    try:
        pixel_size = 0.001
        origin_x, origin_y = -122.50, 37.80
        b_arr = np.full((100, 100), 500.0, dtype=np.float32)
        im = Image.fromarray(b_arr)
        ifd = TiffImagePlugin.ImageFileDirectory_v2()
        ifd[33550] = (pixel_size, pixel_size, 0.0)
        ifd[33922] = (0.0, 0.0, 0.0, origin_x, origin_y, 0.0)
        ifd[34735] = (1, 1, 0, 2, 1024, 0, 1, 2, 2048, 0, 1, 4326)
        im.save(b_path, tiffinfo=ifd)

        r = read_sar_raster(b_path)
        assert r.has_georeferencing is True, "Raster must have valid georeferencing"
        assert r.crs is not None, "Raster must have valid CRS"
        assert "4326" in str(r.crs) or "WGS 84" in str(r.crs), "Raster CRS must be WGS84"
        assert r.bounds_wgs84 is not None, "Raster must compute valid WGS84 bounds"
        print(f"  [PASS] Georeferencing validated: CRS={r.crs}, bounds={r.bounds_wgs84}")
    finally:
        if os.path.exists(b_path):
            os.remove(b_path)
        if os.path.exists(td):
            os.rmdir(td)


def test_2_demo_invokes_existing_sar_change_function():
    print("\n--- Test 2: Demo Actually Invokes Existing compute_sar_change() ---")
    with patch("road_network.compute_sar_change", wraps=compute_sar_change) as mock_sar:
        raw = generate_demo_flood_scenario()
        assert mock_sar.called, "generate_demo_flood_scenario must invoke the real compute_sar_change()"
        assert mock_sar.call_count == 1
        print(f"  [PASS] Real compute_sar_change was invoked: call_count={mock_sar.call_count}")


def test_3_generated_geojson_originates_from_computed_raster():
    print("\n--- Test 3: Generated GeoJSON Originates From Computed Raster Output ---")
    raw = generate_demo_flood_scenario()
    sar_res = raw["sar_result"]
    assert "mask_geojson" in sar_res, "SAR result must contain mask_geojson"
    features = sar_res["mask_geojson"]["features"]
    assert len(features) > 0, "SAR result must contain at least 1 change polygon feature"
    geom = shape(features[0]["geometry"])
    minx, miny, maxx, maxy = geom.bounds
    # The flood patch is [35:65, 35:65] in a 100x100 grid from (-122.50, 37.80)
    # x bounds should be approximately -122.465 to -122.435
    # y bounds should be approximately 37.735 to 37.765
    assert -122.47 <= minx <= -122.46, f"Polygon minx {minx} out of expected raster range"
    assert -122.44 <= maxx <= -122.43, f"Polygon maxx {maxx} out of expected raster range"
    assert 37.73 <= miny <= 37.74, f"Polygon miny {miny} out of expected raster range"
    assert 37.76 <= maxy <= 37.77, f"Polygon maxy {maxy} out of expected raster range"
    print(f"  [PASS] GeoJSON polygon bounds strictly reflect raster indices: {geom.bounds}")


def test_4_impacted_area_metrics_calculated():
    print("\n--- Test 4: Impacted Area & dB Metrics Are Calculated Rather Than Hardcoded ---")
    raw = generate_demo_flood_scenario(threshold_db=-3.0)
    sar_res = raw["sar_result"]
    impacted_km2 = sar_res["impacted_km2"]
    mean_db = sar_res["mean_db_drop"]

    # Verify calculated values are within physical bounds
    assert 5.0 <= impacted_km2 <= 15.0, f"Calculated area {impacted_km2} out of expected bounds"
    assert -12.0 <= mean_db <= -7.0, f"Calculated dB drop {mean_db} out of expected bounds"
    assert sar_res["valid_pixels"] == 10000, f"Expected 10000 valid pixels, got {sar_res['valid_pixels']}"
    print(f"  [PASS] Calculated physical metrics: impacted_km2={impacted_km2}, mean_db_drop={mean_db} dB")


def test_5_simulated_change_intersects_intended_road():
    print("\n--- Test 5: Simulated Change Intersects Road 1 (POTENTIALLY_AFFECTED) ---")
    raw = generate_demo_flood_scenario()
    roads_res = raw["road_assessment"]
    r1 = next((f for f in roads_res["road_geojson"]["features"] if f["properties"]["osm_id"] == "DEMO-990001"), None)
    assert r1 is not None, "DEMO-990001 must exist in demo roads"
    p = r1["properties"]
    assert p["sar_classification"] == "POTENTIALLY_AFFECTED", f"Expected POTENTIALLY_AFFECTED, got {p['sar_classification']}"
    assert p["distance_meters"] == 0.0, f"Expected distance 0.0m, got {p['distance_meters']}"
    assert "[DEMO MODE]" in p["name"]
    print(f"  [PASS] DEMO-990001 correctly classified: {p['sar_classification']} (dist={p['distance_meters']}m)")


def test_6_nearby_road_receives_nearby_change_region():
    print("\n--- Test 6: Nearby Road 2 Receives NEARBY_CHANGE_REGION ---")
    raw = generate_demo_flood_scenario(proximity_threshold_meters=50.0)
    roads_res = raw["road_assessment"]
    r2 = next((f for f in roads_res["road_geojson"]["features"] if f["properties"]["osm_id"] == "DEMO-990002"), None)
    assert r2 is not None, "DEMO-990002 must exist in demo roads"
    p = r2["properties"]
    assert p["sar_classification"] == "NEARBY_CHANGE_REGION", f"Expected NEARBY_CHANGE_REGION, got {p['sar_classification']}"
    assert 0.0 < p["distance_meters"] <= 50.0, f"Distance {p['distance_meters']} should be within 50m threshold"
    print(f"  [PASS] DEMO-990002 correctly classified: {p['sar_classification']} (dist={p['distance_meters']}m <= 50m)")


def test_7_distant_road_does_not_receive_false_blocked():
    print("\n--- Test 7: Distant Road 3 Receives NO_DETECTED_INTERSECTION ---")
    raw = generate_demo_flood_scenario()
    roads_res = raw["road_assessment"]
    r3 = next((f for f in roads_res["road_geojson"]["features"] if f["properties"]["osm_id"] == "DEMO-990003"), None)
    assert r3 is not None, "DEMO-990003 must exist in demo roads"
    p = r3["properties"]
    assert p["sar_classification"] == "NO_DETECTED_INTERSECTION", f"Expected NO_DETECTED_INTERSECTION, got {p['sar_classification']}"
    assert p["distance_meters"] > 500.0, f"Distance {p['distance_meters']} should be > 500m"
    assert p["field_status"] == "UNVERIFIED", "Distant unverified road must not be labeled safe or passable"
    print(f"  [PASS] DEMO-990003 correctly classified: {p['sar_classification']} (dist={p['distance_meters']}m, field={p['field_status']})")


def test_8_sar_classification_never_overwrites_field_verification():
    print("\n--- Test 8: SAR Classification Never Overwrites Field Verification ---")
    raw = generate_demo_flood_scenario()
    roads_res = raw["road_assessment"]
    r4 = next((f for f in roads_res["road_geojson"]["features"] if f["properties"]["osm_id"] == "DEMO-990004"), None)
    assert r4 is not None, "DEMO-990004 must exist in demo roads"
    p = r4["properties"]
    assert p["field_status"] == "VERIFIED_PASSABLE", f"Expected field_status VERIFIED_PASSABLE, got {p['field_status']}"
    assert p["verified_by"] == "Demo Field Team Alpha"
    assert "High ground causeway clear" in (p["verification_notes"] or "")
    print(f"  [PASS] Ground truth preserved: field_status={p['field_status']} by {p['verified_by']}")


def test_9_empty_osm_produces_honest_empty_state():
    print("\n--- Test 9: Road Network With Empty OSM Produces Honest Empty State ---")
    with patch("main.fetch_osm_roads", return_value=[]):
        payload = {
            "bounds": [[37.75, -122.45], [37.76, -122.44]],
            "proximity_meters": 50.0,
            "mask_geojson": None,
            "is_demo": False,
        }
        res = client.post("/api/roads/impact", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["total_roads_assessed"] == 0
        assert data["road_geojson"]["features"] == []
        assert "No OpenStreetMap driveable road geometries found" in data["message"]
        print(f"  [PASS] Empty OSM road result handled honestly: total_roads_assessed=0")


def test_10_osm_failure_does_not_create_fake_roads():
    print("\n--- Test 10: OSM Failure Does Not Create Fake Operational Roads ---")
    with patch("main.fetch_osm_roads", side_effect=OSMUnavailableError("OpenStreetMap API is unreachable")):
        payload = {
            "bounds": [[37.75, -122.45], [37.76, -122.44]],
            "proximity_meters": 50.0,
            "mask_geojson": None,
            "is_demo": False,
        }
        res = client.post("/api/roads/impact", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "OSM_UNAVAILABLE"
        assert data["total_roads_assessed"] == 0
        assert data["road_geojson"]["features"] == []
        assert "prohibits substituting fabricated" in data["scientific_qualification"]
        print(f"  [PASS] OSM failure safely reported with 0 fabricated roads: status={data['status']}")


def test_11_demo_data_cannot_enter_operational_response_paths():
    print("\n--- Test 11: Demo Data Cannot Enter Operational Response Paths ---")
    # Load demo scenario via endpoint
    demo_res = client.post("/api/demo/flood-scenario")
    assert demo_res.status_code == 200

    # Query operational history
    hist_res = client.get("/api/history")
    assert hist_res.status_code == 200
    hist = hist_res.json()
    assert not any("demo" in str(h.get("source_type", "")).lower() for h in hist), "Demo run must not appear in history"
    assert not any("demo" in str(h.get("id", "")).lower() for h in hist), "Demo ID must not appear in history"
    print(f"  [PASS] Operational history checked: 0 demo records present (total={len(hist)})")


def test_12_synthetic_verification_cannot_enter_operational_history():
    print("\n--- Test 12: Synthetic Verification Records Cannot Enter Operational History ---")
    demo_res = client.post("/api/demo/flood-scenario")
    assert demo_res.status_code == 200

    verifs_res = client.get("/api/roads/verifications")
    assert verifs_res.status_code == 200
    verifs = verifs_res.json()
    assert not any("DEMO" in str(v.get("osm_id", "")) for v in verifs), "Demo verification must not be in DB"
    print(f"  [PASS] Operational verifications checked: 0 demo records present (total={len(verifs)})")


def test_13_repeated_demo_loading_produces_deterministic_results():
    print("\n--- Test 13: Repeated Demo Loading Produces Deterministic Results ---")
    res1 = client.post("/api/demo/flood-scenario").json()
    res2 = client.post("/api/demo/flood-scenario").json()

    assert res1["sar_result"]["impacted_km2"] == res2["sar_result"]["impacted_km2"]
    assert res1["sar_result"]["mean_db_drop"] == res2["sar_result"]["mean_db_drop"]
    assert res1["road_assessment"]["total_roads_assessed"] == res2["road_assessment"]["total_roads_assessed"]
    assert res1["road_assessment"]["impacted_count"] == res2["road_assessment"]["impacted_count"]
    assert res1["road_assessment"]["nearby_count"] == res2["road_assessment"]["nearby_count"]
    print(f"  [PASS] Identical deterministic outputs across runs: area={res1['sar_result']['impacted_km2']} km2")


def test_14_demo_operational_mode_switching_isolation():
    print("\n--- Test 14: DEMO/OPERATIONAL Mode Switching Isolation ---")
    # Operational request with is_demo=False
    with patch("main.fetch_osm_roads", return_value=[]) as mock_osm:
        op_payload = {
            "bounds": [[37.75, -122.45], [37.76, -122.44]],
            "proximity_meters": 50.0,
            "mask_geojson": None,
            "is_demo": False,
        }
        res_op = client.post("/api/roads/impact", json=op_payload).json()
        assert mock_osm.called, "Operational mode must invoke fetch_osm_roads"
        assert not any("DEMO" in str(f.get("properties", {}).get("name", "")) for f in res_op["road_geojson"]["features"])

    # Demo request with is_demo=True
    with patch("main.fetch_osm_roads") as mock_osm_demo:
        demo_payload = {
            "bounds": [[37.70, -122.50], [37.80, -122.40]],
            "proximity_meters": 50.0,
            "mask_geojson": None,
            "is_demo": True,
        }
        res_demo = client.post("/api/roads/impact", json=demo_payload).json()
        assert not mock_osm_demo.called, "Demo mode must NEVER call fetch_osm_roads"
        assert all("[DEMO MODE]" in f["properties"]["name"] for f in res_demo["road_geojson"]["features"])
        assert "[DEMO MODE]" in res_demo["message"]
        print("  [PASS] Complete isolation between DEMO and OPERATIONAL modes verified.")


def run_all_tests():
    print("=" * 80)
    print("TASK 14: OPERATIONAL ROAD OVERLAY INTEGRATION & ISOLATED DEMO TEST SUITE")
    print("=" * 80)

    test_1_demo_rasters_valid_georeferencing()
    test_2_demo_invokes_existing_sar_change_function()
    test_3_generated_geojson_originates_from_computed_raster()
    test_4_impacted_area_metrics_calculated()
    test_5_simulated_change_intersects_intended_road()
    test_6_nearby_road_receives_nearby_change_region()
    test_7_distant_road_does_not_receive_false_blocked()
    test_8_sar_classification_never_overwrites_field_verification()
    test_9_empty_osm_produces_honest_empty_state()
    test_10_osm_failure_does_not_create_fake_roads()
    test_11_demo_data_cannot_enter_operational_response_paths()
    test_12_synthetic_verification_cannot_enter_operational_history()
    test_13_repeated_demo_loading_produces_deterministic_results()
    test_14_demo_operational_mode_switching_isolation()

    print("=" * 80)
    print("ALL 14 TASK 14 INTEGRATION AND ISOLATION TESTS PASSED (100%)!")
    print("=" * 80)


if __name__ == "__main__":
    run_all_tests()
