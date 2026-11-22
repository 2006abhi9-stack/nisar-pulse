"""
Observation Pairing & Compatibility Engine
Normalizes observations from NASA ASF and ISRO Bhoonidhi into a common internal representation,
evaluates strict scientific radar compatibility rules, computes explainable rankings, and
automatically identifies optimal historical BEFORE and recent AFTER observation pairs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from shapely import wkt as shapely_wkt
from shapely.geometry import shape as shapely_shape

from bhoonidhi_client import BhoonidhiProduct, get_bhoonidhi_client
from schemas import (
    CommonObservation,
    GranuleResponse,
    ObservationPair,
    ObservationPairSearchRequest,
    ObservationPairSearchResponse,
)

logger = logging.getLogger("nisar_pulse.pairing")

# ESA declared Sentinel-1B mission ended following permanent anomaly on Dec 23, 2021
S1B_END_OF_MISSION = datetime(2021, 12, 23, 23, 59, 59, tzinfo=timezone.utc)


def normalize_asf_granule(item: GranuleResponse | dict[str, Any]) -> CommonObservation:
    """
    Normalizes a NASA ASF catalogue record into the CommonObservation format.
    Determines instrument, radar frequency band, and product type.
    """
    if isinstance(item, GranuleResponse):
        raw_id = item.id
        granule_name = item.granule_name
        platform_raw = item.platform
        processing_level = item.processing_level
        polarization = item.polarization
        acq_time = item.acquisition_time
        footprint = item.footprint_geojson
        download_url = item.download_url
        raw_dict = item.model_dump()
    else:
        raw_id = str(item.get("id") or item.get("fileID") or "")
        granule_name = str(item.get("granule_name") or item.get("fileID") or item.get("sceneName") or raw_id)
        platform_raw = str(item.get("platform") or "")
        processing_level = item.get("processing_level") or item.get("processingLevel")
        polarization = item.get("polarization")
        acq_time = item.get("acquisition_time")
        if isinstance(acq_time, str):
            try:
                acq_time = datetime.fromisoformat(acq_time.replace("Z", "+00:00"))
            except Exception:
                acq_time = None
        footprint = item.get("footprint_geojson")
        download_url = item.get("download_url") or item.get("url")
        raw_dict = dict(item)

    p_upper = platform_raw.upper()
    g_upper = granule_name.upper()

    # Determine instrument, platform, and frequency band (preserve exact S1 variant)
    is_s1b = "SENTINEL-1B" in p_upper or "S1B" in p_upper or g_upper.startswith("S1B_")
    if is_s1b:
        platform = "Sentinel-1B"
        instrument = "C-SAR"
        frequency_band = "C-band"
        collection_id = "SENTINEL-1"
    elif "SENTINEL-1A" in p_upper or "S1A" in p_upper or g_upper.startswith("S1A_"):
        platform = "Sentinel-1A"
        instrument = "C-SAR"
        frequency_band = "C-band"
        collection_id = "SENTINEL-1"
    elif "SENTINEL-1C" in p_upper or "S1C" in p_upper or g_upper.startswith("S1C_"):
        platform = "Sentinel-1C"
        instrument = "C-SAR"
        frequency_band = "C-band"
        collection_id = "SENTINEL-1"
    elif "SENTINEL-1D" in p_upper or "S1D" in p_upper or g_upper.startswith("S1D_"):
        platform = "Sentinel-1D"
        instrument = "C-SAR"
        frequency_band = "C-band"
        collection_id = "SENTINEL-1"
    elif "SENTINEL" in p_upper or "S1" in p_upper:
        platform = "Sentinel-1"
        instrument = "C-SAR"
        frequency_band = "C-band"
        collection_id = "SENTINEL-1"
    elif "NISAR" in p_upper:
        platform = "NISAR"
        instrument = "LSAR"  # NASA ASF hosts NISAR L-band SAR observations
        frequency_band = "L-band"
        collection_id = "NISAR"
    else:
        platform = platform_raw or "Unknown"
        instrument = "Unknown-SAR"
        frequency_band = "Unknown-band"
        collection_id = "UNKNOWN"

    # Determine product type
    prod_type = None
    level_str = str(processing_level or "").upper()
    if "GRD" in level_str or "_GRD" in g_upper or "GRD" in g_upper:
        prod_type = "GRD"
    elif "GCOV" in level_str or "_GCOV" in g_upper or "GCOV" in g_upper:
        prod_type = "GCOV"
    elif "GUNW" in level_str or "_GUNW" in g_upper or "GUNW" in g_upper:
        prod_type = "GUNW"
    elif "RSLC" in level_str or "_RSLC" in g_upper or "RSLC" in g_upper:
        prod_type = "RSLC"
    elif "SLC" in level_str or "_SLC" in g_upper or "SLC" in g_upper:
        prod_type = "SLC"
    elif level_str:
        prod_type = level_str

    # Qualification & Warnings
    warnings: list[str] = []
    qualification = "COMPATIBLE_CANDIDATE"

    # Check for ancillary records
    if any(k in g_upper for k in ["ECMWF", "SOIL", "WEATHER", "AUX", "THUMBNAIL"]):
        qualification = "UNSUPPORTED_PRODUCT"
        warnings.append("Ancillary non-radar observation record.")

    # Check for unsupported slant-range or InSAR products for 2D change detection
    if prod_type in ("SLC", "RSLC", "RAW", "RIFG", "L1"):
        qualification = "UNSUPPORTED_FOR_CHANGE_DETECTION"
        warnings.append(
            f"Level-1 {prod_type} products require geometric terrain correction and are unsupported for direct 2D backscatter comparison."
        )
    elif prod_type == "GUNW":
        qualification = "UNSUPPORTED_FOR_CHANGE_DETECTION"
        warnings.append(
            "GUNW (Geocoded Unwrapped Interferogram) products contain interferometric phase/coherence "
            "and cannot be used for radiometric backscatter change detection."
        )

    # Check for Sentinel-1B post-mission lifetime violation
    if is_s1b and acq_time:
        # Normalize timezone if naive
        check_time = acq_time if acq_time.tzinfo else acq_time.replace(tzinfo=timezone.utc)
        if check_time > S1B_END_OF_MISSION:
            qualification = "INVALID_METADATA"
            warnings.append(
                f"Impossible observation: Sentinel-1B operations ended on December 23, 2021; "
                f"acquisition dated {acq_time.strftime('%Y-%m-%d')} cannot be authentic satellite imagery."
            )

    # Check footprint
    if not footprint or not isinstance(footprint, dict) or not footprint.get("coordinates"):
        qualification = "INSUFFICIENT_METADATA"
        warnings.append("Missing or unverified spatial footprint geometry.")

    if not acq_time:
        warnings.append("Missing acquisition timestamp.")

    return CommonObservation(
        provider="NASA_ASF",
        original_id=granule_name,
        collection_id=collection_id,
        platform=platform,
        instrument=instrument,
        frequency_band=frequency_band,
        product_type=prod_type,
        processing_level=processing_level or ("L2" if prod_type in ("GCOV", "GUNW") else "L1"),
        polarization=polarization,
        acquisition_time=acq_time,
        orbit_direction=raw_dict.get("orbit_direction") or raw_dict.get("flightDirection"),
        track_or_orbit=str(raw_dict.get("pathNumber") or raw_dict.get("relativeOrbit") or "") or None,
        incidence_angle=None,
        footprint_geojson=footprint,
        is_online=True,
        download_url=download_url,
        qualification=qualification,
        warnings=warnings,
        raw_metadata=raw_dict,
    )


def normalize_bhoonidhi_product(item: BhoonidhiProduct | dict[str, Any]) -> CommonObservation:
    """
    Normalizes an ISRO Bhoonidhi STAC product into the CommonObservation format.
    Represents NISAR S-band (SSAR) observations.
    """
    if isinstance(item, BhoonidhiProduct):
        item_id = item.item_id
        collection_id = item.collection_id
        platform = item.platform
        product_type = item.product_type or "GCOV"
        processing_level = item.processing_level or "L2"
        polarization = item.polarization
        acq_time = item.acquisition_time
        footprint = item.footprint_geojson
        orbit_dir = item.orbit_direction
        is_online = item.is_online
        download_url = item.download_url
        orig_qualification = item.qualification
        qual_reason = item.qualification_reason
        raw_dict = item.model_dump()
    else:
        item_id = str(item.get("item_id") or item.get("id") or "")
        collection_id = str(item.get("collection_id") or item.get("collection") or "NISAR_SSAR_GCOV")
        platform = str(item.get("platform") or "NISAR")
        product_type = item.get("product_type") or "GCOV"
        processing_level = item.get("processing_level") or "L2"
        polarization = item.get("polarization")
        acq_time = item.get("acquisition_time")
        if isinstance(acq_time, str):
            try:
                acq_time = datetime.fromisoformat(acq_time.replace("Z", "+00:00"))
            except Exception:
                acq_time = None
        footprint = item.get("footprint_geojson") or item.get("geometry")
        orbit_dir = item.get("orbit_direction")
        is_online = bool(item.get("is_online", True))
        download_url = item.get("download_url")
        orig_qualification = item.get("qualification", "COMPATIBLE_CANDIDATE")
        qual_reason = item.get("qualification_reason", "")
        raw_dict = dict(item)

    warnings: list[str] = []
    qualification = orig_qualification

    if qualification == "DOWNLOADABLE_CANDIDATE":
        qualification = "COMPATIBLE_CANDIDATE"
    elif qualification == "CATALOGUE_ONLY":
        warnings.append("Catalogue-indexed record without direct online asset.")
    elif qualification in ("UNSUPPORTED_PRODUCT", "INVALID_METADATA"):
        warnings.append(qual_reason or "Disqualified during catalogue inspection.")

    return CommonObservation(
        provider="ISRO_BHOONIDHI",
        original_id=item_id,
        collection_id=collection_id,
        platform=platform,
        instrument="SSAR",  # ISRO S-band SAR instrument
        frequency_band="S-band",
        product_type=product_type,
        processing_level=processing_level,
        polarization=polarization,
        acquisition_time=acq_time,
        orbit_direction=orbit_dir,
        track_or_orbit=None,
        incidence_angle=None,
        footprint_geojson=footprint,
        is_online=is_online,
        download_url=download_url,
        qualification=qualification,
        warnings=warnings,
        raw_metadata=raw_dict,
    )


def _parse_polarization_channels(pol_str: str | None) -> set[str]:
    """Extracts constituent polarization channels (e.g. 'VV+VH' -> {'VV', 'VH'})."""
    if not pol_str:
        return set()
    cleaned = pol_str.replace("/", "+").replace(",", "+").replace(" ", "+")
    return {p.strip().upper() for p in cleaned.split("+") if p.strip()}


def evaluate_pair_compatibility(
    before: CommonObservation,
    after: CommonObservation,
    aoi_geom: Any | None = None,
) -> tuple[bool, str, list[str], list[str], list[str]]:
    """
    Evaluates hard radar compatibility rules between a BEFORE and AFTER observation.
    Returns: (is_compatible, status, compatibility_reasons, rejection_reasons, warnings)
    """
    compat_reasons: list[str] = []
    reject_reasons: list[str] = []
    warnings: list[str] = []

    # 1. Identity Check
    if before.original_id == after.original_id:
        reject_reasons.append("Identity check failed: Same observation selected for both BEFORE and AFTER.")

    # 2. Chronological Ordering
    if not before.acquisition_time or not after.acquisition_time:
        reject_reasons.append("Missing acquisition timestamp: Cannot verify chronological BEFORE/AFTER sequence.")
    elif before.acquisition_time >= after.acquisition_time:
        reject_reasons.append(
            f"Chronological order violation: BEFORE acquisition ({before.acquisition_time.strftime('%Y-%m-%d %H:%M')}) "
            f"must strictly precede AFTER acquisition ({after.acquisition_time.strftime('%Y-%m-%d %H:%M')})."
        )
    else:
        compat_reasons.append(
            f"Valid temporal sequence: Baseline ({before.acquisition_time.strftime('%Y-%m-%d')}) "
            f"precedes Event ({after.acquisition_time.strftime('%Y-%m-%d')})."
        )

    # 2b. Sentinel-1B Mission Lifetime Verification
    for obs, label in [(before, "BEFORE"), (after, "AFTER")]:
        is_b = obs.platform == "Sentinel-1B" or obs.original_id.upper().startswith("S1B_")
        if is_b and obs.acquisition_time:
            c_time = obs.acquisition_time if obs.acquisition_time.tzinfo else obs.acquisition_time.replace(tzinfo=timezone.utc)
            if c_time > S1B_END_OF_MISSION:
                reject_reasons.append(
                    f"Impossible {label} observation: Sentinel-1B mission ended on December 23, 2021. "
                    f"Observation dated {obs.acquisition_time.strftime('%Y-%m-%d')} cannot be authentic satellite imagery."
                )

    # 3. Radar Frequency Band Match
    if before.frequency_band != after.frequency_band:
        reject_reasons.append(
            f"Radar frequency mismatch: Cannot compare {before.frequency_band} ({before.platform}) "
            f"with {after.frequency_band} ({after.platform}). Observations must operate in the exact same radar band."
        )
    else:
        compat_reasons.append(f"Matching radar frequency: {before.frequency_band}.")

    # 4. Radar Instrument Match
    if before.instrument != after.instrument:
        reject_reasons.append(
            f"Radar instrument mismatch: Cannot compare {before.instrument} with {after.instrument}. "
            f"Both observations must be acquired by the same radar instrument."
        )
    else:
        compat_reasons.append(f"Matching radar instrument: {before.instrument} ({before.platform}).")

    # 5. Product Family & Radiometric Backscatter Compatibility
    p1 = (before.product_type or "").upper()
    p2 = (after.product_type or "").upper()
    g1_u = before.original_id.upper()
    g2_u = after.original_id.upper()

    # Detect product family from identifier if unspecified
    if not p1:
        if "RSLC" in g1_u:
            p1 = "RSLC"
        elif "GUNW" in g1_u:
            p1 = "GUNW"
        elif "GCOV" in g1_u:
            p1 = "GCOV"
        elif "GRD" in g1_u:
            p1 = "GRD"
        elif "SLC" in g1_u:
            p1 = "SLC"

    if not p2:
        if "RSLC" in g2_u:
            p2 = "RSLC"
        elif "GUNW" in g2_u:
            p2 = "GUNW"
        elif "GCOV" in g2_u:
            p2 = "GCOV"
        elif "GRD" in g2_u:
            p2 = "GRD"
        elif "SLC" in g2_u:
            p2 = "SLC"

    unsupported_types = {"SLC", "RSLC", "RAW", "RIFG", "L1"}
    if p1 in unsupported_types or p2 in unsupported_types or "RSLC" in g1_u or "RSLC" in g2_u:
        bad_p = p1 if (p1 in unsupported_types or "RSLC" in g1_u) else p2
        reject_reasons.append(
            f"Unsupported product format '{bad_p}': Level-1 slant-range complex products (RSLC/SLC) require geometric terrain correction "
            "and are unsupported for direct 2D backscatter change detection."
        )

    if p1 == "GUNW" or p2 == "GUNW" or "GUNW" in g1_u or "GUNW" in g2_u:
        reject_reasons.append(
            "Unsupported product format 'GUNW': Geocoded Unwrapped Interferograms contain interferometric phase/coherence "
            "and cannot be used for radiometric backscatter change detection."
        )

    valid_families = {"GCOV", "GRD"}
    if not p1 or not p2:
        reject_reasons.append("Unidentified product format: Observations must have an identified radar backscatter product family.")
    elif p1 != p2:
        reject_reasons.append(
            f"Product family mismatch: Cannot compare '{p1}' with '{p2}'. "
            "Radiometric change detection requires matching product families (e.g. GCOV to GCOV, or GRD to GRD)."
        )
    elif p1 not in valid_families:
        reject_reasons.append(
            f"Product family '{p1}' is unsupported for radiometric backscatter change detection. "
            f"Supported families are {sorted(list(valid_families))}."
        )
    else:
        compat_reasons.append(f"Matching, supported backscatter product family: {p1}.")

    # 6. Ancillary Product Rejection
    g1_upper = before.original_id.upper()
    g2_upper = after.original_id.upper()
    ancillary_keywords = ["ECMWF", "SOIL", "WEATHER", "AUX", "THUMBNAIL"]
    if any(k in g1_upper for k in ancillary_keywords) or any(k in g2_upper for k in ancillary_keywords):
        reject_reasons.append("Ancillary product exclusion: Soil-moisture grids and auxiliary records cannot be paired for SAR change detection.")

    # 7. Polarization Channel Compatibility
    pols_before = _parse_polarization_channels(before.polarization)
    pols_after = _parse_polarization_channels(after.polarization)

    if pols_before and pols_after:
        common_pols = pols_before & pols_after
        if not common_pols:
            reject_reasons.append(
                f"Polarization channel mismatch: Cannot compare {before.polarization} with {after.polarization}. "
                "Observations share no common polarization channel."
            )
        else:
            compat_reasons.append(f"Compatible polarization: Shared channel(s) {sorted(list(common_pols))}.")
            if pols_before != pols_after:
                warnings.append(
                    f"Partial polarization match ({before.polarization} vs {after.polarization}). Common channel used for analysis."
                )
    else:
        warnings.append("Unspecified polarization channels; assuming standard co-polarized channel.")

    # 8. Spatial Footprint & AOI Coverage
    if not before.footprint_geojson or not after.footprint_geojson:
        reject_reasons.append("Invalid metadata: Missing spatial footprint coordinates in one or both observations.")
    elif aoi_geom is not None:
        try:
            b_shape = shapely_shape(before.footprint_geojson)
            a_shape = shapely_shape(after.footprint_geojson)

            if not b_shape.is_valid:
                b_shape = b_shape.buffer(0)
            if not a_shape.is_valid:
                a_shape = a_shape.buffer(0)

            b_inter = b_shape.intersection(aoi_geom).area
            a_inter = a_shape.intersection(aoi_geom).area

            if aoi_geom.area > 0:
                b_cov = (b_inter / aoi_geom.area) * 100.0
                a_cov = (a_inter / aoi_geom.area) * 100.0
                if b_cov < 5.0 or a_cov < 5.0:
                    reject_reasons.append(
                        f"Insufficient AOI spatial coverage: Before covers {b_cov:.1f}% and After covers {a_cov:.1f}% of the selected AOI."
                    )
                else:
                    compat_reasons.append(f"Sufficient AOI coverage: Before ({b_cov:.1f}%), After ({a_cov:.1f}%).")
        except Exception as e:
            reject_reasons.append(f"Spatial footprint geometric validation error: {e}")

    # 9. Orbit Direction (Soft Warning)
    if before.orbit_direction and after.orbit_direction:
        if before.orbit_direction.upper() != after.orbit_direction.upper():
            warnings.append(
                f"Opposing orbit directions ({before.orbit_direction} vs {after.orbit_direction}); "
                "topographic aspect and layover disparities may affect backscatter change."
            )
        else:
            compat_reasons.append(f"Matching orbit direction: {before.orbit_direction}.")
    else:
        warnings.append("Orbit direction unspecified for one or both observations.")

    # Determine Status
    if reject_reasons:
        is_compatible = False
        if any("Invalid metadata" in r or "Missing" in r for r in reject_reasons):
            status = "INSUFFICIENT_METADATA"
        elif any("Unsupported product" in r or "unsupported for direct 2D backscatter" in r or "interferometric" in r for r in reject_reasons):
            status = "UNSUPPORTED_FOR_CHANGE_DETECTION"
        elif any("Ancillary" in r for r in reject_reasons):
            status = "UNSUPPORTED_PRODUCT"
        else:
            status = "INCOMPATIBLE"
    else:
        is_compatible = True
        if not before.is_online or not after.is_online:
            status = "DOWNLOAD_REQUIRED"
            warnings.append("One or both observations are catalogue-only and require downloading/staging before analysis.")
        else:
            status = "COMPATIBLE_CANDIDATE"

    return is_compatible, status, compat_reasons, reject_reasons, warnings


def compute_pair_ranking(
    before: CommonObservation,
    after: CommonObservation,
    aoi_geom: Any | None = None,
) -> tuple[float, str, float, float]:
    """
    Computes explainable soft ranking score (0.0 to 1.0) and metrics for a compatible observation pair.
    Prefers:
    1. Maximum mutual AOI coverage (0.40 max)
    2. Exact polarization match (0.20 max)
    3. Matching orbit direction (0.20 max)
    4. Ideal temporal delta (12 to 45 days) and recent after-date (0.20 max)
    """
    aoi_coverage_pct = 100.0
    if aoi_geom is not None and before.footprint_geojson and after.footprint_geojson:
        try:
            b_shape = shapely_shape(before.footprint_geojson)
            a_shape = shapely_shape(after.footprint_geojson)
            if not b_shape.is_valid:
                b_shape = b_shape.buffer(0)
            if not a_shape.is_valid:
                a_shape = a_shape.buffer(0)
            mutual = b_shape.intersection(a_shape).intersection(aoi_geom).area
            if aoi_geom.area > 0:
                aoi_coverage_pct = min(100.0, max(0.0, (mutual / aoi_geom.area) * 100.0))
        except Exception:
            aoi_coverage_pct = 50.0

    # Temporal delta
    temporal_delta_days = 0.0
    if before.acquisition_time and after.acquisition_time:
        diff_sec = (after.acquisition_time - before.acquisition_time).total_seconds()
        temporal_delta_days = max(0.0, diff_sec / 86400.0)

    # 1. Spatial Coverage Score (weight: 0.40)
    spatial_score = (aoi_coverage_pct / 100.0) * 0.40

    # 2. Polarization Score (weight: 0.20)
    pol1 = before.polarization or ""
    pol2 = after.polarization or ""
    if pol1 and pol2 and pol1.upper() == pol2.upper():
        pol_score = 0.20
        pol_desc = f"Identical {pol1} polarization"
    elif pol1 and pol2 and (_parse_polarization_channels(pol1) & _parse_polarization_channels(pol2)):
        pol_score = 0.12
        pol_desc = f"Shared channels ({pol1} / {pol2})"
    else:
        pol_score = 0.08
        pol_desc = "Default polarization"

    # 3. Orbit Direction Score (weight: 0.20)
    orb1 = (before.orbit_direction or "").upper()
    orb2 = (after.orbit_direction or "").upper()
    if orb1 and orb2 and orb1 == orb2:
        orbit_score = 0.20
        orbit_desc = f"Matching {orb1} pass"
    elif orb1 and orb2:
        orbit_score = 0.05
        orbit_desc = f"Differing pass ({orb1} vs {orb2})"
    else:
        orbit_score = 0.10
        orbit_desc = "Unspecified orbit pass"

    # 4. Temporal Quality Score (weight: 0.20)
    # Sweet spot is 6 to 45 days separation
    if 6.0 <= temporal_delta_days <= 45.0:
        temporal_score = 0.20
        temp_desc = f"Ideal {temporal_delta_days:.0f}d temporal interval"
    elif 45.0 < temporal_delta_days <= 90.0:
        temporal_score = 0.15
        temp_desc = f"Acceptable {temporal_delta_days:.0f}d interval"
    elif 1.0 <= temporal_delta_days < 6.0:
        temporal_score = 0.10
        temp_desc = f"Short {temporal_delta_days:.1f}d interval"
    else:
        temporal_score = max(0.02, 0.20 - min(0.18, (abs(temporal_delta_days - 30.0) / 365.0) * 0.20))
        temp_desc = f"{temporal_delta_days:.0f}d interval"

    total_score = round(spatial_score + pol_score + orbit_score + temporal_score, 3)
    explanation = f"{aoi_coverage_pct:.1f}% AOI overlap; {pol_desc}; {orbit_desc}; {temp_desc}."

    return total_score, explanation, round(aoi_coverage_pct, 1), round(temporal_delta_days, 1)


class ObservationPairingService:
    """Service that orchestrates multi-catalogue search, normalization, and compatible pair ranking."""

    @staticmethod
    async def find_pairs(req: ObservationPairSearchRequest) -> ObservationPairSearchResponse:
        search_id = str(uuid.uuid4())
        warnings: list[str] = []

        # 1. Parse AOI geometry
        try:
            aoi_geom = shapely_wkt.loads(req.wkt_polygon)
        except Exception as e:
            return ObservationPairSearchResponse(
                search_id=search_id,
                total_observations_found=0,
                total_compatible_pairs=0,
                recommended_pair=None,
                alternative_pairs=[],
                status="ERROR",
                message=f"Invalid target AOI WKT polygon: {e}",
            )

        # 2. Discover candidate observations from providers
        candidates: list[CommonObservation] = []

        # Provider A: NASA ASF (Sentinel-1 and NISAR L-band)
        if req.provider_preference in ("ALL", "NASA_ASF"):
            datasets_to_search = []
            if req.dataset_preference in ("ALL", "SENTINEL-1"):
                datasets_to_search.append("SENTINEL-1")
            if req.dataset_preference in ("ALL", "NISAR"):
                datasets_to_search.append("NISAR")

            for ds in datasets_to_search:
                try:
                    import asf_search as asf

                    asf_opts: dict[str, Any] = {
                        "intersectsWith": req.wkt_polygon,
                        "maxResults": min(req.max_candidates, 50),
                    }
                    if ds == "NISAR":
                        asf_opts["dataset"] = "NISAR"
                    elif ds == "SENTINEL-1":
                        asf_opts["platform"] = asf.PLATFORM.SENTINEL1

                    if req.start_date:
                        asf_opts["start"] = f"{req.start_date}T00:00:00Z"
                    if req.end_date:
                        asf_opts["end"] = f"{req.end_date}T23:59:59Z"

                    results = asf.search(**asf_opts)
                    for item in results:
                        props = getattr(item, "properties", {})
                        geom = getattr(item, "geojson", lambda: None)() or {}
                        footprint = geom.get("geometry") if isinstance(geom, dict) else None
                        granule_name = props.get("fileID") or props.get("sceneName")
                        if not granule_name:
                            continue

                        # Basic GeoJSON validation
                        if footprint and isinstance(footprint, dict):
                            coords = footprint.get("coordinates")
                            if not coords or not isinstance(coords, list) or len(coords) == 0:
                                footprint = None

                        norm = normalize_asf_granule({
                            "fileID": granule_name,
                            "platform": props.get("platform") or ds,
                            "processingLevel": props.get("processingLevel"),
                            "polarization": props.get("polarization"),
                            "acquisition_time": props.get("startTime"),
                            "footprint_geojson": footprint,
                            "url": props.get("url"),
                        })
                        candidates.append(norm)
                except Exception as e:
                    logger.warning("NASA ASF search attempt notice for %s: %s", ds, e)
                    warnings.append(f"NASA ASF query ({ds}) returned notice: {str(e)[:120]}")

        # Provider B: ISRO Bhoonidhi (NISAR S-band)
        if req.provider_preference in ("ALL", "ISRO_BHOONIDHI") and req.dataset_preference in ("ALL", "NISAR"):
            try:
                bhoonidhi = get_bhoonidhi_client()
                if bhoonidhi.is_configured():
                    from schemas import BhoonidhiSearchRequest

                    b_req = BhoonidhiSearchRequest(
                        wkt_polygon=req.wkt_polygon,
                        start_date=req.start_date,
                        end_date=req.end_date,
                        collection="NISAR_SSAR_GCOV",
                        max_results=req.max_candidates,
                    )
                    b_res = await bhoonidhi.search_products(b_req)
                    for prod in b_res.products:
                        candidates.append(normalize_bhoonidhi_product(prod))
                else:
                    warnings.append("ISRO Bhoonidhi provider credentials unconfigured; S-band catalogue not queried.")
            except Exception as e:
                logger.warning("Bhoonidhi search notice: %s", e)
                warnings.append(f"Bhoonidhi catalogue query notice: {str(e)[:120]}")

        total_found = len(candidates)
        if total_found == 0:
            return ObservationPairSearchResponse(
                search_id=search_id,
                total_observations_found=0,
                total_compatible_pairs=0,
                recommended_pair=None,
                alternative_pairs=[],
                status="NO_COMPATIBLE_PAIR",
                message="No satellite observations found covering the selected AOI and temporal range.",
                warnings=warnings,
            )

        # 3. Filter valid candidate observations
        valid_candidates = [
            c for c in candidates
            if c.acquisition_time is not None
            and c.footprint_geojson is not None
            and c.qualification in ("COMPATIBLE_CANDIDATE", "CATALOGUE_ONLY")
        ]

        # Group observations by radar family (frequency_band, instrument)
        family_groups: dict[tuple[str, str], list[CommonObservation]] = {}
        for c in valid_candidates:
            key = (c.frequency_band, c.instrument)
            family_groups.setdefault(key, []).append(c)

        # 4. Construct candidate pairs and evaluate compatibility
        compatible_pairs: list[ObservationPair] = []

        for (freq, inst), obs_list in family_groups.items():
            # Sort chronologically
            sorted_obs = sorted(obs_list, key=lambda x: x.acquisition_time or datetime.min)
            n = len(sorted_obs)
            if n < 2:
                continue

            for i in range(n):
                for j in range(i + 1, n):
                    before_obs = sorted_obs[i]
                    after_obs = sorted_obs[j]

                    is_compat, status, comp_reasons, rej_reasons, pair_warnings = evaluate_pair_compatibility(
                        before_obs, after_obs, aoi_geom
                    )

                    if is_compat:
                        score, explanation, aoi_cov, delta_days = compute_pair_ranking(before_obs, after_obs, aoi_geom)
                        pair_id = f"pair-{uuid.uuid4().hex[:12]}"
                        compatible_pairs.append(
                            ObservationPair(
                                pair_id=pair_id,
                                before_observation=before_obs,
                                after_observation=after_obs,
                                is_compatible=True,
                                status=status,
                                compatibility_reasons=comp_reasons,
                                rejection_reasons=[],
                                warnings=pair_warnings,
                                ranking_score=score,
                                ranking_explanation=explanation,
                                aoi_coverage_percent=aoi_cov,
                                temporal_delta_days=delta_days,
                            )
                        )

        total_compatible = len(compatible_pairs)
        if total_compatible == 0:
            return ObservationPairSearchResponse(
                search_id=search_id,
                total_observations_found=total_found,
                total_compatible_pairs=0,
                recommended_pair=None,
                alternative_pairs=[],
                status="NO_COMPATIBLE_PAIR",
                message=(
                    f"Found {total_found} observations, but 0 compatible BEFORE/AFTER pairs could be formed. "
                    "Observations may belong to differing sensor families, lack sufficient temporal separation, "
                    "or have incomplete AOI coverage."
                ),
                warnings=warnings,
            )

        # 5. Sort compatible pairs by ranking score descending
        ranked_pairs = sorted(compatible_pairs, key=lambda p: p.ranking_score, reverse=True)

        recommended = ranked_pairs[0]
        alternatives = ranked_pairs[1:10]

        return ObservationPairSearchResponse(
            search_id=search_id,
            total_observations_found=total_found,
            total_compatible_pairs=total_compatible,
            recommended_pair=recommended,
            alternative_pairs=alternatives,
            status="SUCCESS",
            message=f"Successfully identified {total_compatible} compatible observation pairs.",
            warnings=warnings,
        )
