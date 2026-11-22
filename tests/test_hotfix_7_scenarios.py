import asyncio
import json
import os
import sys
import httpx
from datetime import datetime
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

# Import app
from backend.main import app

async def run_tests():
    print("Starting 7 controlled test scenarios...")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Scenario 1: Multiple valid granules
        print("\n--- Scenario 1: Multiple valid granules ---")
        mock_item1 = MagicMock()
        mock_item1.properties = {
            "fileID": "SCENE_VALID_1",
            "platform": "Sentinel-1A",
            "processingLevel": "GRD",
            "polarization": "VV+VH",
            "startTime": "2026-02-01T12:00:00Z",
            "url": "https://asf.alaska.edu/valid1.zip",
        }
        mock_item1.geojson.return_value = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-122.5, 37.7], [-122.4, 37.7], [-122.4, 37.8], [-122.5, 37.8], [-122.5, 37.7]]],
            },
        }
        mock_item2 = MagicMock()
        mock_item2.properties = {
            "fileID": "SCENE_VALID_2",
            "platform": "Sentinel-1B",
            "processingLevel": "GRD",
            "polarization": "VV",
            "startTime": "2026-02-12T12:00:00Z",
            "url": "https://asf.alaska.edu/valid2.zip",
        }
        mock_item2.geojson.return_value = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-122.45, 37.72], [-122.35, 37.72], [-122.35, 37.82], [-122.45, 37.82], [-122.45, 37.72]]],
            },
        }

        with patch("asf_search.search", return_value=[mock_item1, mock_item2]):
            resp = await client.post("/api/search/granules", json={
                "wkt_polygon": "POLYGON((-122.5 37.7, -122.4 37.7, -122.4 37.8, -122.5 37.8, -122.5 37.7))",
                "dataset": "SENTINEL-1",
            })
            assert resp.status_code == 200, f"Status: {resp.status_code}"
            data = resp.json()
            assert data["total_count"] == 2, f"Count: {data['total_count']}"
            assert data["granules"][0]["footprint_geojson"]["coordinates"] is not None
            print("Scenario 1 PASSED: 2 valid granules returned with valid footprints.")

        # Scenario 2: Empty results
        print("\n--- Scenario 2: Empty results ---")
        with patch("asf_search.search", return_value=[]):
            resp = await client.post("/api/search/granules", json={
                "wkt_polygon": "POLYGON((-122.5 37.7, -122.4 37.7, -122.4 37.8, -122.5 37.8, -122.5 37.7))",
                "dataset": "SENTINEL-1",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_count"] == 0
            assert len(data["granules"]) == 0
            assert "0 granules found" in data["message"]
            print("Scenario 2 PASSED: 0 granules returned with friendly message, no error.")

        # Scenario 3: Polarization array normalization
        print("\n--- Scenario 3: Polarization array normalization ---")
        mock_item3 = MagicMock()
        mock_item3.properties = {
            "fileID": "SCENE_POL_ARRAY",
            "platform": "NISAR",
            "processingLevel": "GCOV",
            "polarization": ["VV", "VH"],
            "startTime": "2026-02-05T10:00:00Z",
        }
        mock_item3.geojson.return_value = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-122.5, 37.7], [-122.4, 37.7], [-122.4, 37.8], [-122.5, 37.8], [-122.5, 37.7]]],
            },
        }
        with patch("asf_search.search", return_value=[mock_item3]):
            resp = await client.post("/api/search/granules", json={
                "wkt_polygon": "POLYGON((-122.5 37.7, -122.4 37.7, -122.4 37.8, -122.5 37.8, -122.5 37.7))",
                "dataset": "NISAR",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["granules"][0]["polarization"] == "VV+VH"
            print("Scenario 3 PASSED: Polarization ['VV', 'VH'] normalized to 'VV+VH'.")

        # Scenario 4: Missing optional fields
        print("\n--- Scenario 4: Missing optional fields ---")
        mock_item4 = MagicMock()
        mock_item4.properties = {
            "fileID": "SCENE_MINIMAL",
            "platform": None,
            "processingLevel": None,
            "polarization": None,
            "startTime": None,
            "url": None,
            "browse": None,
        }
        mock_item4.geojson.return_value = {}
        with patch("asf_search.search", return_value=[mock_item4]):
            resp = await client.post("/api/search/granules", json={
                "wkt_polygon": "POLYGON((-122.5 37.7, -122.4 37.7, -122.4 37.8, -122.5 37.8, -122.5 37.7))",
                "dataset": "NISAR",
            })
            assert resp.status_code == 200
            data = resp.json()
            g = data["granules"][0]
            assert g["acquisition_time"] is None
            assert g["processing_level"] is None
            assert g["polarization"] is None
            assert g["footprint_geojson"] is None
            print("Scenario 4 PASSED: Missing optional fields handled safely as null.")

        # Scenario 5: Invalid/malformed footprint (coordinates: None or empty)
        print("\n--- Scenario 5: Invalid or malformed footprint ---")
        mock_item5 = MagicMock()
        mock_item5.properties = {
            "fileID": "SCENE_BAD_FOOTPRINT",
            "platform": "NISAR",
            "processingLevel": "GCOV",
            "startTime": "2026-02-01T00:00:00Z",
        }
        # This is the exact NASA ASF NISAR return that caused the crash!
        mock_item5.geojson.return_value = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": None,
            },
        }
        with patch("asf_search.search", return_value=[mock_item5]):
            resp = await client.post("/api/search/granules", json={
                "wkt_polygon": "POLYGON((-122.5 37.7, -122.4 37.7, -122.4 37.8, -122.5 37.8, -122.5 37.7))",
                "dataset": "NISAR",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["granules"][0]["footprint_geojson"] is None, f"Got: {data['granules'][0]['footprint_geojson']}"
            print("Scenario 5 PASSED: Malformed footprint (coordinates: None) sanitized to None.")

        # Scenario 6: Upstream ASF HTTP error
        print("\n--- Scenario 6: Upstream ASF HTTP error ---")
        with patch("asf_search.search", side_effect=Exception("500 Server Error: Internal Error from NASA CMR")):
            resp = await client.post("/api/search/granules", json={
                "wkt_polygon": "POLYGON((-122.5 37.7, -122.4 37.7, -122.4 37.8, -122.5 37.8, -122.5 37.7))",
                "dataset": "SENTINEL-1",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_count"] == 0
            assert "NASA ASF" in data["message"]
            print("Scenario 6 PASSED: Upstream error caught gracefully and returned as friendly message.")

        # Scenario 7: Network failure / timeout
        print("\n--- Scenario 7: Simulated network failure / timeout ---")
        with patch("asf_search.search", side_effect=TimeoutError("Connection to asf.alaska.edu timed out")):
            resp = await client.post("/api/search/granules", json={
                "wkt_polygon": "POLYGON((-122.5 37.7, -122.4 37.7, -122.4 37.8, -122.5 37.8, -122.5 37.7))",
                "dataset": "SENTINEL-1",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_count"] == 0
            assert "NASA ASF" in data["message"]
            print("Scenario 7 PASSED: Network timeout caught gracefully without crashing backend.")

        print("\nALL 7 CONTROLLED TEST SCENARIOS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(run_tests())
