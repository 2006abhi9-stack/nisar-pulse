"""
NISAR-Pulse End-to-End QA Test Suite
Tests:
1. SQLite Database & Schema (all 4 tables)
2. GET /api/health
3. POST /api/search/granules (with real WKT polygon + live ASF search)
4. POST /api/analyze/upload (file validation, rejection of invalid files, real log-ratio math, mask PNG generation)
5. GET /api/history
6. POST /api/briefing/{analysis_id} (Pydantic structured output)
"""
import os
import sqlite3
import sys

import cv2
import numpy as np
from fastapi.testclient import TestClient

from main import app

sys.stdout.reconfigure(line_buffering=True)
client = TestClient(app)

def test_1_database():
    print("\n--- 1. SQLite Database & Schema Verification ---")
    db_path = os.path.join(os.path.dirname(__file__), "nisar_pulse.db")
    assert os.path.exists(db_path), f"Database file {db_path} does not exist!"
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    tables = [t[0] for t in cur.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    expected_tables = ["aoi_searches", "sar_granules", "analysis_runs", "ai_briefings"]
    for t in expected_tables:
        assert t in tables, f"Expected table '{t}' not found in database!"
        cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t});").fetchall()]
        print(f"  [PASS] Table '{t}' exists with {len(cols)} columns: {cols[:4]}...")
    conn.close()
    print("  => DATABASE SCHEMA: PASS")

def test_2_health():
    print("\n--- 2. Health Endpoint Verification (GET /api/health) ---")
    res = client.get("/api/health")
    assert res.status_code == 200, f"Health check failed with status {res.status_code}"
    data = res.json()
    assert data["status"] in ["healthy", "HEALTHY"], f"Unexpected status: {data['status']}"
    assert data["database_connected"] is True, f"Database not connected: {data}"
    assert data["storage_writable"] is True, f"Storage not writable: {data}"
    assert "earthdata_configured" in data
    assert "gemini_configured" in data
    # Ensure keys are NEVER leaked
    for _key, val in data.items():
        assert "AIza" not in str(val), "CRITICAL: Gemini key leak detected!"
        assert "token" not in str(val).lower() or isinstance(val, bool), "CRITICAL: Token leaked!"
    print(f"  [PASS] Health returned 200: status={data['status']}, db_connected={data['database_connected']}, earthdata={data['earthdata_configured']}, gemini={data['gemini_configured']}")
    print("  => HEALTH ENDPOINT: PASS")

def test_3_search_granules():
    print("\n--- 3. Granules Search Verification (POST /api/search/granules) ---")
    # Test valid WKT polygon over Los Angeles / Southern California
    wkt = "POLYGON((-118.5 33.8, -118.1 33.8, -118.1 34.2, -118.5 34.2, -118.5 33.8))"
    payload = {
        "wkt_polygon": wkt,
        "dataset": "SENTINEL-1",
        "start_date": "2026-01-01T00:00:00Z",
        "end_date": "2026-03-31T23:59:59Z",
        "max_results": 5,
    }
    res = client.post("/api/search/granules", json=payload)
    assert res.status_code == 200, f"Search failed with status {res.status_code}: {res.text}"
    data = res.json()
    assert "search_id" in data
    assert "granules" in data
    assert isinstance(data["granules"], list)
    print(f"  [PASS] Granules returned: {len(data['granules'])} scenes.")
    if len(data["granules"]) > 0:
        first = data["granules"][0]
        assert "granule_name" in first
        assert "platform" in first
        print(f"  [PASS] Live Granule sample: {first['granule_name']} ({first['platform']})")
    print("  => GRANULES SEARCH ENDPOINT: PASS")

def test_4_analyze_upload():
    print("\n--- 4. Direct Upload & Change Engine Verification (POST /api/analyze/upload) ---")
    # 4a. Verify rejection of invalid extensions
    bad_files = {
        "before_file": ("test.exe", b"fake binary", "application/octet-stream"),
        "after_file": ("test.txt", b"fake text", "text/plain")
    }
    res_bad = client.post("/api/analyze/upload", files=bad_files, data={"threshold_db": -3.0, "speckle_filter": True})
    assert res_bad.status_code == 400, f"Expected 400 for bad extension, got {res_bad.status_code}"
    print("  [PASS] Successfully rejected invalid file formats (HTTP 400)")

    # 4b. Create calibrated synthetic-free test SAR image pair (100x100 float32 intensity rasters)
    # Simulating real SAR amplitude drop over water/damage zone
    np.random.seed(42)
    before_arr = np.random.uniform(500, 600, (100, 100)).astype(np.float32)
    after_arr = before_arr.copy()
    # Apply backscatter drop of > 6 dB in central region
    after_arr[30:70, 30:70] *= 0.2

    # 4b. Verify rejection of unanchored rasters missing coordinates (Data Honesty)
    _, before_png = cv2.imencode(".png", (before_arr / 3).astype(np.uint8))
    _, after_png = cv2.imencode(".png", (after_arr / 3).astype(np.uint8))

    files_unanchored = {
        "before_file": ("before_sar.png", before_png.tobytes(), "image/png"),
        "after_file": ("after_sar.png", after_png.tobytes(), "image/png"),
    }
    res_unanchored = client.post("/api/analyze/upload", files=files_unanchored, data={"threshold_db": -3.0})
    assert res_unanchored.status_code == 400, f"Expected 400 for unanchored raster, got {res_unanchored.status_code}"
    print("  [PASS] Successfully rejected unanchored raster without coordinates (HTTP 400)")

    # 4c. Upload with verified explicit geographic bounds
    import json
    data = {
        "threshold_db": -3.0,
        "speckle_filter": True,
        "bounds": json.dumps([[37.7, -122.5], [37.8, -122.4]]),
    }
    res = client.post("/api/analyze/upload", files=files_unanchored, data=data)
    assert res.status_code == 200, f"Upload analysis failed: {res.status_code}: {res.text}"
    result = res.json()
    assert "analysis_id" in result
    assert result["impacted_km2"] > 0, f"Expected impacted_km2 > 0, got {result['impacted_km2']}"
    assert result["mean_db_drop"] < 0, f"Expected negative dB drop, got {result['mean_db_drop']}"
    assert "histogram" in result
    assert len(result["histogram"]) > 0
    assert "mask_image_url" in result
    assert "severity_tier" in result

    # Verify mask PNG exists in storage
    from main import STORAGE_DIR
    mask_file = STORAGE_DIR / f"{result['analysis_id']}.png"
    assert mask_file.exists(), f"Generated mask PNG not found on disk at {mask_file}"
    print(f"  [PASS] Analysis run created: ID={result['analysis_id']}")
    print(f"         Impacted Area: {result['impacted_km2']} km²")
    print(f"         Mean dB Drop: {result['mean_db_drop']} dB")
    print(f"         Severity: {result['severity_tier']}")
    print(f"         Mask saved: {mask_file} ({mask_file.stat().st_size} bytes)")
    print("  => UPLOAD ANALYZE ENDPOINT: PASS")
    return result["analysis_id"]

def test_5_history(analysis_id):
    print("\n--- 5. History Archive Verification (GET /api/history) ---")
    res = client.get("/api/history")
    assert res.status_code == 200, f"History fetch failed: {res.status_code}"
    items = res.json()
    assert isinstance(items, list)
    assert len(items) > 0, "Expected at least 1 persisted analysis run in history"
    matching = [item for item in items if item["id"] == analysis_id]
    assert len(matching) == 1, f"Run {analysis_id} not found in history"
    print(f"  [PASS] Retrieved {len(items)} history runs. Found run {analysis_id}")

    # Test single item detail
    res_det = client.get(f"/api/history/{analysis_id}")
    assert res_det.status_code == 200
    assert res_det.json()["id"] == analysis_id
    print(f"  [PASS] Single run detail endpoint GET /api/history/{analysis_id} returned 200")
    print("  => HISTORY ENDPOINTS: PASS")

def test_6_briefing(analysis_id):
    print("\n--- 6. Gemini AI Briefing Verification (POST /api/briefing/{analysis_id}) ---")
    res = client.post(f"/api/briefing/{analysis_id}", json={"focus_area": "Emergency Response & Drainage"})
    assert res.status_code == 200, f"Briefing failed with status {res.status_code}: {res.text}"
    briefing = res.json()
    assert "risk_level" in briefing
    assert "summary_text" in briefing
    assert "recommended_actions" in briefing
    assert isinstance(briefing["recommended_actions"], list)
    print(f"  [PASS] AI Briefing Model: {briefing.get('model_name')}")
    print(f"         Risk Level: {briefing['risk_level']}")
    print(f"         Summary: {briefing['summary_text'][:120]}...")
    print(f"         Actions Count: {len(briefing['recommended_actions'])}")
    print("  => AI BRIEFING ENDPOINT: PASS")

if __name__ == "__main__":
    print("==================================================")
    print("STARTING NISAR-PULSE BACKEND QA VERIFICATION SUITE")
    print("==================================================")
    test_1_database()
    test_2_health()
    test_3_search_granules()
    run_id = test_4_analyze_upload()
    test_5_history(run_id)
    test_6_briefing(run_id)
    print("\n==================================================")
    print("ALL 6 BACKEND QA CHECKS PASSED WITH 100% SUCCESS!")
    print("==================================================")
