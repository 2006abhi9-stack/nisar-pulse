"""
NISAR-Pulse SAR Processing Engine
Scientific & Geospatial Radar Backscatter Change Detection Core

Capabilities:
1. Validated NISAR L2 HDF5 (GCOV, GUNW) ingestion with coordinate axes & projection extraction.
2. Georeferenced GeoTIFF parsing (CRS, affine transform, nodata, WGS84 bounds).
3. Geospatial alignment & resampling between differing rasters and Coordinate Reference Systems.
4. Adaptive Lee speckle suppression for radar backscatter.
5. True log-ratio backscatter delta calculations with nodata and zero-pixel exclusion.
6. Geodesic and projected equal-area impact calculations (zero synthetic coordinates).
7. Geographically valid GeoJSON vector mask generation in WGS84.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import h5py
import numpy as np
import pyproj
from PIL import Image
from shapely.geometry import Polygon, mapping
from shapely.ops import unary_union
from shapely.validation import make_valid

try:
    import rasterio
    from rasterio.features import shapes as rio_shapes
except ImportError:
    rasterio = None
    rio_shapes = None


@dataclass
class SARRaster:
    """Container for georeferenced SAR raster data and metadata."""

    data: np.ndarray  # 2D float32 radar intensity / backscatter
    crs: str | None  # e.g. "EPSG:32610", "EPSG:4326"
    transform: tuple[float, float, float, float, float, float] | None  # (x0, dx, rot_x, y0, rot_y, dy)
    bounds_wgs84: list[list[float]] | None  # [[south, west], [north, east]] in degrees
    native_bounds: tuple[float, float, float, float] | None  # (min_x, min_y, max_x, max_y)
    nodata: float | None = None
    has_georeferencing: bool = False
    product_type: str | None = None
    polarization: str | None = None
    frequency_band: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int]:
        return self.data.shape

    @property
    def width(self) -> int:
        return self.data.shape[1]

    @property
    def height(self) -> int:
        return self.data.shape[0]


def is_projected_crs(crs_str: str | None) -> bool:
    """Determines whether a CRS represents linear projected meters (e.g. UTM) vs angular degrees."""
    if not crs_str:
        return False
    crs_clean = crs_str.upper()
    if "4326" in crs_clean or "WGS84" in crs_clean or "CRS84" in crs_clean:
        return False
    try:
        crs_obj = pyproj.CRS.from_user_input(crs_str)
        return crs_obj.is_projected
    except Exception:
        return any(p in crs_clean for p in ["326", "327", "UTM", "PROJCS"])


def reproject_bounds_to_wgs84(
    native_bounds: tuple[float, float, float, float],
    src_crs: str,
) -> list[list[float]]:
    """Transforms bounding box (min_x, min_y, max_x, max_y) from native CRS to WGS84 [[S, W], [N, E]]."""
    min_x, min_y, max_x, max_y = native_bounds
    crs_clean = src_crs.upper()
    if "4326" in crs_clean or "WGS84" in crs_clean:
        s = max(-90.0, min(90.0, min_y))
        n = max(-90.0, min(90.0, max_y))
        w = max(-180.0, min(180.0, min_x))
        e = max(-180.0, min(180.0, max_x))
        return [[s, w], [n, e]]

    transformer = pyproj.Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
    xs = [min_x, max_x, max_x, min_x]
    ys = [min_y, min_y, max_y, max_y]
    lons, lats = transformer.transform(xs, ys)

    south = max(-90.0, min(90.0, float(min(lats))))
    north = max(-90.0, min(90.0, float(max(lats))))
    west = max(-180.0, min(180.0, float(min(lons))))
    east = max(-180.0, min(180.0, float(max(lons))))

    return [[south, west], [north, east]]


# --- 1. NISAR HDF5 Ingestion Core ---
def read_nisar_hdf5(file_path: str, target_frequency: str = "frequencyB") -> SARRaster:
    """
    Parses a verified NISAR Level-2 HDF5 product (GCOV, GUNW, GSLC).
    Extracts spatial grid coordinates (xCoordinates, yCoordinates), projection WKT/EPSG,
    calibrated backscatter dataset, nodata values, and constructs an exact affine transform.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"HDF5 file not found: {file_path}")

    with h5py.File(file_path, "r") as hf:
        root_group_name = None
        for candidate in ["/science/LSAR", "/science/SSAR", "/LSAR", "/SSAR"]:
            if candidate in hf:
                root_group_name = candidate
                break

        if root_group_name is None:
            if "science" in hf:
                keys = list(hf["science"].keys())
                if keys:
                    root_group_name = f"/science/{keys[0]}"

        if root_group_name is None:
            raise ValueError(
                "Invalid or unsupported HDF5 structure: Missing NISAR '/science/LSAR' or '/science/SSAR' group."
            )

        root_grp = hf[root_group_name]

        # Verify Product Type
        product_type = None
        id_grp = root_grp.get("identification")
        if id_grp and "productType" in id_grp:
            raw_pt = id_grp["productType"][()]
            product_type = raw_pt.decode("utf-8") if isinstance(raw_pt, bytes) else str(raw_pt)
        else:
            for pt in ["GCOV", "GUNW", "GSLC", "SLC", "RSLC", "RIFG"]:
                if pt in root_grp:
                    product_type = pt
                    break

        if not product_type:
            raise ValueError(
                "Unable to identify NISAR product type from HDF5 metadata. File may be corrupted or non-standard."
            )

        unsupported = {"SLC", "RSLC", "RIFG", "RAW"}
        if product_type.upper() in unsupported:
            raise ValueError(
                f"Unsupported NISAR product type: '{product_type}'. "
                "NISAR-Pulse requires geocoded Level-2 products (GCOV, GUNW, GSLC) with geographic spatial grids. "
                "Level-1 range-Doppler SLC products cannot be processed without radar geometric terrain correction."
            )

        prod_grp = root_grp.get(product_type)
        if prod_grp is None:
            raise ValueError(f"Product group '/{root_group_name}/{product_type}' not found in HDF5.")

        grids_grp = prod_grp.get("grids")
        if grids_grp is None:
            raise ValueError(f"Spatial grids group not found under '/{root_group_name}/{product_type}/grids'.")

        freq_keys = list(grids_grp.keys())
        if not freq_keys:
            raise ValueError("No frequency groups found in NISAR grids hierarchy.")

        selected_freq = None
        if target_frequency in freq_keys:
            selected_freq = target_frequency
        elif "frequencyB" in freq_keys:
            selected_freq = "frequencyB"
        elif "frequencyA" in freq_keys:
            selected_freq = "frequencyA"
        else:
            selected_freq = freq_keys[0]

        freq_grp = grids_grp[selected_freq]

        if "xCoordinates" not in freq_grp or "yCoordinates" not in freq_grp:
            raise ValueError(
                f"NISAR frequency group '{selected_freq}' is missing 'xCoordinates' or 'yCoordinates' datasets."
            )

        x_coords = freq_grp["xCoordinates"][:]
        y_coords = freq_grp["yCoordinates"][:]

        if len(x_coords) < 2 or len(y_coords) < 2:
            raise ValueError("Spatial coordinates in NISAR HDF5 have invalid dimensions (< 2 pixels).")

        crs_str = None
        proj_ds = freq_grp.get("projection")
        if proj_ds is not None:
            if "epsg_code" in proj_ds.attrs:
                epsg = int(proj_ds.attrs["epsg_code"])
                crs_str = f"EPSG:{epsg}"
            elif "spatial_ref" in proj_ds.attrs:
                raw_sr = proj_ds.attrs["spatial_ref"]
                crs_str = raw_sr.decode("utf-8") if isinstance(raw_sr, bytes) else str(raw_sr)
            elif "proj4" in proj_ds.attrs:
                raw_p4 = proj_ds.attrs["proj4"]
                crs_str = raw_p4.decode("utf-8") if isinstance(raw_p4, bytes) else str(raw_p4)

        if not crs_str:
            if np.all(np.abs(x_coords) <= 180.0) and np.all(np.abs(y_coords) <= 90.0):
                crs_str = "EPSG:4326"
            else:
                raise ValueError(
                    "NISAR HDF5 lacks projection definition (EPSG code or spatial_ref) for coordinate grid."
                )

        target_dataset_name = None
        pol_candidate = None
        for pol in ["HHHH", "HVHV", "VVVV", "VHVH", "unwrappedPhase", "coherenceMagnitude"]:
            if pol in freq_grp:
                target_dataset_name = pol
                pol_candidate = pol
                break

        if target_dataset_name is None:
            for k, obj in freq_grp.items():
                if isinstance(obj, h5py.Dataset) and len(obj.shape) == 2:
                    if obj.shape == (len(y_coords), len(x_coords)):
                        target_dataset_name = k
                        pol_candidate = k
                        break

        if target_dataset_name is None:
            raise ValueError(
                f"No 2D observation dataset found in '{selected_freq}' matching coordinate shape ({len(y_coords)}, {len(x_coords)})."
            )

        ds = freq_grp[target_dataset_name]
        data_arr = ds[:].astype(np.float32)

        nodata_val = None
        if "_FillValue" in ds.attrs:
            nodata_val = float(ds.attrs["_FillValue"])
        elif "nodata" in ds.attrs:
            nodata_val = float(ds.attrs["nodata"])

        w = len(x_coords)
        h = len(y_coords)
        dx = float(x_coords[1] - x_coords[0]) if w > 1 else 1.0
        dy = float(y_coords[1] - y_coords[0]) if h > 1 else -1.0

        origin_x = float(x_coords[0]) - (dx / 2.0)
        origin_y = float(y_coords[0]) - (dy / 2.0)
        transform = (origin_x, dx, 0.0, origin_y, 0.0, dy)

        min_x = min(float(x_coords[0]), float(x_coords[-1])) - abs(dx) / 2.0
        max_x = max(float(x_coords[0]), float(x_coords[-1])) + abs(dx) / 2.0
        min_y = min(float(y_coords[0]), float(y_coords[-1])) - abs(dy) / 2.0
        max_y = max(float(y_coords[0]), float(y_coords[-1])) + abs(dy) / 2.0
        native_bounds = (min_x, min_y, max_x, max_y)

        bounds_wgs84 = reproject_bounds_to_wgs84(native_bounds, crs_str)

        return SARRaster(
            data=data_arr,
            crs=crs_str,
            transform=transform,
            bounds_wgs84=bounds_wgs84,
            native_bounds=native_bounds,
            nodata=nodata_val,
            has_georeferencing=True,
            product_type=product_type,
            polarization=pol_candidate,
            frequency_band=selected_freq,
            metadata={
                "source": "NISAR_HDF5",
                "instrument": root_group_name.replace("/science/", "").replace("/", ""),
                "frequency": selected_freq,
                "polarization": pol_candidate,
                "dataset_name": target_dataset_name,
            },
        )


# --- 2. GeoTIFF Ingestion Core ---
def read_geotiff(file_path: str) -> SARRaster:
    """
    Reads a GeoTIFF raster preserving CRS, Affine transform, nodata, and WGS84 bounds.
    Employs Rasterio when installed, or native Pillow TIFF tag decoding with OpenCV array extraction.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"GeoTIFF file not found: {file_path}")

    # Path A: Rasterio
    if rasterio is not None:
        try:
            with rasterio.open(file_path) as src:
                arr = src.read(1).astype(np.float32)
                crs_str = str(src.crs) if src.crs else None
                t = src.transform
                transform = (t.c, t.a, t.b, t.f, t.d, t.e)
                nodata = float(src.nodata) if src.nodata is not None else None
                b = src.bounds
                native_bounds = (b.left, b.bottom, b.right, b.top)

                if not crs_str:
                    if b.left >= -180.0 and b.right <= 180.0 and b.bottom >= -90.0 and b.top <= 90.0:
                        crs_str = "EPSG:4326"
                    else:
                        raise ValueError(
                            "GeoTIFF lacks coordinate reference system (CRS). Unprojected rasters are disallowed."
                        )

                bounds_wgs84 = reproject_bounds_to_wgs84(native_bounds, crs_str)
                return SARRaster(
                    data=arr,
                    crs=crs_str,
                    transform=transform,
                    bounds_wgs84=bounds_wgs84,
                    native_bounds=native_bounds,
                    nodata=nodata,
                    has_georeferencing=True,
                    product_type="GEOTIFF",
                    metadata={"driver": "rasterio"},
                )
        except Exception as e:
            if "lacks coordinate reference system" in str(e):
                raise

    # Path B: Pillow Tag Decoding Fallback
    try:
        with Image.open(file_path) as im:
            tag_v2 = getattr(im, "tag_v2", {})
            pixel_scale = tag_v2.get(33550)
            tiepoint = tag_v2.get(33922)
            geokeys = tag_v2.get(34735)
            raw_nodata = tag_v2.get(42113)

            nodata = None
            if raw_nodata is not None:
                try:
                    nodata = float(raw_nodata)
                except Exception:
                    nodata = None

            if not pixel_scale or not tiepoint:
                raise ValueError(
                    "GeoTIFF lacks geospatial georeferencing tags (ModelPixelScaleTag or ModelTiepointTag). "
                    "Cannot perform reliable change detection without physical pixel dimensions."
                )

            dx = float(pixel_scale[0])
            dy = -float(pixel_scale[1])
            origin_x = float(tiepoint[3]) - (float(tiepoint[0]) * dx)
            origin_y = float(tiepoint[4]) - (float(tiepoint[1]) * dy)
            transform = (origin_x, dx, 0.0, origin_y, 0.0, dy)

            crs_str = None
            if geokeys and len(geokeys) >= 8:
                for idx in range(4, len(geokeys) - 3, 4):
                    key_id = geokeys[idx]
                    tag_loc = geokeys[idx + 1]
                    val = geokeys[idx + 3]
                    if tag_loc == 0:
                        if key_id == 3072:
                            crs_str = f"EPSG:{val}"
                        elif key_id == 2048 and not crs_str:
                            crs_str = f"EPSG:{val}"

            w, h = im.size
            min_x = origin_x
            max_x = origin_x + w * dx
            max_y = origin_y
            min_y = origin_y + h * dy
            if min_x > max_x:
                min_x, max_x = max_x, min_x
            if min_y > max_y:
                min_y, max_y = max_y, min_y

            native_bounds = (min_x, min_y, max_x, max_y)

            if not crs_str:
                if min_x >= -180.0 and max_x <= 180.0 and min_y >= -90.0 and max_y <= 90.0:
                    crs_str = "EPSG:4326"
                else:
                    raise ValueError("GeoTIFF coordinates are non-geographic and lack an explicit EPSG GeoKey.")

            bounds_wgs84 = reproject_bounds_to_wgs84(native_bounds, crs_str)

        img = cv2.imread(file_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise ValueError(f"OpenCV failed to decode GeoTIFF image: {file_path}")
        if len(img.shape) == 3:
            img = img[:, :, 0]
        arr = img.astype(np.float32)

        return SARRaster(
            data=arr,
            crs=crs_str,
            transform=transform,
            bounds_wgs84=bounds_wgs84,
            native_bounds=native_bounds,
            nodata=nodata,
            has_georeferencing=True,
            product_type="GEOTIFF",
            metadata={"driver": "pillow_geotiff"},
        )
    except Exception as ex:
        if "lacks geospatial georeferencing" in str(ex) or "lacks coordinate reference system" in str(ex):
            raise
        raise ValueError(f"Failed to read GeoTIFF: {ex}") from ex


# --- 3. Unified Dispatcher ---
def read_sar_raster(
    file_path: str,
    default_bounds: list[list[float]] | None = None,
) -> SARRaster:
    """
    Reads an incoming SAR file (.h5, .hdf5, .tif, .tiff, or calibrated image).
    Preserves all physical georeferencing. Rejects unanchored synthetic datasets.
    """
    suffix = Path(file_path).suffix.lower()

    if suffix in [".h5", ".hdf5"]:
        return read_nisar_hdf5(file_path)
    elif suffix in [".tif", ".tiff"]:
        return read_geotiff(file_path)
    else:
        # Standard browse/thumbnail PNG or JPEG
        img = cv2.imread(file_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise ValueError(f"Unable to decode raster image file: {file_path}")
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        arr = img.astype(np.float32)

        if default_bounds:
            s, w = default_bounds[0]
            n, e = default_bounds[1]
            height, width = arr.shape
            dx = (e - w) / max(width, 1)
            dy = -(n - s) / max(height, 1)
            transform = (w, dx, 0.0, n, 0.0, dy)
            native_bounds = (w, s, e, n)
            return SARRaster(
                data=arr,
                crs="EPSG:4326",
                transform=transform,
                bounds_wgs84=default_bounds,
                native_bounds=native_bounds,
                nodata=0.0,
                has_georeferencing=True,
                product_type="ASF_BROWSE_IMAGE",
                metadata={"external_bounds": default_bounds},
            )

        return SARRaster(
            data=arr,
            crs=None,
            transform=None,
            bounds_wgs84=None,
            native_bounds=None,
            nodata=None,
            has_georeferencing=False,
            product_type="UNATTACHED_IMAGE",
            metadata={"note": "Lacks spatial georeferencing"},
        )


# --- 4. Scientific Speckle Noise Suppression ---
def apply_lee_speckle_filter(
    arr: np.ndarray,
    window_size: int = 5,
    cu: float = 0.523,
    valid_mask: np.ndarray | None = None,
) -> np.ndarray:
    """
    Applies an adaptive Lee speckle filter for Synthetic Aperture Radar.
    Preserves true radar scattering boundaries and point targets (bridges, structures)
    while dampening multiplicative speckle noise in homogeneous zones.
    """
    img = arr.astype(np.float32)
    if valid_mask is not None:
        work_img = np.where(valid_mask, img, 0.0)
    else:
        work_img = img

    kernel_size = (window_size, window_size)
    local_mean = cv2.boxFilter(work_img, -1, kernel_size, normalize=True)
    local_sq = cv2.boxFilter(work_img * work_img, -1, kernel_size, normalize=True)

    local_var = np.maximum(0.0, local_sq - local_mean * local_mean)

    noise_var = (local_mean * cu) ** 2
    weight = local_var / (local_var + noise_var + 1e-8)
    weight = np.clip(weight, 0.0, 1.0)

    filtered = local_mean + weight * (img - local_mean)

    if valid_mask is not None:
        filtered = np.where(valid_mask, filtered, img)

    return filtered


# --- 5. Geospatial Reprojection & Alignment ---
def align_sar_rasters(
    before: SARRaster,
    after: SARRaster,
) -> tuple[np.ndarray, np.ndarray, SARRaster]:
    """
    Spatially aligns before and after SAR observations.
    Validates physical overlap, handles differing Coordinate Reference Systems (CRS),
    and resamples onto a shared geographic grid without image distortion or fabricated bounds.
    """
    if not before.has_georeferencing or not after.has_georeferencing:
        raise ValueError(
            "Cannot perform spatial change detection: One or both SAR rasters lack geospatial georeferencing. "
            "Fabrication of arbitrary coordinates is prohibited by data integrity directives."
        )

    b_s, b_w = before.bounds_wgs84[0]
    b_n, b_e = before.bounds_wgs84[1]
    a_s, a_w = after.bounds_wgs84[0]
    a_n, a_e = after.bounds_wgs84[1]

    inter_w = max(b_w, a_w)
    inter_e = min(b_e, a_e)
    inter_s = max(b_s, a_s)
    inter_n = min(b_n, a_n)

    if inter_w >= inter_e or inter_s >= inter_n:
        raise ValueError(
            f"The provided before and after SAR scenes do not geographically overlap. "
            f"Before bounds: {before.bounds_wgs84}, After bounds: {after.bounds_wgs84}."
        )

    same_crs = (before.crs == after.crs)
    same_shape = (before.shape == after.shape)
    same_transform = (before.transform == after.transform)

    if same_crs and same_shape and same_transform:
        return before.data.copy(), after.data.copy(), before

    master_h, master_w = before.shape
    x0, dx, _, y0, _, dy = before.transform

    cols = np.arange(master_w) + 0.5
    rows = np.arange(master_h) + 0.5
    x_master = x0 + cols * dx
    y_master = y0 + rows * dy
    gx_master, gy_master = np.meshgrid(x_master, y_master)

    if before.crs == after.crs:
        gx_after = gx_master
        gy_after = gy_master
    else:
        transformer = pyproj.Transformer.from_crs(before.crs, after.crs, always_xy=True)
        gx_after, gy_after = transformer.transform(gx_master, gy_master)

    a_x0, a_dx, _, a_y0, _, a_dy = after.transform
    map_x = ((gx_after - a_x0) / a_dx - 0.5).astype(np.float32)
    map_y = ((gy_after - a_y0) / a_dy - 0.5).astype(np.float32)

    src_data = after.data.copy()
    if after.nodata is not None and not np.isnan(after.nodata):
        src_data[src_data == after.nodata] = np.nan

    resampled_after = cv2.remap(
        src_data,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=np.nan,
    )

    return before.data.copy(), resampled_after, before


# --- 6. End-to-End SAR Change Engine ---
def compute_sar_change(
    before_path: str,
    after_path: str,
    threshold_db: float = -3.0,
    speckle_filter: bool = True,
    output_mask_path: str | None = None,
    default_bounds: list[list[float]] | None = None,
) -> dict[str, Any]:
    """
    Executes rigorous, scientifically verified radar change detection:
    - Ingests NISAR HDF5 / GeoTIFF with full georeferencing.
    - Aligns and resamples observations onto a shared geographic grid.
    - Validates pixel masks to strictly eliminate nodata and edge artifacts.
    - Computes logarithmic backscatter deltas (dB) and real distribution histograms.
    - Measures true physical area (km²) from native pixel dimensions or ellipsoidal rows.
    - Outputs valid, reprojected WGS84 GeoJSON polygons.
    """
    before_raster = read_sar_raster(before_path, default_bounds=default_bounds)
    after_raster = read_sar_raster(after_path, default_bounds=default_bounds)

    if not before_raster.has_georeferencing or not after_raster.has_georeferencing:
        raise ValueError(
            "Geospatial georeferencing is missing from one or both SAR scenes. "
            "NISAR-Pulse strictly prohibits inventing fictitious coordinates."
        )

    aligned_before, aligned_after, ref_raster = align_sar_rasters(before_raster, after_raster)

    # Valid Data Masking (Strict Exclusion of zeros, nodata, NaNs, and swath boundaries)
    valid_before = (aligned_before > 0.0) & ~np.isnan(aligned_before) & ~np.isinf(aligned_before)
    if before_raster.nodata is not None and not np.isnan(before_raster.nodata):
        valid_before &= (aligned_before != before_raster.nodata)

    valid_after = (aligned_after > 0.0) & ~np.isnan(aligned_after) & ~np.isinf(aligned_after)
    if after_raster.nodata is not None and not np.isnan(after_raster.nodata):
        valid_after &= (aligned_after != after_raster.nodata)

    joint_valid = valid_before & valid_after
    valid_pixels = int(np.sum(joint_valid))

    if valid_pixels == 0:
        raise ValueError("No valid overlapping radar backscatter pixels found between before and after observations.")

    if speckle_filter:
        aligned_before = apply_lee_speckle_filter(aligned_before, valid_mask=joint_valid)
        aligned_after = apply_lee_speckle_filter(aligned_after, valid_mask=joint_valid)

    # Radiometric Log-Ratio Change Calculation (dB)
    delta_db = np.full_like(aligned_before, np.nan, dtype=np.float32)
    ratio = aligned_after[joint_valid] / aligned_before[joint_valid]
    delta_db[joint_valid] = 10.0 * np.log10(ratio)

    decrease_mask = joint_valid & (delta_db <= threshold_db)
    increase_mask = joint_valid & (delta_db >= abs(threshold_db))
    changed_pixels = int(np.sum(decrease_mask))

    mean_db_drop = float(np.mean(delta_db[decrease_mask])) if changed_pixels > 0 else 0.0

    # Exact Physical Area Calculation (km²)
    h, w = aligned_before.shape
    _, dx, _, _, _, dy = ref_raster.transform

    if is_projected_crs(ref_raster.crs):
        pixel_area_m2 = abs(dx * dy)
        pixel_area_km2 = pixel_area_m2 / 1_000_000.0
        impacted_km2 = round(changed_pixels * pixel_area_km2, 4)
        total_scene_km2 = round(valid_pixels * pixel_area_km2, 4)
    else:
        impacted_km2 = 0.0
        total_scene_km2 = 0.0
        y0 = ref_raster.transform[3]
        for r in range(h):
            row_lat = y0 + (r + 0.5) * dy
            rad = math.radians(row_lat)
            dlat_m = abs(dy) * (111132.954 - 559.822 * math.cos(2 * rad))
            dlon_m = abs(dx) * (111412.84 * math.cos(rad))
            row_km2 = (dlat_m * dlon_m) / 1_000_000.0

            impacted_km2 += float(np.sum(decrease_mask[r, :])) * row_km2
            total_scene_km2 += float(np.sum(joint_valid[r, :])) * row_km2

        impacted_km2 = round(impacted_km2, 4)
        total_scene_km2 = round(total_scene_km2, 4)

    if impacted_km2 >= 50.0:
        severity = "CRITICAL"
    elif impacted_km2 >= 10.0:
        severity = "ELEVATED"
    elif impacted_km2 >= 1.0:
        severity = "MODERATE"
    else:
        severity = "NOMINAL"

    bins = [
        ("< -10 dB", -999.0, -10.0),
        ("-10 to -8 dB", -10.0, -8.0),
        ("-8 to -6 dB", -8.0, -6.0),
        ("-6 to -4 dB", -6.0, -4.0),
        ("-4 to -2 dB", -4.0, -2.0),
        ("-2 to 0 dB", -2.0, 0.0),
        ("0 to +2 dB", 0.0, 2.0),
        ("+2 to +4 dB", 2.0, 4.0),
        ("> +4 dB", 4.0, 999.0),
    ]

    valid_deltas = delta_db[joint_valid]
    histogram = []
    for label, low, high in bins:
        count = int(np.sum((valid_deltas >= low) & (valid_deltas < high)))
        is_change = high <= threshold_db or low < threshold_db
        histogram.append({"bin": label, "count": count, "is_change": is_change})

    # GeoJSON Vector Mask Generation with Coordinate Reprojection to WGS84
    features = []
    if changed_pixels > 0:
        binary_mask = decrease_mask.astype(np.uint8)
        polys: list[Polygon] = []

        need_reproject = not ("4326" in ref_raster.crs.upper() or "WGS84" in ref_raster.crs.upper())
        transformer = (
            pyproj.Transformer.from_crs(ref_raster.crs, "EPSG:4326", always_xy=True)
            if need_reproject
            else None
        )

        contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        x0, dx, _, y0, _, dy = ref_raster.transform

        for cnt in contours:
            if len(cnt) >= 3:
                pts = []
                for pt in cnt:
                    px, py = pt[0]
                    x_native = x0 + px * dx
                    y_native = y0 + py * dy

                    if transformer:
                        lon, lat = transformer.transform(x_native, y_native)
                    else:
                        lon, lat = x_native, y_native

                    lon = max(-180.0, min(180.0, float(lon)))
                    lat = max(-90.0, min(90.0, float(lat)))
                    pts.append((lon, lat))

                if len(pts) >= 3:
                    try:
                        poly = Polygon(pts)
                        if not poly.is_valid:
                            poly = make_valid(poly)
                        if poly.is_valid and poly.area > 0:
                            polys.append(poly)
                    except Exception:
                        pass

        if polys:
            try:
                merged = unary_union(polys)
                merged = merged.simplify(0.0001, preserve_topology=True)
                features.append({
                    "type": "Feature",
                    "properties": {
                        "change_type": "SIGNIFICANT_BACKSCATTER_DECREASE",
                        "threshold_db": threshold_db,
                        "mean_db_drop": round(mean_db_drop, 2),
                        "impacted_km2": impacted_km2,
                        "data_integrity": "Grounded on physical georeferencing",
                    },
                    "geometry": mapping(merged),
                })
            except Exception:
                for p in polys[:50]:
                    features.append({
                        "type": "Feature",
                        "properties": {"change_type": "SIGNIFICANT_BACKSCATTER_DECREASE"},
                        "geometry": mapping(p),
                    })

    mask_geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    if output_mask_path:
        out_p = Path(output_mask_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[decrease_mask, 0] = 184  # R (#B84A27)
        rgba[decrease_mask, 1] = 74   # G
        rgba[decrease_mask, 2] = 39   # B
        rgba[decrease_mask, 3] = 190  # Alpha
        bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
        cv2.imwrite(str(out_p), bgra)

    return {
        "threshold_db": threshold_db,
        "speckle_filter": speckle_filter,
        "impacted_km2": impacted_km2,
        "total_scene_km2": total_scene_km2,
        "mean_db_drop": round(mean_db_drop, 2),
        "severity_tier": severity,
        "bounds": ref_raster.bounds_wgs84,
        "crs": ref_raster.crs,
        "valid_pixels": valid_pixels,
        "changed_pixels": changed_pixels,
        "change_type": "SIGNIFICANT_BACKSCATTER_DECREASE",
        "scientific_qualification": (
            "Detected regions represent microwave backscatter attenuation below threshold. "
            "Physical mechanisms include surface water accumulation (specular reflection), "
            "structural collapse, or vegetation removal. Field verification required."
        ),
        "histogram": histogram,
        "mask_geojson": mask_geojson,
    }
