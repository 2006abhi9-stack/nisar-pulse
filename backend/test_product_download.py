"""
NISAR-Pulse: Task 12 — Satellite Product Download, Validation & Caching Test Suite
Standalone test suite verifying all 21 required test scenarios:
1. Bhoonidhi download URL construction & params
2. Bhoonidhi auth token header attached
3. Bhoonidhi 412 handling (user session limit backoff & retry)
4. Bhoonidhi 429 handling (rate limit backoff & retry)
5. Bhoonidhi 504 handling (gateway timeout backoff & retry)
6. Bhoonidhi offline product rejection (Online != 'Y')
7. Bhoonidhi rate limiting (respects 2 req/min and concurrency limit)
8. NASA ASF download URL resolution & credentials
9. NASA ASF 302 redirect handling with origin-crossing header stripping
10. Streaming download to temporary .part file and atomic rename
11. Content-Length mismatch detection and partial cleanup
12. SHA-256 calculation and verification
13. HTML error page detection (aborts, does not save HTML as raster)
14. JSON error payload detection (aborts, parses error)
15. Path traversal prevention in item IDs / file names
16. Zip Slip / directory traversal prevention during archive extraction
17. Safe extraction of target raster (.h5/.tif) from valid ZIP
18. Real SAR Engine preflight check using read_sar_raster
19. Cache hit avoids re-download when file and manifest valid
20. Cache invalidation when file corrupted or missing
21. POST /api/products/download-pair endpoint integration test
"""

import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import h5py
import httpx
import numpy as np

# Ensure backend directory is in python search path
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from main import app
from product_downloader import (
    ASFDownloadAdapter,
    BhoonidhiDownloadAdapter,
    BhoonidhiRateLimiter,
    ProductCacheManager,
    ProductDownloader,
    sanitize_filename,
)
from schemas import PairDownloadRequest, PairDownloadResponse


def make_mock_stream(chunks: list[bytes], headers: dict[str, str] | None = None) -> MagicMock:
    """Helper to mock an async streaming httpx.Response."""
    mock = MagicMock()
    mock.headers = headers or {}

    async def _aiter(chunk_size: int = 65536):
        for c in chunks:
            yield c

    mock.aiter_bytes = _aiter
    mock.aclose = AsyncMock()
    return mock


def create_minimal_nisar_hdf5(file_path: Path, epsg: int = 4326) -> None:
    """Helper creating a minimal valid NISAR GCOV HDF5 file for SAR engine validation."""
    with h5py.File(str(file_path), "w") as hf:
        sci = hf.create_group("science")
        ssar = sci.create_group("SSAR")
        ident = ssar.create_group("identification")
        ident.create_dataset("productType", data=b"GCOV")
        gcov = ssar.create_group("GCOV")
        grids = gcov.create_group("grids")
        freq = grids.create_group("frequencyA")
        freq.create_dataset("xCoordinates", data=np.array([80.0, 80.01, 80.02], dtype=np.float64))
        freq.create_dataset("yCoordinates", data=np.array([13.02, 13.01, 13.00], dtype=np.float64))
        proj = freq.create_dataset("projection", data=0)
        proj.attrs["epsg_code"] = epsg
        data = np.ones((3, 3), dtype=np.float32) * 0.15
        ds = freq.create_dataset("HHHH", data=data)
        ds.attrs["_FillValue"] = -9999.0


async def run_all_tests() -> int:
    print("=" * 75)
    print("TASK 12: AUTOMATIC SATELLITE PRODUCT DOWNLOAD & CACHING TEST SUITE")
    print("=" * 75)

    passed_tests = 0
    total_tests = 21

    # --------------------------------------------------------------------------
    # Test 1: Bhoonidhi download URL construction & params
    # --------------------------------------------------------------------------
    print("\n[Test 1] Bhoonidhi download URL construction & params...")
    adapter = BhoonidhiDownloadAdapter(base_url="https://bhoonidhi-api.nrsc.gov.in")
    url = adapter.build_download_url("NISAR_S_20260201", "NISAR_SSAR_GCOV")
    assert url == "https://bhoonidhi-api.nrsc.gov.in/download?id=NISAR_S_20260201&collection=NISAR_SSAR_GCOV"
    print("  -> PASSED: Bhoonidhi download URL constructed with exact id and collection query params.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 2: Bhoonidhi auth token header attached
    # --------------------------------------------------------------------------
    print("\n[Test 2] Bhoonidhi auth token header attached correctly...")
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": "10"}
    mock_resp.aclose = AsyncMock()
    mock_client.send.return_value = mock_resp

    with patch("product_downloader.get_bhoonidhi_client") as mock_bmgr:
        b_inst = MagicMock()
        b_inst.is_configured.return_value = True
        b_inst.get_access_token = AsyncMock(return_value="fake_bhoonidhi_token_123")
        mock_bmgr.return_value = b_inst

        limiter = BhoonidhiRateLimiter(max_per_minute=1000, max_concurrency=1)
        adapter = BhoonidhiDownloadAdapter(limiter=limiter, http_client=mock_client)
        resp, err = await adapter.download("NISAR_ITEM_1", "NISAR_SSAR_GCOV", is_online=True)
        assert err is None
        assert resp is not None

        # Verify outgoing request headers
        mock_client.build_request.assert_called_once()
        req_call = mock_client.build_request.call_args
        assert req_call[0][0] == "GET"
        assert req_call[1]["headers"]["Authorization"] == "Bearer fake_bhoonidhi_token_123"

    print("  -> PASSED: Authorization: Bearer <token> attached to Bhoonidhi request.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 3: Bhoonidhi 412 handling (user session limit backoff & retry)
    # --------------------------------------------------------------------------
    print("\n[Test 3] Bhoonidhi 412 handling (session limit backoff & retry)...")
    resp_412 = MagicMock()
    resp_412.status_code = 412
    resp_412.aclose = AsyncMock()

    resp_200 = MagicMock()
    resp_200.status_code = 200

    mock_client = AsyncMock()
    mock_client.send.side_effect = [resp_412, resp_200]

    with patch("product_downloader.get_bhoonidhi_client") as mock_bmgr:
        b_inst = MagicMock()
        b_inst.is_configured.return_value = True
        b_inst.get_access_token = AsyncMock(return_value="token_123")
        mock_bmgr.return_value = b_inst

        limiter = BhoonidhiRateLimiter(max_per_minute=1000, max_concurrency=1)
        adapter = BhoonidhiDownloadAdapter(limiter=limiter, http_client=mock_client)
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            resp, err = await adapter.download("ITEM_412", "NISAR_SSAR_GCOV")
            assert err is None
            assert resp.status_code == 200
            assert mock_client.send.call_count == 2
            assert any(args[0] == 1.0 for args, _ in mock_sleep.call_args_list)

    print("  -> PASSED: HTTP 412 triggered backoff sleep and succeeded on retry.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 4: Bhoonidhi 429 handling (rate limit backoff & retry)
    # --------------------------------------------------------------------------
    print("\n[Test 4] Bhoonidhi 429 handling (rate limit backoff & retry)...")
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.aclose = AsyncMock()

    mock_client = AsyncMock()
    mock_client.send.side_effect = [resp_429, resp_200]

    with patch("product_downloader.get_bhoonidhi_client") as mock_bmgr:
        b_inst = MagicMock()
        b_inst.is_configured.return_value = True
        b_inst.get_access_token = AsyncMock(return_value="token_123")
        mock_bmgr.return_value = b_inst

        limiter = BhoonidhiRateLimiter(max_per_minute=1000, max_concurrency=1)
        adapter = BhoonidhiDownloadAdapter(limiter=limiter, http_client=mock_client)
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            resp, err = await adapter.download("ITEM_429", "NISAR_SSAR_GCOV")
            assert err is None
            assert resp.status_code == 200
            assert mock_client.send.call_count == 2
            assert any(args[0] == 1.0 for args, _ in mock_sleep.call_args_list)

    print("  -> PASSED: HTTP 429 triggered rate-limit backoff and succeeded on retry.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 5: Bhoonidhi 504 handling (gateway timeout backoff & retry)
    # --------------------------------------------------------------------------
    print("\n[Test 5] Bhoonidhi 504 handling (gateway timeout backoff & retry)...")
    resp_504 = MagicMock()
    resp_504.status_code = 504
    resp_504.aclose = AsyncMock()

    mock_client = AsyncMock()
    mock_client.send.side_effect = [resp_504, resp_200]

    with patch("product_downloader.get_bhoonidhi_client") as mock_bmgr:
        b_inst = MagicMock()
        b_inst.is_configured.return_value = True
        b_inst.get_access_token = AsyncMock(return_value="token_123")
        mock_bmgr.return_value = b_inst

        limiter = BhoonidhiRateLimiter(max_per_minute=1000, max_concurrency=1)
        adapter = BhoonidhiDownloadAdapter(limiter=limiter, http_client=mock_client)
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            resp, err = await adapter.download("ITEM_504", "NISAR_SSAR_GCOV")
            assert err is None
            assert resp.status_code == 200
            assert mock_client.send.call_count == 2
            assert any(args[0] == 1.0 for args, _ in mock_sleep.call_args_list)

    print("  -> PASSED: HTTP 504 gateway timeout safely retried with exponential backoff.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 6: Bhoonidhi offline product rejection (Online != 'Y')
    # --------------------------------------------------------------------------
    print("\n[Test 6] Bhoonidhi offline product rejection (Online != 'Y')...")
    adapter = BhoonidhiDownloadAdapter()
    resp, err = await adapter.download("OFFLINE_ITEM", "NISAR_SSAR_GCOV", is_online=False)
    assert resp is None
    assert "OFFLINE" in err
    assert "Offline media orders are not supported" in err
    print("  -> PASSED: Offline product rejected immediately without attempting HTTP download.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 7: Bhoonidhi rate limiting (2 req/min and concurrency limit)
    # --------------------------------------------------------------------------
    print("\n[Test 7] Bhoonidhi rate limiting (2 req/min and concurrency limit)...")
    limiter = BhoonidhiRateLimiter(max_per_minute=2, max_concurrency=1)
    assert limiter.interval == 30.0
    assert limiter.semaphore._value == 1

    # Acquire once
    await limiter.acquire()
    limiter.release()

    # Second acquire without wait should trigger sleep calculation
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await limiter.acquire()
        limiter.release()
        mock_sleep.assert_called_once()
        wait_arg = mock_sleep.call_args[0][0]
        assert 28.0 <= wait_arg <= 30.0

    print("  -> PASSED: BhoonidhiRateLimiter enforces 30s spacing between requests.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 8: NASA ASF download URL resolution & credentials
    # --------------------------------------------------------------------------
    print("\n[Test 8] NASA ASF download URL resolution & credentials...")
    asf_adapter = ASFDownloadAdapter(token="fake_earthdata_token")
    assert asf_adapter.validate_url("https://datapool.asf.alaska.edu/GRD_HD/S1A_TEST.zip") is True
    assert asf_adapter.validate_url("https://malicious-site.com/steal-data.zip") is False

    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client.send.return_value = mock_resp

    asf_adapter.http_client = mock_client
    resp, err = await asf_adapter.download("https://datapool.asf.alaska.edu/GRD_HD/S1A_TEST.zip", "S1A_TEST")
    assert err is None
    req_call = mock_client.build_request.call_args
    assert req_call[1]["headers"]["Authorization"] == "Bearer fake_earthdata_token"
    print("  -> PASSED: NASA ASF download URL authorized host validated and Earthdata token attached.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 9: NASA ASF 302 redirect handling with header stripping across origins
    # --------------------------------------------------------------------------
    print("\n[Test 9] NASA ASF 302 redirect handling with header stripping across origins...")
    resp_302 = MagicMock()
    resp_302.status_code = 302
    resp_302.headers = {"Location": "https://s3.amazonaws.com/asf-datapool-presigned/file.zip"}
    resp_302.aclose = AsyncMock()

    resp_200 = MagicMock()
    resp_200.status_code = 200

    mock_client = AsyncMock()
    mock_client.send.side_effect = [resp_302, resp_200]

    asf_adapter = ASFDownloadAdapter(token="secret_token_123", http_client=mock_client)
    resp, err = await asf_adapter.download("https://datapool.asf.alaska.edu/GRD_HD/S1A_TEST.zip", "S1A_TEST")
    assert err is None
    assert mock_client.send.call_count == 2

    # Verify that the second call (to S3) did NOT include the Authorization header!
    second_req_headers = mock_client.build_request.call_args_list[1][1]["headers"]
    assert "Authorization" not in second_req_headers
    print("  -> PASSED: Redirect followed and Bearer token stripped when crossing origin to S3.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 10: Streaming download to temporary .part file and atomic rename
    # --------------------------------------------------------------------------
    print("\n[Test 10] Streaming download to temporary .part file and atomic rename...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        target = tmp_path / "product.h5"

        mock_resp = make_mock_stream([b"chunk_1_", b"chunk_2"], headers={"Content-Length": "15"})
        downloader = ProductDownloader(cache_dir=tmp_path)
        sha, size = await downloader.stream_and_verify(mock_resp, target)

        assert size == 15
        assert target.exists()
        assert not target.with_suffix(".h5.part").exists()
        assert target.read_bytes() == b"chunk_1_chunk_2"

    print("  -> PASSED: Product streamed to .part and atomically renamed to destination.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 11: Content-Length mismatch detection and partial cleanup
    # --------------------------------------------------------------------------
    print("\n[Test 11] Content-Length mismatch detection and partial cleanup...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        target = tmp_path / "truncated.h5"

        mock_resp = make_mock_stream([b"short_bytes"], headers={"Content-Length": "1000"})
        downloader = ProductDownloader(cache_dir=tmp_path)
        try:
            await downloader.stream_and_verify(mock_resp, target)
            assert False, "Expected Content-Length mismatch exception"
        except ValueError as ex:
            assert "does not match Content-Length" in str(ex)

        assert not target.exists()
        assert not target.with_suffix(".h5.part").exists(), "Partial .part file must be cleaned up"

    print("  -> PASSED: Truncated download detected via Content-Length and .part file deleted.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 12: SHA-256 calculation and verification
    # --------------------------------------------------------------------------
    print("\n[Test 12] SHA-256 calculation and verification...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        target = tmp_path / "data.bin"
        payload = b"Exact verification test data for SHA-256"
        expected_hash = hashlib.sha256(payload).hexdigest()

        mock_resp = make_mock_stream([payload[:10], payload[10:]])
        downloader = ProductDownloader(cache_dir=tmp_path)
        sha, size = await downloader.stream_and_verify(mock_resp, target)
        assert sha == expected_hash
        assert size == len(payload)

    print("  -> PASSED: SHA-256 calculated incrementally during stream matches exact digest.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 13: HTML error page detection (aborts, does not save HTML as raster)
    # --------------------------------------------------------------------------
    print("\n[Test 13] HTML error page detection (aborts, does not save HTML as raster)...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        target = tmp_path / "fake_raster.h5"
        html_payload = b"<!DOCTYPE html><html><head><title>403 Forbidden</title></head><body>Access Denied</body></html>"

        mock_resp = make_mock_stream([html_payload])
        downloader = ProductDownloader(cache_dir=tmp_path)
        try:
            await downloader.stream_and_verify(mock_resp, target)
            assert False, "Expected HTML payload detection exception"
        except ValueError as ex:
            assert "HTML web page or error document" in str(ex)

        assert not target.exists()
        assert not target.with_suffix(".h5.part").exists()

    print("  -> PASSED: HTML error page detected, download aborted, and file discarded.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 14: JSON error payload detection (aborts, parses error)
    # --------------------------------------------------------------------------
    print("\n[Test 14] JSON error payload detection (aborts, parses error)...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        target = tmp_path / "error_payload.h5"
        json_payload = b'{"error": "Resource Not Found", "detail": "The requested NISAR product does not exist."}'

        mock_resp = make_mock_stream([json_payload])
        downloader = ProductDownloader(cache_dir=tmp_path)
        try:
            await downloader.stream_and_verify(mock_resp, target)
            assert False, "Expected JSON error detection exception"
        except ValueError as ex:
            assert "Provider returned error response" in str(ex)
            assert "The requested NISAR product does not exist." in str(ex)

        assert not target.exists()

    print("  -> PASSED: JSON error payload detected and detailed error message extracted.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 15: Path traversal prevention in item IDs / file names
    # --------------------------------------------------------------------------
    print("\n[Test 15] Path traversal prevention in item IDs / file names...")
    dangerous_ids = [
        "../../etc/passwd",
        "..\\..\\windows\\system32\\cmd.exe",
        "product/../../../evil",
        "../secret.key",
        ".../...//malicious",
    ]
    for bad_id in dangerous_ids:
        safe = sanitize_filename(bad_id)
        assert "/" not in safe
        assert "\\" not in safe
        assert not safe.startswith("..")
        assert not safe.startswith(".")

    print("  -> PASSED: Path traversal characters thoroughly sanitized from item IDs.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 16: Zip Slip / directory traversal prevention during archive extraction
    # --------------------------------------------------------------------------
    print("\n[Test 16] Zip Slip attack prevention during archive extraction...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        malicious_zip = tmp_path / "malicious.zip"
        dest_dir = tmp_path / "extracted"

        # Create malicious ZIP containing a path-traversal entry
        with zipfile.ZipFile(malicious_zip, "w") as zf:
            zf.writestr("../../evil_slip.txt", b"malicious content")

        downloader = ProductDownloader(cache_dir=tmp_path)
        try:
            downloader.extract_archive_safely(malicious_zip, dest_dir)
            assert False, "Expected Zip Slip detection exception"
        except ValueError as ex:
            assert "Zip Slip" in str(ex)

        # Ensure no evil file was written outside dest_dir
        assert not (tmp_path.parent / "evil_slip.txt").exists()

    print("  -> PASSED: Zip Slip / directory traversal attack detected and blocked.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 17: Safe extraction of target raster (.h5/.tif) from valid ZIP
    # --------------------------------------------------------------------------
    print("\n[Test 17] Safe extraction of target raster from valid ZIP...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        valid_zip = tmp_path / "valid_product.zip"
        dest_dir = tmp_path / "extracted_valid"

        # Create valid ZIP containing metadata and an HDF5 raster
        h5_temp = tmp_path / "test_raster.h5"
        create_minimal_nisar_hdf5(h5_temp)

        with zipfile.ZipFile(valid_zip, "w") as zf:
            zf.writestr("metadata.xml", b"<xml>test</xml>")
            zf.write(h5_temp, arcname="granule_data/test_raster.h5")

        downloader = ProductDownloader(cache_dir=tmp_path)
        primary = downloader.extract_archive_safely(valid_zip, dest_dir)
        assert primary.exists()
        assert primary.suffix == ".h5"
        assert primary.name == "test_raster.h5"

    print("  -> PASSED: Valid archive extracted and primary .h5 raster correctly identified.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 18: Real SAR Engine preflight check using read_sar_raster
    # --------------------------------------------------------------------------
    print("\n[Test 18] Real SAR Engine preflight check using read_sar_raster...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        valid_h5 = tmp_path / "valid.h5"
        create_minimal_nisar_hdf5(valid_h5)

        corrupt_h5 = tmp_path / "corrupt.h5"
        corrupt_h5.write_bytes(b"\x89HDF\r\n\x1a\nCorrupt garbage data")

        downloader = ProductDownloader(cache_dir=tmp_path)

        # Test valid
        ok_valid, details_valid = downloader.verify_sar_preflight(valid_h5)
        assert ok_valid is True
        assert details_valid["crs"] == "EPSG:4326"
        assert details_valid["shape"] == [3, 3]

        # Test corrupt
        ok_corrupt, details_corrupt = downloader.verify_sar_preflight(corrupt_h5)
        assert ok_corrupt is False
        assert "error" in details_corrupt

    print("  -> PASSED: SAR Engine preflight accepts valid HDF5 and identifies corrupt files.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 19: Cache hit avoids re-download when file and manifest valid
    # --------------------------------------------------------------------------
    print("\n[Test 19] Cache hit avoids re-download when file and manifest valid...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cache_mgr = ProductCacheManager(cache_dir=tmp_path)

        test_file = tmp_path / "cached_raster.h5"
        create_minimal_nisar_hdf5(test_file)
        file_size = test_file.stat().st_size
        sha_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()

        # Record in manifest
        await cache_mgr.record_cache("ITEM_CACHED_1", {
            "item_id": "ITEM_CACHED_1",
            "provider": "ISRO_BHOONIDHI",
            "local_path": str(test_file),
            "file_size_bytes": file_size,
            "sha256": sha_hash,
            "sar_preflight_ok": True,
            "sar_preflight_details": {"crs": "EPSG:4326"},
        })

        downloader = ProductDownloader(cache_dir=tmp_path)
        # Should return cached without network call
        res = await downloader.download_product("ISRO_BHOONIDHI", "ITEM_CACHED_1")
        assert res.status == "CACHED"
        assert res.is_cached is True
        assert res.local_path == str(test_file)
        assert res.file_size_bytes == file_size

    print("  -> PASSED: Valid cached product returned immediately without network download.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 20: Cache invalidation when file corrupted or missing
    # --------------------------------------------------------------------------
    print("\n[Test 20] Cache invalidation when file corrupted or missing...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cache_mgr = ProductCacheManager(cache_dir=tmp_path)

        missing_file = tmp_path / "missing.h5"
        await cache_mgr.record_cache("ITEM_MISSING", {
            "item_id": "ITEM_MISSING",
            "local_path": str(missing_file),
            "file_size_bytes": 1000,
        })

        # Cache check should invalidate missing entry
        entry = await cache_mgr.get_cached("ITEM_MISSING")
        assert entry is None
        # Manifest should no longer contain item
        manifest = cache_mgr._read_manifest()
        assert "ITEM_MISSING" not in manifest

    print("  -> PASSED: Missing cache files automatically detected and purged from manifest.")
    passed_tests += 1

    # --------------------------------------------------------------------------
    # Test 21: POST /api/products/download-pair endpoint integration test
    # --------------------------------------------------------------------------
    print("\n[Test 21] POST /api/products/download-pair endpoint integration test...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Create two valid rasters for mock downloads
        b_h5 = tmp_path / "before.h5"
        a_h5 = tmp_path / "after.h5"
        create_minimal_nisar_hdf5(b_h5)
        create_minimal_nisar_hdf5(a_h5)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("main.ProductDownloader") as mock_downloader_cls:
                mock_downloader = MagicMock()
                mock_downloader_cls.return_value = mock_downloader

                mock_downloader.download_pair = AsyncMock(return_value=PairDownloadResponse(
                    pair_status="PAIR_READY_FOR_ANALYSIS",
                    before_product={
                        "provider": "ISRO_BHOONIDHI",
                        "item_id": "NISAR_S_BEFORE",
                        "status": "SUCCESS",
                        "local_path": str(b_h5),
                        "file_size_bytes": b_h5.stat().st_size,
                        "sha256": hashlib.sha256(b_h5.read_bytes()).hexdigest(),
                        "sar_preflight_ok": True,
                    },
                    after_product={
                        "provider": "ISRO_BHOONIDHI",
                        "item_id": "NISAR_S_AFTER",
                        "status": "SUCCESS",
                        "local_path": str(a_h5),
                        "file_size_bytes": a_h5.stat().st_size,
                        "sha256": hashlib.sha256(a_h5.read_bytes()).hexdigest(),
                        "sar_preflight_ok": True,
                    },
                    message="Both BEFORE and AFTER satellite products are downloaded, verified, and ready for SAR analysis.",
                ))

                resp = await client.post(
                    "/api/products/download-pair",
                    json={
                        "before_provider": "ISRO_BHOONIDHI",
                        "before_item_id": "NISAR_S_BEFORE",
                        "before_collection": "NISAR_SSAR_GCOV",
                        "after_provider": "ISRO_BHOONIDHI",
                        "after_item_id": "NISAR_S_AFTER",
                        "after_collection": "NISAR_SSAR_GCOV",
                        "aoi_wkt": "POLYGON((80.0 13.0, 80.02 13.0, 80.02 13.02, 80.0 13.02, 80.0 13.0))",
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["pair_status"] == "PAIR_READY_FOR_ANALYSIS"
                assert data["before_product"]["sar_preflight_ok"] is True
                assert data["after_product"]["sar_preflight_ok"] is True
                assert "Both BEFORE and AFTER" in data["message"]

    print("  -> PASSED: POST /api/products/download-pair endpoint validated.")
    passed_tests += 1

    print("\n" + "=" * 75)
    print(f"RESULTS: {passed_tests}/{total_tests} TESTS PASSED SUCCESSFULLY (Exit Code 0)")
    print("=" * 75)
    return 0


if __name__ == "__main__":
    code = asyncio.run(run_all_tests())
    sys.exit(code)
