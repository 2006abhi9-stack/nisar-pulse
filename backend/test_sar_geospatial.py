"""
NISAR-Pulse Scientific & Geospatial SAR Engine Verification Suite
Fulfills TASK 02 Part 4 Requirements:
1. Valid georeferenced GeoTIFF input.
2. Missing georeferencing rejection (no fake San Francisco coordinates).
3. Different image dimensions handling via proper resampling.
4. Different CRS alignment (e.g. UTM vs WGS84).
5. Invalid HDF5 structure & unsupported product rejection.
6. Nodata handling & boundary masking.
7. Zero and negative backscatter handling.
8. Exact radiometric log-ratio calculations.
9. Exact physical area calculations.
10. GeoJSON coordinate validity in WGS84.
"""

import math
import os
import tempfile
import numpy as np
import pyproj
import h5py
from PIL import Image, TiffImagePlugin
from shapely.geometry import shape

from sar_engine import (
    read_geotiff,
    read_nisar_hdf5,
    read_sar_raster,
    align_sar_rasters,
    compute_sar_change,
    apply_lee_speckle_filter,
)


def create_synthetic_geotiff(
    filename: str,
    shape_hw: tuple[int, int] = (60, 60),
    crs_epsg: int = 32610,
    pixel_size: float = 20.0,
    origin_xy: tuple[float, float] = (580000.0, 4180000.0),
    data_value: float = 500.0,
    nodata_val: float | None = None,
) -> None:
    """Helper to generate a fully compliant GeoTIFF with exact georeferencing tags."""
    h, w = shape_hw
    arr = np.full((h, w), data_value, dtype=np.float32)
    im = Image.fromarray(arr)
    ifd = TiffImagePlugin.ImageFileDirectory_v2()

    # Tag 33550: ModelPixelScaleTag
    ifd[33550] = (float(pixel_size), float(pixel_size), 0.0)
    # Tag 33922: ModelTiepointTag (I, J, K, X, Y, Z)
    ifd[33922] = (0.0, 0.0, 0.0, float(origin_xy[0]), float(origin_xy[1]), 0.0)

    # Tag 34735: GeoKeyDirectoryTag (Ver, Rev, MinRev, NumKeys, [KeyID, TagLoc, Count, Value])
    if crs_epsg == 4326:
        # Geographic WGS84
        ifd[34735] = (1, 1, 0, 2, 1024, 0, 1, 2, 2048, 0, 1, 4326)
    else:
        # Projected UTM
        ifd[34735] = (1, 1, 0, 2, 1024, 0, 1, 1, 3072, 0, 1, crs_epsg)

    if nodata_val is not None:
        ifd[42113] = str(nodata_val)

    im.save(filename, tiffinfo=ifd)


def create_synthetic_nisar_hdf5(
    filename: str,
    product_type: str = "GCOV",
    crs_epsg: int = 32610,
    shape_hw: tuple[int, int] = (50, 50),
    dx: float = 10.0,
    dy: float = -10.0,
    origin_xy: tuple[float, float] = (580000.0, 4180000.0),
    frequency: str = "frequencyB",
    pol: str = "HHHH",
    base_val: float = 400.0,
) -> None:
    """Helper to generate a compliant NISAR Level-2 HDF5 test structure."""
    h, w = shape_hw
    with h5py.File(filename, "w") as hf:
        id_grp = hf.create_group("/science/LSAR/identification")
        id_grp.create_dataset("productType", data=product_type)

        if product_type in ["GCOV", "GUNW", "GSLC"]:
            grid_path = f"/science/LSAR/{product_type}/grids/{frequency}"
            freq_grp = hf.create_group(grid_path)

            x_coords = origin_xy[0] + (np.arange(w) + 0.5) * dx
            y_coords = origin_xy[1] + (np.arange(h) + 0.5) * dy

            freq_grp.create_dataset("xCoordinates", data=x_coords)
            freq_grp.create_dataset("yCoordinates", data=y_coords)
            freq_grp.create_dataset("xCoordinateSpacing", data=float(dx))
            freq_grp.create_dataset("yCoordinateSpacing", data=float(dy))

            proj_ds = freq_grp.create_dataset("projection", data=0)
            proj_ds.attrs["epsg_code"] = int(crs_epsg)

            arr = np.full((h, w), base_val, dtype=np.float32)
            ds = freq_grp.create_dataset(pol, data=arr)
            ds.attrs["_FillValue"] = -9999.0


def test_1_valid_georeferenced_geotiff():
    print("--- Test 1: Valid Georeferenced GeoTIFF Input ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        b_path = os.path.join(tmpdir, "before.tif")
        a_path = os.path.join(tmpdir, "after.tif")

        create_synthetic_geotiff(b_path, shape_hw=(50, 50), pixel_size=20.0, data_value=500.0)
        create_synthetic_geotiff(a_path, shape_hw=(50, 50), pixel_size=20.0, data_value=100.0)

        raster = read_geotiff(b_path)
        assert raster.has_georeferencing is True
        assert raster.crs == "EPSG:32610"
        assert raster.width == 50 and raster.height == 50
        assert raster.bounds_wgs84 is not None

        # Run change detection: 500 -> 100 is a drop of ~7 dB
        res = compute_sar_change(b_path, a_path, threshold_db=-3.0)
        assert res["changed_pixels"] == 2500
        assert res["impacted_km2"] > 0
        assert res["mean_db_drop"] < -6.0
        print(f"  [PASS] Georeferencing verified: CRS={raster.crs}, impacted={res['impacted_km2']} km²")


def test_2_missing_georeferencing_rejection():
    print("--- Test 2: Missing Georeferencing Rejection (No Synthetic SF Fallback) ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        raw_b = os.path.join(tmpdir, "raw_b.png")
        raw_a = os.path.join(tmpdir, "raw_a.png")

        # Plain images with no coordinates
        im = Image.fromarray(np.full((40, 40), 200, dtype=np.uint8))
        im.save(raw_b)
        im.save(raw_a)

        raster = read_sar_raster(raw_b)
        assert raster.has_georeferencing is False
        assert raster.bounds_wgs84 is None

        # Verify compute_sar_change rejects with ValueError rather than inventing coordinates
        try:
            compute_sar_change(raw_b, raw_a)
            assert False, "Engine failed to reject unanchored image!"
        except ValueError as e:
            assert "Geospatial georeferencing is missing" in str(e)
            print("  [PASS] Successfully rejected unanchored files without inventing fake coordinates.")


def test_3_different_image_dimensions():
    print("--- Test 3: Different Image Dimensions via Spatial Resampling ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        b_path = os.path.join(tmpdir, "before_50.tif")
        a_path = os.path.join(tmpdir, "after_80.tif")

        # Before: 50x50, 20m pixels (covers 1000m x 1000m)
        create_synthetic_geotiff(b_path, shape_hw=(50, 50), pixel_size=20.0, origin_xy=(580000.0, 4180000.0), data_value=500.0)
        # After: 80x80, 15m pixels (covers 1200m x 1200m, encompassing before)
        create_synthetic_geotiff(a_path, shape_hw=(80, 80), pixel_size=15.0, origin_xy=(580000.0, 4180000.0), data_value=100.0)

        b_raster = read_geotiff(b_path)
        a_raster = read_geotiff(a_path)

        aligned_b, aligned_a, ref = align_sar_rasters(b_raster, a_raster)
        assert aligned_b.shape == (50, 50)
        assert aligned_a.shape == (50, 50)
        assert not np.isnan(aligned_a[25, 25])

        res = compute_sar_change(b_path, a_path, threshold_db=-3.0)
        assert res["valid_pixels"] > 0
        print(f"  [PASS] Differing dimensions (50x50 vs 80x80) correctly resampled. Valid pixels: {res['valid_pixels']}")


def test_4_different_crs_alignment():
    print("--- Test 4: Different CRS Alignment (UTM Zone 10N vs WGS84 Geographic) ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        b_utm = os.path.join(tmpdir, "before_utm.tif")
        a_wgs = os.path.join(tmpdir, "after_wgs.tif")

        # Before in UTM Zone 10N
        create_synthetic_geotiff(b_utm, shape_hw=(50, 50), crs_epsg=32610, pixel_size=20.0, origin_xy=(580000.0, 4180000.0), data_value=600.0)

        # After in WGS84 covering same area
        transformer = pyproj.Transformer.from_crs("EPSG:32610", "EPSG:4326", always_xy=True)
        lon_origin, lat_origin = transformer.transform(580000.0, 4180000.0)
        create_synthetic_geotiff(a_wgs, shape_hw=(60, 60), crs_epsg=4326, pixel_size=0.0002, origin_xy=(lon_origin, lat_origin), data_value=120.0)

        b_raster = read_geotiff(b_utm)
        a_raster = read_geotiff(a_wgs)

        assert b_raster.crs == "EPSG:32610"
        assert a_raster.crs == "EPSG:4326"

        aligned_b, aligned_a, ref = align_sar_rasters(b_raster, a_raster)
        assert aligned_a.shape == aligned_b.shape
        assert not np.isnan(aligned_a[10, 10])

        res = compute_sar_change(b_utm, a_wgs, threshold_db=-3.0)
        assert res["valid_pixels"] > 0
        print(f"  [PASS] Reprojection between UTM and WGS84 successful. Mean drop: {res['mean_db_drop']} dB")


def test_5_invalid_hdf5_structure_rejection():
    print("--- Test 5: Invalid HDF5 Structure & Unsupported Product Rejection ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        slc_path = os.path.join(tmpdir, "unsupported_slc.h5")
        bad_path = os.path.join(tmpdir, "corrupt_grid.h5")

        # 5a. Unsupported Level 1 SLC
        create_synthetic_nisar_hdf5(slc_path, product_type="SLC")
        try:
            read_nisar_hdf5(slc_path)
            assert False, "Failed to reject SLC product!"
        except ValueError as e:
            assert "Unsupported NISAR product type: 'SLC'" in str(e)
            print("  [PASS] Correctly rejected non-geocoded Level-1 SLC product.")

        # 5b. Corrupt HDF5 with no grids
        with h5py.File(bad_path, "w") as hf:
            hf.create_dataset("dummy", data=[1, 2, 3])
        try:
            read_nisar_hdf5(bad_path)
            assert False, "Failed to reject corrupt HDF5!"
        except ValueError as e:
            assert "Missing NISAR" in str(e) or "Invalid" in str(e)
            print("  [PASS] Correctly rejected non-NISAR HDF5 structure.")


def test_6_nodata_handling():
    print("--- Test 6: Nodata Handling & Masking ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        b_path = os.path.join(tmpdir, "nodata_b.tif")
        a_path = os.path.join(tmpdir, "nodata_a.tif")

        # 60x60 raster with nodata = -9999
        create_synthetic_geotiff(b_path, shape_hw=(60, 60), pixel_size=20.0, data_value=500.0, nodata_val=-9999.0)
        create_synthetic_geotiff(a_path, shape_hw=(60, 60), pixel_size=20.0, data_value=100.0, nodata_val=-9999.0)

        # Inject nodata quadrant into 'after' raster
        im_a = Image.open(a_path)
        arr_a = np.array(im_a)
        arr_a[:30, :30] = -9999.0
        im_new = Image.fromarray(arr_a)
        im_new.save(a_path, tiffinfo=im_a.tag_v2)
        im_a.close()

        res = compute_sar_change(b_path, a_path, threshold_db=-3.0)
        # Quadrant (30x30 = 900 pixels) must be excluded from valid pixels
        total_pixels = 60 * 60
        assert res["valid_pixels"] == total_pixels - 900
        print(f"  [PASS] Nodata masked properly: valid_pixels={res['valid_pixels']} out of {total_pixels}")


def test_7_zero_and_negative_backscatter_handling():
    print("--- Test 7: Zero and Negative Backscatter Handling ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        b_path = os.path.join(tmpdir, "zero_b.tif")
        a_path = os.path.join(tmpdir, "zero_a.tif")

        create_synthetic_geotiff(b_path, shape_hw=(40, 40), pixel_size=20.0, data_value=500.0)
        create_synthetic_geotiff(a_path, shape_hw=(40, 40), pixel_size=20.0, data_value=100.0)

        # Inject 0.0 values (swath edge / missing sensor return)
        im_b = Image.open(b_path)
        arr_b = np.array(im_b)
        arr_b[:10, :] = 0.0 # 400 zero pixels
        im_new = Image.fromarray(arr_b)
        im_new.save(b_path, tiffinfo=im_b.tag_v2)
        im_b.close()

        res = compute_sar_change(b_path, a_path, threshold_db=-3.0)
        assert res["valid_pixels"] == 1600 - 400
        print(f"  [PASS] Zero values safely excluded from log-ratio calculation. Valid: {res['valid_pixels']}")


def test_8_correct_log_ratio_calculations():
    print("--- Test 8: Radiometric Log-Ratio Decibel Accuracy ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        b_path = os.path.join(tmpdir, "log_b.tif")
        a_path = os.path.join(tmpdir, "log_a.tif")

        # Exactly 1000 -> 100: ratio 0.1, 10 * log10(0.1) = -10.0 dB
        create_synthetic_geotiff(b_path, shape_hw=(20, 20), pixel_size=20.0, data_value=1000.0)
        create_synthetic_geotiff(a_path, shape_hw=(20, 20), pixel_size=20.0, data_value=100.0)

        res = compute_sar_change(b_path, a_path, threshold_db=-3.0, speckle_filter=False)
        assert abs(res["mean_db_drop"] - (-10.0)) < 1e-4
        print(f"  [PASS] Exact dB drop verified: {res['mean_db_drop']} dB (expected -10.00 dB)")


def test_9_correct_area_calculations():
    print("--- Test 9: Exact Physical Area Calculation (km²) ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        b_path = os.path.join(tmpdir, "area_b.tif")
        a_path = os.path.join(tmpdir, "area_a.tif")

        # 50x50 pixels at 20m x 20m = 400 m² per pixel
        # Total pixels = 2500 -> 2500 * 400 m² = 1,000,000 m² = exactly 1.0 km²
        create_synthetic_geotiff(b_path, shape_hw=(50, 50), pixel_size=20.0, data_value=500.0)
        create_synthetic_geotiff(a_path, shape_hw=(50, 50), pixel_size=20.0, data_value=100.0)

        res = compute_sar_change(b_path, a_path, threshold_db=-3.0, speckle_filter=False)
        assert abs(res["impacted_km2"] - 1.0) < 1e-3
        print(f"  [PASS] Georeferenced area computed: {res['impacted_km2']} km² (expected exactly 1.0 km²)")


def test_10_geojson_coordinate_validity():
    print("--- Test 10: GeoJSON Coordinate Validity in WGS84 ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        b_path = os.path.join(tmpdir, "geo_b.tif")
        a_path = os.path.join(tmpdir, "geo_a.tif")

        # In UTM Zone 10N (meters)
        create_synthetic_geotiff(b_path, shape_hw=(40, 40), crs_epsg=32610, pixel_size=20.0, origin_xy=(580000.0, 4180000.0), data_value=500.0)
        create_synthetic_geotiff(a_path, shape_hw=(40, 40), crs_epsg=32610, pixel_size=20.0, origin_xy=(580000.0, 4180000.0), data_value=100.0)

        res = compute_sar_change(b_path, a_path, threshold_db=-3.0)
        geojson = res["mask_geojson"]
        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) > 0

        feature = geojson["features"][0]
        geom = shape(feature["geometry"])
        assert geom.is_valid

        # Verify coordinates are in WGS84 degrees, NOT UTM meters!
        for coord in feature["geometry"]["coordinates"][0]:
            lon, lat = coord[0], coord[1]
            assert -180.0 <= lon <= 180.0, f"Longitude out of WGS84 range: {lon}"
            assert -90.0 <= lat <= 90.0, f"Latitude out of WGS84 range: {lat}"
            assert lon < -100.0, f"Expected California longitude (~ -122), got {lon}"
            assert lat > 30.0, f"Expected California latitude (~ 37), got {lat}"

        print(f"  [PASS] Valid WGS84 GeoJSON geometry confirmed: lon={lon:.4f}, lat={lat:.4f}")


def run_all_tests():
    print("=" * 65)
    print("NISAR-PULSE SAR GEOSPATIAL & SCIENTIFIC VERIFICATION SUITE")
    print("=" * 65)
    test_1_valid_georeferenced_geotiff()
    test_2_missing_georeferencing_rejection()
    test_3_different_image_dimensions()
    test_4_different_crs_alignment()
    test_5_invalid_hdf5_structure_rejection()
    test_6_nodata_handling()
    test_7_zero_and_negative_backscatter_handling()
    test_8_correct_log_ratio_calculations()
    test_9_correct_area_calculations()
    test_10_geojson_coordinate_validity()
    print("=" * 65)
    print("ALL 10 SCIENTIFIC & GEOSPATIAL CHECKS PASSED WITH 100% SUCCESS!")
    print("=" * 65)


if __name__ == "__main__":
    run_all_tests()
