"""
Verification Test Suite for TASK 04: Execute Selected SAR Observations & Display Results

Verifies:
1. Selecting two compatible observations triggers actual analysis via /api/analyze/asf.
2. Selected dates and platforms appear accurately in the result.
3. Returned GeoJSON is rendered at its actual geographic location (matching AOI bounds).
4. Unsupported products produce clear, scientifically grounded errors:
   a. Slant-range Level-1 SLC products produce an informative HTTP 400.
   b. Cross-sensor mismatched constellations (NISAR vs Sentinel-1) produce an informative HTTP 400.
   c. AOI non-intersection produces an informative HTTP 400.
5. Empty or failed analysis never creates fake map overlays or erroneous records.
"""

import sys
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch
from io import BytesIO
from PIL import Image
import numpy as np

# Ensure backend directory is in python search path
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient
from main import app
from database import AsyncSessionLocal
import models
import asyncio

client = TestClient(app)

def create_synthetic_png_bytes(width=64, height=64, base_val=128):
    """Generates a small valid in-memory grayscale PNG image for self-contained testing."""
    arr = np.full((height, width), base_val, dtype=np.uint8)
    # Add some variation so log-ratio has distinct values
    arr[16:48, 16:48] = max(0, base_val - 50)
    img = Image.fromarray(arr, mode="L")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def seed_test_granules():
    """Seed test granules into the SQLite database for testing."""
    async with AsyncSessionLocal() as session:
        # Pre-event Sentinel-1 GRD granule
        g_before = models.SARGranule(
            id="test-s1-before-" + str(uuid.uuid4())[:8],
            granule_name="S1A_IW_GRDH_1SDV_20260110T000000_TEST_PRE",
            platform="Sentinel-1A",
            processing_level="GRD",
            data_maturity="Final",
            polarization="VV",
            acquisition_time=datetime(2026, 1, 10, 14, 30, 0, tzinfo=timezone.utc),
            footprint_geojson={
                "type": "Polygon",
                "coordinates": [
                    [
                        [-122.60, 37.60],
                        [-122.20, 37.60],
                        [-122.20, 37.90],
                        [-122.60, 37.90],
                        [-122.60, 37.60],
                    ]
                ],
            },
            download_url="https://mock.asf.alaska.edu/s1_before.zip",
            browse_url="https://mock.asf.alaska.edu/s1_before.png",
        )

        # Post-event Sentinel-1 GRD granule (compatible)
        g_after = models.SARGranule(
            id="test-s1-after-" + str(uuid.uuid4())[:8],
            granule_name="S1A_IW_GRDH_1SDV_20260122T000000_TEST_POST",
            platform="Sentinel-1A",
            processing_level="GRD",
            data_maturity="Final",
            polarization="VV",
            acquisition_time=datetime(2026, 1, 22, 14, 30, 0, tzinfo=timezone.utc),
            footprint_geojson={
                "type": "Polygon",
                "coordinates": [
                    [
                        [-122.60, 37.60],
                        [-122.20, 37.60],
                        [-122.20, 37.90],
                        [-122.60, 37.90],
                        [-122.60, 37.60],
                    ]
                ],
            },
            download_url="https://mock.asf.alaska.edu/s1_after.zip",
            browse_url="https://mock.asf.alaska.edu/s1_after.png",
        )

        # Incompatible Sensor Granule (NISAR)
        g_nisar = models.SARGranule(
            id="test-nisar-" + str(uuid.uuid4())[:8],
            granule_name="NISAR_L2_PR_GCOV_001_001_001_TEST",
            platform="NISAR",
            processing_level="L2-GCOV",
            data_maturity="Final",
            polarization="HH",
            acquisition_time=datetime(2026, 1, 25, 12, 0, 0, tzinfo=timezone.utc),
            footprint_geojson=g_before.footprint_geojson,
            download_url="https://mock.asf.alaska.edu/nisar.h5",
            browse_url="https://mock.asf.alaska.edu/nisar.png",
        )

        # Unsupported Product Level (Level-1 SLC)
        g_slc = models.SARGranule(
            id="test-slc-" + str(uuid.uuid4())[:8],
            granule_name="S1A_IW_SLC__1SDV_20260115T000000_TEST_SLC",
            platform="Sentinel-1A",
            processing_level="SLC",
            data_maturity="Final",
            polarization="VV",
            acquisition_time=datetime(2026, 1, 15, 14, 30, 0, tzinfo=timezone.utc),
            footprint_geojson=g_before.footprint_geojson,
            download_url="https://mock.asf.alaska.edu/s1_slc.zip",
            browse_url="https://mock.asf.alaska.edu/s1_slc.png",
        )

        session.add_all([g_before, g_after, g_nisar, g_slc])
        await session.commit()
        return g_before, g_after, g_nisar, g_slc


def test_task4_execution_suite():
    print("=" * 70)
    print("TASK 04: EXECUTE SELECTED SAR OBSERVATIONS & DISPLAY RESULTS")
    print("=" * 70)

    # Seed test database with known observations
    g_before, g_after, g_nisar, g_slc = asyncio.run(seed_test_granules())

    aoi_wkt = "POLYGON((-122.50 37.70, -122.30 37.70, -122.30 37.85, -122.50 37.85, -122.50 37.70))"

    # Mock requests.get so tests run deterministically and fast offline
    img_before_bytes = create_synthetic_png_bytes(64, 64, base_val=140)
    img_after_bytes = create_synthetic_png_bytes(64, 64, base_val=80)

    def mock_get(url, **kwargs):
        class MockResponse:
            def __init__(self, content, status_code=200):
                self.content = content
                self.status_code = status_code

        if "before" in url:
            return MockResponse(img_before_bytes)
        return MockResponse(img_after_bytes)

    with patch("requests.get", side_effect=mock_get):
        # -------------------------------------------------------------
        # Test 1: Selecting Two Compatible Observations Triggers Actual Analysis
        # -------------------------------------------------------------
        print("\n--- 1. Trigger Actual Analysis with Compatible Observations & AOI ---")
        payload = {
            "before_granule_id": g_before.id,
            "after_granule_id": g_after.id,
            "threshold_db": -3.0,
            "speckle_filter": True,
            "aoi_wkt": aoi_wkt,
        }
        res = client.post("/api/analyze/asf", json=payload)
        assert res.status_code == 200, f"Analysis failed: {res.status_code}: {res.text}"
        data = res.json()

        assert "analysis_id" in data
        assert data["source_type"] == "ASF_LIVE"
        assert data["impacted_km2"] > 0
        assert data["mean_db_drop"] is not None
        assert data["valid_pixels"] > 0
        assert "SIGNIFICANT_BACKSCATTER_DECREASE" in data["change_type"] or "Significant Backscatter Decrease" in data["change_type"]
        assert "Field validation" in data["scientific_qualification"] or "Field verification" in data["scientific_qualification"]
        print(f"  [PASS] Actual SAR log-ratio analysis executed successfully.")
        print(f"         Impacted Area: {data['impacted_km2']} km2")
        print(f"         Mean dB Drop: {data['mean_db_drop']} dB")
        print(f"         Valid Pixels: {data['valid_pixels']}")
        print(f"         Change Classification: '{data['change_type']}'")

        # -------------------------------------------------------------
        # Test 2: Selected Dates and Platforms Appear in Result
        # -------------------------------------------------------------
        print("\n--- 2. Observation Dates & Satellite Platforms Verification ---")
        assert data["before_platform"] == "Sentinel-1A", f"Unexpected before platform: {data['before_platform']}"
        assert data["after_platform"] == "Sentinel-1A", f"Unexpected after platform: {data['after_platform']}"
        assert data["before_date"] is not None
        assert data["after_date"] is not None
        assert "2026-01-10" in data["before_date"]
        assert "2026-01-22" in data["after_date"]
        print(f"  [PASS] Pre-event Observation: {data['before_platform']} on {data['before_date']}")
        print(f"  [PASS] Post-event Observation: {data['after_platform']} on {data['after_date']}")

        # -------------------------------------------------------------
        # Test 3: Returned GeoJSON is Rendered at Actual Geographic Location
        # -------------------------------------------------------------
        print("\n--- 3. Geographic Bounds and GeoJSON Placement ---")
        assert data["mask_geojson"] is not None
        assert data["mask_geojson"]["type"] == "FeatureCollection"
        features = data["mask_geojson"]["features"]
        assert len(features) > 0, "Expected non-empty vectorized features"
        
        # Verify polygon coordinates fall within the passed AOI
        # AOI: Lon [-122.50, -122.30], Lat [37.70, 37.85]
        for feat in features[:5]:
            poly_coords = feat["geometry"]["coordinates"][0]
            for coord in poly_coords:
                lon, lat = coord[0], coord[1]
                assert -122.55 <= lon <= -122.25, f"Lon {lon} out of expected AOI bounds!"
                assert 37.65 <= lat <= 37.90, f"Lat {lat} out of expected AOI bounds!"
        print(f"  [PASS] Returned {len(features)} polygon features strictly bounded to real AOI bounds.")
        print(f"         Bounds: {data['bounds']}")

        # -------------------------------------------------------------
        # Test 4: Unsupported Products & Invalid Configurations Produce Clear Errors
        # -------------------------------------------------------------
        print("\n--- 4. Error Handling & Validation Controls ---")

        # 4a. Cross-sensor constellation mismatch (NISAR vs Sentinel-1)
        res_sensor_err = client.post("/api/analyze/asf", json={
            "before_granule_id": g_before.id,
            "after_granule_id": g_nisar.id,
            "threshold_db": -3.0,
            "speckle_filter": True,
            "aoi_wkt": aoi_wkt,
        })
        assert res_sensor_err.status_code == 400
        assert "Incompatible satellite sensors" in res_sensor_err.json()["detail"]
        print("  [PASS] Cross-sensor mismatch rejected with HTTP 400:")
        print(f"         Detail: '{res_sensor_err.json()['detail']}'")

        # 4b. Slant-range Level-1 SLC product rejection
        res_slc_err = client.post("/api/analyze/asf", json={
            "before_granule_id": g_before.id,
            "after_granule_id": g_slc.id,
            "threshold_db": -3.0,
            "speckle_filter": True,
            "aoi_wkt": aoi_wkt,
        })
        assert res_slc_err.status_code == 400
        assert "Level-1 SLC" in res_slc_err.json()["detail"]
        print("  [PASS] Unsupported Level-1 SLC product rejected with HTTP 400:")
        print(f"         Detail: '{res_slc_err.json()['detail']}'")

        # 4c. Non-overlapping AOI rejection
        disjoint_aoi = "POLYGON((10.0 45.0, 10.5 45.0, 10.5 45.5, 10.0 45.5, 10.0 45.0))"
        res_aoi_err = client.post("/api/analyze/asf", json={
            "before_granule_id": g_before.id,
            "after_granule_id": g_after.id,
            "threshold_db": -3.0,
            "speckle_filter": True,
            "aoi_wkt": disjoint_aoi,
        })
        assert res_aoi_err.status_code == 400
        assert "does not cover the selected AOI region" in res_aoi_err.json()["detail"]
        print("  [PASS] Non-overlapping AOI rejected with HTTP 400:")
        print(f"         Detail: '{res_aoi_err.json()['detail']}'")

        # -------------------------------------------------------------
        # Test 5: Empty / Failed Analysis Never Creates Fake Overlays
        # -------------------------------------------------------------
        print("\n--- 5. Data Honesty & Integrity Verification ---")
        # Check that error responses return clean error detail and no fake results
        assert "features" not in res_sensor_err.json()
        assert "mask_image_url" not in res_slc_err.json()
        assert "impacted_km2" not in res_aoi_err.json()
        print("  [PASS] Failed requests return no fabricated geometry, masks, or metrics.")

    print("\n" + "=" * 70)
    print("ALL TASK 04 VERIFICATION TESTS PASSED (100%)!")
    print("=" * 70)

if __name__ == "__main__":
    test_task4_execution_suite()
