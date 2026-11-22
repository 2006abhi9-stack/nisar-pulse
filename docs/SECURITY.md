# Security, Sanitization & Isolation Architecture

## 1. Environment Secrets Isolation
- All sensitive credentials MUST be loaded strictly through environment variables managed in `/backend/.env`.
- Under no circumstances may API keys, bearer tokens, or database credentials be committed to version control.
- An explicit `.gitignore` must exclude:
  - `.env`
  - `*.db`, `*.sqlite3`
  - `storage/masks/*` (except `.gitkeep`)
  - `node_modules/`, `dist/`, `__pycache__/`, `.venv/`
- Standard `/backend/.env.example` must be provided with redacted placeholder values.

---

## 2. API Key Sanitization & Masking
- The `/api/health` and `/api/settings` diagnostics endpoints MUST NEVER return raw key strings.
- Keys must be sanitized or masked (e.g. `eyJh...9xZ0` or `AIza...4bX1`) displaying only the first 4 and last 4 characters, or purely a boolean confirmation of whether the token exists and passes validation.

---

## 3. CORS & Network Boundary
- FastAPI CORS middleware is locked to approved frontend origins:
  - `http://localhost:5173`
  - `http://127.0.0.1:5173`
- Wildcard `allow_origins=["*"]` is strictly forbidden in production configurations.
- Allow standard HTTP methods: `GET`, `POST`, `DELETE`, `OPTIONS`.

---

## 4. File Upload Sanitization & Resource Protection
- **Allowed Extensions:** `.h5`, `.hdf5`, `.tif`, `.tiff`, `.png`.
- **File Size Ceiling:** Strict maximum limit of `50 MB` per file to prevent Denial-of-Service (DoS) and out-of-memory crashes during array manipulation.
- **Filename Randomization:** Uploaded files and generated masks must be saved using cryptographically secure UUIDv4 filenames (e.g. `9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d.png`). Never trust user-supplied file names or file paths directly on the host filesystem.
- **Path Traversal Guards:** File paths must be resolved and checked against the explicit absolute directory boundary of `/storage/masks/`.

---

## 5. Prompt Injection Defense (Gemini Telemetry Guard)
- When preparing analysis metrics to synthesize AI field briefings, raw user inputs or unverified strings must never be concatenated into the system prompt.
- Numerical measurements (area in $km^2$, mean dB drop, histogram counts, coordinates) must be formatted into clean, structured XML data blocks:
  ```xml
  <telemetry>
    <analysis_id>f5195e33-7bb4-4cf5-94cb-047b7468165b</analysis_id>
    <platform>NISAR</platform>
    <impacted_area_km2>42.85</impacted_area_km2>
    <mean_db_drop>-5.12</mean_db_drop>
    <threshold_db>-3.0</threshold_db>
  </telemetry>
  ```
- The Gemini model is instructed via system instructions to treat the contents within `<telemetry>` strictly as observational sensor facts, ignoring any prompt manipulation instructions embedded inside metadata strings.
