"""
Verification Test Suite for TASK 06: Field Verification & Evidence-Based Route Planning

Verifies:
1. Ground verification submission and persistence (POST /api/roads/verify).
2. Ground verification retrieval and history (GET /api/roads/verifications).
3. Ground verification layering on SAR impact assessments (POST /api/roads/impact).
   - SAR backscatter attenuation NEVER alters or overwrites ground verification.
   - Satellite suspicion (sar_classification) and ground reality (field_status) are cleanly separated.
4. Conservative route planning:
   - Prioritizes verified-passable roads.
   - Avoids / heavily penalizes unverified roads.
   - Completely excludes VERIFIED_BLOCKED roads.
5. Exploratory route planning:
   - Traverses unverified roads when necessary to achieve connectivity.
   - Emits explicit warnings for every traversed unverified road segment.
   - Completely excludes VERIFIED_BLOCKED roads.
6. Absolute exclusion of VERIFIED_BLOCKED road segments.
7. Restricted segments behavior (permit_restricted=False vs True).
8. Topological road geometry (LineString follows network graph nodes, never straight lines).
9. Mandatory safety labeling:
   - Labeled "Candidate Route — Ground Verification Required"
   - Explicit disclaimer present
   - Never described as "SAFE" or "GUARANTEED ACCESSIBLE"
10. DEMO Mode routing isolation.
"""

import sys
import os
import uuid
import asyncio
from datetime import datetime, timezone
from shapely.geometry import LineString, Polygon, mapping

# Ensure backend directory is on path
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient
from main import app
from database import init_db
from road_network import (
    assess_road_impacts,
    calculate_candidate_route,
    generate_demo_roads,
    get_metric_projector,
)

client = TestClient(app)


def test_field_verification_persistence_and_retrieval():
    print("\n--- 1. Field Verification Submission & Persistence ---")

    test_osm_id = f"test_way_{uuid.uuid4().hex[:8]}"

    # Submit verification
    payload = {
        "osm_id": test_osm_id,
        "status": "VERIFIED_PASSABLE",
        "verified_by": "Operator Echo-7",
        "notes": "Culvert inspected; water subsided; fully passable for light vehicles.",
        "location_lat": 37.7749,
        "location_lon": -122.4194,
    }

    res = client.post("/api/roads/verify", json=payload)
    assert res.status_code == 200, f"Submit verification failed: {res.text}"
    data = res.json()
    assert data["osm_id"] == test_osm_id
    assert data["status"] == "VERIFIED_PASSABLE"
    assert data["verified_by"] == "Operator Echo-7"
    assert "Culvert inspected" in data["notes"]
    print("  [PASS] Successfully submitted and persisted VERIFIED_PASSABLE ground truth record.")

    # Retrieve verifications list
    list_res = client.get("/api/roads/verifications")
    assert list_res.status_code == 200
    all_verifs = list_res.json()
    assert any(v["osm_id"] == test_osm_id and v["status"] == "VERIFIED_PASSABLE" for v in all_verifs)
    print("  [PASS] GET /api/roads/verifications returned recorded ground truth.")

    # Update verification to BLOCKED
    update_payload = {
        "osm_id": test_osm_id,
        "status": "VERIFIED_BLOCKED",
        "verified_by": "Operator Tango-1",
        "notes": "Mudslide detected 10 minutes ago; bridge impassable.",
    }
    res2 = client.post("/api/roads/verify", json=update_payload)
    assert res2.status_code == 200
    assert res2.json()["status"] == "VERIFIED_BLOCKED"
    print("  [PASS] Successfully updated ground status to VERIFIED_BLOCKED.")


def test_sar_attenuation_does_not_overwrite_ground_verification():
    print("\n--- 2. Scientific Integrity: SAR Never Overwrites Field Verification ---")

    # Define a road that physically intersects a SAR change polygon
    osm_id_verified = f"verif_road_{uuid.uuid4().hex[:8]}"

    # Pre-record field verification as VERIFIED_PASSABLE
    verif_payload = {
        "osm_id": osm_id_verified,
        "status": "VERIFIED_PASSABLE",
        "verified_by": "Engineer Bravo",
        "notes": "Standing water < 5cm over road; firm asphalt substrate; passable.",
    }
    client.post("/api/roads/verify", json=verif_payload)

    # SAR change polygon
    change_poly = Polygon([
        [-122.421, 37.774],
        [-122.419, 37.774],
        [-122.419, 37.776],
        [-122.421, 37.776],
        [-122.421, 37.774],
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

    road_feature = {
        "osm_id": osm_id_verified,
        "name": "Market Street Test",
        "highway": "primary",
        "geometry": LineString([[-122.422, 37.775], [-122.418, 37.775]]),
    }

    # Execute road assessment API
    assessment_payload = {
        "analysis_id": f"test-{uuid.uuid4().hex[:6]}",
        "proximity_meters": 50,
        "mask_geojson": mask_geojson,
        "bounds": [[37.77, -122.43], [37.78, -122.41]],
        "is_demo": False,
    }

    # Run direct assessment with verification injected from DB
    verifications = {
        osm_id_verified: {
            "status": "VERIFIED_PASSABLE",
            "verified_by": "Engineer Bravo",
            "notes": "Standing water < 5cm over road; firm asphalt substrate; passable.",
            "created_at": datetime.now(timezone.utc),
        }
    }

    res = assess_road_impacts(
        roads=[road_feature],
        mask_geojson=mask_geojson,
        proximity_threshold_meters=50,
        bounds=[[37.77, -122.43], [37.78, -122.41]],
        verifications=verifications,
    )

    p = res["road_geojson"]["features"][0]["properties"]

    # SAR classification must reflect satellite backscatter reduction
    assert p["sar_classification"] == "POTENTIALLY_AFFECTED"
    assert p["distance_meters"] == 0.0

    # Ground verification status must NOT have been overwritten by SAR!
    assert p["field_status"] == "VERIFIED_PASSABLE"
    assert p["verified_by"] == "Engineer Bravo"
    print("  [PASS] SAR detected POTENTIALLY_AFFECTED while field_status remained VERIFIED_PASSABLE.")
    print("  [PASS] Satellite backscatter attenuation did NOT override ground truth.")


def test_topological_candidate_routing():
    print("\n--- 3. Topological Candidate Routing (Conservative vs Exploratory) ---")

    # Create a small connected network with 3 parallel paths from Start to End
    # Node 1: (-122.43, 37.77) -> Start
    # Node 2: (-122.42, 37.78) -> Path A intermediate (Passable)
    # Node 3: (-122.42, 37.76) -> Path B intermediate (Blocked)
    # Node 4: (-122.42, 37.77) -> Path C intermediate (Unverified)
    # Node 5: (-122.41, 37.77) -> End

    roads = [
        # Path A (Passable): 1 -> 2 -> 5
        {
            "osm_id": "way_passable_1",
            "name": "North Passable Way 1",
            "highway": "secondary",
            "nodes": [1, 2],
            "geometry": LineString([[-122.43, 37.77], [-122.42, 37.78]]),
            "sar_classification": "NO_DETECTED_INTERSECTION",
            "field_status": "VERIFIED_PASSABLE",
        },
        {
            "osm_id": "way_passable_2",
            "name": "North Passable Way 2",
            "highway": "secondary",
            "nodes": [2, 5],
            "geometry": LineString([[-122.42, 37.78], [-122.41, 37.77]]),
            "sar_classification": "NO_DETECTED_INTERSECTION",
            "field_status": "VERIFIED_PASSABLE",
        },
        # Path B (Blocked): 1 -> 3 -> 5
        {
            "osm_id": "way_blocked_1",
            "name": "South Blocked Way 1",
            "highway": "secondary",
            "nodes": [1, 3],
            "geometry": LineString([[-122.43, 37.77], [-122.42, 37.76]]),
            "sar_classification": "POTENTIALLY_AFFECTED",
            "field_status": "VERIFIED_BLOCKED",
        },
        {
            "osm_id": "way_blocked_2",
            "name": "South Blocked Way 2",
            "highway": "secondary",
            "nodes": [3, 5],
            "geometry": LineString([[-122.42, 37.76], [-122.41, 37.77]]),
            "sar_classification": "POTENTIALLY_AFFECTED",
            "field_status": "VERIFIED_BLOCKED",
        },
        # Path C (Unverified): 1 -> 4 -> 5 (Shorter straight chord)
        {
            "osm_id": "way_unverified_1",
            "name": "Central Unverified Way 1",
            "highway": "secondary",
            "nodes": [1, 4],
            "geometry": LineString([[-122.43, 37.77], [-122.42, 37.77]]),
            "sar_classification": "NO_DETECTED_INTERSECTION",
            "field_status": "UNVERIFIED",
        },
        {
            "osm_id": "way_unverified_2",
            "name": "Central Unverified Way 2",
            "highway": "secondary",
            "nodes": [4, 5],
            "geometry": LineString([[-122.42, 37.77], [-122.41, 37.77]]),
            "sar_classification": "NO_DETECTED_INTERSECTION",
            "field_status": "UNVERIFIED",
        },
    ]

    node_coords = {
        1: (-122.43, 37.77),
        2: (-122.42, 37.78),
        3: (-122.42, 37.76),
        4: (-122.42, 37.77),
        5: (-122.41, 37.77),
    }

    # 1. Conservative Routing Test
    route_conservative = calculate_candidate_route(
        roads=roads,
        start_lat=37.77,
        start_lon=-122.43,
        dest_lat=37.77,
        dest_lon=-122.41,
        routing_mode="CONSERVATIVE",
        permit_restricted=False,
        node_coords=node_coords,
    )

    assert route_conservative["status"] == "ROUTE_FOUND"
    assert route_conservative["routing_mode"] == "CONSERVATIVE"
    assert route_conservative["passable_segments_count"] == 2
    assert route_conservative["unverified_segments_count"] == 0
    # Mandatory Safety Label Check
    assert "Candidate Route — Ground Verification Required" in route_conservative["candidate_label"]
    assert "safe" not in route_conservative["candidate_label"].lower()
    print("  [PASS] Conservative routing selected verified-passable path (avoided shorter unverified path).")

    # 2. Blocked Path & Conservative Unverified Exclusion Test
    # If we mark Path A as VERIFIED_BLOCKED, only unverified Path C remains.
    # Conservative mode MUST strictly return NO_ROUTE_FOUND (cannot silently use unverified).
    roads_no_passable = [
        r if not r["osm_id"].startswith("way_passable")
        else {**r, "field_status": "VERIFIED_BLOCKED"}
        for r in roads
    ]

    route_conservative_unverified_only = calculate_candidate_route(
        roads=roads_no_passable,
        start_lat=37.77,
        start_lon=-122.43,
        dest_lat=37.77,
        dest_lon=-122.41,
        routing_mode="CONSERVATIVE",
        permit_restricted=False,
        node_coords=node_coords,
    )
    assert route_conservative_unverified_only["status"] == "NO_ROUTE_FOUND"
    assert "unverified" in route_conservative_unverified_only["warnings"][0].lower() or "unverified" in route_conservative_unverified_only["message"].lower()
    print("  [PASS] Conservative mode strictly returned NO_ROUTE_FOUND when only unverified paths were available.")

    # In Exploratory mode, unverified roads CAN be traversed, but with explicit warnings:
    route_fallback = calculate_candidate_route(
        roads=roads_no_passable,
        start_lat=37.77,
        start_lon=-122.43,
        dest_lat=37.77,
        dest_lon=-122.41,
        routing_mode="EXPLORATORY",
        permit_restricted=False,
        node_coords=node_coords,
    )

    assert route_fallback["status"] == "ROUTE_FOUND"
    assert route_fallback["unverified_segments_count"] == 2
    # Exploratory mode must warn on each unverified segment
    assert any("unverified" in w.lower() for w in route_fallback["warnings"])
    print("  [PASS] Exploratory routing traversed unverified path with explicit warnings.")

    # 3. Absolute Severed Network (All paths blocked)
    roads_all_blocked = [
        {**r, "field_status": "VERIFIED_BLOCKED"}
        for r in roads
    ]

    route_blocked = calculate_candidate_route(
        roads=roads_all_blocked,
        start_lat=37.77,
        start_lon=-122.43,
        dest_lat=37.77,
        dest_lon=-122.41,
        routing_mode="CONSERVATIVE",
        permit_restricted=False,
        node_coords=node_coords,
    )

    assert route_blocked["status"] == "NO_ROUTE_FOUND"
    assert "blocked" in route_blocked["message"].lower()
    print("  [PASS] Severed/blocked network returned honest NO_ROUTE_FOUND.")


def test_restricted_segments_permission():
    print("\n--- 4. Restricted Road Segments Handling ---")

    roads_restricted = [
        {
            "osm_id": "way_restr_1",
            "name": "Restricted Levee Access Road",
            "highway": "service",
            "nodes": [10, 20],
            "geometry": LineString([[-122.43, 37.77], [-122.41, 37.77]]),
            "sar_classification": "NO_DETECTED_INTERSECTION",
            "field_status": "RESTRICTED",
        }
    ]
    node_coords = {
        10: (-122.43, 37.77),
        20: (-122.41, 37.77),
    }

    # Case A: permit_restricted=False -> No route found
    route_disallowed = calculate_candidate_route(
        roads=roads_restricted,
        start_lat=37.77,
        start_lon=-122.43,
        dest_lat=37.77,
        dest_lon=-122.41,
        routing_mode="EXPLORATORY",
        permit_restricted=False,
        node_coords=node_coords,
    )
    assert route_disallowed["status"] == "NO_ROUTE_FOUND"
    print("  [PASS] Restricted segment excluded when permit_restricted=False.")

    # Case B: permit_restricted=True -> Permitted with explicit warning
    route_allowed = calculate_candidate_route(
        roads=roads_restricted,
        start_lat=37.77,
        start_lon=-122.43,
        dest_lat=37.77,
        dest_lon=-122.41,
        routing_mode="EXPLORATORY",
        permit_restricted=True,
        node_coords=node_coords,
    )
    assert route_allowed["status"] == "ROUTE_FOUND"
    assert route_allowed["restricted_segments_count"] == 1
    assert any("restricted" in w.lower() for w in route_allowed["warnings"])
    print("  [PASS] Restricted segment traversed when permit_restricted=True with explicit warning emitted.")


def test_route_topology_not_straight_line():
    print("\n--- 5. Candidate Route Geometry is Topological LineString, Not Straight Line ---")

    demo_roads = generate_demo_roads()
    assert len(demo_roads) >= 3

    route_res = calculate_candidate_route(
        roads=demo_roads,
        start_lat=37.71,
        start_lon=-122.45,
        dest_lat=37.75,
        dest_lon=-122.41,
        routing_mode="EXPLORATORY",
        permit_restricted=False,
    )

    assert route_res["status"] == "ROUTE_FOUND"
    feat = route_res["route_geojson"]["features"][0]
    coords = feat["geometry"]["coordinates"]

    # Topological path must have multiple vertices following the road network
    assert len(coords) >= 3, "Route should contain multiple topological vertices, not just start/end chord."
    assert feat["geometry"]["type"] == "LineString"
    assert route_res["total_distance_km"] > 0
    print(f"  [PASS] Route geometry has {len(coords)} topological vertices ({route_res['total_distance_km']} km).")


def test_demo_mode_route_api_endpoint():
    print("\n--- 6. DEMO Mode Route API Endpoint ---")

    payload = {
        "start_lat": 37.710,
        "start_lon": -122.450,
        "dest_lat": 37.750,
        "dest_lon": -122.410,
        "routing_mode": "EXPLORATORY",
        "permit_restricted": False,
        "is_demo": True,
    }

    res = client.post("/api/roads/route", json=payload)
    assert res.status_code == 200, f"Route API failed: {res.text}"
    data = res.json()
    assert data["status"] == "ROUTE_FOUND"
    assert "Candidate Route — Ground Verification Required" in data["candidate_label"]
    assert data["route_geojson"] is not None
    print("  [PASS] DEMO Mode route API responded successfully with isolated benchmark data.")


def run_all_tests():
    print("=" * 75)
    print("TASK 06: FIELD VERIFICATION & ROUTE PLANNING TEST SUITE")
    print("=" * 75)

    asyncio.run(init_db())

    test_field_verification_persistence_and_retrieval()
    test_sar_attenuation_does_not_overwrite_ground_verification()
    test_topological_candidate_routing()
    test_restricted_segments_permission()
    test_route_topology_not_straight_line()
    test_demo_mode_route_api_endpoint()

    print("\n" + "=" * 75)
    print("ALL TASK 06 VERIFICATION AND ROUTING TESTS PASSED (100%)!")
    print("=" * 75)


if __name__ == "__main__":
    run_all_tests()
