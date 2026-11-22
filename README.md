# NISAR-Pulse: SAR-Based Surface Change & Disaster Tracker

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-4A3525.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-4F6D48.svg)](https://fastapi.tiangolo.com)
[![React 18](https://img.shields.io/badge/React-18.2+-B84A27.svg)](https://react.dev)
[![Leaflet](https://img.shields.io/badge/Leaflet-1.9.4-C2822A.svg)](https://leafletjs.com)
[![Ruff](https://img.shields.io/badge/linter-ruff-36261A.svg)](https://astral.sh/ruff)

An all-weather, day/night Synthetic Aperture Radar (SAR) surface change detection and tactical disaster tracker engineered for emergency response agencies, earth scientists, and space tech missions. Leverages dual-frequency L/S-band NISAR (NASA-ISRO SAR) products and ESA Sentinel-1 C-band SAR observations to deliver physically verified backscatter change detection and AI-synthesized field tactical briefings.

---

## Architecture Overview

```
nisar-pulse/
├── docs/                   # 12 Specification & Architecture Standards
│   ├── PRD.md              # Product Requirements Document
│   ├── DESIGN.md           # Brown & Beige Cartographic Design Tokens
│   ├── PAGES.md            # 4-Page React Router Specifications
│   ├── DATABASE.md         # SQLite / PostgreSQL SQLAlchemy 2.0 Schema
│   ├── API_SPEC.md         # FastAPI REST Endpoints & Schemas
│   ├── PLUGINS.md          # Geospatial, Leaflet, and Dev Plugins
│   ├── UI_UX.md            # Cartographic Ergonomics & Micro-Interactions
│   ├── ARCHITECTURE.md     # Monorepo Blueprint
│   ├── SECURITY.md         # Token Isolation & Prompt Guard Rails
│   ├── TRANSITIONS.md      # Mechanical Deceleration Profiles
│   ├── BUTTONS.md          # Tactile Button States & Variants
│   └── ANTI_AI_SLOP.md     # Real-Data Integrity Directives
├── backend/                # FastAPI Asynchronous Geospatial Core
│   ├── .env.example        # Environment Template
│   ├── main.py             # FastAPI App & REST Endpoints
│   ├── database.py         # SQLAlchemy aiosqlite Async Session
│   ├── models.py           # Database Entities
│   ├── schemas.py          # Pydantic v2 Models
│   ├── sar_engine.py       # Log-Ratio Change Engine & Shapely Vectorizer
│   └── ai_service.py       # Google Gemini Structured Briefing Synthesis
├── frontend/               # React 18 + Vite + TypeScript Client
│   ├── src/
│   │   ├── pages/          # LiveMissionPage, UploadPage, HistoryPage, SettingsPage
│   │   ├── components/     # TopCommandBar, Button, Card, HistogramChart, AIBriefingCard
│   │   └── api/client.ts   # Typed API Client
├── storage/
│   └── masks/              # Generated Terracotta (#B84A27) Change Overlays
└── .vscode/
    └── extensions.json     # Recommended Ruff & SQLite Extensions
```

---

## Quickstart Guide

### 1. Instant One-Click Launch (Recommended)
You can launch the full application (Backend + Frontend SPA) with a single command:
* **Command Prompt:** double-click or run `run.bat`
* **PowerShell:** `.\run.ps1`
* **Direct Python CLI:**
  ```powershell
  python -m uvicorn main:app --port 8000 --app-dir backend
  ```
Then open your browser at **`http://localhost:8000`**.

---

### 2. Manual Development Setup

#### Backend API:
```powershell
cd backend
python -m uvicorn main:app --reload --port 8000
```
- Web Application & Map Interface: `http://localhost:8000`
- Interactive API Docs (Swagger): `http://localhost:8000/docs`
- Health Diagnostics: `http://localhost:8000/api/health`

#### Frontend Dev Server (Optional, if Node.js is installed):
```powershell
cd frontend
npm install
npm run dev
```
- Dev Server: `http://localhost:5173` (proxies `/api` and `/masks` to port 8000)

---

### 3. Environment Secrets Setup
Configure your tokens in `backend/.env` if you wish to use live NASA Earthdata or Google Gemini:
```env
# NASA Earthdata Bearer Token (Register at https://urs.earthdata.nasa.gov/)
EARTHDATA_TOKEN=your_earthdata_token_here

# Google Gemini API Key (Generate at https://aistudio.google.com/)
GEMINI_API_KEY=your_gemini_api_key_here

# SQLite Async Database Connection String
DATABASE_URL=sqlite+aiosqlite:///./nisar_pulse.db

# Storage Directory for Vector & Raster Masks
STORAGE_DIR=../storage/masks
```
*(Note: A pre-configured `.env` is already present in `backend/` with demo credentials and fallback support).*

---

## Deployment to Render & Cloud

### 1-Click Render Deployment (via GitHub Blueprint)

This repository includes a production multi-stage `Dockerfile` and a `render.yaml` blueprint.

1. **Push to GitHub**:
   Run the included deployment script or standard Git commands:
   ```powershell
   .\deploy_to_github.ps1
   ```
   *(Or `deploy_to_github.bat` on Command Prompt)*

2. **Deploy on Render**:
   - Go to [dashboard.render.com](https://dashboard.render.com)
   - Click **New +** -> **Blueprint**
   - Connect your GitHub repository
   - Render reads `render.yaml` and provisions the Web Service using Docker automatically!
   - Under **Environment Variables**, provide your optional API keys (`GEMINI_API_KEY`, `EARTHDATA_TOKEN`).
   - Click **Apply** — your app is live on `https://<your-service>.onrender.com`!

---

## Verification & Code Quality

- **Python Linting:** Zero warnings via `ruff check .`
- **TypeScript & Bundler:** Zero errors via `tsc && vite build`
