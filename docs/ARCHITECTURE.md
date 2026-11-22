# System Architecture & Monorepo Directory Layout

## 1. Directory Tree

```
nisar-pulse/
├── .vscode/
│   └── extensions.json                 # Recommended workspace extensions (Ruff, SQLite)
├── docs/
│   ├── PRD.md                          # Product requirements & objectives
│   ├── DESIGN.md                       # Brown & Beige cartographic theme tokens
│   ├── PAGES.md                        # 4-page routing & layout specs
│   ├── DATABASE.md                     # SQLAlchemy async models & ERD
│   ├── API_SPEC.md                     # FastAPI REST API endpoints
│   ├── PLUGINS.md                      # Geospatial, Leaflet, and Dev plugins
│   ├── UI_UX.md                        # Ergonomics, micro-interactions, layout
│   ├── ARCHITECTURE.md                 # Monorepo blueprint & dependencies
│   ├── SECURITY.md                     # Token isolation & input sanitization
│   ├── TRANSITIONS.md                  # Motion curves & timing standards
│   ├── BUTTONS.md                      # UI button variants & states
│   └── ANTI_AI_SLOP.md                 # Strict code quality & data honesty rules
├── storage/
│   └── masks/                          # Generated PNG change mask overlays
├── backend/
│   ├── .env.example                    # Template for secrets and DB URL
│   ├── pyproject.toml                  # Ruff configuration & metadata
│   ├── requirements.txt                # Exact pinned Python packages
│   ├── main.py                         # FastAPI application entrypoint & routing
│   ├── database.py                     # SQLAlchemy async engine & sessionmaker
│   ├── models.py                       # Database table models
│   ├── schemas.py                      # Pydantic request/response schemas
│   ├── sar_engine.py                   # Rioxarray / HDF5 / OpenCV processing core
│   └── ai_service.py                   # Google Gemini briefing synthesis
└── frontend/
    ├── package.json                    # Frontend dependencies & scripts
    ├── tsconfig.json                   # TypeScript compiler configuration
    ├── vite.config.ts                  # Vite build tooling with proxy
    ├── tailwind.config.js              # Theme colors, fonts, and radii
    ├── index.html                      # HTML shell with Google Fonts links
    └── src/
        ├── index.css                   # Tailwind directives & theme variables
        ├── App.tsx                     # Router configuration & command bar shell
        ├── main.tsx                    # React DOM entrypoint
        ├── types/
        │   └── index.ts                # TypeScript interfaces matching backend models
        ├── api/
        │   └── client.ts               # Typed Axios / Fetch HTTP client
        ├── components/
        │   ├── TopCommandBar.tsx       # Global 52px top bar with mission clock
        │   ├── Button.tsx              # Standardized button variants
        │   ├── Card.tsx                # Alabaster Cream panel containers
        │   ├── Modal.tsx               # System dialogs and focus views
        │   ├── HistogramChart.tsx      # Recharts dB distribution component
        │   └── AIBriefingCard.tsx      # Gemini field summary & action checklist
        └── pages/
            ├── LiveMissionPage.tsx     # 100vh Leaflet mission workspace (/)
            ├── UploadPage.tsx          # Local .h5 / .tif file analyzer (/upload)
            ├── HistoryPage.tsx         # SQLite analysis archive (/history)
            └── SettingsPage.tsx        # System diagnostics & API health (/settings)
```

---

## 2. Core Dependencies & Tooling

### 2.1 Backend (`/backend/requirements.txt`)
- `fastapi>=0.110.0` & `uvicorn>=0.28.0` — Async ASGI server & web framework
- `sqlalchemy>=2.0.25` & `aiosqlite>=0.19.0` — Async ORM and SQLite driver
- `asf_search>=7.0.0` — Official NASA Alaska Satellite Facility Python client
- `earthaccess>=0.9.0` — NASA Earthdata cloud discovery and direct streaming
- `rioxarray>=0.15.0` & `xarray>=2024.1.0` — Geospatial raster array alignment
- `rasterio>=1.3.9` — GeoTIFF reading, affine transforms, polygon vectorization
- `h5py>=3.10.0` — HDF5 binary parsing for NISAR Level 2 GCOV/GUNW
- `shapely>=2.0.2` & `geopandas>=0.14.2` — Vector topology & geodesic area math
- `pyproj>=3.6.0` — Rigorous geodetic transformations and CRS handling
- `opencv-python-headless>=4.9.0.80` — Fast C-optimized spatial speckle filters & contouring
- `numpy>=1.26.0` — Array-level log-ratio operations
- `google-genai>=0.1.1` — Official Google Gemini API client
- `python-dotenv>=1.0.1` — Environment variable loader
- `python-multipart>=0.0.9` — Multipart/form-data upload handler
- `pydantic>=2.6.0` — Schema validation
- `ruff>=0.3.0` — High-speed Python code linter

### 2.2 Frontend (`/frontend/package.json`)
- `react@^18.2.0` & `react-dom@^18.2.0`
- `react-router-dom@^6.22.0` — Client-side SPA routing
- `leaflet@^1.9.4` & `react-leaflet@^4.2.1` — Interactive mapping
- `@geoman-io/leaflet-geoman-free@^2.14.2` — AOI polygon & rectangle drawing
- `leaflet-side-by-side@^2.2.0` — Before/After split curtain comparison
- `leaflet-control-geocoder@^2.4.0` — Nominatim place search
- `leaflet-compass@^1.5.7` — HUD navigational rose
- `recharts@^2.12.0` — Tactical telemetry histogram visualizations
- `lucide-react@^0.350.0` — Crisp, minimal icon set (16px/20px)
- `tailwindcss@^3.4.1` & `autoprefixer@^10.4.18` — Utility-first styling

---

## 3. Scientifically & Geographically Reliable SAR Engine Architecture

```
[ Pre-Disaster SAR Raster ]   [ Post-Disaster SAR Raster ]
        │                                  │
        ▼                                  ▼
[ SARRaster Reader: HDF5 (GCOV/GUNW) or GeoTIFF (EPSG/Affine) ]
  • Extracts true native CRS & 6-element Affine transform
  • Calculates native and WGS84 bounding envelopes
  • Rejects unanchored rasters (Zero Synthetic SF Coordinates)
        │                                  │
        └───────────────┬──────────────────┘
                        ▼
       [ Geographic Alignment & Resampling ]
  • Checks physical geospatial overlap (rejects non-overlapping scenes)
  • Warps 'after' grid to 'before' CRS/resolution via PyProj & Bilinear Remap
  • Strictly preserves nodata and out-of-bounds as NaN (No cv2.resize distortion)
                        │
                        ▼
       [ Adaptive Lee Speckle Filtering ]
  • Multiplicative SAR noise filter with local variance estimation
  • Preserves sharp hydrological edges and backscatter boundaries
                        │
                        ▼
       [ Radiometric Log-Ratio Decibel Engine ]
  • Delta dB = 10 * log10(after / before)
  • Strict valid mask: before > 0, after > 0, non-NaN, non-nodata
  • Negative drop thresholding (e.g. <= -3.0 dB)
                        │
                        ▼
   [ Scientific Classification & Geodesic Area Calculation ]
  • Labeled as 'SIGNIFICANT_BACKSCATTER_DECREASE' with qualification note
  • Defensible Physical Area (km²): UTM meter integration or WGS84 latitude-strip ellipsoidal math
  • Vectorizes contours through exact Affine transform -> Valid WGS84 GeoJSON Polygons
  • Generates alpha-masked PNG overlay for Leaflet UI
```

### 3.1 Data Honesty Guarantees
1. **No Fabricated Fallbacks:** Missing georeferencing raises HTTP 400. The engine never outputs synthetic San Francisco or placeholder coordinates.
2. **Defensible Terminology:** Backscatter drops are reported as "Significant Backscatter Decrease", explicitly noting that field confirmation or multi-temporal thresholding is required to verify actual water inundation versus smooth soil/geometry changes.
3. **Exact Pixel-Geometry Math:** Areas reflect only georeferenced valid pixels, never the full scene bounding box.

