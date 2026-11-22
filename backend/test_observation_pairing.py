"""
Comprehensive Unit & Integration Test Suite for Observation Pairing & Compatibility Engine.
Tests all 17 mandatory scenarios for hard compatibility rules, soft ranking preferences,
and integration with NASA ASF and ISRO Bhoonidhi.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import httpx
from shapely import wkt as shapely_wkt

from main import app
from observation_pairing import (
    CommonObservation,
    ObservationPairingService,
    compute_pair_ranking,
    evaluate_pair_compatibility,
    normalize_asf_granule,
    normalize_bhoonidhi_product,
)
from schemas import (
    ObservationPairSearchRequest,
    ObservationPairSearchResponse,
)

SAMPLE_WKT = "POLYGON((-122.5 37.7, -122.4 37.7, -122.4 37.8, -122.5 37.8, -122.5 37.7))"
AOI_GEOM = shapely_wkt.loads(SAMPLE_WKT)
FULL_COORDS = [[[-122.55, 37.65], [-122.35, 37.65], [-122.35, 37.85], [-122.55, 37.85], [-122.55, 37.65]]]
PARTIAL_COORDS = [[[-122.5, 37.7], [-122.45, 37.7], [-122.45, 37.75], [-122.5, 37.75], [-122.5, 37.7]]]
DISJOINT_COORDS = [[[10.0, 10.0], [11.0, 10.0], [11.0, 11.0], [10.0, 11.0], [10.0, 10.0]]]


def make_obs(
    obs_id: str,
    provider: str = "ISRO_BHOONIDHI",
    platform: str = "NISAR",
    instrument: str = "SSAR",
    frequency_band: str = "S-band",
    product_type: str = "GCOV",
    polarization: str = "HH",
    acq_time: datetime | str | None = "2026-02-01T00:00:00Z",
    orbit_direction: str | None = "DESCENDING",
    footprint: list | None = None,
    is_online: bool = True,
) -> CommonObservation:
    dt = None
    if isinstance(acq_time, str):
        dt = datetime.fromisoformat(acq_time.replace("Z", "+00:00"))
    elif isinstance(acq_time, datetime):
        dt = acq_time

    coords = footprint if footprint is not None else FULL_COORDS
    geom = {"type": "Polygon", "coordinates": coords} if coords != "NONE" else None

    return CommonObservation(
        provider=provider,
        original_id=obs_id,
        collection_id=f"{platform}_{instrument}_{product_type}",
        platform=platform,
        instrument=instrument,
        frequency_band=frequency_band,
        product_type=product_type,
        processing_level="L2" if product_type == "GCOV" else "L1",
        polarization=polarization,
        acquisition_time=dt,
        orbit_direction=orbit_direction,
        footprint_geojson=geom,
        is_online=is_online,
        download_url=f"https://data.provider.org/download/{obs_id}",
        qualification="COMPATIBLE_CANDIDATE" if geom else "INVALID_METADATA",
    )


async def run_all_tests() -> int:
    total_tests = 17
    passed_tests = 0
    print("=" * 75)
    print("TASK 11: OBSERVATION PAIRING & COMPATIBILITY ENGINE TEST SUITE")
    print("=" * 75)

    # --------------------------------------------------------------------------
    # Test 1: Compatible NISAR S-band GCOV observations
    # --------------------------------------------------------------------------
    print("\n[Test 1] Compatible NISAR S-band GCOV observations...")
    b_nisar_s = make_obs("NISAR_S_GCOV_BEFORE", acq_time="2026-02-01T00:00:00Z", instrument="SSAR", frequency_band="S-band")
    a_nisar_s = make_obs("NISAR_S_GCOV_AFTER", acq_time="2026-02-15T00:00:00Z", instrument="SSAR", frequency_band="S-band")
    is_compat, status, comp_reasons, rej_reasons, warnings = evaluate_pair_compatibility(b_nisar_s, a_nisar_s, AOI_GEOM)
    assert is_compat is True, f"Expected compatible, got rej: {rej_reasons}"
    assert status == "COMPATIBLE_CANDIDATE"
    assert any("S-band" in r for r in comp_reasons)
    print("  -> PASSED: NISAR S-band GCOV pair accepted as COMPATIBLE_CANDIDATE.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 2: Compatible NISAR L-band observations
    # --------------------------------------------------------------------------
    print("\n[Test 2] Compatible NISAR L-band observations...")
    b_nisar_l = make_obs("NISAR_L_GCOV_BEFORE", provider="NASA_ASF", instrument="LSAR", frequency_band="L-band", acq_time="2026-02-01T00:00:00Z")
    a_nisar_l = make_obs("NISAR_L_GCOV_AFTER", provider="NASA_ASF", instrument="LSAR", frequency_band="L-band", acq_time="2026-02-15T00:00:00Z")
    is_compat, status, comp_reasons, rej_reasons, warnings = evaluate_pair_compatibility(b_nisar_l, a_nisar_l, AOI_GEOM)
    assert is_compat is True, f"Expected compatible, got rej: {rej_reasons}"
    assert status == "COMPATIBLE_CANDIDATE"
    assert any("L-band" in r for r in comp_reasons)
    print("  -> PASSED: NISAR L-band GCOV pair accepted as COMPATIBLE_CANDIDATE.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 3: Compatible Sentinel-1 observations & Sentinel-1B Mission Lifetime
    # --------------------------------------------------------------------------
    print("\n[Test 3] Compatible Sentinel-1 observations & Sentinel-1B Mission Lifetime...")
    b_s1 = make_obs("S1A_GRD_BEFORE", provider="NASA_ASF", platform="Sentinel-1A", instrument="C-SAR", frequency_band="C-band", product_type="GRD", polarization="VV+VH", acq_time="2026-02-01T00:00:00Z")
    a_s1 = make_obs("S1A_GRD_AFTER", provider="NASA_ASF", platform="Sentinel-1A", instrument="C-SAR", frequency_band="C-band", product_type="GRD", polarization="VV+VH", acq_time="2026-02-13T00:00:00Z")
    is_compat, status, comp_reasons, rej_reasons, warnings = evaluate_pair_compatibility(b_s1, a_s1, AOI_GEOM)
    assert is_compat is True, f"Expected compatible, got rej: {rej_reasons}"
    assert status == "COMPATIBLE_CANDIDATE"
    assert any("C-band" in r for r in comp_reasons)
    
    # Regression test: Impossible Sentinel-1B observation post Dec 23, 2021 must be rejected
    a_s1b_impossible = make_obs("S1B_GRD_AFTER_IMPOSSIBLE", provider="NASA_ASF", platform="Sentinel-1B", instrument="C-SAR", frequency_band="C-band", product_type="GRD", polarization="VV+VH", acq_time="2026-02-13T00:00:00Z")
    is_compat_b, status_b, _, rej_b, _ = evaluate_pair_compatibility(b_s1, a_s1b_impossible, AOI_GEOM)
    assert is_compat_b is False, "Sentinel-1B after Dec 23, 2021 must be strictly rejected"
    assert any("Sentinel-1B mission ended on December 23, 2021" in r for r in rej_b)
    print("  -> PASSED: Sentinel-1 C-band GRD pair accepted as COMPATIBLE_CANDIDATE, post-2021 Sentinel-1B strictly rejected.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 4: NISAR S-band and L-band mismatch rejection
    # --------------------------------------------------------------------------
    print("\n[Test 4] NISAR S-band and L-band mismatch rejection...")
    is_compat, status, comp_reasons, rej_reasons, warnings = evaluate_pair_compatibility(b_nisar_s, a_nisar_l, AOI_GEOM)
    assert is_compat is False, "Expected cross-frequency S-band/L-band pair to be rejected"
    assert status == "INCOMPATIBLE"
    assert any("Radar frequency mismatch" in r for r in rej_reasons), f"Expected frequency mismatch, got: {rej_reasons}"
    assert any("S-band" in r and "L-band" in r for r in rej_reasons)
    print("  -> PASSED: Cross-frequency NISAR S-band vs L-band pair strictly rejected.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 5: Sentinel-1 and NISAR mismatch rejection
    # --------------------------------------------------------------------------
    print("\n[Test 5] Sentinel-1 and NISAR mismatch rejection...")
    is_compat, status, comp_reasons, rej_reasons, warnings = evaluate_pair_compatibility(b_s1, a_nisar_s, AOI_GEOM)
    assert is_compat is False, "Expected Sentinel-1 and NISAR to be rejected"
    assert status == "INCOMPATIBLE"
    assert any("frequency mismatch" in r.lower() or "instrument mismatch" in r.lower() for r in rej_reasons)
    print("  -> PASSED: Cross-sensor Sentinel-1 (C-band) vs NISAR (S-band) strictly rejected.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 6: Polarization mismatch
    # --------------------------------------------------------------------------
    print("\n[Test 6] Polarization mismatch rejection...")
    b_hh = make_obs("NISAR_HH", polarization="HH", acq_time="2026-02-01T00:00:00Z")
    a_vv = make_obs("NISAR_VV", polarization="VV", acq_time="2026-02-15T00:00:00Z")
    is_compat, status, comp_reasons, rej_reasons, warnings = evaluate_pair_compatibility(b_hh, a_vv, AOI_GEOM)
    assert is_compat is False, "Expected HH vs VV with no common channel to be rejected"
    assert status == "INCOMPATIBLE"
    assert any("Polarization channel mismatch" in r for r in rej_reasons)
    print("  -> PASSED: Incompatible polarizations (HH vs VV) rejected.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 7: Product-family mismatch
    # --------------------------------------------------------------------------
    print("\n[Test 7] Product-family mismatch rejection...")
    b_gcov = make_obs("NISAR_GCOV", product_type="GCOV", acq_time="2026-02-01T00:00:00Z")
    a_gunw = make_obs("NISAR_GUNW", product_type="GUNW", acq_time="2026-02-15T00:00:00Z")
    is_compat, status, comp_reasons, rej_reasons, warnings = evaluate_pair_compatibility(b_gcov, a_gunw, AOI_GEOM)
    assert is_compat is False, "Expected GCOV vs GUNW family mismatch to be rejected"
    assert status in ("INCOMPATIBLE", "UNSUPPORTED_FOR_CHANGE_DETECTION")
    assert any("Product family mismatch" in r or "Unsupported product format" in r for r in rej_reasons)
    print("  -> PASSED: Incompatible product families (GCOV vs GUNW) rejected.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 8: Ancillary ECMWF records excluded from SAR pairing
    # --------------------------------------------------------------------------
    print("\n[Test 8] Ancillary ECMWF records excluded from SAR pairing...")
    b_ecmwf = make_obs("ECMWF_SMST_SOIL_ANCILLARY_001", acq_time="2026-02-01T00:00:00Z")
    a_valid = make_obs("NISAR_S_VALID", acq_time="2026-02-15T00:00:00Z")
    is_compat, status, comp_reasons, rej_reasons, warnings = evaluate_pair_compatibility(b_ecmwf, a_valid, AOI_GEOM)
    assert is_compat is False, "Expected ECMWF ancillary record to be rejected"
    assert status == "UNSUPPORTED_PRODUCT"
    assert any("Ancillary product exclusion" in r for r in rej_reasons)
    print("  -> PASSED: ECMWF soil-moisture ancillary record excluded from SAR pairing.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 9: Invalid or missing acquisition timestamps
    # --------------------------------------------------------------------------
    print("\n[Test 9] Invalid or missing acquisition timestamps...")
    b_no_time = make_obs("NISAR_NO_TIME", acq_time=None)
    a_valid = make_obs("NISAR_VALID", acq_time="2026-02-15T00:00:00Z")
    is_compat, status, comp_reasons, rej_reasons, warnings = evaluate_pair_compatibility(b_no_time, a_valid, AOI_GEOM)
    assert is_compat is False
    assert status == "INSUFFICIENT_METADATA"
    assert any("Missing acquisition timestamp" in r for r in rej_reasons)
    print("  -> PASSED: Missing timestamp produces INSUFFICIENT_METADATA.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 10: Insufficient AOI footprint coverage
    # --------------------------------------------------------------------------
    print("\n[Test 10] Insufficient AOI footprint coverage rejection...")
    b_disjoint = make_obs("NISAR_DISJOINT", footprint=DISJOINT_COORDS, acq_time="2026-02-01T00:00:00Z")
    a_valid = make_obs("NISAR_VALID", acq_time="2026-02-15T00:00:00Z")
    is_compat, status, comp_reasons, rej_reasons, warnings = evaluate_pair_compatibility(b_disjoint, a_valid, AOI_GEOM)
    assert is_compat is False
    assert status == "INCOMPATIBLE"
    assert any("Insufficient AOI spatial coverage" in r for r in rej_reasons)
    print("  -> PASSED: Disjoint footprint (<5% overlap) strictly rejected.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 11: Unsupported product formats (e.g. Level-1 SLC)
    # --------------------------------------------------------------------------
    print("\n[Test 11] Unsupported product formats (SLC) rejection...")
    b_slc = make_obs("S1A_SLC_BEFORE", product_type="SLC", acq_time="2026-02-01T00:00:00Z")
    a_grd = make_obs("S1A_GRD_AFTER", product_type="GRD", acq_time="2026-02-15T00:00:00Z")
    is_compat, status, comp_reasons, rej_reasons, warnings = evaluate_pair_compatibility(b_slc, a_grd, AOI_GEOM)
    assert is_compat is False
    assert status in ("UNSUPPORTED_PRODUCT", "UNSUPPORTED_FOR_CHANGE_DETECTION")
    assert any("Level-1" in r or "SLC" in r for r in rej_reasons)
    print("  -> PASSED: Level-1 SLC rejected as UNSUPPORTED_FOR_CHANGE_DETECTION.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 12: Missing optional metadata produces a warning rather than invented values
    # --------------------------------------------------------------------------
    print("\n[Test 12] Missing optional metadata produces warnings rather than invented values...")
    b_no_orbit = make_obs("NISAR_NO_ORBIT", orbit_direction=None, acq_time="2026-02-01T00:00:00Z")
    a_valid = make_obs("NISAR_VALID", orbit_direction="ASCENDING", acq_time="2026-02-15T00:00:00Z")
    is_compat, status, comp_reasons, rej_reasons, warnings = evaluate_pair_compatibility(b_no_orbit, a_valid, AOI_GEOM)
    assert is_compat is True, "Missing optional orbit direction should not reject pair"
    assert status == "COMPATIBLE_CANDIDATE"
    assert any("Orbit direction unspecified" in w for w in warnings)
    assert b_no_orbit.orbit_direction is None, "Missing field must remain None, not fabricated"
    print("  -> PASSED: Missing optional orbit metadata logged as warning, not fabricated.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 13: Correct chronological BEFORE/AFTER ordering
    # --------------------------------------------------------------------------
    print("\n[Test 13] Correct chronological BEFORE/AFTER ordering...")
    b_later = make_obs("NISAR_LATER", acq_time="2026-02-20T00:00:00Z")
    a_earlier = make_obs("NISAR_EARLIER", acq_time="2026-02-01T00:00:00Z")
    is_compat, status, comp_reasons, rej_reasons, warnings = evaluate_pair_compatibility(b_later, a_earlier, AOI_GEOM)
    assert is_compat is False, "Expected inverted chronological order to be rejected"
    assert status == "INCOMPATIBLE"
    assert any("Chronological order violation" in r for r in rej_reasons)
    print("  -> PASSED: Inverted temporal sequence strictly rejected.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 14: Ranking prefers the best compatible pair
    # --------------------------------------------------------------------------
    print("\n[Test 14] Ranking prefers the best compatible pair...")
    b_best = make_obs("NISAR_BEST_BEFORE", acq_time="2026-02-01T00:00:00Z", orbit_direction="DESCENDING", polarization="HH", footprint=FULL_COORDS)
    a_best = make_obs("NISAR_BEST_AFTER", acq_time="2026-02-15T00:00:00Z", orbit_direction="DESCENDING", polarization="HH", footprint=FULL_COORDS)

    b_suboptimal = make_obs("NISAR_SUB_BEFORE", acq_time="2026-01-01T00:00:00Z", orbit_direction="ASCENDING", polarization="HH", footprint=PARTIAL_COORDS)
    a_suboptimal = make_obs("NISAR_SUB_AFTER", acq_time="2026-03-30T00:00:00Z", orbit_direction="DESCENDING", polarization="HH", footprint=PARTIAL_COORDS)

    score_best, expl_best, cov_best, delta_best = compute_pair_ranking(b_best, a_best, AOI_GEOM)
    score_sub, expl_sub, cov_sub, delta_sub = compute_pair_ranking(b_suboptimal, a_suboptimal, AOI_GEOM)

    assert score_best > score_sub, f"Expected best pair score ({score_best}) > sub score ({score_sub})"
    assert cov_best == 100.0
    assert "Matching DESCENDING pass" in expl_best
    print(f"  -> PASSED: Ranking correctly scored optimal pair ({score_best}) over suboptimal pair ({score_sub}).")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 15: No compatible observations returns an honest empty result
    # --------------------------------------------------------------------------
    print("\n[Test 15] No compatible observations returns honest NO_COMPATIBLE_PAIR...")
    with patch("asf_search.search", return_value=[]):
        with patch("bhoonidhi_client.get_bhoonidhi_client") as mock_b_getter:
            mock_b = MagicMock()
            mock_b.is_configured.return_value = False
            mock_b_getter.return_value = mock_b

            req = ObservationPairSearchRequest(wkt_polygon=SAMPLE_WKT, max_candidates=10)
            res = await ObservationPairingService.find_pairs(req)
            assert res.status == "NO_COMPATIBLE_PAIR"
            assert res.total_compatible_pairs == 0
            assert res.recommended_pair is None
            assert "0 compatible" in res.message or "No satellite observations" in res.message
            print("  -> PASSED: Empty candidate set returned honest NO_COMPATIBLE_PAIR status.")
            passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 16: Provider failure does not silently fabricate alternatives
    # --------------------------------------------------------------------------
    print("\n[Test 16] Provider failure does not silently fabricate alternatives...")
    with patch("asf_search.search", side_effect=Exception("Connection to ASF failed")):
        with patch("bhoonidhi_client.get_bhoonidhi_client") as mock_b_getter:
            mock_b = MagicMock()
            mock_b.is_configured.return_value = False
            mock_b_getter.return_value = mock_b

            req = ObservationPairSearchRequest(wkt_polygon=SAMPLE_WKT, max_candidates=10)
            res = await ObservationPairingService.find_pairs(req)
            assert res.status == "NO_COMPATIBLE_PAIR"
            assert res.total_observations_found == 0
            assert res.recommended_pair is None
            assert len(res.alternative_pairs) == 0
            assert any("ASF" in w for w in res.warnings)
            print("  -> PASSED: Provider exception cleanly reported via warnings without fabricating pairs.")
            passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 17: Existing ASF and Bhoonidhi search endpoints remain unaffected
    # --------------------------------------------------------------------------
    print("\n[Test 17] Existing ASF and Bhoonidhi search endpoints remain unaffected...")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Check ASF endpoint
        mock_asf_item = MagicMock()
        mock_asf_item.properties = {
            "fileID": "S1A_TEST_PAIR_ENDPOINT",
            "platform": "Sentinel-1A",
            "processingLevel": "GRD",
            "polarization": "VV",
            "startTime": "2026-02-01T10:00:00Z",
            "url": "https://asf.alaska.edu/test.zip",
        }
        mock_asf_item.geojson.return_value = {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": FULL_COORDS},
        }

        with patch("asf_search.search", return_value=[mock_asf_item]):
            asf_resp = await client.post(
                "/api/search/granules",
                json={"wkt_polygon": SAMPLE_WKT, "dataset": "SENTINEL-1"},
            )
            assert asf_resp.status_code == 200
            asf_data = asf_resp.json()
            assert asf_data["total_count"] == 1
            assert asf_data["granules"][0]["granule_name"] == "S1A_TEST_PAIR_ENDPOINT"

        # Check Bhoonidhi endpoint
        b_resp = await client.post(
            "/api/search/bhoonidhi",
            json={"wkt_polygon": SAMPLE_WKT, "collection": "NISAR_SSAR_GCOV"},
        )
        assert b_resp.status_code == 200
        b_data = b_resp.json()
        assert b_data["provider_status"] == "NOT_CONFIGURED"

        # Check new Observation Pairs endpoint
        with patch("asf_search.search", return_value=[mock_asf_item]):
            pair_resp = await client.post(
                "/api/search/observation-pairs",
                json={"wkt_polygon": SAMPLE_WKT, "dataset_preference": "SENTINEL-1"},
            )
            assert pair_resp.status_code == 200
            pair_data = pair_resp.json()
            assert "total_compatible_pairs" in pair_data

    print("  -> PASSED: All three endpoints (/granules, /bhoonidhi, /observation-pairs) fully functional.")
    passed_tests += 1

    print("\n" + "=" * 75)
    print(f"RESULTS: {passed_tests}/{total_tests} TESTS PASSED SUCCESSFULLY (Exit Code 0)")
    print("=" * 75)
    return 0


if __name__ == "__main__":
    code = asyncio.run(run_all_tests())
    sys.exit(code)
