# Product Requirements Document (PRD) — NISAR-Pulse

## 1. Executive Summary
**NISAR-Pulse** is an all-weather, day-and-night Synthetic Aperture Radar (SAR) surface change and disaster tracker designed for emergency response coordinators, remote sensing analysts, and space tech missions. Leveraging dual-frequency L/S-band NISAR (NASA-ISRO SAR) provisional/validated products and ESA Sentinel-1 C-band SAR observations, NISAR-Pulse provides accurate, physically grounded backscatter change detection and AI-synthesized field tactical briefings.

## 2. Core Value Proposition & Objectives
- **All-Weather Earth Observation:** Unlike optical sensors limited by cloud cover, atmospheric haze, or nighttime conditions, microwave SAR penetrates weather barriers to deliver uninterrupted surface state intelligence.
- **Strict Data Integrity:** Absolute prohibition of synthetic images, hardcoded disaster scenarios, or fake coordinates. Every calculation traces directly to live NASA Alaska Satellite Facility (ASF) archives or real user-supplied SAR granules (`.h5`, `.tif`, `.png`).
- **Rapid Decision Support:** Automatically computes decibel (dB) log-ratio backscatter differences (`10 * log10(after / before)`), filters speckle noise, measures exact geodesic affected area ($km^2$) using vector polygons, and generates structured tactical briefings via Google Gemini.

## 3. End-to-End User Workflow
```
[1. AOI & Time Horizon]
User draws Polygon AOI via Geoman or searches location via Geocoder
Selects Satellite Collection (NISAR GCOV/GUNW or Sentinel-1) & Date Range
              │
              ▼
[2. Live NASA ASF Query]
Backend queries ASF API via `asf_search` with polygon WKT & parameters
Real granules returned with footprints, polarization (HH/HV/VV/VH), and browse imagery
Granules and search record persisted to SQLite / PostgreSQL database
              │
              ▼
[3. Pair Selection & Verification]
User selects explicit Before & After granules from the result list
(Alternatively, user directly uploads local verified `.h5` or `.tif` files on `/upload`)
              │
              ▼
[4. Radiometric & Spatial Engine Execution]
Backend aligns rasters using rioxarray `.rio.reproject_match()`
Executes speckle suppression (Lee/OpenCV Gaussian/bilateral filter)
Computes log-ratio backscatter delta (dB)
Thresholds significant drops/gains and vectorizes mask to GeoJSON with Shapely/GeoPandas
Computes real histogram distribution and geodesic impacted area (km²)
Saves visual mask PNG overlay to `/storage/masks/` and analysis record to DB
              │
              ▼
[5. Structured AI Tactical Field Briefing]
Backend reads saved analysis record, formats XML-delimited telemetry prompt
Queries Gemini (`google-genai` SDK) with strict Pydantic JSON schema
Generates risk level, tactical summary, and prioritized action plan
Persists briefing and renders on map workspace
```

## 4. Key Functional Requirements

### 4.1 Granule Discovery (ASF Live Search)
- Search parameters: WKT polygon geometry, start/end dates, platform (`NISAR`, `SENTINEL-1`), processing level (`GCOV`, `GUNW`, `SLC`, `GRD`), data maturity (`VALIDATED`, `PROVISIONAL`).
- NISAR preference: Prioritize Frequency B bands first for low-latency transmission and streamlined processing.
- Persistent logging: Store every query in `aoi_searches` and associated granules in `sar_granules`.

### 4.2 SAR Change Detection Engine
- Input support: NISAR HDF5 (`.h5` files with HDF5 hierarchy `/science/LSAR/GCOV/grids/frequencyB/`) and GeoTIFF (`.tif`/`.tiff` single/multi-band amplitude/intensity rasters).
- Alignment: Reproject and resample `after` raster to match `before` coordinate reference system (CRS) and spatial resolution via `rioxarray`.
- Mathematical formula:
  $$\Delta \sigma^0_{\text{dB}} = 10 \cdot \log_{10}\left(\frac{\sigma^0_{\text{after}} + \epsilon}{\sigma^0_{\text{before}} + \epsilon}\right)$$
- Change classification: Negative delta thresholding (typically $\le -3.0$ dB) identifies flood inundation, structural collapse, or deforestation; positive delta identifies soil moisture surge or new structures.
- Vectorization & Area: Polygonize binary mask with `shapely` and `geopandas`, project to equal-area projection or compute geodesic area in $km^2$.

### 4.3 AI Field Briefing Generation
- Uses Google Gemini models with structured JSON output enforcing `risk_level` (`CRITICAL`, `ELEVATED`, `MODERATE`, `NOMINAL`), `summary_text`, `primary_driver`, `impacted_area_km2`, `mean_db_change`, and `recommended_actions`.
- Raw inputs strictly restricted to database telemetry (no subjective model speculation).

### 4.4 Analysis History & Export
- List all historical analyses from SQLite/PostgreSQL.
- Instant reload onto the interactive map with single click.
- Export analysis footprints and change masks as GeoJSON and run metadata as CSV.

## 5. Non-Functional Requirements
- **Performance:** Live search response $< 3$ seconds; change detection on uploaded files $< 8$ seconds for standard tiles.
- **Portability:** Containerized or locally runnable via standard Python 3.10+ and Node.js 18+.
- **Reliability:** Graceful error handling for missing credentials, offline NASA servers, or zero-granule return states without UI crash.
