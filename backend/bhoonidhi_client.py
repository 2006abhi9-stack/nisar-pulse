"""
Bhoonidhi Client — ISRO Satellite Data Catalogue Integration
Provides authenticated STAC search, token lifecycle management, and strict
radar product qualification for NISAR S-band SAR products.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping as shapely_mapping, shape as shapely_shape

from schemas import (
    BhoonidhiProduct,
    BhoonidhiProductQualification,
    BhoonidhiProviderStatus,
    BhoonidhiSearchRequest,
    BhoonidhiSearchResponse,
)

logger = logging.getLogger("nisar_pulse.bhoonidhi")

DEFAULT_BHOONIDHI_BASE_URL = "https://bhoonidhi-api.nrsc.gov.in"
DEFAULT_COLLECTION = "NISAR_SSAR_GCOV"
MAX_PAGES_LIMIT = 5
DEFAULT_REQUEST_TIMEOUT = 25.0


def _parse_iso_datetime(val: Any) -> datetime | None:
    """Safely parses ISO datetime string into UTC datetime object."""
    if not val or not isinstance(val, str):
        return None
    try:
        clean = val.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _parse_polarization(props: dict[str, Any]) -> str | None:
    """Normalizes polarization list or string into standard format (e.g. 'HH' or 'HH+HV')."""
    raw = props.get("sar:polarizations") or props.get("polarization") or props.get("polarizations")
    if isinstance(raw, list):
        return "+".join(str(p).strip().upper() for p in raw if p)
    if isinstance(raw, str) and raw.strip():
        return raw.strip().upper()
    return None


def _parse_orbit_direction(props: dict[str, Any]) -> str | None:
    """Extracts normalized orbit direction ('ASCENDING' / 'DESCENDING')."""
    raw = (
        props.get("sat:orbit_state")
        or props.get("orbit_direction")
        or props.get("orbitDirection")
        or props.get("sar:orbit_direction")
    )
    if isinstance(raw, str) and raw.strip():
        return raw.strip().upper()
    return None


def _parse_look_direction(props: dict[str, Any]) -> str | None:
    """Extracts normalized radar look direction ('RIGHT' / 'LEFT')."""
    raw = (
        props.get("sar:looks_range_direction")
        or props.get("look_direction")
        or props.get("sar:look_direction")
        or props.get("lookDirection")
    )
    if isinstance(raw, str) and raw.strip():
        return raw.strip().upper()
    return None


def _parse_online(props: dict[str, Any]) -> bool:
    """Checks online/download availability from STAC item properties."""
    raw = props.get("Online") if "Online" in props else props.get("online")
    if raw is None:
        raw = props.get("is_online", props.get("download_available"))
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return raw == 1
    if isinstance(raw, str):
        return raw.strip().upper() in ("Y", "YES", "TRUE", "1", "ONLINE")
    return False


def _sanitize_assets(assets: dict[str, Any]) -> dict[str, Any]:
    """Sanitizes STAC assets dictionary ensuring no auth tokens or secrets are exposed."""
    if not isinstance(assets, dict):
        return {}
    clean: dict[str, Any] = {}
    for k, v in assets.items():
        if isinstance(v, dict):
            asset_info = dict(v)
            href = asset_info.get("href")
            if isinstance(href, str) and "?" in href:
                # Strip sensitive query parameters like ?token= or ?access_token=
                sanitized_href = re.sub(r"([?&](?:token|access_token|key|secret)=)[^&]+", r"\1[REDACTED]", href)
                asset_info["href"] = sanitized_href
            clean[k] = asset_info
    return clean


def _has_radar_data_asset(assets: dict[str, Any]) -> bool:
    """Checks whether assets include actual downloadable radar data (HDF5, GeoTIFF, etc.)."""
    if not isinstance(assets, dict) or not assets:
        return False
    data_keys = {"data", "hdf5", "h5", "product", "download", "geotiff", "tiff", "raster"}
    for key, val in assets.items():
        k_lower = key.lower()
        if k_lower in data_keys:
            return True
        if isinstance(val, dict):
            roles = val.get("roles") or []
            if "data" in roles:
                return True
            mime = (val.get("type") or "").lower()
            if any(t in mime for t in ["hdf", "h5", "geotiff", "tiff", "application/x-hdf"]):
                return True
            href = (val.get("href") or "").lower()
            if any(ext in href for ext in [".h5", ".hdf5", ".tif", ".tiff", ".zip", ".tar"]):
                return True
    return False


def _extract_download_url(assets: dict[str, Any], props: dict[str, Any]) -> str | None:
    """Extracts primary download URL from STAC assets or properties."""
    if isinstance(assets, dict):
        for key in ["data", "hdf5", "h5", "product", "download"]:
            if key in assets and isinstance(assets[key], dict):
                href = assets[key].get("href")
                if href and isinstance(href, str):
                    return href
        for val in assets.values():
            if isinstance(val, dict) and "data" in (val.get("roles") or []):
                href = val.get("href")
                if href and isinstance(href, str):
                    return href
    url_prop = props.get("url") or props.get("download_url") or props.get("downloadUrl")
    if isinstance(url_prop, str) and url_prop.strip():
        return url_prop.strip()
    return None


def qualify_and_normalize_product(item: dict[str, Any]) -> BhoonidhiProduct:
    """
    Normalizes a Bhoonidhi STAC item and strictly qualifies its scientific SAR suitability.
    Only genuine NISAR S-band GCOV products with valid geometries are qualified as DOWNLOADABLE_CANDIDATE.
    Ancillary files, weather products, quicklooks, and unreferenced items are rejected or flagged.
    """
    item_id = str(item.get("id") or "").strip()
    collection_id = str(item.get("collection") or "").strip()
    props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
    geometry = item.get("geometry")
    assets = item.get("assets") if isinstance(item.get("assets"), dict) else {}

    # 1. Footprint & Geometry Validation
    footprint = None
    has_valid_footprint = False
    if geometry and isinstance(geometry, dict):
        coords = geometry.get("coordinates")
        g_type = geometry.get("type")
        if coords and isinstance(coords, list) and len(coords) > 0:
            if g_type == "Polygon" and isinstance(coords[0], list) and len(coords[0]) >= 3:
                footprint = geometry
                has_valid_footprint = True
            elif g_type == "MultiPolygon" and isinstance(coords[0], list) and len(coords[0]) > 0:
                if isinstance(coords[0][0], list) and len(coords[0][0]) >= 3:
                    footprint = geometry
                    has_valid_footprint = True

    # Check for invalid metadata
    if not item_id or not collection_id:
        return BhoonidhiProduct(
            item_id=item_id or "UNKNOWN",
            collection_id=collection_id or "UNKNOWN",
            provider="ISRO / Bhoonidhi",
            platform="NISAR",
            sensor_band="S-band",
            qualification=BhoonidhiProductQualification.INVALID_METADATA,
            qualification_reason="Missing required item identifier or collection ID",
            footprint_geojson=None,
        )

    if not has_valid_footprint:
        return BhoonidhiProduct(
            item_id=item_id,
            collection_id=collection_id,
            provider="ISRO / Bhoonidhi",
            platform=props.get("platform") or "NISAR",
            sensor_band=props.get("sensor") or "S-band",
            product_type=props.get("product_type") or props.get("sar:product_type"),
            processing_level=props.get("processing:level") or props.get("processing_level"),
            acquisition_time=_parse_iso_datetime(props.get("datetime") or props.get("start_datetime")),
            polarization=_parse_polarization(props),
            orbit_direction=_parse_orbit_direction(props),
            look_direction=_parse_look_direction(props),
            is_online=_parse_online(props),
            download_url=_extract_download_url(assets, props),
            assets=_sanitize_assets(assets),
            qualification=BhoonidhiProductQualification.INVALID_METADATA,
            qualification_reason="Invalid or missing spatial footprint coordinates in STAC geometry",
            footprint_geojson=None,
        )

    # 2. Strict Collection & Instrument Qualification
    is_target_collection = collection_id.upper() == DEFAULT_COLLECTION

    title = str(props.get("title") or item_id).upper()
    prod_type_prop = str(
        props.get("product_type")
        or props.get("sar:product_type")
        or props.get("processing:level")
        or ""
    ).upper()

    # Reject ancillary records, soil-moisture grids, weather, browse, or unsupported InSAR levels
    is_ancillary = any(
        kw in title
        for kw in ["ECMWF", "SOIL", "WEATHER", "AUX", "THUMBNAIL", "QUICKLOOK", "BROWSE", "METADATA"]
    ) or any(
        unsupp in prod_type_prop
        for unsupp in ["SLC", "GUNW", "RIFG", "RSLC", "RAW", "INSAR"]
    )

    sensor_str = str(props.get("sensor") or props.get("sar:instrument_mode") or "S-band").upper()
    is_s_band = "S" in sensor_str or "SSAR" in collection_id.upper()

    if not is_target_collection or is_ancillary or not is_s_band:
        reasons: list[str] = []
        if not is_target_collection:
            reasons.append(f"Non-target collection '{collection_id}' (expected {DEFAULT_COLLECTION})")
        if is_ancillary:
            reasons.append("Ancillary non-backscatter or unsupported product type")
        if not is_s_band:
            reasons.append("Instrument frequency is not S-band")

        return BhoonidhiProduct(
            item_id=item_id,
            collection_id=collection_id,
            provider="ISRO / Bhoonidhi",
            platform=props.get("platform") or "NISAR",
            sensor_band="S-band",
            product_type=props.get("product_type") or "ANCILLARY",
            processing_level=props.get("processing:level") or props.get("processing_level"),
            acquisition_time=_parse_iso_datetime(props.get("datetime") or props.get("start_datetime")),
            polarization=_parse_polarization(props),
            orbit_direction=_parse_orbit_direction(props),
            look_direction=_parse_look_direction(props),
            footprint_geojson=footprint,
            is_online=_parse_online(props),
            download_url=_extract_download_url(assets, props),
            assets=_sanitize_assets(assets),
            qualification=BhoonidhiProductQualification.UNSUPPORTED_PRODUCT,
            qualification_reason="; ".join(reasons) or "Unsupported product",
        )

    # 3. Online Downloadability Qualification
    is_online = _parse_online(props)
    download_url = _extract_download_url(assets, props)
    has_data = _has_radar_data_asset(assets)

    if is_online and (download_url or has_data):
        qualification = BhoonidhiProductQualification.DOWNLOADABLE_CANDIDATE
        qualification_reason = "Verified NISAR S-band GCOV product with online downloadable data asset"
    else:
        qualification = BhoonidhiProductQualification.CATALOGUE_ONLY
        qualification_reason = "Product indexed in catalogue but offline or lacking direct download asset"

    return BhoonidhiProduct(
        item_id=item_id,
        collection_id=collection_id,
        provider="ISRO / Bhoonidhi",
        platform=props.get("platform") or "NISAR",
        sensor_band="S-band",
        product_type=props.get("product_type") or "GCOV",
        processing_level=props.get("processing:level") or "L2",
        acquisition_time=_parse_iso_datetime(props.get("datetime") or props.get("start_datetime")),
        polarization=_parse_polarization(props),
        orbit_direction=_parse_orbit_direction(props),
        look_direction=_parse_look_direction(props),
        footprint_geojson=footprint,
        is_online=is_online,
        download_url=download_url,
        assets=_sanitize_assets(assets),
        qualification=qualification,
        qualification_reason=qualification_reason,
    )


class BhoonidhiClient:
    """
    Client for ISRO's Bhoonidhi STAC and Auth APIs.
    Implements cached authentication, automatic token refresh, concurrency lock,
    and STAC search with CQL2-JSON online filtering.
    """

    def __init__(
        self,
        base_url: str | None = None,
        user_id: str | None = None,
        password: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("BHOONIDHI_BASE_URL", DEFAULT_BHOONIDHI_BASE_URL)).rstrip("/")
        self._user_id_override = user_id
        self._password_override = password
        self._http_client = http_client
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def user_id(self) -> str | None:
        raw = self._user_id_override or os.getenv("BHOONIDHI_USER_ID")
        return raw.strip() if raw and raw.strip() else None

    @property
    def password(self) -> str | None:
        raw = self._password_override or os.getenv("BHOONIDHI_PASSWORD")
        return raw.strip() if raw and raw.strip() else None

    def is_configured(self) -> bool:
        """Returns True if Bhoonidhi credentials are configured via environment variables or explicit parameters."""
        return bool(self.user_id and self.password)

    def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is not None:
            if isinstance(self._http_client, httpx.AsyncClient):
                if not self._http_client.is_closed:
                    return self._http_client
            else:
                return self._http_client
        return httpx.AsyncClient(timeout=DEFAULT_REQUEST_TIMEOUT)

    async def get_access_token(self) -> str | None:
        """
        Thread-safe token retrieval. Returns cached token, or refreshes/authenticates.
        Never logs or exposes tokens or credentials.
        """
        if not self.is_configured():
            return None

        async with self._lock:
            now = time.time()
            # If current access token is valid for more than 60 seconds, reuse it
            if self._access_token and (self._token_expires_at - now > 60):
                return self._access_token

            # Try refresh token flow if available
            if self._refresh_token:
                refreshed = await self._refresh_token_flow()
                if refreshed:
                    return self._access_token

            # Otherwise authenticate with username & password
            return await self._authenticate_flow()

    async def _authenticate_flow(self) -> str | None:
        """Authenticates against Bhoonidhi /auth/token using configured credentials."""
        user = self.user_id
        pwd = self.password
        if not user or not pwd:
            return None

        url = f"{self.base_url}/auth/token"
        payload = {
            "username": user,
            "password": pwd,
        }

        client = self._get_client()
        should_close = client is not self._http_client
        try:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            if resp.status_code == 200:
                data = resp.json()
                token = data.get("access_token") or data.get("token")
                refresh = data.get("refresh_token")
                expires_in = float(data.get("expires_in", 3600))
                if token:
                    self._access_token = str(token)
                    self._refresh_token = str(refresh) if refresh else None
                    self._token_expires_at = time.time() + expires_in
                    logger.info("Bhoonidhi token successfully obtained (expires in %.0fs)", expires_in)
                    return self._access_token
            elif resp.status_code == 401:
                logger.warning("Bhoonidhi authentication failed (HTTP 401: Invalid credentials)")
                raise PermissionError("Bhoonidhi authentication failed: Invalid credentials")
            elif resp.status_code == 429:
                logger.warning("Bhoonidhi authentication rate limited (HTTP 429)")
                raise RuntimeError("Bhoonidhi rate limit exceeded during authentication")
            else:
                logger.warning("Bhoonidhi authentication returned unexpected status %d", resp.status_code)
                raise RuntimeError(f"Bhoonidhi authentication error: HTTP {resp.status_code}")
        finally:
            if should_close:
                await client.aclose()

        return None

    async def _refresh_token_flow(self) -> bool:
        """Attempts to refresh expired access token using cached refresh token."""
        if not self._refresh_token:
            return False

        url = f"{self.base_url}/auth/token"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }

        client = self._get_client()
        should_close = client is not self._http_client
        try:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            if resp.status_code == 200:
                data = resp.json()
                token = data.get("access_token") or data.get("token")
                refresh = data.get("refresh_token")
                expires_in = float(data.get("expires_in", 3600))
                if token:
                    self._access_token = str(token)
                    if refresh:
                        self._refresh_token = str(refresh)
                    self._token_expires_at = time.time() + expires_in
                    logger.info("Bhoonidhi token refreshed successfully")
                    return True
            else:
                logger.info("Bhoonidhi refresh token rejected (HTTP %d); will re-authenticate", resp.status_code)
                self._refresh_token = None
                return False
        except Exception as e:
            logger.info("Bhoonidhi refresh token attempt error (%s); will re-authenticate", type(e).__name__)
            self._refresh_token = None
            return False
        finally:
            if should_close:
                await client.aclose()

    async def search_products(self, req: BhoonidhiSearchRequest) -> BhoonidhiSearchResponse:
        """
        Executes AOI-based STAC search against Bhoonidhi /data/search.
        Applies CQL2-JSON 'Online = Y' filter, follows pagination, and qualifies all products.
        """
        collection = req.collection or DEFAULT_COLLECTION

        # 1. Check configuration
        if not self.is_configured():
            return BhoonidhiSearchResponse(
                provider_status=BhoonidhiProviderStatus.NOT_CONFIGURED,
                collection_searched=collection,
                total_count=0,
                products=[],
                has_more=False,
                message="Bhoonidhi provider is NOT_CONFIGURED. Set BHOONIDHI_USER_ID and BHOONIDHI_PASSWORD environment variables to enable ISRO S-band catalogue discovery.",
                warning="Catalogue credentials missing. Live NISAR S-band discovery is inactive.",
            )

        # 2. Extract and validate AOI GeoJSON geometry
        aoi_geojson: dict[str, Any] | None = None
        if req.geojson_polygon and isinstance(req.geojson_polygon, dict):
            aoi_geojson = req.geojson_polygon
        elif req.wkt_polygon and isinstance(req.wkt_polygon, str) and req.wkt_polygon.strip():
            try:
                geom = shapely_wkt.loads(req.wkt_polygon)
                raw_map = shapely_mapping(geom)
                import json as py_json
                aoi_geojson = py_json.loads(py_json.dumps(raw_map))
            except Exception as e:
                return BhoonidhiSearchResponse(
                    provider_status=BhoonidhiProviderStatus.ERROR,
                    collection_searched=collection,
                    total_count=0,
                    products=[],
                    has_more=False,
                    message=f"Invalid WKT polygon provided for AOI: {e}",
                )

        if not aoi_geojson or not isinstance(aoi_geojson, dict):
            return BhoonidhiSearchResponse(
                provider_status=BhoonidhiProviderStatus.ERROR,
                collection_searched=collection,
                total_count=0,
                products=[],
                has_more=False,
                message="A valid AOI geometry (WKT or GeoJSON polygon) is required for Bhoonidhi spatial search.",
            )

        # 3. Obtain authentication token
        token: str | None = None
        try:
            token = await self.get_access_token()
        except PermissionError:
            return BhoonidhiSearchResponse(
                provider_status=BhoonidhiProviderStatus.AUTHENTICATION_FAILED,
                collection_searched=collection,
                total_count=0,
                products=[],
                has_more=False,
                message="Bhoonidhi authentication failed: Invalid BHOONIDHI_USER_ID or BHOONIDHI_PASSWORD.",
            )
        except RuntimeError as e:
            err_str = str(e)
            if "rate limit" in err_str.lower():
                return BhoonidhiSearchResponse(
                    provider_status=BhoonidhiProviderStatus.RATE_LIMITED,
                    collection_searched=collection,
                    total_count=0,
                    products=[],
                    has_more=False,
                    message="Bhoonidhi API rate limit exceeded during authentication.",
                )
            return BhoonidhiSearchResponse(
                provider_status=BhoonidhiProviderStatus.SERVICE_UNAVAILABLE,
                collection_searched=collection,
                total_count=0,
                products=[],
                has_more=False,
                message=f"Bhoonidhi authentication service unavailable: {err_str}",
            )
        except (httpx.TimeoutException, TimeoutError):
            return BhoonidhiSearchResponse(
                provider_status=BhoonidhiProviderStatus.SERVICE_UNAVAILABLE,
                collection_searched=collection,
                total_count=0,
                products=[],
                has_more=False,
                message="Connection to Bhoonidhi authentication endpoint timed out.",
            )
        except Exception as e:
            return BhoonidhiSearchResponse(
                provider_status=BhoonidhiProviderStatus.ERROR,
                collection_searched=collection,
                total_count=0,
                products=[],
                has_more=False,
                message=f"Bhoonidhi authentication error: {type(e).__name__}",
            )

        if not token:
            return BhoonidhiSearchResponse(
                provider_status=BhoonidhiProviderStatus.AUTHENTICATION_FAILED,
                collection_searched=collection,
                total_count=0,
                products=[],
                has_more=False,
                message="Bhoonidhi authentication failed to obtain valid access token.",
            )

        # 4. Build STAC Search Request
        limit = max(1, min(req.max_results, 500))
        search_body: dict[str, Any] = {
            "collections": [collection],
            "intersects": aoi_geojson,
            "limit": limit,
            "filter": {
                "op": "=",
                "args": [{"property": "Online"}, "Y"],
            },
            "filter-lang": "cql2-json",
        }

        # Date range handling (RFC 3339 interval)
        if req.start_date and req.end_date:
            search_body["datetime"] = f"{req.start_date}T00:00:00Z/{req.end_date}T23:59:59Z"
        elif req.start_date:
            search_body["datetime"] = f"{req.start_date}T00:00:00Z/.."
        elif req.end_date:
            search_body["datetime"] = f"../{req.end_date}T23:59:59Z"

        # 5. Execute STAC search with pagination & deduplication
        all_products: list[BhoonidhiProduct] = []
        seen_ids: set[str] = set()
        next_url: str | None = f"{self.base_url}/data/search"
        page = 0
        has_more = False

        client = self._get_client()
        should_close = client is not self._http_client

        try:
            while next_url and page < MAX_PAGES_LIMIT and len(all_products) < req.max_results:
                page += 1
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }

                if page == 1:
                    resp = await client.post(next_url, json=search_body, headers=headers)
                else:
                    # Pagination link GET or POST
                    resp = await client.get(next_url, headers=headers)

                if resp.status_code == 401:
                    # Try token refresh once
                    logger.info("Bhoonidhi token expired during search; refreshing...")
                    async with self._lock:
                        refreshed = await self._authenticate_flow()
                    if refreshed:
                        token = refreshed
                        headers["Authorization"] = f"Bearer {token}"
                        if page == 1:
                            resp = await client.post(next_url, json=search_body, headers=headers)
                        else:
                            resp = await client.get(next_url, headers=headers)
                    if resp.status_code == 401:
                        return BhoonidhiSearchResponse(
                            provider_status=BhoonidhiProviderStatus.AUTHENTICATION_FAILED,
                            collection_searched=collection,
                            total_count=len(all_products),
                            products=all_products,
                            has_more=False,
                            message="Bhoonidhi authentication expired or rejected during search.",
                        )

                if resp.status_code == 429:
                    return BhoonidhiSearchResponse(
                        provider_status=BhoonidhiProviderStatus.RATE_LIMITED,
                        collection_searched=collection,
                        total_count=len(all_products),
                        products=all_products,
                        has_more=False,
                        message="Bhoonidhi rate limit exceeded during catalogue search.",
                    )

                if resp.status_code in (500, 502, 503, 504):
                    return BhoonidhiSearchResponse(
                        provider_status=BhoonidhiProviderStatus.SERVICE_UNAVAILABLE,
                        collection_searched=collection,
                        total_count=len(all_products),
                        products=all_products,
                        has_more=False,
                        message=f"Bhoonidhi catalogue search service unavailable (HTTP {resp.status_code}).",
                    )

                if resp.status_code != 200:
                    return BhoonidhiSearchResponse(
                        provider_status=BhoonidhiProviderStatus.ERROR,
                        collection_searched=collection,
                        total_count=len(all_products),
                        products=all_products,
                        has_more=False,
                        message=f"Bhoonidhi search request failed with status {resp.status_code}.",
                    )

                data = resp.json()
                features = data.get("features") or []

                for feat in features:
                    if not isinstance(feat, dict):
                        continue
                    fid = str(feat.get("id") or "")
                    if fid and fid in seen_ids:
                        continue
                    if fid:
                        seen_ids.add(fid)

                    product = qualify_and_normalize_product(feat)
                    all_products.append(product)
                    if len(all_products) >= req.max_results:
                        break

                # Check for next page link
                links = data.get("links") or []
                next_link = next((l for l in links if isinstance(l, dict) and l.get("rel") == "next"), None)
                if next_link and next_link.get("href"):
                    next_url = next_link["href"]
                    has_more = True
                else:
                    next_url = None
                    has_more = False

        except (httpx.TimeoutException, TimeoutError):
            return BhoonidhiSearchResponse(
                provider_status=BhoonidhiProviderStatus.SERVICE_UNAVAILABLE,
                collection_searched=collection,
                total_count=len(all_products),
                products=all_products,
                has_more=False,
                message="Connection to Bhoonidhi STAC catalogue timed out.",
            )
        except Exception as e:
            return BhoonidhiSearchResponse(
                provider_status=BhoonidhiProviderStatus.ERROR,
                collection_searched=collection,
                total_count=len(all_products),
                products=all_products,
                has_more=False,
                message=f"Bhoonidhi search error: {type(e).__name__}",
            )
        finally:
            if should_close:
                await client.aclose()

        msg = None
        if len(all_products) == 0:
            msg = f"0 products found in Bhoonidhi collection '{collection}' for this AOI and temporal range."

        return BhoonidhiSearchResponse(
            provider_status=BhoonidhiProviderStatus.ONLINE,
            collection_searched=collection,
            total_count=len(all_products),
            products=all_products,
            has_more=has_more,
            message=msg,
        )


_global_bhoonidhi_client: BhoonidhiClient | None = None


def get_bhoonidhi_client() -> BhoonidhiClient:
    """Returns singleton BhoonidhiClient instance."""
    global _global_bhoonidhi_client
    if _global_bhoonidhi_client is None:
        _global_bhoonidhi_client = BhoonidhiClient()
    return _global_bhoonidhi_client
