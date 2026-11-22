# Application Page Architecture — 4-Page React Router App

## 1. Global Navigation & Layout Container
All routes share the persistent **Top Command Bar** (`52px` height) adhering to `#FDFBF7` with bottom border `1px solid #D8C9B5`.
- **Left:** System Monogram + Product Name `NISAR-Pulse` + Real-time UTC Mission Clock (`JetBrains Mono`).
- **Center:** Route Navigation Pills (`/` Live Mission, `/upload` Local File SAR, `/history` Run Archive, `/settings` System Diagnostics).
- **Right:** Earthdata Connection State + Gemini API Readiness Status indicator + Quick Help Trigger.

---

## 2. Route Specifications

### 2.1 `/` — Live Map & Mission Workspace
- **Viewport Structure:** Locked to `100vh` with `overflow-hidden`. The Leaflet canvas spans the entire screen beneath the 52px command bar.
- **Left Collapsible Rail (320px width):**
  - Search Criteria Card: Location geocoder input (`leaflet-control-geocoder`), date range picker, satellite platform selector (`NISAR`, `SENTINEL-1`), and data maturity switch.
  - AOI Drawing Controller: Geoman toolbar trigger (`Draw Bounding Box`, `Draw Polygon`, `Clear AOI`).
  - Search Execution Button: "Query ASF Satellite Archive" with loading spinner and result counter.
  - Real Granules Result List: Scrollable list of returned real granules with acquisition timestamp, platform, orbit, polarization, and browse thumbnail preview.
  - Pair Selection Interface: Selectable radio buttons to assign active granule to `[BEFORE]` and `[AFTER]`.
  - "Run SAR Change Detection" trigger.
- **Right Collapsible Rail (360px width):**
  - Analysis Results Header: Impact summary, severity tier badge (`CRITICAL`, `ELEVATED`, `MODERATE`, `NOMINAL`).
  - Key Telemetry Metrics Card: Total impacted area ($km^2$), mean backscatter drop ($\Delta \text{dB}$), peak reduction pixel value.
  - Histogram Distribution Chart: Recharts interactive bar chart showing pixel frequency vs. dB delta range with threshold marker.
  - AI Mission Briefing Card: Gemini structured briefing containing executive summary, primary driver deduction, and prioritized tactical response checklist.
  - Export Operations: Buttons to export GeoJSON polygon mask, download composite GeoTIFF, and save analysis record.
- **Map Center Overlays & HUD:**
  - `leaflet-compass`: Visual navigation rose in top-right corner.
  - Before/After Split Curtain: `leaflet-side-by-side` swipe curtain allowing interactive scrubbing between pre-event and post-event imagery.
  - Granule Footprint Layer: Interactive vector bounding boxes showing the exact satellite swath coverage.
  - Terracotta Change Vector Layer: Vectorized GeoJSON polygon layer highlighting areas exceeding the dB drop threshold.

---

### 2.2 `/upload` — Direct SAR File Analyzer
- **Purpose:** Standalone laboratory environment for running change detection on user-provided `.h5` (NISAR GCOV/GUNW HDF5) or `.tif`/`.tiff` (Sentinel-1 or radiometric GeoTIFFs) files.
- **Dual Drag-and-Drop Dropzones:**
  - Dropzone A: Pre-Event SAR Granule (`Before File`).
  - Dropzone B: Post-Event SAR Granule (`After File`).
- **Parameter Controls Panel:**
  - Change Detection Threshold Slider: `-1.0 dB` to `-12.0 dB` (default: `-3.0 dB`).
  - Speckle Filtering Toggle: Enables/disables adaptive spatial filter (Lee/Bilateral filter) with kernel size selection (3x3, 5x5).
  - Normalization & Polarization Picker: Select polarization channel (`HH`, `HV`, `VV`, `VH`).
- **Execution & Output:**
  - Visual processing progress bar.
  - Side-by-side thumbnail comparisons with resulting Terracotta change mask preview.
  - Direct button to inspect results on the `/` Live Map workspace.

---

### 2.3 `/history` — Analysis Archive & Audit Trail
- **Purpose:** Comprehensive historical audit table tracking all previous SAR change detection runs stored in SQLite/PostgreSQL.
- **Table Columns:**
  - Timestamp (UTC ISO format in `JetBrains Mono`).
  - Source Type (`ASF Live Archive` vs `Local File Upload`).
  - Satellite Platform / Product Level.
  - Threshold Applied ($\Delta \text{dB}$).
  - Impacted Footprint Area ($km^2$).
  - Mean dB Shift ($\mu_{\Delta \text{dB}}$).
  - Severity Tier Badge.
  - AI Briefing Status (`Available` / `Pending`).
  - Actions: `View on Map`, `Export GeoJSON`, `Export CSV Row`, `Delete Record`.
- **Search & Filters:** Search by granule name, filter by date range or severity level.

---

### 2.4 `/settings` — API & System Diagnostics
- **NASA Earthdata Status Card:**
  - `EARTHDATA_TOKEN` connection status: Validates against NASA URS authentication endpoint.
  - Shows masked token string (e.g. `eyJh...9xZ0`, never exposes complete token).
  - Setup instruction guide with direct link to NASA Earthdata Login.
- **Google Gemini API Status Card:**
  - `GEMINI_API_KEY` presence and connectivity status.
  - Model target: `gemini-2.5-flash` or default configured model.
  - Latency ping test button.
- **Database Storage Diagnostics:**
  - SQLite Database file location and size on disk.
  - Total records count: `aoi_searches`, `sar_granules`, `analysis_runs`, `ai_briefings`.
  - Storage directory cleanup utility for `/storage/masks/`.
