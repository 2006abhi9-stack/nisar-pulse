"""
Comprehensive Unit & Integration Test Suite for Bhoonidhi NISAR S-Band Catalogue Integration.
Tests all 14 mandatory scenarios using mocked HTTP responses and verifies independence from NASA ASF.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import httpx
from bhoonidhi_client import (
    BhoonidhiClient,
    BhoonidhiProductQualification,
    BhoonidhiProviderStatus,
    qualify_and_normalize_product,
)
from main import app
from schemas import (
    BhoonidhiSearchRequest,
    BhoonidhiSearchResponse,
)

SAMPLE_WKT = "POLYGON((-122.5 37.7, -122.4 37.7, -122.4 37.8, -122.5 37.8, -122.5 37.7))"
SAMPLE_COORDS = [[[-122.5, 37.7], [-122.4, 37.7], [-122.4, 37.8], [-122.5, 37.8], [-122.5, 37.7]]]


def create_mock_stac_item(
    item_id: str,
    collection: str = "NISAR_SSAR_GCOV",
    coordinates: list | None = None,
    online: str | bool = "Y",
    has_data_asset: bool = True,
    product_type: str = "GCOV",
    title: str | None = None,
    polarization: str | list = "HH+HV",
    datetime_str: str = "2026-02-15T10:30:00Z",
) -> dict:
    if coordinates is None:
        geom = {"type": "Polygon", "coordinates": SAMPLE_COORDS}
    elif coordinates == "NONE":
        geom = {"type": "Polygon", "coordinates": None}
    elif coordinates == "EMPTY":
        geom = {"type": "Polygon", "coordinates": []}
    else:
        geom = {"type": "Polygon", "coordinates": coordinates}

    assets = {}
    if has_data_asset:
        assets["data"] = {
            "href": f"https://bhoonidhi-api.nrsc.gov.in/download/{item_id}.h5",
            "type": "application/x-hdf5",
            "roles": ["data"],
            "title": "NISAR S-band GCOV HDF5 Product",
        }
    assets["thumbnail"] = {
        "href": f"https://bhoonidhi-api.nrsc.gov.in/browse/{item_id}.png",
        "type": "image/png",
        "roles": ["thumbnail"],
    }

    return {
        "type": "Feature",
        "id": item_id,
        "collection": collection,
        "geometry": geom,
        "properties": {
            "title": title or item_id,
            "platform": "NISAR",
            "sensor": "SSAR (S-band)",
            "product_type": product_type,
            "processing:level": "L2",
            "datetime": datetime_str,
            "polarization": polarization,
            "sat:orbit_state": "descending",
            "sar:looks_range_direction": "right",
            "Online": online,
        },
        "assets": assets,
        "links": [],
    }


async def run_all_tests() -> int:
    total_tests = 14
    passed_tests = 0
    print("=" * 70)
    print("TASK 10: BHOONIDHI NISAR S-BAND CATALOGUE INTEGRATION TEST SUITE")
    print("=" * 70)

    # --------------------------------------------------------------------------
    # Test 1: Missing credentials produce NOT_CONFIGURED
    # --------------------------------------------------------------------------
    print("\n[Test 1] Missing credentials produce NOT_CONFIGURED status...")
    with patch.dict(os.environ, {"BHOONIDHI_USER_ID": "", "BHOONIDHI_PASSWORD": ""}, clear=False):
        client = BhoonidhiClient(user_id=None, password=None)
        req = BhoonidhiSearchRequest(wkt_polygon=SAMPLE_WKT, max_results=10)
        res = await client.search_products(req)
        assert res.provider_status == BhoonidhiProviderStatus.NOT_CONFIGURED, f"Expected NOT_CONFIGURED, got {res.provider_status}"
        assert res.total_count == 0, "Expected 0 results"
        assert len(res.products) == 0, "Expected empty products list"
        assert "NOT_CONFIGURED" in (res.message or ""), "Expected clear message"
        print("  -> PASSED: NOT_CONFIGURED returned, no fabricated products or requests.")
        passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 2: Authentication returns a token that is cached
    # --------------------------------------------------------------------------
    print("\n[Test 2] Authentication returns a token that is cached...")
    mock_auth_resp = MagicMock()
    mock_auth_resp.status_code = 200
    mock_auth_resp.json.return_value = {
        "access_token": "token_abc_123_valid",
        "refresh_token": "refresh_xyz_789",
        "expires_in": 3600,
    }

    mock_http = AsyncMock()
    mock_http.post.return_value = mock_auth_resp

    client = BhoonidhiClient(user_id="test_user", password="test_password", http_client=mock_http)
    token1 = await client.get_access_token()
    assert token1 == "token_abc_123_valid", f"Expected token_abc_123_valid, got {token1}"
    assert mock_http.post.call_count == 1, "Expected exactly 1 auth request"

    # Second call should use cache without new HTTP call
    token2 = await client.get_access_token()
    assert token2 == "token_abc_123_valid", "Expected cached token"
    assert mock_http.post.call_count == 1, "Expected HTTP call count to remain 1 (cached)"
    print("  -> PASSED: Token acquired and cached across subsequent requests.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 3: Expired access token can be refreshed
    # --------------------------------------------------------------------------
    print("\n[Test 3] Expired access token can be refreshed...")
    mock_refresh_resp = MagicMock()
    mock_refresh_resp.status_code = 200
    mock_refresh_resp.json.return_value = {
        "access_token": "token_refreshed_999",
        "refresh_token": "refresh_new_888",
        "expires_in": 3600,
    }

    mock_http_refresh = AsyncMock()
    mock_http_refresh.post.return_value = mock_refresh_resp

    client = BhoonidhiClient(user_id="test_user", password="test_password", http_client=mock_http_refresh)
    # Simulate expired token
    client._access_token = "old_expired_token"
    client._refresh_token = "refresh_xyz_789"
    client._token_expires_at = time.time() - 100  # expired

    refreshed_token = await client.get_access_token()
    assert refreshed_token == "token_refreshed_999", f"Expected token_refreshed_999, got {refreshed_token}"
    assert mock_http_refresh.post.call_count == 1
    # Check that grant_type refresh_token was used
    call_args = mock_http_refresh.post.call_args
    sent_payload = call_args[1].get("json") or {}
    assert sent_payload.get("grant_type") == "refresh_token"
    assert sent_payload.get("refresh_token") == "refresh_xyz_789"
    print("  -> PASSED: Expired token refreshed via refresh_token flow.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 4: AOI GeoJSON is sent correctly
    # --------------------------------------------------------------------------
    print("\n[Test 4] AOI GeoJSON is sent correctly...")
    captured_bodies = []

    async def mock_post(url, json=None, headers=None):
        if "/auth/token" in url:
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"access_token": "tok", "expires_in": 3600}
            return m
        if "/data/search" in url:
            captured_bodies.append(json)
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"type": "FeatureCollection", "features": [], "links": []}
            return m
        raise ValueError(f"Unexpected url: {url}")

    mock_client = AsyncMock()
    mock_client.post.side_effect = mock_post

    client = BhoonidhiClient(user_id="test_user", password="test_password", http_client=mock_client)
    req = BhoonidhiSearchRequest(wkt_polygon=SAMPLE_WKT, max_results=10)
    await client.search_products(req)

    assert len(captured_bodies) == 1, "Expected 1 search request"
    body = captured_bodies[0]
    assert "intersects" in body, "Expected intersects geometry in search body"
    intersects = body["intersects"]
    assert intersects.get("type") == "Polygon", f"Expected Polygon, got {intersects.get('type')}"
    coords = intersects.get("coordinates")
    assert isinstance(coords, list) and len(coords[0]) == 5, "Expected closed 5-vertex polygon ring"
    assert coords[0][0] == [-122.5, 37.7], f"Expected start coordinate [-122.5, 37.7], got {coords[0][0]}"
    print("  -> PASSED: WKT polygon converted to exact GeoJSON Polygon coordinates.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 5: Search is restricted to NISAR_SSAR_GCOV
    # --------------------------------------------------------------------------
    print("\n[Test 5] Search is restricted to NISAR_SSAR_GCOV collection...")
    assert body.get("collections") == ["NISAR_SSAR_GCOV"], f"Expected ['NISAR_SSAR_GCOV'], got {body.get('collections')}"
    print("  -> PASSED: STAC search explicitly specifies collections=['NISAR_SSAR_GCOV'].")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 6: Online = Y filtering is applied
    # --------------------------------------------------------------------------
    print("\n[Test 6] Online = Y filtering is applied via CQL2-JSON...")
    assert body.get("filter-lang") == "cql2-json", f"Expected cql2-json, got {body.get('filter-lang')}"
    expected_filter = {"op": "=", "args": [{"property": "Online"}, "Y"]}
    assert body.get("filter") == expected_filter, f"Expected {expected_filter}, got {body.get('filter')}"
    print("  -> PASSED: CQL2-JSON filter specifies Online = Y.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 7: Pagination is handled correctly
    # --------------------------------------------------------------------------
    print("\n[Test 7] Pagination is handled correctly...")
    item_p1 = create_mock_stac_item("NISAR_SSAR_GCOV_PAGE1_ITEM")
    item_p2 = create_mock_stac_item("NISAR_SSAR_GCOV_PAGE2_ITEM")

    async def mock_pagination_post(url, json=None, headers=None):
        if "/auth/token" in url:
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"access_token": "tok", "expires_in": 3600}
            return m
        if "/data/search" in url:
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {
                "type": "FeatureCollection",
                "features": [item_p1],
                "links": [{"rel": "next", "href": "https://bhoonidhi-api.nrsc.gov.in/data/search?page=2"}],
            }
            return m
        raise ValueError(f"Unexpected URL: {url}")

    async def mock_pagination_get(url, headers=None):
        if "page=2" in url:
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {
                "type": "FeatureCollection",
                "features": [item_p2],
                "links": [],
            }
            return m
        raise ValueError(f"Unexpected GET URL: {url}")

    mock_pag_client = AsyncMock()
    mock_pag_client.post.side_effect = mock_pagination_post
    mock_pag_client.get.side_effect = mock_pagination_get

    client = BhoonidhiClient(user_id="test_user", password="test_password", http_client=mock_pag_client)
    res_pag = await client.search_products(BhoonidhiSearchRequest(wkt_polygon=SAMPLE_WKT, max_results=10))

    assert res_pag.total_count == 2, f"Expected 2 products, got {res_pag.total_count}"
    assert res_pag.products[0].item_id == "NISAR_SSAR_GCOV_PAGE1_ITEM"
    assert res_pag.products[1].item_id == "NISAR_SSAR_GCOV_PAGE2_ITEM"
    assert res_pag.has_more is False
    print("  -> PASSED: Next link followed; retrieved items across multiple pages.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 8: Duplicate item IDs are removed
    # --------------------------------------------------------------------------
    print("\n[Test 8] Duplicate item IDs are removed...")
    item_dup = create_mock_stac_item("NISAR_SSAR_GCOV_DUPLICATE_ID")
    item_unique = create_mock_stac_item("NISAR_SSAR_GCOV_UNIQUE_ID")

    async def mock_dup_post(url, json=None, headers=None):
        if "/auth/token" in url:
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"access_token": "tok", "expires_in": 3600}
            return m
        m = MagicMock()
        m.status_code = 200
        # Return duplicate in same batch
        m.json.return_value = {
            "type": "FeatureCollection",
            "features": [item_dup, item_dup, item_unique],
            "links": [],
        }
        return m

    mock_dup_client = AsyncMock()
    mock_dup_client.post.side_effect = mock_dup_post

    client = BhoonidhiClient(user_id="test_user", password="test_password", http_client=mock_dup_client)
    res_dup = await client.search_products(BhoonidhiSearchRequest(wkt_polygon=SAMPLE_WKT, max_results=10))
    assert res_dup.total_count == 2, f"Expected 2 unique products, got {res_dup.total_count}"
    ids = [p.item_id for p in res_dup.products]
    assert ids == ["NISAR_SSAR_GCOV_DUPLICATE_ID", "NISAR_SSAR_GCOV_UNIQUE_ID"]
    print("  -> PASSED: Duplicate STAC items successfully deduplicated.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 9: Ancillary products are not classified as radar candidates
    # --------------------------------------------------------------------------
    print("\n[Test 9] Ancillary products are not classified as radar candidates...")
    item_ecmwf = create_mock_stac_item("ECMWF_SMST_SOIL_ANCILLARY_001", title="ECMWF SOIL MOISTURE AUX")
    item_weather = create_mock_stac_item("WEATHER_AUX_002", title="WEATHER AUXILIARY")
    item_slc = create_mock_stac_item("NISAR_SSAR_SLC_003", product_type="SLC")
    item_other_coll = create_mock_stac_item("OTHER_COLL_004", collection="RESOURCESAT_LISS3")
    item_valid_radar = create_mock_stac_item("NISAR_SSAR_GCOV_VALID_RADAR")

    q_ecmwf = qualify_and_normalize_product(item_ecmwf)
    q_weather = qualify_and_normalize_product(item_weather)
    q_slc = qualify_and_normalize_product(item_slc)
    q_other = qualify_and_normalize_product(item_other_coll)
    q_valid = qualify_and_normalize_product(item_valid_radar)

    assert q_ecmwf.qualification == BhoonidhiProductQualification.UNSUPPORTED_PRODUCT
    assert q_weather.qualification == BhoonidhiProductQualification.UNSUPPORTED_PRODUCT
    assert q_slc.qualification == BhoonidhiProductQualification.UNSUPPORTED_PRODUCT
    assert q_other.qualification == BhoonidhiProductQualification.UNSUPPORTED_PRODUCT
    assert q_valid.qualification == BhoonidhiProductQualification.DOWNLOADABLE_CANDIDATE
    print("  -> PASSED: Ancillary/weather/SLC/wrong-collection items qualified as UNSUPPORTED_PRODUCT.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 10: Invalid footprints are rejected
    # --------------------------------------------------------------------------
    print("\n[Test 10] Invalid footprints are rejected...")
    item_null_coords = create_mock_stac_item("BAD_GEOM_NULL", coordinates="NONE")
    item_empty_coords = create_mock_stac_item("BAD_GEOM_EMPTY", coordinates="EMPTY")

    q_null = qualify_and_normalize_product(item_null_coords)
    q_empty = qualify_and_normalize_product(item_empty_coords)

    assert q_null.qualification == BhoonidhiProductQualification.INVALID_METADATA
    assert q_null.footprint_geojson is None
    assert "footprint" in q_null.qualification_reason.lower()

    assert q_empty.qualification == BhoonidhiProductQualification.INVALID_METADATA
    assert q_empty.footprint_geojson is None
    print("  -> PASSED: Missing/null coordinates properly qualified as INVALID_METADATA.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 11: Missing optional metadata does not crash the response
    # --------------------------------------------------------------------------
    print("\n[Test 11] Missing optional metadata does not crash the response...")
    minimal_item = {
        "type": "Feature",
        "id": "MINIMAL_ITEM_001",
        "collection": "NISAR_SSAR_GCOV",
        "geometry": {"type": "Polygon", "coordinates": SAMPLE_COORDS},
        "properties": {},  # No datetime, polarization, sat:orbit_state, etc.
        "assets": {},
    }
    q_min = qualify_and_normalize_product(minimal_item)
    assert q_min.item_id == "MINIMAL_ITEM_001"
    assert q_min.acquisition_time is None
    assert q_min.polarization is None
    assert q_min.orbit_direction is None
    assert q_min.qualification == BhoonidhiProductQualification.CATALOGUE_ONLY
    print("  -> PASSED: Missing metadata fields safely default to None without exceptions.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 12: HTTP errors and timeouts are handled safely
    # --------------------------------------------------------------------------
    print("\n[Test 12] HTTP errors and timeouts are handled safely...")

    async def mock_err_post(url, json=None, headers=None):
        if "/auth/token" in url:
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"access_token": "tok", "expires_in": 3600}
            return m
        # Simulate 500 error
        m = MagicMock()
        m.status_code = 500
        return m

    mock_err_client = AsyncMock()
    mock_err_client.post.side_effect = mock_err_post

    client = BhoonidhiClient(user_id="test_user", password="test_password", http_client=mock_err_client)
    res_err = await client.search_products(BhoonidhiSearchRequest(wkt_polygon=SAMPLE_WKT))
    assert res_err.provider_status == BhoonidhiProviderStatus.SERVICE_UNAVAILABLE
    assert res_err.total_count == 0

    # Simulate timeout
    mock_timeout_client = AsyncMock()
    mock_timeout_client.post.side_effect = httpx.TimeoutException("Search timed out")
    client_timeout = BhoonidhiClient(user_id="test_user", password="test_password", http_client=mock_timeout_client)
    res_timeout = await client_timeout.search_products(BhoonidhiSearchRequest(wkt_polygon=SAMPLE_WKT))
    assert res_timeout.provider_status == BhoonidhiProviderStatus.SERVICE_UNAVAILABLE
    assert "timed out" in (res_timeout.message or "").lower()
    print("  -> PASSED: HTTP 500 and timeout return clean SERVICE_UNAVAILABLE response.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 13: No credentials or tokens appear in API responses or logs
    # --------------------------------------------------------------------------
    print("\n[Test 13] No credentials or tokens appear in API responses or logs...")
    secret_pass = "UltraSecretPassword987!"
    secret_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sensitive_payload.signature"

    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    logger = logging.getLogger("nisar_pulse.bhoonidhi")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    async def mock_secret_post(url, json=None, headers=None):
        if "/auth/token" in url:
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"access_token": secret_token, "expires_in": 3600}
            return m
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = {
            "type": "FeatureCollection",
            "features": [create_mock_stac_item("NISAR_SAFE_ITEM")],
            "links": [],
        }
        return m

    mock_sec_client = AsyncMock()
    mock_sec_client.post.side_effect = mock_secret_post

    client = BhoonidhiClient(user_id="secret_user", password=secret_pass, http_client=mock_sec_client)
    res_sec = await client.search_products(BhoonidhiSearchRequest(wkt_polygon=SAMPLE_WKT))

    res_json_str = res_sec.model_dump_json()
    assert secret_pass not in res_json_str, "CRITICAL: Password leaked in response JSON!"
    assert secret_token not in res_json_str, "CRITICAL: Access token leaked in response JSON!"

    logs_text = log_stream.getvalue()
    assert secret_pass not in logs_text, "CRITICAL: Password leaked in logs!"
    assert secret_token not in logs_text, "CRITICAL: Access token leaked in logs!"
    logger.removeHandler(handler)
    print("  -> PASSED: Neither credentials nor tokens leaked in API responses or logs.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 14: Existing NASA ASF search behavior remains unaffected
    # --------------------------------------------------------------------------
    print("\n[Test 14] Existing NASA ASF search behavior remains unaffected...")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as asgi_client:
        mock_asf_item = MagicMock()
        mock_asf_item.properties = {
            "fileID": "S1A_IW_GRDH_TEST_SCENE",
            "platform": "Sentinel-1A",
            "processingLevel": "GRD",
            "polarization": "VV+VH",
            "startTime": "2026-02-10T12:00:00Z",
            "url": "https://asf.alaska.edu/test.zip",
        }
        mock_asf_item.geojson.return_value = {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": SAMPLE_COORDS},
        }

        with patch("asf_search.search", return_value=[mock_asf_item]):
            resp = await asgi_client.post(
                "/api/search/granules",
                json={"wkt_polygon": SAMPLE_WKT, "dataset": "SENTINEL-1"},
            )
            assert resp.status_code == 200, f"Expected 200 from ASF search, got {resp.status_code}"
            data = resp.json()
            assert data["total_count"] == 1
            assert data["granules"][0]["granule_name"] == "S1A_IW_GRDH_TEST_SCENE"
            assert data["granules"][0]["platform"] == "Sentinel-1A"

        # Also verify new Bhoonidhi endpoint is reachable via FastAPI router
        bhoonidhi_resp = await asgi_client.post(
            "/api/search/bhoonidhi",
            json={"wkt_polygon": SAMPLE_WKT, "collection": "NISAR_SSAR_GCOV"},
        )
        assert bhoonidhi_resp.status_code == 200, f"Expected 200 from Bhoonidhi endpoint, got {bhoonidhi_resp.status_code}"
        b_data = bhoonidhi_resp.json()
        assert "provider_status" in b_data
        assert b_data["collection_searched"] == "NISAR_SSAR_GCOV"

    print("  -> PASSED: NASA ASF search /api/search/granules remains completely functional.")
    passed_tests += 1

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed_tests}/{total_tests} TESTS PASSED SUCCESSFULLY (Exit Code 0)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)
