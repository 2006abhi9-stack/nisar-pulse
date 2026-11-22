"""
Verification script for TASK 03:
Validates the /api/analyze/upload API response and data integrity for frontend map consumption.
Tests:
1. End-to-end /api/analyze/upload response payload schema and values.
2. GeoJSON polygon coordinates are valid WGS84 [lon, lat] pairs within [-180, 180] and [-90, 90].
3. Leaflet bounds compatibility: bounds are [[min_lat, min_lon], [max_lat, max_lon]].
4. Scientific naming: 'change_type' is 'SIGNIFICANT_BACKSCATTER_DECREASE' and 'scientific_qualification' is present.
5. Metrics presence: impacted_km2, mean_db_drop, valid_pixels, crs.
6. Empty geometry handling: test behavior when threshold produces zero change.
7. Error handling: invalid files or missing georeferencing return clear 400 errors without crashing.
"""

import json
import numpy as np
import cv2
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def run_task3_verification():
    print("=" * 65)
    print("TASK 03: FRONTEND MAP & ANALYSIS CONTRACT VERIFICATION")
    print("=" * 65)

    # 1. Setup georeferenced synthetic SAR rasters (100x100)
    np.random.seed(42)
    before_arr = np.random.uniform(500, 600, (100, 100)).astype(np.float32)
    after_arr = before_arr.copy()
    # 40x40 area in center has backscatter drop (> -6 dB)
    after_arr[30:70, 30:70] *= 0.2

    _, before_png = cv2.imencode(".png", (before_arr / 3).astype(np.uint8))
    _, after_png = cv2.imencode(".png", (after_arr / 3).astype(np.uint8))

    files = {
        "before_file": ("before.png", before_png.tobytes(), "image/png"),
        "after_file": ("after.png", after_png.tobytes(), "image/png"),
    }
    bounds = [[37.70, -122.50], [37.80, -122.40]]
    data = {
        "threshold_db": -3.0,
        "speckle_filter": True,
        "bounds": json.dumps(bounds),
    }

    # 2. Test successful upload and response
    print("\n--- 1. Testing /api/analyze/upload Response Payload ---")
    res = client.post("/api/analyze/upload", files=files, data=data)
    assert res.status_code == 200, f"Analysis upload failed: {res.status_code}: {res.text}"
    result = res.json()
    print("  [PASS] HTTP 200 OK received from /api/analyze/upload")

    # 3. Verify Metrics Presence (Requirement 5)
    print("\n--- 2. Verifying Compact Analysis Summary Metrics ---")
    assert "impacted_km2" in result and result["impacted_km2"] > 0
    print(f"  [PASS] impacted_km2: {result['impacted_km2']} km²")

    assert "mean_db_drop" in result and result["mean_db_drop"] < 0
    print(f"  [PASS] mean_db_drop: {result['mean_db_drop']} dB")

    assert "valid_pixels" in result and result["valid_pixels"] == 10000
    print(f"  [PASS] valid_pixels: {result['valid_pixels']}")

    assert "crs" in result and "EPSG" in result["crs"]
    print(f"  [PASS] crs: {result['crs']}")

    # 4. Verify Scientific Naming (Requirement 6)
    print("\n--- 3. Verifying Scientific Naming and Qualification ---")
    assert "change_type" in result
    assert result["change_type"] == "SIGNIFICANT_BACKSCATTER_DECREASE"
    print(f"  [PASS] change_type: '{result['change_type']}' (Defensible scientific naming)")

    assert "scientific_qualification" in result
    assert "Field verification" in result["scientific_qualification"]
    print(f"  [PASS] scientific_qualification: '{result['scientific_qualification'][:65]}...'")

    # 5. Verify Map Bounds Compatibility (Requirement 4)
    print("\n--- 4. Verifying Bounds Zoom Compatibility ---")
    assert "bounds" in result and result["bounds"] is not None
    ret_bounds = result["bounds"]
    assert len(ret_bounds) == 2, f"Bounds must have 2 points, got {ret_bounds}"
    sw, ne = ret_bounds[0], ret_bounds[1]
    assert sw[0] < ne[0], f"South lat ({sw[0]}) must be < North lat ({ne[0]})"
    assert sw[1] < ne[1], f"West lon ({sw[1]}) must be < East lon ({ne[1]})"
    print(f"  [PASS] Bounds valid for Leaflet flyToBounds: SW={sw}, NE={ne}")

    # 6. Verify GeoJSON Polygons (Requirement 3)
    print("\n--- 5. Verifying GeoJSON Geometry & WGS84 Coordinates ---")
    assert "mask_geojson" in result
    geojson = result["mask_geojson"]
    assert geojson["type"] == "FeatureCollection"
    assert "features" in geojson and len(geojson["features"]) > 0
    print(f"  [PASS] FeatureCollection contains {len(geojson['features'])} change polygon features")

    feature = geojson["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] in ["Polygon", "MultiPolygon"]
    coords = feature["geometry"]["coordinates"]

    # Verify coordinates are in valid longitude [-180, 180] and latitude [-90, 90]
    sample_coord = coords[0][0]
    lon, lat = sample_coord[0], sample_coord[1]
    assert -180.0 <= lon <= 180.0, f"Invalid longitude: {lon}"
    assert -90.0 <= lat <= 90.0, f"Invalid latitude: {lat}"
    print(f"  [PASS] Sample WGS84 coordinate: lon={lon:.6f}, lat={lat:.6f}")

    # 7. Test Empty Geometry Handling (Requirement 7)
    print("\n--- 6. Verifying Empty Geometry Handling ---")
    # Using an impossibly low threshold (-50 dB) where no pixels drop that much
    data_empty = {
        "threshold_db": -50.0,
        "speckle_filter": True,
        "bounds": json.dumps(bounds),
    }
    files_empty = {
        "before_file": ("before.png", before_png.tobytes(), "image/png"),
        "after_file": ("after.png", after_png.tobytes(), "image/png"),
    }
    res_empty = client.post("/api/analyze/upload", files=files_empty, data=data_empty)
    assert res_empty.status_code == 200
    res_empty_data = res_empty.json()
    assert res_empty_data["impacted_km2"] == 0.0
    assert len(res_empty_data["mask_geojson"]["features"]) == 0
    print("  [PASS] Empty geometry handled cleanly: impacted_km2=0, features=[]")

    # 8. Test Failed Uploads & Missing Optional Fields Gracefully (Requirement 7)
    print("\n--- 7. Verifying Error Handling on Failed Uploads ---")
    bad_files = {
        "before_file": ("bad.exe", b"invalid executable", "application/octet-stream"),
        "after_file": ("bad.txt", b"invalid text", "text/plain"),
    }
    res_fail = client.post("/api/analyze/upload", files=bad_files, data=data)
    assert res_fail.status_code == 400
    print(f"  [PASS] Invalid file rejection: HTTP 400, detail='{res_fail.json()['detail']}'")

    unanchored_files = {
        "before_file": ("before.png", before_png.tobytes(), "image/png"),
        "after_file": ("after.png", after_png.tobytes(), "image/png"),
    }
    res_no_bounds = client.post("/api/analyze/upload", files=unanchored_files, data={"threshold_db": -3.0})
    assert res_no_bounds.status_code == 400
    print(f"  [PASS] Unanchored file rejection: HTTP 400, detail='{res_no_bounds.json()['detail']}'")

    print("\n" + "=" * 65)
    print("ALL TASK 03 MAP & ANALYSIS CHECKS PASSED WITH 100% SUCCESS!")
    print("=" * 65)

if __name__ == "__main__":
    run_task3_verification()
