# UI/UX & Layout Interaction Guidelines

## 1. Ergonomic Space Budgeting & Grid Architecture
- **Locked Viewport:** The primary mission workspace (`/`) is strictly locked to `100vh` with `overflow-hidden`. Users should never encounter double scrollbars or window-level scrolling on the map view.
- **Collapsible Rails:**
  - **Left Rail (320px width):** Mission parameters, AOI inputs, and granule discovery list. Features a tactile collapse toggle (`<` / `>`) with a slim 24px vertical grab bar.
  - **Right Rail (360px width):** Analytics telemetry, dB histogram, and AI briefing. Collapsible independently to grant full-screen map visibility during detailed spatial inspection.
  - **Center Canvas:** Dynamically expands from `calc(100vw - 680px)` to `100vw` depending on rail state, with automatic Leaflet `map.invalidateSize()` recalculation.

---

## 2. Micro-Interactions & State Design

### 2.1 Empty States
- When no AOI is drawn: Render a centered Sandstone dashed card with a compass icon and concise instructions: *"Define Area of Interest: Draw a polygon on the map or search a coordinate to query real NASA satellite passes."*
- When ASF search returns 0 granules: Render an actionable notice: *"0 scenes found for this bounding box and date range. Adjust your temporal window or select an alternative satellite platform."*
- When no analysis is selected: Show informative placeholder explaining the Before/After pairing mechanism.

### 2.2 Loading Shimmer & Progress
- Skeleton loaders must use the warm palette:
  - Base: `#EAE0D0`
  - Shimmer wave: `linear-gradient(90deg, #EAE0D0 0%, #F5EFE6 50%, #EAE0D0 100%)`
- Progress bars during raster computation must be determinate or pseudo-determinate, indicating active phase: *"Reprojecting rasters...", "Applying 5x5 speckle filter...", "Calculating dB log-ratio..."*.

### 2.3 Histogram Display (Recharts)
- Integrated into the right telemetry rail.
- Bars styled with `#4A3525` (nominal distribution) transitioning to `#B84A27` (Burnt Terracotta) for values below the negative change threshold.
- Tooltip styled in `#FDFBF7` with sandstone border and `JetBrains Mono` numerical readouts.

### 2.4 Cartographic Visual Feedback
- Hovering over a granule in the left rail highlights its vector footprint on the map with a glowing `#4A3525` stroke.
- Clicking a granule triggers a smooth `1.0s` Leaflet `flyToBounds` transition smoothly framing the scene footprint.
