"""
NISAR-Pulse Product Downloader, Validator & Cache Subsystem
Provides automated, authenticated streaming downloads of satellite SAR products
from ISRO Bhoonidhi and NASA ASF catalogues, with SHA-256 integrity checks,
safe archive extraction, SAR engine preflight, and local cache management.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from bhoonidhi_client import DEFAULT_BHOONIDHI_BASE_URL, get_bhoonidhi_client
from sar_engine import read_sar_raster
from schemas import PairDownloadRequest, PairDownloadResponse, ProductDownloadResult

logger = logging.getLogger("nisar_pulse.downloader")

# Default Cache Directory — strictly outside frontend/public, frontend/dist, and storage/masks
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / "data" / "cache"

# Magic byte signatures
HDF5_MAGIC = b"\x89HDF"
TIFF_LITTLE_ENDIAN = b"II*\x00"
TIFF_BIG_ENDIAN = b"MM\x00*"
ZIP_MAGIC = b"PK\x03\x04"

# Allowed NASA ASF domains to prevent SSRF
ALLOWED_ASF_HOSTS = {
    "datapool.asf.alaska.edu",
    "search.asf.alaska.edu",
    "urs.earthdata.nasa.gov",
    "asf.alaska.edu",
    "nasa.gov",
    "s3.amazonaws.com",
}


def sanitize_filename(item_id: str) -> str:
    """Sanitizes an item ID into a safe filesystem-compatible filename."""
    # Remove directory separators and dangerous characters
    cleaned = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", item_id)
    # Strip any leading dots to prevent hidden or parent directory traversal
    cleaned = cleaned.lstrip(".")
    return cleaned or "unnamed_product"


def compute_file_sha256(path: Path) -> str:
    """Computes exact SHA-256 hexadecimal digest from actual file bytes in 64KB blocks."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_cache_directory() -> Path:
    """Resolves and creates the local product cache directory."""
    env_dir = os.getenv("NISAR_CACHE_DIR")
    if env_dir and env_dir.strip():
        cache_path = Path(env_dir.strip()).resolve()
    else:
        cache_path = DEFAULT_CACHE_DIR.resolve()

    # Security check: Ensure cache is NOT inside public, dist, or static masks
    backend_root = Path(__file__).resolve().parent
    workspace_root = backend_root.parent
    forbidden_dirs = [
        workspace_root / "frontend" / "public",
        workspace_root / "frontend" / "dist",
        workspace_root / "storage" / "masks",
        backend_root / "storage" / "masks",
    ]
    for forbidden in forbidden_dirs:
        try:
            if forbidden.exists() and os.path.commonpath([str(cache_path), str(forbidden.resolve())]) == str(forbidden.resolve()):
                raise ValueError(
                    f"Insecure cache directory: {cache_path} cannot be placed inside public web root {forbidden}"
                )
        except ValueError:
            # Different drives on Windows will raise ValueError from commonpath, which is safe
            pass

    cache_path.mkdir(parents=True, exist_ok=True)
    return cache_path


class BhoonidhiRateLimiter:
    """
    Token bucket and concurrency limiter for ISRO Bhoonidhi.
    Rules: Maximum 2 requests per minute (30s interval), max concurrency (default 1).
    """

    def __init__(self, max_per_minute: int = 2, max_concurrency: int = 1) -> None:
        self.max_per_minute = max_per_minute
        self.interval = 60.0 / max(1, max_per_minute)
        self.max_concurrency = max_concurrency
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquires concurrency slot and rate-limit window."""
        await self.semaphore.acquire()
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.interval:
                wait_time = self.interval - elapsed
                logger.info("Bhoonidhi rate limit: sleeping %.2fs before request", wait_time)
                await asyncio.sleep(wait_time)
            self._last_request_time = time.time()

    def release(self) -> None:
        """Releases concurrency slot."""
        self.semaphore.release()

    def reset(self) -> None:
        """Resets rate limiter state (useful for tests)."""
        self._last_request_time = 0.0


# Global Bhoonidhi rate limiter instance
bhoonidhi_limiter = BhoonidhiRateLimiter(max_per_minute=2, max_concurrency=1)


class BhoonidhiDownloadAdapter:
    """Adapter for downloading NISAR products from ISRO Bhoonidhi API."""

    def __init__(
        self,
        base_url: str | None = None,
        limiter: BhoonidhiRateLimiter | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("BHOONIDHI_BASE_URL", DEFAULT_BHOONIDHI_BASE_URL)).rstrip("/")
        self.limiter = limiter or bhoonidhi_limiter
        self.http_client = http_client

    def build_download_url(self, item_id: str, collection: str) -> str:
        """Constructs official Bhoonidhi download URL."""
        return f"{self.base_url}/download?id={item_id}&collection={collection}"

    async def download(
        self,
        item_id: str,
        collection: str,
        is_online: bool = True,
        max_retries: int = 3,
    ) -> tuple[httpx.Response | None, str | None]:
        """
        Executes authenticated download request with rate limiting and retry backoff.
        Returns (response, error_message).
        """
        if not is_online:
            return None, "Product is currently OFFLINE in ISRO Bhoonidhi catalogue. Offline media orders are not supported."

        client_mgr = get_bhoonidhi_client()
        if not client_mgr.is_configured():
            return None, "ISRO Bhoonidhi credentials (BHOONIDHI_USER_ID, BHOONIDHI_PASSWORD) are not configured."

        token = await client_mgr.get_access_token()
        if not token:
            return None, "Failed to obtain authentication access token from ISRO Bhoonidhi."

        url = self.build_download_url(item_id, collection)
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "NISAR-Pulse-Downloader/1.0",
        }

        client = self.http_client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=120.0))
        should_close = client is not self.http_client

        backoff = 1.0
        for attempt in range(1, max_retries + 1):
            await self.limiter.acquire()
            try:
                # Open streaming request
                req = client.build_request("GET", url, headers=headers)
                resp = await client.send(req, stream=True)

                if resp.status_code == 200:
                    return resp, None

                # Handle transient retryable error codes
                if resp.status_code in (412, 429, 504):
                    await resp.aclose()
                    if attempt < max_retries:
                        logger.warning(
                            "Bhoonidhi returned HTTP %d on attempt %d/%d. Backing off for %.1fs...",
                            resp.status_code,
                            attempt,
                            max_retries,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                        backoff *= 2.0
                        continue
                    else:
                        return None, f"Bhoonidhi download failed with HTTP {resp.status_code} after {max_retries} attempts."

                # Non-retryable error
                await resp.aclose()
                return None, f"Bhoonidhi download rejected with HTTP {resp.status_code}."

            except (httpx.TimeoutException, httpx.NetworkError) as ex:
                if attempt < max_retries:
                    logger.warning("Bhoonidhi network exception (%s) on attempt %d. Retrying...", ex, attempt)
                    await asyncio.sleep(backoff)
                    backoff *= 2.0
                else:
                    return None, f"Network error connecting to Bhoonidhi: {ex}"
            finally:
                self.limiter.release()

        if should_close:
            await client.aclose()

        return None, f"Failed to download product from Bhoonidhi after {max_retries} attempts."


class ASFDownloadAdapter:
    """Adapter for downloading SAR granules from NASA ASF."""

    def __init__(
        self,
        token: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = token or os.getenv("EARTHDATA_TOKEN") or os.getenv("NASA_EARTHDATA_TOKEN")
        self.http_client = http_client

    def validate_url(self, url: str) -> bool:
        """Validates that URL belongs to an authorized NASA / ASF domain to prevent SSRF."""
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False
            hostname = parsed.hostname.lower() if parsed.hostname else ""
            return any(hostname == allowed or hostname.endswith("." + allowed) for allowed in ALLOWED_ASF_HOSTS)
        except Exception:
            return False

    async def download(
        self,
        download_url: str,
        item_id: str,
    ) -> tuple[httpx.Response | None, str | None]:
        """
        Executes streaming download for NASA ASF granule.
        Handles HTTP 302 redirects without leaking Bearer tokens to third-party domains.
        """
        if not self.validate_url(download_url):
            return None, f"Invalid or unauthorized download URL host for NASA ASF: {download_url}"

        client = self.http_client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(60.0, read=120.0),
        )
        should_close = client is not self.http_client

        current_url = download_url
        headers: dict[str, str] = {
            "User-Agent": "NISAR-Pulse-Downloader/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        try:
            # Handle redirect hops safely
            for _ in range(5):
                req = client.build_request("GET", current_url, headers=headers)
                resp = await client.send(req, stream=True)

                if resp.status_code in (301, 302, 303, 307, 308):
                    redirect_url = resp.headers.get("Location")
                    await resp.aclose()
                    if not redirect_url:
                        return None, "NASA ASF returned redirect without Location header."

                    # Check origin for credential stripping
                    parsed_orig = urlparse(current_url)
                    parsed_dest = urlparse(redirect_url)
                    if parsed_orig.netloc != parsed_dest.netloc:
                        # Strip Authorization header when redirecting across origins (e.g. to AWS S3 presigned URL)
                        headers.pop("Authorization", None)

                    current_url = redirect_url
                    continue

                if resp.status_code == 200:
                    return resp, None

                await resp.aclose()
                return None, f"NASA ASF download failed with HTTP {resp.status_code}."

            return None, "Too many redirects encountered while downloading from NASA ASF."

        except Exception as ex:
            return None, f"Exception occurred while downloading from NASA ASF: {ex}"
        finally:
            if should_close and not self.http_client:
                # Do not close if client is returned in open stream
                pass


class ProductCacheManager:
    """Manages the local product cache and manifest index."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or get_cache_directory()
        self.manifest_path = self.cache_dir / "manifest.json"
        self._lock = asyncio.Lock()

    def _read_manifest(self) -> dict[str, Any]:
        """Reads manifest file or returns empty dictionary."""
        if not self.manifest_path.exists():
            return {}
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception as ex:
            logger.warning("Corrupted manifest.json encountered (%s), reinitializing.", ex)
            return {}

    def _write_manifest(self, data: dict[str, Any]) -> None:
        """Writes manifest file atomically."""
        tmp = self.manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.manifest_path)

    async def get_cached(self, item_id: str) -> dict[str, Any] | None:
        """Checks if a verified cached product exists and verifies disk integrity and SHA-256 hash."""
        async with self._lock:
            manifest = self._read_manifest()
            entry = manifest.get(item_id)
            if not entry:
                return None

            file_path = Path(entry.get("local_path", ""))
            if not file_path.exists():
                logger.warning("Cache entry for %s missing file on disk. Invalidating.", item_id)
                manifest.pop(item_id, None)
                self._write_manifest(manifest)
                return None

            # 1. Verify size matches
            actual_size = file_path.stat().st_size
            expected_size = entry.get("file_size_bytes")
            if expected_size is not None and actual_size != expected_size:
                logger.warning(
                    "Cache entry for %s corrupted on disk (size mismatch: actual %d != expected %d). Invalidating.",
                    item_id,
                    actual_size,
                    expected_size,
                )
                manifest.pop(item_id, None)
                self._write_manifest(manifest)
                return None

            # 2. Verify actual SHA-256 matches on-disk content
            expected_sha = entry.get("sha256")
            if expected_sha:
                try:
                    actual_sha = compute_file_sha256(file_path)
                    if actual_sha.lower() != expected_sha.lower():
                        logger.warning(
                            "Cache entry for %s corrupted on disk (SHA-256 mismatch: actual %s != expected %s). Invalidating.",
                            item_id,
                            actual_sha,
                            expected_sha,
                        )
                        manifest.pop(item_id, None)
                        self._write_manifest(manifest)
                        return None
                except Exception as ex:
                    logger.warning("Failed to compute SHA-256 for cache entry %s: %s. Invalidating.", item_id, ex)
                    manifest.pop(item_id, None)
                    self._write_manifest(manifest)
                    return None

            return entry

    async def record_cache(self, item_id: str, record: dict[str, Any]) -> None:
        """Records a verified product in the manifest."""
        async with self._lock:
            manifest = self._read_manifest()
            manifest[item_id] = record
            self._write_manifest(manifest)


class ProductDownloader:
    """
    Main orchestration class for satellite product download, streaming verification,
    safe archive extraction, SAR engine preflight, and caching.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        bhoonidhi_adapter: BhoonidhiDownloadAdapter | None = None,
        asf_adapter: ASFDownloadAdapter | None = None,
    ) -> None:
        self.cache_dir = cache_dir or get_cache_directory()
        self.cache_manager = ProductCacheManager(self.cache_dir)
        self.bhoonidhi_adapter = bhoonidhi_adapter or BhoonidhiDownloadAdapter()
        self.asf_adapter = asf_adapter or ASFDownloadAdapter()

    async def stream_and_verify(
        self,
        resp: httpx.Response,
        target_path: Path,
        expected_size: int | None = None,
    ) -> tuple[str, int]:
        """
        Streams response chunks into a temporary .part file, computes SHA-256 on the fly,
        detects HTML/JSON error payloads, verifies Content-Length, and atomically renames.
        Returns: (sha256_hex, total_bytes)
        """
        part_path = target_path.with_suffix(target_path.suffix + ".part")
        hasher = hashlib.sha256()
        total_bytes = 0
        first_chunk = True

        try:
            with open(part_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    if not chunk:
                        continue

                    # Check first chunk for HTML or JSON error responses
                    if first_chunk:
                        first_chunk = False
                        chunk_head = chunk[:512].lstrip()
                        # HTML error detection
                        if (
                            chunk_head.startswith(b"<!DOCTYPE html")
                            or chunk_head.startswith(b"<html")
                            or chunk_head.startswith(b"<HTML")
                            or b"<head>" in chunk_head.lower()
                        ):
                            raise ValueError(
                                "Provider returned an HTML web page or error document instead of binary satellite data."
                            )

                        # JSON error payload detection
                        if chunk_head.startswith(b"{"):
                            try:
                                json_err = json.loads(chunk.decode("utf-8", errors="ignore"))
                                if any(k in json_err for k in ["error", "message", "detail", "status"]):
                                    msg = json_err.get("detail") or json_err.get("message") or json_err.get("error")
                                    raise ValueError(f"Provider returned error response: {msg}")
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                pass

                    f.write(chunk)
                    hasher.update(chunk)
                    total_bytes += len(chunk)

            # Verify Content-Length if provided
            content_length_header = resp.headers.get("Content-Length")
            if content_length_header:
                try:
                    cl_bytes = int(content_length_header)
                    if total_bytes != cl_bytes:
                        raise ValueError(
                            f"Downloaded file size ({total_bytes} bytes) does not match Content-Length ({cl_bytes} bytes)."
                        )
                except ValueError as ex:
                    if "does not match" in str(ex):
                        raise

            # Atomic rename from .part to target path
            part_path.replace(target_path)
            return hasher.hexdigest(), total_bytes

        except Exception:
            if part_path.exists():
                part_path.unlink()
            raise
        finally:
            await resp.aclose()

    def extract_archive_safely(self, zip_path: Path, dest_dir: Path) -> Path:
        """
        Safely extracts an archive with strict Zip Slip / directory traversal protection.
        Finds and returns the primary SAR raster file (.h5, .hdf5, .tif, .tiff).
        """
        dest_dir.resolve().mkdir(parents=True, exist_ok=True)
        resolved_dest = dest_dir.resolve()

        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                # Prevent directory traversal attacks
                target_file = (dest_dir / member.filename).resolve()
                try:
                    if os.path.commonpath([str(resolved_dest), str(target_file)]) != str(resolved_dest):
                        raise ValueError(f"Directory traversal / Zip Slip attempt detected: {member.filename}")
                except ValueError as ex:
                    if "Zip Slip" in str(ex):
                        raise
                    raise ValueError(f"Invalid archive member path: {member.filename}")

            # Safe extraction
            zf.extractall(dest_dir)

        # Locate primary raster file
        candidates: list[Path] = []
        for root, _, files in os.walk(dest_dir):
            for file in files:
                f_path = Path(root) / file
                suf = f_path.suffix.lower()
                if suf in [".h5", ".hdf5", ".tif", ".tiff"]:
                    candidates.append(f_path)

        if not candidates:
            raise ValueError(f"No valid SAR raster file (.h5, .tif) found in extracted archive: {zip_path.name}")

        # Prefer HDF5 if both exist
        hdf5_candidates = [c for c in candidates if c.suffix.lower() in [".h5", ".hdf5"]]
        if hdf5_candidates:
            return hdf5_candidates[0]
        return candidates[0]

    def verify_sar_preflight(self, raster_path: Path) -> tuple[bool, dict[str, Any]]:
        """
        Validates the downloaded/extracted file against the actual SAR Engine reader.
        Returns: (is_ok, details_dict)
        """
        try:
            raster = read_sar_raster(str(raster_path))
            return True, {
                "crs": raster.crs,
                "shape": list(raster.data.shape),
                "bounds_wgs84": raster.bounds_wgs84,
                "product_type": raster.product_type,
            }
        except Exception as ex:
            return False, {"error": str(ex)}

    async def download_product(
        self,
        provider: str,
        item_id: str,
        collection_id: str | None = None,
        download_url: str | None = None,
        is_online: bool = True,
    ) -> ProductDownloadResult:
        """
        Downloads, validates, extracts (if ZIP), and caches a single satellite product.
        """
        provider_norm = provider.upper()
        safe_name = sanitize_filename(item_id)

        # 1. Check local cache
        cached_entry = await self.cache_manager.get_cached(item_id)
        if cached_entry:
            local_path = cached_entry.get("local_path")
            return ProductDownloadResult(
                provider=provider_norm,
                collection_id=collection_id or cached_entry.get("collection_id"),
                item_id=item_id,
                status="CACHED",
                local_path=local_path,
                file_size_bytes=cached_entry.get("file_size_bytes"),
                sha256=cached_entry.get("sha256"),
                is_cached=True,
                sar_preflight_ok=cached_entry.get("sar_preflight_ok", True),
                sar_preflight_details=cached_entry.get("sar_preflight_details", {}),
            )

        # 2. Select download adapter
        resp: httpx.Response | None = None
        err_msg: str | None = None

        if "BHOONIDHI" in provider_norm or "ISRO" in provider_norm:
            coll = collection_id or "NISAR_SSAR_GCOV"
            resp, err_msg = await self.bhoonidhi_adapter.download(
                item_id=item_id,
                collection=coll,
                is_online=is_online,
            )
        elif "ASF" in provider_norm or "NASA" in provider_norm:
            if not download_url:
                # Default ASF data download URL format
                download_url = f"https://datapool.asf.alaska.edu/GRD_HD/{item_id}.zip"
            resp, err_msg = await self.asf_adapter.download(download_url=download_url, item_id=item_id)
        else:
            return ProductDownloadResult(
                provider=provider_norm,
                collection_id=collection_id,
                item_id=item_id,
                status="FAILED",
                validation_error=f"Unsupported satellite provider: '{provider}'",
            )

        if err_msg or resp is None:
            status = "OFFLINE" if err_msg and "OFFLINE" in err_msg else "FAILED"
            return ProductDownloadResult(
                provider=provider_norm,
                collection_id=collection_id,
                item_id=item_id,
                status=status,
                validation_error=err_msg or "Unknown download error",
            )

        # 3. Stream and verify download
        # Check initial extension from URL or item_id
        target_ext = ".zip" if "ASF" in provider_norm or (download_url and download_url.endswith(".zip")) else ".h5"
        raw_download_path = self.cache_dir / f"{safe_name}{target_ext}"

        try:
            sha256_hash, file_size = await self.stream_and_verify(resp, raw_download_path)
        except Exception as ex:
            return ProductDownloadResult(
                provider=provider_norm,
                collection_id=collection_id,
                item_id=item_id,
                status="FAILED",
                validation_error=f"Download streaming verification failed: {ex}",
            )

        # 4. Handle ZIP archive extraction if applicable
        primary_raster_path = raw_download_path
        if raw_download_path.suffix.lower() == ".zip":
            extract_dir = self.cache_dir / f"{safe_name}_extracted"
            try:
                primary_raster_path = self.extract_archive_safely(raw_download_path, extract_dir)
            except Exception as ex:
                return ProductDownloadResult(
                    provider=provider_norm,
                    collection_id=collection_id,
                    item_id=item_id,
                    status="FAILED",
                    local_path=str(raw_download_path),
                    file_size_bytes=file_size,
                    sha256=sha256_hash,
                    validation_error=f"Safe archive extraction failed: {ex}",
                )

        # Compute exact hash and size for the primary raster file
        raster_file_size = primary_raster_path.stat().st_size
        raster_sha256 = compute_file_sha256(primary_raster_path)

        # 5. SAR Preflight Check
        preflight_ok, preflight_details = self.verify_sar_preflight(primary_raster_path)

        # 6. Record in cache manifest
        cache_record = {
            "item_id": item_id,
            "provider": provider_norm,
            "collection_id": collection_id,
            "local_path": str(primary_raster_path.resolve()),
            "raw_download_path": str(raw_download_path.resolve()),
            "file_size_bytes": raster_file_size,
            "sha256": raster_sha256,
            "raw_file_size_bytes": file_size,
            "raw_sha256": sha256_hash,
            "sar_preflight_ok": preflight_ok,
            "sar_preflight_details": preflight_details,
            "download_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.cache_manager.record_cache(item_id, cache_record)

        return ProductDownloadResult(
            provider=provider_norm,
            collection_id=collection_id,
            item_id=item_id,
            status="SUCCESS",
            local_path=str(primary_raster_path.resolve()),
            file_size_bytes=raster_file_size,
            sha256=raster_sha256,
            is_cached=False,
            sar_preflight_ok=preflight_ok,
            sar_preflight_details=preflight_details,
            warnings=[] if preflight_ok else [f"SAR Engine preflight warning: {preflight_details.get('error')}"],
        )

    async def download_pair(self, req: PairDownloadRequest) -> PairDownloadResponse:
        """
        Coordinates downloading and validation of a BEFORE and AFTER satellite observation pair.
        """
        warnings: list[str] = []

        # Download BEFORE product
        before_res = await self.download_product(
            provider=req.before_provider,
            item_id=req.before_item_id,
            collection_id=req.before_collection,
            download_url=req.before_download_url,
        )

        # Download AFTER product
        after_res = await self.download_product(
            provider=req.after_provider,
            item_id=req.after_item_id,
            collection_id=req.after_collection,
            download_url=req.after_download_url,
        )

        # Evaluate overall status
        before_ok = before_res.status in ("SUCCESS", "CACHED") and before_res.sar_preflight_ok
        after_ok = after_res.status in ("SUCCESS", "CACHED") and after_res.sar_preflight_ok

        if before_ok and after_ok:
            pair_status = "PAIR_READY_FOR_ANALYSIS"
            message = "Both BEFORE and AFTER satellite products are downloaded, verified, and ready for SAR analysis."
        elif before_res.status in ("SUCCESS", "CACHED") or after_res.status in ("SUCCESS", "CACHED"):
            pair_status = "PARTIAL"
            failed_side = "AFTER" if before_ok else "BEFORE"
            message = f"Partial download completed: {failed_side} product failed validation or download."
        elif not before_res.sar_preflight_ok or not after_res.sar_preflight_ok:
            pair_status = "PAIR_UNSUPPORTED"
            message = "One or more downloaded products could not be parsed by the SAR engine."
        else:
            pair_status = "DOWNLOAD_FAILED"
            message = "Failed to download satellite observation pair from provider(s)."

        if before_res.warnings:
            warnings.extend([f"BEFORE: {w}" for w in before_res.warnings])
        if after_res.warnings:
            warnings.extend([f"AFTER: {w}" for w in after_res.warnings])

        return PairDownloadResponse(
            pair_status=pair_status,
            before_product=before_res,
            after_product=after_res,
            message=message,
            warnings=warnings,
        )
