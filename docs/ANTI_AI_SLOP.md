# Anti-AI Slop & Data Integrity Directives

## 1. Absolute Zero-Tolerance for Synthetic or Pre-Assumed Data
- **No Mock Arrays or Dummy Rasters:** Under no circumstances shall the application generate synthetic procedural noise, fake Gaussian blobs, or hardcoded raster matrices disguised as satellite imagery.
- **No Pre-Populated Disaster Scenarios:** Do not hardcode fictional "Hurricane Katrina 2026" or "California Earthquake" mock scenarios into the UI or database seeders.
- **Physical Provenance Required:** Every coordinate polygon, satellite granule identifier, decibel change value, and square kilometer metric MUST originate from:
  1. Live authenticated queries to NASA ASF (`asf_search` / `earthaccess`), OR
  2. Physical SAR files (`.h5`, `.tif`, `.tiff`, `.png`) explicitly provided by the user.
- **Honest Empty States:** If an ASF search returns 0 granules, or if the user has not uploaded files, the application must display a clean, transparent empty state explaining the exact reason and providing guidance—never fall back to placeholder numbers or canned data.

---

## 2. Visual & Architectural Integrity

### 2.1 Color & Palette Discipline
- **Prohibited:** No purple/indigo/cyan neon glows, no futuristic sci-fi gradients, no generic AI-styled gradients (`from-purple-500 to-indigo-600`), and no glassy blurred blobs.
- **Mandated:** Strict fidelity to the Brown & Beige Cartographic Theme (`#F5EFE6`, `#FDFBF7`, `#EAE0D0`, `#D8C9B5`, `#4A3525`, `#B84A27`).

### 2.2 Iconography vs. Emojis
- **Zero Emojis in User Interface:** Never use unicode emojis (e.g., 🚀, 🛰️, ⚠️, 💥, 📊) in headings, buttons, badges, logs, or tactical cards.
- **Mandated:** Use crisp, consistent `16px` or `18px` vector icons from `lucide-react` (e.g. `Satellite`, `Compass`, `Layers`, `Radio`, `FileText`, `AlertTriangle`).

### 2.3 Purpose-Driven Layouts
- **No Marketing Fluff:** No "hero banner" with marketing copy like *"Empowering Next-Gen Earth Intelligence With AI"*.
- **Tactical Utility:** The user lands directly on an operational 100vh mission workspace ready for immediate spatial queries and data analysis.

### 2.4 Code Cleanliness & Conciseness
- **Modular Codebase:** Keep files modular, focused, and ideally under 200-250 lines. Separate API logic, types, components, and mathematical kernels.
- **Zero Console Spam:** Eliminate stray `console.log` or debug statements from production code. Use structured Python logging in the backend.
- **Type Safety:** 100% strict TypeScript types and Pydantic schemas without `any` workarounds.
