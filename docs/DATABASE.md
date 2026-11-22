# Database Architecture & Schema Specification

## 1. Overview & Engine Configuration
The database layer is engineered with **SQLAlchemy 2.0 Async** using `aiosqlite` for local zero-configuration SQLite operation, with instant compatibility for enterprise PostgreSQL deployments by simply altering `DATABASE_URL` in `/backend/.env`.

- **Default Local Connection String:** `sqlite+aiosqlite:///./nisar_pulse.db`
- **PostgreSQL Connection String:** `postgresql+asyncpg://user:pass@host:5432/nisar_pulse`
- **Naming Conventions:** Lowercase snake_case table and column names; UUID primary keys stored as strings in SQLite or native UUID in Postgres.

---

## 2. Entity Relationship Diagram (ERD)

```
┌─────────────────────┐
│    aoi_searches     │
├─────────────────────┤
│ id (PK, UUID)       │◄──┐
│ name                │   │
│ wkt_polygon         │   │
│ dataset             │   │
│ start_date          │   │
│ end_date            │   │
│ results_count       │   │
│ created_at          │   │
└─────────────────────┘   │
                          │ 1:N
┌─────────────────────┐   │
│    sar_granules     │   │
├─────────────────────┤   │
│ id (PK, UUID)       │   │
│ search_id (FK)      ├───┘
│ granule_name (UQ)   │◄───────────────┐ (before/after granule FKs)
│ platform            │                │
│ processing_level    │                │
│ data_maturity       │                │
│ polarization        │                │
│ acquisition_time    │                │
│ footprint_geojson   │                │
│ download_url        │                │
│ browse_url          │                │
│ created_at          │                │
└─────────────────────┘                │
                                       │
┌──────────────────────────────────────┴──────────────┐
│                   analysis_runs                     │
├─────────────────────────────────────────────────────┤
│ id (PK, UUID)                                       │◄──┐
│ before_granule_id (FK, nullable)                    │   │
│ after_granule_id (FK, nullable)                     │   │
│ source_type ('ASF_LIVE' | 'USER_UPLOAD')            │   │
│ threshold_db (FLOAT)                                │   │
│ speckle_filter (BOOLEAN)                            │   │
│ impacted_km2 (FLOAT)                                │   │
│ mean_db_drop (FLOAT)                                │   │
│ severity_tier ('CRITICAL'|'ELEVATED'|'MODERATE'...) │   │
│ mask_image_path (VARCHAR)                           │   │
│ mask_geojson (JSON)                                 │   │
│ histogram_json (JSON)                               │   │
│ bounds_json (JSON)                                  │   │
│ created_at (TIMESTAMP)                              │   │
└─────────────────────────────────────────────────────┘   │
                                                          │ 1:1 or 1:N
┌─────────────────────────────────────────────────────┐   │
│                    ai_briefings                     │   │
├─────────────────────────────────────────────────────┤   │
│ id (PK, UUID)                                       │   │
│ analysis_id (FK)                                    ├───┘
│ model_name (VARCHAR)                                │
│ risk_level ('CRITICAL'|'ELEVATED'|'MODERATE'|'LOW') │
│ summary_text (TEXT)                                 │
│ recommended_actions_json (JSON)                     │
│ created_at (TIMESTAMP)                              │
└─────────────────────────────────────────────────────┘
```

---

## 3. Detailed Table Definitions

### 3.1 `aoi_searches`
Tracks user polygon queries executed against NASA ASF.
- `id`: String(36), Primary Key (UUIDv4).
- `name`: String(255), Optional human label (e.g., "California Coast AOI").
- `wkt_polygon`: Text, Mandatory Well-Known Text polygon (`POLYGON((...))`).
- `dataset`: String(64), Satellite platform (`NISAR`, `SENTINEL-1`).
- `start_date`: Date / DateTime, Lower bound of search window.
- `end_date`: Date / DateTime, Upper bound of search window.
- `results_count`: Integer, Number of matching granules returned by ASF.
- `created_at`: DateTime, UTC timestamp with timezone.

### 3.2 `sar_granules`
Stores normalized satellite scenes returned by live ASF queries.
- `id`: String(36), Primary Key (UUIDv4).
- `search_id`: String(36), Foreign Key references `aoi_searches.id` (on delete cascade).
- `granule_name`: String(255), Unique natural key from satellite operator.
- `platform`: String(32), e.g. `NISAR`, `SENTINEL-1A`, `SENTINEL-1B`.
- `processing_level`: String(32), e.g. `GCOV`, `GUNW`, `GRD`, `SLC`.
- `data_maturity`: String(32), e.g. `PROVISIONAL`, `VALIDATED`.
- `polarization`: String(32), e.g. `HH`, `HV`, `VV`, `VH`, `HH+HV`.
- `acquisition_time`: DateTime, Timestamp of satellite sensor pass.
- `footprint_geojson`: JSON / Text, GeoJSON polygon representing swath boundaries on the WGS84 ellipsoid.
- `download_url`: Text, Authenticated NASA Earthdata or ASF granule download link.
- `browse_url`: Text, Public URL to pre-computed quicklook/browse optical thumbnail.
- `created_at`: DateTime, UTC creation timestamp.

### 3.3 `analysis_runs`
Records every executed change detection computation.
- `id`: String(36), Primary Key (UUIDv4).
- `before_granule_id`: String(36), Foreign Key references `sar_granules.id` (nullable for uploads).
- `after_granule_id`: String(36), Foreign Key references `sar_granules.id` (nullable for uploads).
- `source_type`: String(32), Mandatory: `'ASF_LIVE'` or `'USER_UPLOAD'`.
- `threshold_db`: Float, Threshold in decibels used to separate change from noise (e.g. `-3.5`).
- `speckle_filter`: Boolean, Whether spatial speckle filtering was applied before log-ratio.
- `impacted_km2`: Float, Exact geodesic area in square kilometers where $\Delta \text{dB} \le \text{threshold}$.
- `mean_db_drop`: Float, Average decibel drop within the detected anomaly mask.
- `severity_tier`: String(32), `'CRITICAL'` ($> 50 \text{ km}^2$), `'ELEVATED'` ($10-50 \text{ km}^2$), `'MODERATE'` ($1-10 \text{ km}^2$), `'NOMINAL'` ($< 1 \text{ km}^2$).
- `mask_image_path`: String(512), Relative path to PNG overlay in `/storage/masks/`.
- `mask_geojson`: JSON / Text, Vectorized GeoJSON multi-polygons of the change mask.
- `histogram_json`: JSON / Text, Discrete frequency bins of backscatter delta values.
- `bounds_json`: JSON / Text, `[ [south, west], [north, east] ]` bounding box coordinates for Leaflet image overlay.
- `created_at`: DateTime, UTC timestamp.

### 3.4 `ai_briefings`
Persists synthesized AI mission briefings generated from analysis runs.
- `id`: String(36), Primary Key (UUIDv4).
- `analysis_id`: String(36), Foreign Key references `analysis_runs.id` (on delete cascade).
- `model_name`: String(64), Identifier of Gemini model employed (e.g. `gemini-2.5-flash`).
- `risk_level`: String(32), Standardized risk classification (`CRITICAL`, `ELEVATED`, `MODERATE`, `NOMINAL`).
- `summary_text`: Text, Executive situational assessment.
- `recommended_actions_json`: JSON / Text, Array of concrete, prioritized actions.
- `created_at`: DateTime, UTC timestamp.
