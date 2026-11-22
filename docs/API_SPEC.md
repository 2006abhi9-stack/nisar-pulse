# Backend REST API Specification

## 1. System Base URL & Protocols
- Base Path: `http://localhost:8000/api`
- Content Type: `application/json` (except file uploads which use `multipart/form-data`)
- Static Asset Serving: `http://localhost:8000/masks/{filename}` maps directly to `/storage/masks/{filename}`.
- CORS Origin: Strict origin restriction to `http://localhost:5173` (Vite dev server) and `http://127.0.0.1:5173`.

---

## 2. Endpoints Catalog

### 2.1 Health & Diagnostics
#### `GET /api/health`
Checks backend process state, SQLite database connectivity, and presence of necessary environmental tokens.
- **Request:** None
- **Response `200 OK`:**
```json
{
  "status": "healthy",
  "database_connected": true,
  "earthdata_configured": true,
  "gemini_configured": true,
  "storage_writable": true,
  "timestamp": "2026-11-21T11:45:00Z"
}
```

---

### 2.2 Live NASA ASF Satellite Search
#### `POST /api/search/granules`
Executes real-time query against NASA Alaska Satellite Facility (ASF) archive using `asf_search.search()`.
- **Request Body:**
```json
{
  "wkt_polygon": "POLYGON((-122.5 37.7, -122.3 37.7, -122.3 37.9, -122.5 37.9, -122.5 37.7))",
  "dataset": "NISAR",
  "start_date": "2026-01-01T00:00:00Z",
  "end_date": "2026-03-01T23:59:59Z",
  "processing_level": "GCOV",
  "max_results": 25
}
```
- **Processing Logic:**
  1. Validates WKT geometry string.
  2. Queries ASF API. If platform is NISAR, prioritizes Frequency B datasets.
  3. Inserts search record into `aoi_searches`.
  4. Upserts each returned granule into `sar_granules`.
- **Response `200 OK`:**
```json
{
  "search_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "total_count": 8,
  "granules": [
    {
      "id": "e2c36c64-4632-4414-b8be-586b4ef84c71",
      "granule_name": "NISAR_L2_PR_GCOV_001_005_A_025_2005_SH_20260210T143000",
      "platform": "NISAR",
      "processing_level": "GCOV",
      "data_maturity": "PROVISIONAL",
      "polarization": "HH",
      "acquisition_time": "2026-02-10T14:30:00Z",
      "footprint_geojson": { "type": "Polygon", "coordinates": [...] },
      "download_url": "https://datapool.asf.alaska.edu/...",
      "browse_url": "https://datapool.asf.alaska.edu/browse/..."
    }
  ]
}
```
- **Response `200 OK` (Empty State):** When zero granules are found, returns `total_count: 0` and `granules: []` with an actionable empty state message.

---

### 2.3 SAR Change Detection Analysis (Local Upload)
#### `POST /api/analyze/upload`
Uploads local pre- and post-event SAR rasters (`.h5`, `.tif`, `.tiff`, `.png`), aligns them, computes log-ratio dB difference, filters speckle, and generates impact metrics.
- **Form Data Fields:**
  - `before_file`: File (Binary, `.h5` or `.tif` or `.png`, max 50 MB)
  - `after_file`: File (Binary, `.h5` or `.tif` or `.png`, max 50 MB)
  - `threshold_db`: Float (default: `-3.0`)
  - `speckle_filter`: Boolean (default: `true`)
  - `polarization`: String (optional, e.g. `'HH'`)
  - `bounds`: JSON String (optional, e.g. `'[[37.7, -122.5], [37.8, -122.4]]'`). Required if uploading unanchored rasters; unanchored rasters lacking bounds are strictly rejected with HTTP 400.
- **Processing Flow:**
  1. Validates file extensions and magic headers.
  2. Reads arrays and extracts geospatial metadata (`CRS`, affine transform, nodata) using `read_nisar_hdf5` (supporting Level 2 GCOV/GUNW) or `read_geotiff`. Rejects Level 1 SLC or unanchored rasters.
  3. Aligns spatial grids via `align_sar_rasters`: verifies physical overlap and resamples `after` onto `before` coordinate grid using `pyproj` geodetic reprojection and bilinear interpolation. Rejects non-overlapping scenes (no arbitrary resizing).
  4. Applies adaptive Lee speckle filter on valid pixel regions.
  5. Computes log-ratio: $\Delta \sigma^0_{\text{dB}} = 10 \cdot \log_{10}\left(\frac{\sigma^0_{\text{after}}}{\sigma^0_{\text{before}}}\right)$ with strict mask where $\sigma^0_{\text{before}} > 0$, $\sigma^0_{\text{after}} > 0$, and non-nodata.
  6. Thresholds pixels where $\Delta \text{dB} \le \text{threshold\_db}$.
  7. Vectorizes binary change mask to GeoJSON polygons mapped through the affine transform into WGS84 coordinates.
  8. Calculates exact physical area ($km^2$) using projection pixel resolution ($dx \times dy$) or WGS84 ellipsoidal latitude-dependent row integration.
  9. Saves colored PNG overlay (`#B84A27` Burnt Terracotta with transparency) to `/storage/masks/{analysis_id}.png`.
  10. Persists record into `analysis_runs`.
- **Response `200 OK`:**
```json
{
  "analysis_id": "f5195e33-7bb4-4cf5-94cb-047b7468165b",
  "source_type": "USER_UPLOAD",
  "threshold_db": -3.0,
  "speckle_filter": true,
  "impacted_km2": 42.85,
  "total_scene_km2": 1500.0,
  "valid_pixels": 1500000,
  "crs": "EPSG:32610",
  "change_type": "SIGNIFICANT_BACKSCATTER_DECREASE",
  "scientific_qualification": "Detected backscatter reduction of <= -3.0 dB. May indicate open surface water inundation, specular reflection, soil moisture changes, or vegetation structural disturbance. Field validation or multi-temporal analysis required to confirm flood extent.",
  "mean_db_drop": -5.12,
  "severity_tier": "ELEVATED",
  "mask_image_url": "/masks/f5195e33-7bb4-4cf5-94cb-047b7468165b.png",
  "mask_geojson": { "type": "FeatureCollection", "features": [...] },
  "bounds": [[37.65, -122.52], [37.85, -122.32]],
  "histogram": [
    { "bin": "-10 to -8 dB", "count": 1420 },
    { "bin": "-8 to -6 dB", "count": 3810 },
    { "bin": "-6 to -4 dB", "count": 9400 },
    { "bin": "-4 to -2 dB", "count": 24100 },
    { "bin": "-2 to 0 dB", "count": 89200 },
    { "bin": "0 to +2 dB", "count": 76500 },
    { "bin": "+2 to +4 dB", "count": 12300 }
  ],
  "created_at": "2026-11-21T11:46:12Z"
}
```

---

### 2.4 SAR Change Detection Analysis (ASF Live Pair)
#### `POST /api/analyze/asf`
Triggers authenticated fetch of two previously indexed ASF granules, downloads or streams raster subsets, and executes the change detection pipeline.
- **Request Body:**
```json
{
  "before_granule_id": "e2c36c64-4632-4414-b8be-586b4ef84c71",
  "after_granule_id": "78ad3bc1-5401-4475-8021-efc8d6263592",
  "threshold_db": -3.5,
  "speckle_filter": true
}
```
- **Response `200 OK`:** Same schema as Section 2.3 with `source_type: "ASF_LIVE"`.

---

### 2.5 Structured Gemini AI Field Briefing
#### `POST /api/briefing/{analysis_id}`
Reads persisted `analysis_runs` record and queries Gemini API with structured output schema.
- **Request Body:** Optional custom context string:
```json
{
  "operational_focus": "Disaster Relief and Critical Infrastructure Evacuation"
}
```
- **Prompt Guard:** All DB metrics are wrapped in `<telemetry>` XML tags.
- **Response `200 OK`:**
```json
{
  "id": "1c7a840e-3fa5-455b-b9f4-e58f0012ab6f",
  "analysis_id": "f5195e33-7bb4-4cf5-94cb-047b7468165b",
  "model_name": "gemini-2.5-flash",
  "risk_level": "ELEVATED",
  "summary_text": "SAR backscatter analysis reveals a 42.85 km² region exhibiting pronounced backscatter loss (mean -5.12 dB), indicative of extensive standing surface water inundation or infrastructure damage following the meteorological event.",
  "primary_driver": "Surface Water Inundation",
  "recommended_actions": [
    "Prioritize aerial drone reconnaissance over the western low-elevation drainage corridor.",
    "Restrict heavy transport access across low-lying transport arteries in the affected sector.",
    "Coordinate with regional emergency management for targeted levee integrity verification."
  ],
  "created_at": "2026-11-21T11:47:00Z"
}
```

---

### 2.6 History Archive
#### `GET /api/history`
Retrieves paginated list of prior analysis runs ordered by `created_at DESC`.
#### `GET /api/history/{analysis_id}`
Retrieves complete record of a specific run, including GeoJSON mask and briefing.
#### `DELETE /api/history/{analysis_id}`
Deletes run record and associated mask image file.
