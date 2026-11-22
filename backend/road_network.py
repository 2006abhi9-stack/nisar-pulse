"""
Evidence-Based Road Network Impact Assessment & Field Verification Engine

Performs spatial impact assessment by intersecting real OpenStreetMap (OSM)
road geometries with SAR radiometric change polygons (mask_geojson) and provides
evidence-based topological route planning integrated with ground-truth verification.

Key Principles:
1. Ground Truth vs. Satellite Suspicion:
   - A satellite backscatter decrease is a proxy for surface condition change.
     It does NOT prove a road is blocked, damaged, or flooded.
   - SAR results NEVER automatically alter a road's ground-verification status.
   - Roads outside change polygons are NEVER labeled "safe".
2. Topological Graph Routing (NetworkX):
   - Routes are computed along actual OSM road network topology, never straight lines.
   - VERIFIED_BLOCKED roads are strictly excluded.
   - RESTRICTED roads are excluded unless explicitly permitted by the operator.
   - Conservative mode aggressively routes around unverified roads using verified-passable roads.
   - Exploratory mode includes unverified roads where necessary, highlighting every uncertain segment.
   - All routes are labeled "Candidate Route — Ground Verification Required", never "SAFE".
3. Metric AEQD Precision:
   - Distances in meters computed via Azimuthal Equidistant projection centered on the AOI.
"""

import logging
import math
import uuid
from typing import Any
import networkx as nx
import numpy as np
import pyproj
import requests
import shapely
from shapely.geometry import LineString, MultiLineString, Point, Polygon, mapping, shape
from shapely.ops import unary_union
from sar_engine import compute_sar_change

logger = logging.getLogger("nisar_pulse.road_network")


class OSMUnavailableError(Exception):
    """Raised when OpenStreetMap API is unreachable or returns an error."""
    pass


def fetch_osm_roads(
    bounds: list[list[float]],
    aoi_polygon: Polygon | None = None,
    timeout: int = 15,
) -> list[dict[str, Any]]:
    """
    Fetches real OpenStreetMap highway ways within the specified bounds.
    Preserves exact node IDs and coordinate dictionaries for graph construction.
    bounds format: [[south, west], [north, east]]
    """
    if not bounds or len(bounds) != 2:
        raise ValueError("Invalid bounds format. Expected [[south, west], [north, east]].")

    south = max(-85.0, min(85.0, float(bounds[0][0])))
    west = max(-180.0, min(180.0, float(bounds[0][1])))
    north = max(-85.0, min(85.0, float(bounds[1][0])))
    east = max(-180.0, min(180.0, float(bounds[1][1])))

    if south > north:
        south, north = north, south
    if west > east:
        west, east = east, west

    lat_span = north - south
    lon_span = east - west
    if lat_span * lon_span > 0.24:
        center_lat = (south + north) / 2.0
        center_lon = (west + east) / 2.0
        south = max(-85.0, center_lat - 0.22)
        north = min(85.0, center_lat + 0.22)
        west = max(-180.0, center_lon - 0.22)
        east = min(180.0, center_lon + 0.22)

    url = "https://api.openstreetmap.org/api/0.6/map.json"
    params = {"bbox": f"{west:.5f},{south:.5f},{east:.5f},{north:.5f}"}
    headers = {"User-Agent": "NISAR-Pulse/1.0 (disaster-intelligence-research; contact@nisar-pulse.org)"}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    except Exception as err:
        logger.error(f"Failed to connect to OpenStreetMap API: {err}")
        raise OSMUnavailableError(f"OpenStreetMap network request failed: {str(err)}") from err

    if resp.status_code != 200:
        logger.warning(f"OSM API returned HTTP {resp.status_code}: {resp.text[:200]}")
        raise OSMUnavailableError(f"OpenStreetMap API returned status {resp.status_code}.")

    try:
        data = resp.json()
    except Exception as err:
        raise OSMUnavailableError("Invalid JSON received from OpenStreetMap API.") from err

    elements = data.get("elements", [])
    nodes = {e["id"]: (float(e["lon"]), float(e["lat"])) for e in elements if e.get("type") == "node"}

    driveable_highways = {
        "motorway", "trunk", "primary", "secondary", "tertiary",
        "unclassified", "residential", "service",
        "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
        "living_street", "road",
    }

    roads = []
    for e in elements:
        if e.get("type") != "way":
            continue
        tags = e.get("tags", {})
        hwy = tags.get("highway")
        if not hwy or hwy not in driveable_highways:
            continue

        node_refs = e.get("nodes", [])
        valid_nodes = [nid for nid in node_refs if nid in nodes]
        coords = [nodes[nid] for nid in valid_nodes]
        if len(coords) < 2:
            continue

        try:
            geom = LineString(coords)
            if not geom.is_valid:
                geom = geom.buffer(0)
            if geom.is_empty:
                continue

            if aoi_polygon and not aoi_polygon.intersects(geom):
                continue

            roads.append({
                "osm_id": str(e["id"]),
                "name": tags.get("name") or tags.get("ref") or "Unnamed Road",
                "highway": hwy,
                "geometry": geom,
                "nodes": valid_nodes,
                "node_coords": {nid: nodes[nid] for nid in valid_nodes},
            })
        except Exception:
            continue

    return roads


def get_metric_projector(center_lon: float, center_lat: float):
    """
    Constructs an Azimuthal Equidistant metric projection centered on the AOI.
    This guarantees true geodesic distance measurement in meters anywhere on Earth.
    """
    proj_str = f"+proj=aeqd +lat_0={center_lat:.5f} +lon_0={center_lon:.5f} +datum=WGS84 +units=m"
    transformer = pyproj.Transformer.from_crs("EPSG:4326", proj_str, always_xy=True)

    def project_coords(coords: np.ndarray) -> np.ndarray:
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return project_coords


def assess_road_impacts(
    roads: list[dict[str, Any]],
    mask_geojson: dict[str, Any] | None,
    proximity_threshold_meters: float = 50.0,
    bounds: list[list[float]] | None = None,
    verifications: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Performs spatial impact assessment against actual SAR change-detection polygons
    and layers persistent ground-truth field verifications.
    """
    assessment_id = str(uuid.uuid4())

    change_geoms = []
    if mask_geojson and "features" in mask_geojson:
        for f in mask_geojson["features"]:
            geom_data = f.get("geometry")
            if not geom_data:
                continue
            try:
                g = shape(geom_data)
                if not g.is_valid:
                    g = g.buffer(0)
                if not g.is_empty:
                    change_geoms.append(g)
            except Exception:
                continue

    has_change = len(change_geoms) > 0
    change_union = unary_union(change_geoms) if has_change else None

    if change_union and not change_union.is_empty:
        center_lon, center_lat = change_union.centroid.x, change_union.centroid.y
    elif bounds and len(bounds) == 2:
        center_lat = (bounds[0][0] + bounds[1][0]) / 2.0
        center_lon = (bounds[0][1] + bounds[1][1]) / 2.0
    else:
        center_lon, center_lat = 0.0, 0.0

    project_to_meters = get_metric_projector(center_lon, center_lat)

    metric_change_union = None
    if change_union and not change_union.is_empty:
        try:
            metric_change_union = shapely.transform(change_union, project_to_meters)
        except Exception as err:
            logger.warning(f"Could not project change union to metric CRS: {err}")
            metric_change_union = None

    features = []
    impacted_count = 0
    nearby_count = 0
    no_intersection_count = 0
    unverified_count = 0

    verif_map = verifications or {}

    for r in roads:
        geom = r["geometry"]
        raw_osm_id = r["osm_id"]
        osm_id = str(raw_osm_id)
        name = r["name"]
        hwy = r["highway"]

        # 1. Retrieve persistent ground-truth verification
        verif_data = verif_map.get(osm_id) or verif_map.get(f"way/{osm_id}") or verif_map.get(osm_id.replace("way/", ""))
        if verif_data:
            field_status = verif_data.get("status", "UNVERIFIED")
            verified_by = verif_data.get("verified_by")
            verified_at = verif_data.get("created_at")
            verif_notes = verif_data.get("notes")
        else:
            field_status = "UNVERIFIED"
            verified_by = None
            verified_at = None
            verif_notes = None

        # 2. Evaluate SAR backscatter attenuation relationship
        if not geom or geom.is_empty:
            classification = "UNVERIFIED"
            dist_m = -1.0
            note = "Assessment unverified: empty or malformed geometry."
            unverified_count += 1
        elif mask_geojson is None:
            # When mask_geojson is None, no SAR analysis has run yet.
            # Road geometries are presented neutrally pending SAR change detection.
            classification = "UNVERIFIED"
            dist_m = -1.0
            note = "Road network retrieved from OpenStreetMap. Pending SAR change detection analysis."
            unverified_count += 1
        elif not has_change or metric_change_union is None or metric_change_union.is_empty:
            classification = "NO_DETECTED_INTERSECTION"
            dist_m = -1.0
            note = (
                "No spatial overlap: Zero backscatter change polygons detected in this observation. "
                "Does NOT confirm road is safe or passable."
            )
            no_intersection_count += 1
        else:
            try:
                if geom.intersects(change_union):
                    classification = "POTENTIALLY_AFFECTED"
                    dist_m = 0.0
                    note = (
                        "Road segment spatially intersects a detected backscatter reduction polygon. "
                        "Microwave attenuation may indicate surface inundation or structural change. "
                        "Field verification required before assuming blockage."
                    )
                    impacted_count += 1
                else:
                    metric_road = shapely.transform(geom, project_to_meters)
                    dist = float(metric_road.distance(metric_change_union))
                    dist_rounded = round(dist, 1)

                    if dist <= proximity_threshold_meters:
                        classification = "NEARBY_CHANGE_REGION"
                        dist_m = dist_rounded
                        note = (
                            f"Road segment lies within {dist_rounded}m (threshold: {proximity_threshold_meters}m) "
                            f"of a detected backscatter reduction polygon. Potential peripheral impact or access disruption."
                        )
                        nearby_count += 1
                    else:
                        classification = "NO_DETECTED_INTERSECTION"
                        dist_m = dist_rounded
                        note = (
                            f"No detected intersection with change polygons ({dist_rounded}m away). "
                            "Does NOT confirm road is safe or passable."
                        )
                        no_intersection_count += 1
            except Exception as e:
                logger.warning(f"Error evaluating road {osm_id}: {e}")
                classification = "UNVERIFIED"
                dist_m = -1.0
                note = f"Assessment unverified: error during geometric evaluation ({str(e)})."
                unverified_count += 1

        # Cache classifications directly on road object for routing engine
        r["sar_classification"] = classification
        r["field_status"] = field_status

        verif_at_str = (
            verified_at.isoformat()
            if hasattr(verified_at, "isoformat")
            else str(verified_at) if verified_at else None
        )

        features.append({
            "type": "Feature",
            "id": f"way/{osm_id}",
            "properties": {
                "osm_id": raw_osm_id,
                "name": name,
                "highway": hwy,
                "classification": classification,
                "sar_classification": classification,
                "field_status": field_status,
                "verified_by": verified_by,
                "verified_at": verif_at_str,
                "verification_notes": verif_notes,
                "distance_meters": dist_m,
                "assessment_note": note,
                "scientific_qualification": (
                    "Satellite backscatter decrease indicates microwave attenuation; "
                    "it does NOT prove physical blockage, structural damage, or water depth. "
                    "On-ground inspection required."
                ),
            },
            "geometry": mapping(geom),
        })

    if mask_geojson is None:
        status = "UNASSESSED_NEUTRAL"
        msg = "Road network retrieved from OpenStreetMap. Pending SAR change detection analysis."
    elif not has_change:
        status = "NO_CHANGE_DETECTED"
        msg = "SAR analysis returned zero change polygons for this scene. All roads recorded as No Detected Intersection."
    else:
        status = "COMPLETED"
        msg = None

    return {
        "assessment_id": assessment_id,
        "status": status,
        "proximity_threshold_meters": proximity_threshold_meters,
        "total_roads_assessed": len(roads),
        "impacted_count": impacted_count,
        "nearby_count": nearby_count,
        "no_intersection_count": no_intersection_count,
        "unverified_count": unverified_count,
        "road_geojson": {
            "type": "FeatureCollection",
            "features": features,
        },
        "message": msg,
        "scientific_qualification": (
            "Evidence-based assessment strictly bounded by satellite observations. "
            "A detected backscatter decrease does NOT prove a road is blocked or impassable. "
            "Roads without detected intersections must NOT be treated as confirmed safe."
        ),
    }


def calculate_candidate_route(
    roads: list[dict[str, Any]],
    start_lat: float,
    start_lon: float,
    dest_lat: float,
    dest_lon: float,
    routing_mode: str = "CONSERVATIVE",
    permit_restricted: bool = False,
    bounds: list[list[float]] | None = None,
    node_coords: dict[Any, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """
    Computes a topological candidate route along the OpenStreetMap network.
    
    Routing Rules:
    1. VERIFIED_BLOCKED roads are strictly excluded.
    2. RESTRICTED roads are excluded unless permit_restricted=True.
    3. VERIFIED_PASSABLE roads are given baseline cost priority.
    4. Conservative mode heavily penalizes UNVERIFIED roads (prefers verified-passable).
    5. Exploratory mode traverses UNVERIFIED roads when needed, with explicit warnings.
    6. Candidate route geometry follows actual road-network topology, never straight lines.
    """
    route_id = str(uuid.uuid4())
    norm_mode = routing_mode.upper().strip()

    if bounds and len(bounds) == 2:
        center_lat = (bounds[0][0] + bounds[1][0]) / 2.0
        center_lon = (bounds[0][1] + bounds[1][1]) / 2.0
    else:
        center_lat = (start_lat + dest_lat) / 2.0
        center_lon = (start_lon + dest_lon) / 2.0

    project_to_meters = get_metric_projector(center_lon, center_lat)

    G = nx.Graph()
    all_node_coords = {}

    for r in roads:
        field_status = r.get("field_status", "UNVERIFIED")
        sar_cls = r.get("sar_classification", "NO_DETECTED_INTERSECTION")
        osm_id = str(r["osm_id"])
        name = r.get("name", "Unnamed Road")
        hwy = r.get("highway", "road")

        # Rule 1: Exclude VERIFIED_BLOCKED
        if field_status == "VERIFIED_BLOCKED":
            continue

        # Rule 2: Exclude RESTRICTED unless permitted
        if field_status == "RESTRICTED" and not permit_restricted:
            continue

        # Rule 3: Strictly exclude UNVERIFIED roads in CONSERVATIVE mode
        if norm_mode == "CONSERVATIVE":
            if field_status != "VERIFIED_PASSABLE":
                if not (permit_restricted and field_status == "RESTRICTED"):
                    continue

        node_list = r.get("nodes", [])
        r_node_coords = r.get("node_coords") or node_coords or {}

        # If node dictionary not stored, extract from LineString coordinates
        if not node_list or not r_node_coords:
            geom = r.get("geometry")
            if isinstance(geom, LineString) and len(geom.coords) >= 2:
                node_list = [f"{osm_id}_{idx}" for idx in range(len(geom.coords))]
                r_node_coords = {f"{osm_id}_{idx}": (c[0], c[1]) for idx, c in enumerate(geom.coords)}

        all_node_coords.update(r_node_coords)

        for i in range(len(node_list) - 1):
            u = node_list[i]
            v = node_list[i + 1]
            p1 = r_node_coords.get(u)
            p2 = r_node_coords.get(v)
            if not p1 or not p2:
                continue

            try:
                m_p1 = project_to_meters(np.array([[p1[0], p1[1]]]))[0]
                m_p2 = project_to_meters(np.array([[p2[0], p2[1]]]))[0]
                seg_len = float(math.hypot(m_p2[0] - m_p1[0], m_p2[1] - m_p1[1]))
                if seg_len <= 0.1:
                    continue

                # Calculate routing weight
                if field_status == "VERIFIED_PASSABLE":
                    weight = seg_len * 1.0
                elif field_status == "RESTRICTED":
                    weight = seg_len * 3.0
                else:  # UNVERIFIED (only traversed in EXPLORATORY mode)
                    weight = seg_len * 1.5
                    if sar_cls == "POTENTIALLY_AFFECTED":
                        weight = seg_len * 5.0
                    elif sar_cls == "NEARBY_CHANGE_REGION":
                        weight = seg_len * 2.5

                G.add_edge(
                    u, v,
                    weight=weight,
                    length_meters=seg_len,
                    osm_id=osm_id,
                    name=name,
                    highway=hwy,
                    sar_classification=sar_cls,
                    field_status=field_status,
                    geometry=LineString([p1, p2]),
                )
            except Exception:
                continue

    if G.number_of_nodes() == 0:
        return {
            "route_id": route_id,
            "status": "NO_ROUTE_FOUND",
            "routing_mode": norm_mode,
            "total_distance_km": 0.0,
            "passable_segments_count": 0,
            "unverified_segments_count": 0,
            "restricted_segments_count": 0,
            "route_geojson": None,
            "warnings": [
                f"No traversable roads found in this region under current exclusions. "
                + ("In Conservative mode, unverified roads are strictly excluded." if norm_mode == "CONSERVATIVE" else "")
            ],
            "candidate_label": "Candidate Route — Ground Verification Required",
            "scientific_qualification": "No traversable road network available.",
            "message": (
                "All roads in this area are unverified, blocked, restricted, or outside network topology."
                if norm_mode == "CONSERVATIVE"
                else "All roads in this area are blocked, restricted, or outside network topology."
            ),
            "created_at": None,
        }

    # Snap start and destination to nearest network nodes
    m_start = project_to_meters(np.array([[start_lon, start_lat]]))[0]
    m_dest = project_to_meters(np.array([[dest_lon, dest_lat]]))[0]

    def find_nearest_node(target_m):
        best_node = None
        best_dist = float("inf")
        for nid in G.nodes():
            coord = all_node_coords.get(nid)
            if not coord:
                continue
            m_coord = project_to_meters(np.array([[coord[0], coord[1]]]))[0]
            d = math.hypot(m_coord[0] - target_m[0], m_coord[1] - target_m[1])
            if d < best_dist:
                best_dist = d
                best_node = nid
        return best_node, best_dist

    start_node, dist_to_start = find_nearest_node(m_start)
    dest_node, dist_to_dest = find_nearest_node(m_dest)

    # Maximum snapping tolerance: 5.0 km
    if not start_node or not dest_node or dist_to_start > 5000.0 or dist_to_dest > 5000.0:
        return {
            "route_id": route_id,
            "status": "NO_ROUTE_FOUND",
            "routing_mode": norm_mode,
            "total_distance_km": 0.0,
            "passable_segments_count": 0,
            "unverified_segments_count": 0,
            "restricted_segments_count": 0,
            "route_geojson": None,
            "warnings": ["Selected start or destination is too far from the analyzed road network."],
            "candidate_label": "Candidate Route — Ground Verification Required",
            "scientific_qualification": "Coordinates unlinked to road network.",
            "message": "Start or destination could not be connected to the accessible road network.",
            "created_at": None,
        }

    # Execute Dijkstra path search
    try:
        path = nx.shortest_path(G, source=start_node, target=dest_node, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return {
            "route_id": route_id,
            "status": "NO_ROUTE_FOUND",
            "routing_mode": norm_mode,
            "total_distance_km": 0.0,
            "passable_segments_count": 0,
            "unverified_segments_count": 0,
            "restricted_segments_count": 0,
            "route_geojson": None,
            "warnings": [
                f"No viable route found between coordinates using {norm_mode} routing rules. "
                + (
                    "In Conservative mode, unverified roads are strictly excluded. Ground-truth confirmation required."
                    if norm_mode == "CONSERVATIVE"
                    else "Connecting pathways may be verified-blocked or excluded."
                )
            ],
            "candidate_label": "Candidate Route — Ground Verification Required",
            "scientific_qualification": "Topological connection blocked, unverified, or unavailable.",
            "message": (
                f"No continuous accessible pathway found under {norm_mode} rules. "
                + ("Unverified roads are strictly excluded in Conservative mode." if norm_mode == "CONSERVATIVE" else "Pathways may be blocked.")
            ),
            "created_at": None,
        }

    # Reconstruct route geometry and segment statistics
    route_coords = []
    total_len_m = 0.0
    passable_count = 0
    unverified_count = 0
    restricted_count = 0
    has_potentially_affected = False
    has_nearby_change = False

    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        edge_data = G[u][v]
        total_len_m += edge_data.get("length_meters", 0.0)

        f_status = edge_data.get("field_status", "UNVERIFIED")
        s_cls = edge_data.get("sar_classification", "NO_DETECTED_INTERSECTION")

        if f_status == "VERIFIED_PASSABLE":
            passable_count += 1
        elif f_status == "RESTRICTED":
            restricted_count += 1
        else:
            unverified_count += 1

        if s_cls == "POTENTIALLY_AFFECTED":
            has_potentially_affected = True
        elif s_cls == "NEARBY_CHANGE_REGION":
            has_nearby_change = True

        p_u = all_node_coords[u]
        p_v = all_node_coords[v]
        if not route_coords:
            route_coords.append(p_u)
        route_coords.append(p_v)

    route_line = LineString(route_coords) if len(route_coords) >= 2 else None
    total_distance_km = round(total_len_m / 1000.0, 2)

    # Compile honest warnings
    warnings = [
        "Candidate Route — Ground Verification Required: This route is generated from satellite SAR and OpenStreetMap road topology. It has NOT been verified safe for travel."
    ]
    if unverified_count > 0:
        warnings.append(
            f"Route contains {unverified_count} unverified segment(s). Ground reconnaissance required before transit."
        )
    if has_potentially_affected:
        warnings.append(
            "WARNING: Route traverses road segment(s) with detected microwave backscatter attenuation. Possible flooding or structure compromise."
        )
    elif has_nearby_change:
        warnings.append(
            "CAUTION: Route passes within proximity buffer of detected change area. Potential peripheral damage or ponding."
        )
    if restricted_count > 0:
        warnings.append(
            f"Route traverses {restricted_count} restricted segment(s) permitted by operator."
        )

    geojson_feature = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(route_line) if route_line else None,
                "properties": {
                    "route_id": route_id,
                    "routing_mode": norm_mode,
                    "total_distance_km": total_distance_km,
                    "passable_segments": passable_count,
                    "unverified_segments": unverified_count,
                    "restricted_segments": restricted_count,
                    "candidate_label": "Candidate Route — Ground Verification Required",
                    "scientific_qualification": (
                        "Candidate route derived from topological graph search over OpenStreetMap. "
                        "A satellite change polygon does not prove a road is impassable, and lack of change does not guarantee safety. "
                        "Field verification required."
                    ),
                },
            }
        ],
    }

    return {
        "route_id": route_id,
        "status": "ROUTE_FOUND",
        "routing_mode": norm_mode,
        "total_distance_km": total_distance_km,
        "passable_segments_count": passable_count,
        "unverified_segments_count": unverified_count,
        "restricted_segments_count": restricted_count,
        "route_geojson": geojson_feature,
        "warnings": warnings,
        "candidate_label": "Candidate Route — Ground Verification Required",
        "scientific_qualification": (
            "Evidence-based routing strictly bounded by satellite observations and ground verification. "
            "Never describe any route as safe or guaranteed accessible."
        ),
        "message": f"Candidate route computed ({total_distance_km} km) following road topology.",
        "created_at": None,
    }


def generate_demo_roads(bounds: list[list[float]] | None = None) -> list[dict[str, Any]]:
    """
    Generates synthetic benchmark road geometries strictly isolated for DEMO MODE.
    Ensures operational mode never encounters or uses synthetic roads.
    Includes connected nodes and coordinates for routing verification.
    """
    if not bounds or len(bounds) != 2:
        bounds = [[37.70, -122.50], [37.80, -122.40]]

    south = float(bounds[0][0])
    west = float(bounds[0][1])
    north = float(bounds[1][0])
    east = float(bounds[1][1])

    mid_lat = (south + north) / 2.0
    mid_lon = (west + east) / 2.0
    lat_span = north - south
    lon_span = east - west

    # Coordinated positions relative to the simulated flood change region
    y_center = mid_lat
    # Road 2 is positioned ~24m south of the change polygon boundary (which is at north - lat_span * 0.64)
    y_nearby = round(north - lat_span * 0.64 - (24.0 / 111139.0), 6)
    # Road 3 is positioned far north, unimpacted
    y_distant = round(north - lat_span * 0.15, 6)
    # North-South relief corridor along eastern edge
    x_corridor = round(east - lon_span * 0.10, 6)
    x_west = round(west + lon_span * 0.10, 6)
    x_mid = round(mid_lon, 6)
    y_south_end = round(south + lat_span * 0.10, 6)
    y_north_end = round(north - lat_span * 0.05, 6)

    # 1. Floodway Crossing: passes directly through center of simulated flood change polygon
    r1_geom = LineString([(x_west, y_center), (x_mid, y_center), (x_corridor, y_center)])
    # 2. Levee Access Way: runs within 50m proximity buffer of change polygon (~24m away)
    r2_geom = LineString([(x_west, y_nearby), (x_mid, y_nearby), (x_corridor, y_nearby)])
    # 3. Ridge Parkway: well distant and outside change polygon (> 400m away)
    r3_geom = LineString([(x_west, y_distant), (x_mid, y_distant), (x_corridor, y_distant)])
    # 4. High Ground Relief Corridor: connects r2, r1, r3 along eastern corridor (provided with demo field verification)
    r4_geom = LineString([
        (x_corridor, y_south_end),
        (x_corridor, y_nearby),
        (x_corridor, y_center),
        (x_corridor, y_distant),
        (x_corridor, y_north_end),
    ])

    return [
        {
            "osm_id": "DEMO-990001",
            "name": "[DEMO MODE] Floodway Crossing",
            "highway": "primary",
            "geometry": r1_geom,
            "nodes": [101, 102, 103],
            "node_coords": {101: (x_west, y_center), 102: (x_mid, y_center), 103: (x_corridor, y_center)},
        },
        {
            "osm_id": "DEMO-990002",
            "name": "[DEMO MODE] Levee Access Way",
            "highway": "secondary",
            "geometry": r2_geom,
            "nodes": [104, 105, 106],
            "node_coords": {104: (x_west, y_nearby), 105: (x_mid, y_nearby), 106: (x_corridor, y_nearby)},
        },
        {
            "osm_id": "DEMO-990003",
            "name": "[DEMO MODE] Ridge Parkway",
            "highway": "residential",
            "geometry": r3_geom,
            "nodes": [107, 108, 109],
            "node_coords": {107: (x_west, y_distant), 108: (x_mid, y_distant), 109: (x_corridor, y_distant)},
        },
        {
            "osm_id": "DEMO-990004",
            "name": "[DEMO MODE] High Ground Relief Corridor",
            "highway": "primary",
            "geometry": r4_geom,
            "nodes": [110, 106, 103, 109, 111],
            "node_coords": {
                110: (x_corridor, y_south_end),
                106: (x_corridor, y_nearby),
                103: (x_corridor, y_center),
                109: (x_corridor, y_distant),
                111: (x_corridor, y_north_end),
            },
        },
    ]


def generate_demo_flood_scenario(
    proximity_threshold_meters: float = 50.0,
    threshold_db: float = -3.0,
) -> dict[str, Any]:
    """
    Creates a deterministic, fully georeferenced synthetic flood demonstration scenario:
    1. Generates synthetic before and after SAR GeoTIFF rasters with baseline backscatter
       and a simulated flood inundation decrease patch in EPSG:4326.
    2. Invokes the real compute_sar_change() algorithm from backend/sar_engine.py.
    3. Runs assess_road_impacts() against the demo road fixtures.
    4. Attaches a demonstration ground-truth field verification for the relief corridor.
    5. Returns compliant SAR and Road results with persistent DEMO labels.
    Does NOT persist any records to operational database tables.
    """
    import os
    import tempfile
    from PIL import Image, TiffImagePlugin

    bounds = [[37.70, -122.50], [37.80, -122.40]]
    td = tempfile.mkdtemp(prefix="nisar_demo_flood_")
    b_path = os.path.join(td, "demo_sar_before.tif")
    a_path = os.path.join(td, "demo_sar_after.tif")

    try:
        h, w = 100, 100
        pixel_size = 0.001
        origin_x, origin_y = -122.50, 37.80

        b_arr = np.full((h, w), 500.0, dtype=np.float32)
        a_arr = np.full((h, w), 500.0, dtype=np.float32)
        # Simulated flood inundation in central patch [35:65, 35:65]
        # Drop from 500.0 to 50.0 represents -10 dB attenuation
        a_arr[35:65, 35:65] = 50.0

        im_b = Image.fromarray(b_arr)
        ifd = TiffImagePlugin.ImageFileDirectory_v2()
        ifd[33550] = (pixel_size, pixel_size, 0.0)
        ifd[33922] = (0.0, 0.0, 0.0, origin_x, origin_y, 0.0)
        ifd[34735] = (1, 1, 0, 2, 1024, 0, 1, 2, 2048, 0, 1, 4326)
        im_b.save(b_path, tiffinfo=ifd)
        Image.fromarray(a_arr).save(a_path, tiffinfo=ifd)

        # Execute actual SAR change engine
        sar_res = compute_sar_change(b_path, a_path, threshold_db=threshold_db, speckle_filter=True)

        # Generate realistic SAR microwave raster overlay (water dark, dry terrain/roads bright)
        try:
            from pathlib import Path
            storage_dir = Path("storage/masks")
            storage_dir.mkdir(parents=True, exist_ok=True)
            raster_png_path = storage_dir / "demo_sar_raster.png"

            # Base terrain backscatter: realistic radar speckle (mean ~155, std ~18)
            np.random.seed(42)
            rh, rw = 400, 400
            speckle = np.random.normal(155, 18, (rh, rw)).clip(95, 215).astype(np.uint8)

            # Permanent water body (bay in northeast): dark microwave specular reflection (~25)
            perm_water = np.zeros((rh, rw), dtype=bool)
            for r in range(rh):
                for c in range(rw):
                    if c > 280 and r < 180:
                        if (c - 280) * 0.8 + (180 - r) * 0.5 > 40:
                            perm_water[r, c] = True

            # Flood inundation area (rows 140:260, cols 140:260)
            flood_patch = np.zeros((rh, rw), dtype=bool)
            flood_patch[140:260, 140:260] = True

            # Roads: bright microwave reflection
            roads_map = np.zeros((rh, rw), dtype=np.uint8)
            roads_map[198:202, 40:360] = 235  # Floodway Crossing
            roads_map[263:267, 40:360] = 225  # Levee Access Way
            roads_map[58:62, 40:360] = 225    # Ridge Parkway
            roads_map[35:380, 358:362] = 245  # High Ground Relief Corridor

            sar_gray = speckle.copy()
            sar_gray[perm_water] = 25  # Permanent water is dark
            sar_gray[roads_map > 0] = roads_map[roads_map > 0]  # Dry roads are bright
            sar_gray[flood_patch] = 28  # Flooded terrain is dark water

            rgba = np.zeros((rh, rw, 4), dtype=np.uint8)
            rgba[:, :, 0] = sar_gray
            rgba[:, :, 1] = sar_gray
            rgba[:, :, 2] = sar_gray
            rgba[:, :, 3] = 230  # Opaque inside AOI bounds

            # Luminous flood highlight tint over the dark flood water
            rgba[flood_patch, 0] = np.clip(sar_gray[flood_patch] * 0.3 + 224 * 0.7, 0, 255).astype(np.uint8)
            rgba[flood_patch, 1] = np.clip(sar_gray[flood_patch] * 0.3 + 109 * 0.7, 0, 255).astype(np.uint8)
            rgba[flood_patch, 2] = np.clip(sar_gray[flood_patch] * 0.3 + 83 * 0.7, 0, 255).astype(np.uint8)
            rgba[flood_patch, 3] = 240

            Image.fromarray(rgba, "RGBA").save(str(raster_png_path))
            sar_res["mask_image_url"] = "/masks/demo_sar_raster.png"
        except Exception as raster_err:
            logger.warning(f"Failed to generate demo SAR raster: {raster_err}")

        demo_roads = generate_demo_roads(bounds)

        demo_verifs = {
            "DEMO-990004": {
                "status": "VERIFIED_PASSABLE",
                "verified_by": "Demo Field Team Alpha",
                "notes": "High ground causeway clear. Spillway active.",
                "created_at": "2026-11-22T03:00:00Z",
            }
        }

        road_res = assess_road_impacts(
            roads=demo_roads,
            mask_geojson=sar_res["mask_geojson"],
            proximity_threshold_meters=proximity_threshold_meters,
            bounds=bounds,
            verifications=demo_verifs,
        )

        return {
            "sar_result": sar_res,
            "road_assessment": road_res,
            "demo_banner": "DEMO MODE — SYNTHETIC SATELLITE AND ROAD DATA",
            "simulated_label": "SIMULATED CHANGE — NOT REAL FLOOD OBSERVATION",
            "scientific_qualification": (
                "[DEMO MODE] Isolated synthetic demonstration dataset for interface and map verification. "
                "Not a real satellite observation, real flooding, or real operational road conditions."
            ),
        }
    finally:
        try:
            if os.path.exists(b_path):
                os.remove(b_path)
            if os.path.exists(a_path):
                os.remove(a_path)
            if os.path.exists(td):
                os.rmdir(td)
        except Exception as cleanup_err:
            logger.warning(f"Error cleaning up demo rasters: {cleanup_err}")
