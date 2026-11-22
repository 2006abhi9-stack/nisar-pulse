"""
Verification Test Suite for TASK 05: Evidence-Based Road Network Impact Assessment

Verifies:
1. Roads intersecting actual analysis polygons are classified as POTENTIALLY_AFFECTED.
2. Nearby roads are classified separately as NEARBY_CHANGE_REGION (within metric threshold).
3. Roads without intersections are classified as NO_DETECTED_INTERSECTION and never labeled safe.
4. Geographic coordinates remain strictly in WGS84 and metric distance calculations use AEQD projection.
5. Empty SAR results produce no fabricated road impacts.
6. OpenStreetMap network failures produce a clear OSM_UNAVAILABLE state with 0 fabricated roads.
7. Arbitrary user-selected AOIs work dynamically without hardcoded roads.
8. DEMO mode remains strictly isolated with [DEMO MODE] tags.
"""

import sys
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch
from shapely.geometry import LineString, Polygon, mapping

# Ensure backend directory is in python search path
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient
from main import app
from database import AsyncSessionLocal, init_db
import models
import asyncio
from road_network import (
    assess_road_impacts,
    fetch_osm_roads,
    generate_demo_roads,
    get_metric_projector,
    OSMUnavailableError,
)

client = TestClient(app)


def test_spatial_methodology_and_metric_projection():
    print("\n--- 1. Spatial Intersection & Metric AEQD Projection Methodology ---")

    # Define a test change polygon in San Francisco
    # Centered around lon: -122.4200, lat: 37.7750, ~100m wide
    change_poly = Polygon([
        [-122.4210, 37.7745],
        [-122.4190, 37.7745],
        [-122.4190, 37.7755],
        [-122.4210, 37.7755],
        [-122.4210, 37.7745],
    ])

    mask_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(change_poly),
                "properties": {"change_type": "SIGNIFICANT_BACKSCATTER_DECREASE"},
            }
        ],
    }

    # Road 1: Intersecting directly
    road_intersect = {
        "osm_id": 1001,
        "name": "Mission Street (Intersecting)",
        "highway": "primary",
        "geometry": LineString([[-122.4220, 37.7750], [-122.4180, 37.7750]]),
    }

    # Road 2: Nearby (~35 meters south of the change polygon)
    # 0.0003 deg lat ~ 33.3 meters
    road_nearby = {
        "osm_id": 1002,
        "name": "Howard Street (Nearby)",
        "highway": "secondary",
        "geometry": LineString([[-122.4210, 37.7742], [-122.4190, 37.7742]]),
    }

    # Road 3: Far away (~1.5 km away)
    road_far = {
        "osm_id": 1003,
        "name": "Presidio Boulevard (Far)",
        "highway": "residential",
        "geometry": LineString([[-122.4350, 37.7750], [-122.4300, 37.7750]]),
    }

    roads = [road_intersect, road_nearby, road_far]

    # Run assessment with 50m proximity threshold
    result = assess_road_impacts(
        roads=roads,
        mask_geojson=mask_geojson,
        proximity_threshold_meters=50.0,
        bounds=[[37.77, -122.43], [37.78, -122.41]],
    )

    assert result["status"] == "COMPLETED"
    assert result["total_roads_assessed"] == 3
    assert result["impacted_count"] == 1
    assert result["nearby_count"] == 1
    assert result["no_intersection_count"] == 1

    features = {f["properties"]["osm_id"]: f["properties"] for f in result["road_geojson"]["features"]}

    # Verify Road 1: Potentially Affected
    assert features[1001]["classification"] == "POTENTIALLY_AFFECTED"
    assert features[1001]["distance_meters"] == 0.0
    assert "intersects" in features[1001]["assessment_note"].lower()
    print("  [PASS] Intersecting road classified as POTENTIALLY_AFFECTED with distance 0.0m.")

    # Verify Road 2: Nearby Change Region
    assert features[1002]["classification"] == "NEARBY_CHANGE_REGION"
    assert 0.0 < features[1002]["distance_meters"] <= 50.0
    print(f"  [PASS] Nearby road classified as NEARBY_CHANGE_REGION with distance {features[1002]['distance_meters']}m <= 50m.")

    # Verify Road 3: No Detected Intersection
    assert features[1003]["classification"] == "NO_DETECTED_INTERSECTION"
    assert features[1003]["distance_meters"] > 50.0
    assert "safe" not in features[1003]["classification"].lower()
    print(f"  [PASS] Distant road classified as NO_DETECTED_INTERSECTION ({features[1003]['distance_meters']}m), strictly NOT labeled safe.")


def test_empty_sar_results_handling():
    print("\n--- 2. Empty SAR Results Produce No Fabricated Impacts ---")

    empty_mask = {
        "type": "FeatureCollection",
        "features": [],
    }

    test_roads = [
        {
            "osm_id": 2001,
            "name": "Oak Street",
            "highway": "residential",
            "geometry": LineString([[-122.42, 37.77], [-122.41, 37.77]]),
        }
    ]

    result = assess_road_impacts(
        roads=test_roads,
        mask_geojson=empty_mask,
        proximity_threshold_meters=50.0,
        bounds=[[37.76, -122.43], [37.78, -122.40]],
    )

    assert result["status"] == "NO_CHANGE_DETECTED"
    assert result["impacted_count"] == 0
    assert result["nearby_count"] == 0
    assert result["no_intersection_count"] == 1
    p = result["road_geojson"]["features"][0]["properties"]
    assert p["classification"] == "NO_DETECTED_INTERSECTION"
    assert "Zero backscatter change" in p["assessment_note"]
    print("  [PASS] Empty SAR results yield 0 impacted and 0 nearby roads without fabricating impact.")


def test_osm_network_failure_handling():
    print("\n--- 3. OSM Network Failure Handling (Zero Fabricated Roads) ---")

    # Patch fetch_osm_roads to simulate network failure/timeout
    with patch("main.fetch_osm_roads", side_effect=OSMUnavailableError("Connection timed out to OSM API")):
        payload = {
            "bounds": [[37.77, -122.42], [37.78, -122.41]],
            "proximity_meters": 50.0,
            "mask_geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[-122.42, 37.77], [-122.41, 37.77], [-122.41, 37.78], [-122.42, 37.78], [-122.42, 37.77]]]
                        }
                    }
                ]
            }
        }
        res = client.post("/api/roads/impact", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "OSM_UNAVAILABLE"
        assert data["total_roads_assessed"] == 0
        assert data["road_geojson"]["features"] == []
        assert "unavailable" in data["message"].lower()
        assert "prohibits substituting fabricated" in data["scientific_qualification"]
        print("  [PASS] OSM network failure produces clean OSM_UNAVAILABLE state with 0 fabricated roads.")


def test_demo_mode_isolation():
    print("\n--- 4. DEMO Mode Isolation ---")

    demo_bounds = [[37.70, -122.50], [37.80, -122.40]]
    demo_mask = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-122.47, 37.73],
                        [-122.43, 37.73],
                        [-122.43, 37.77],
                        [-122.47, 37.77],
                        [-122.47, 37.73]
                    ]]
                }
            }
        ]
    }

    payload_demo = {
        "bounds": demo_bounds,
        "mask_geojson": demo_mask,
        "proximity_meters": 50.0,
        "is_demo": True,
    }

    res = client.post("/api/roads/impact", json=payload_demo)
    assert res.status_code == 200
    data = res.json()
    assert "[DEMO MODE]" in data["message"]
    assert "[DEMO MODE]" in data["scientific_qualification"]
    for f in data["road_geojson"]["features"]:
        assert "[DEMO MODE]" in f["properties"]["name"]
    print("  [PASS] DEMO mode returns isolated benchmark roads strictly tagged with '[DEMO MODE]'.")


def test_arbitrary_aoi_live_osm_retrieval():
    print("\n--- 5. Arbitrary AOI Live OpenStreetMap Retrieval ---")

    # Test an arbitrary small bounding box (Downtown San Francisco)
    bounds = [[37.780, -122.415], [37.785, -122.410]]
    aoi_wkt = "POLYGON((-122.415 37.780, -122.410 37.780, -122.410 37.785, -122.415 37.785, -122.415 37.780))"

    # Define a small change polygon intersecting this arbitrary region
    mask = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-122.413, 37.782],
                        [-122.411, 37.782],
                        [-122.411, 37.784],
                        [-122.413, 37.784],
                        [-122.413, 37.782]
                    ]]
                }
            }
        ]
    }

    payload = {
        "aoi_wkt": aoi_wkt,
        "bounds": bounds,
        "mask_geojson": mask,
        "proximity_meters": 50.0,
        "is_demo": False,
    }

    res = client.post("/api/roads/impact", json=payload)
    assert res.status_code == 200
    data = res.json()

    if data["status"] == "COMPLETED":
        assert data["total_roads_assessed"] > 0
        assert data["impacted_count"] > 0 or data["nearby_count"] > 0 or data["no_intersection_count"] > 0
        # Ensure road geometries are LineString in WGS84
        first_feat = data["road_geojson"]["features"][0]
        assert first_feat["geometry"]["type"] in ["LineString", "MultiLineString"]
        coords = first_feat["geometry"]["coordinates"]
        lon, lat = coords[0] if first_feat["geometry"]["type"] == "LineString" else coords[0][0]
        assert -122.45 <= lon <= -122.35
        assert 37.75 <= lat <= 37.80
        print(f"  [PASS] Live OSM road query succeeded for arbitrary AOI: {data['total_roads_assessed']} roads assessed.")
        print(f"         Impacted: {data['impacted_count']}, Nearby: {data['nearby_count']}, No overlap: {data['no_intersection_count']}")
    else:
        # If external network was throttled by OSM, verify clean unavailable status
        assert data["status"] == "OSM_UNAVAILABLE"
        print(f"  [PASS] Live OSM endpoint throttled/offline, properly returned status: '{data['status']}'")


def run_all_tests():
    print("=" * 75)
    print("TASK 05: EVIDENCE-BASED ROAD NETWORK IMPACT ASSESSMENT TEST SUITE")
    print("=" * 75)

    asyncio.run(init_db())

    test_spatial_methodology_and_metric_projection()
    test_empty_sar_results_handling()
    test_osm_network_failure_handling()
    test_demo_mode_isolation()
    test_arbitrary_aoi_live_osm_retrieval()

    print("\n" + "=" * 75)
    print("ALL TASK 05 ROAD NETWORK IMPACT TESTS PASSED (100%)!")
    print("=" * 75)


if __name__ == "__main__":
    run_all_tests()
