# Design System Specification — Brown & Beige Cartographic Theme

## 1. Visual Philosophy & Aesthetic Identity
NISAR-Pulse adopts a tactile, field-ready cartographic aesthetic inspired by archival topographical expedition charts, mission flight boards, and precision optical instruments. It intentionally rejects the ubiquitous dark-mode blue/cyan "cyberpunk" tropes in favor of an ergonomic, warm, earth-toned visual language suited for high-stress operational analysis.

---

## 2. Color Palette & Tokens

| Token Name | Hex Code | Role & Usage |
| :--- | :--- | :--- |
| `canvas-sand` | `#F5EFE6` | Primary window/body background (Warm Sand Beige) |
| `surface-cream` | `#FDFBF7` | Floating panels, modals, toolbars, cards (Alabaster Cream) |
| `surface-recessed` | `#EAE0D0` | Input backgrounds, active tab pills, badge counters (Warm Oat) |
| `border-sandstone` | `#D8C9B5` | 1px clean spatial separators and panel borders |
| `border-subtle` | `#E5D9C8` | Inner divider lines, card sub-headers |
| `accent-espresso` | `#4A3525` | Primary action buttons, active states, key brand elements |
| `accent-umber` | `#634832` | Hover state for espresso buttons and controls |
| `alert-terracotta`| `#B84A27` | Change mask overlay, negative dB drops, critical alerts |
| `alert-terracotta-bg` | `rgba(184, 74, 39, 0.10)` | Alert card backgrounds and negative change tags |
| `warning-ochre` | `#C2822A` | Cautionary warnings, moderate risk indicators |
| `warning-ochre-bg`| `rgba(194, 130, 42, 0.12)` | Warning chips, provisional data tags |
| `success-sage` | `#4F6D48` | Validated data markers, online connectivity indicators |
| `text-roast` | `#231810` | Primary typography, headers, metric values |
| `text-taupe` | `#6E5A4B` | Secondary labels, captions, metadata descriptions |

---

## 3. Typography Standards

### 3.1 Primary Font: Space Grotesk
- **Usage:** All interface headers, button labels, navigation pills, status badges, and narrative summaries.
- **Weights:** Regular (400), Medium (500), SemiBold (600), Bold (700).
- **Attributes:** Clean geometric clarity, architectural legibility.

### 3.2 Monospace Font: JetBrains Mono
- **MANDATORY USAGE:** All numerical outputs, coordinates (`lat/lon`), decibel values (`dB`), area metrics (`km²`), granule IDs, UTC timestamps, JSON payloads, and technical parameters.
- **Weights:** Regular (400), Medium (500), Bold (700).
- **Rule:** Never render numerical sensor values or satellite identifiers in a proportional font.

---

## 4. Elevation, Radii & Surface Rules
- **Base Border Radius:** `6px` for buttons, cards, pills, and input fields.
- **Floating Controls Radius:** `8px` for map overlays, HUD instruments, and modals.
- **Shadows:** Soft physical diffuse lighting.
  - Sub-surface: `0 1px 2px rgba(74, 53, 37, 0.05)`
  - Elevated Panel: `0 4px 12px rgba(74, 53, 37, 0.08)`
  - Floating Modal / Drawer: `0 12px 32px rgba(74, 53, 37, 0.14)`
- **Borders:** Every panel, card, and modal MUST have an explicit `1px solid #D8C9B5` border.

---

## 5. Map Styling & Cartographic Cartridge
- **Basemap:** CartoDB Voyager tiles with custom CSS filter: `sepia(12%) contrast(98%) brightness(99%)`.
- **AOI Polygons:**
  - Border: `2px solid #4A3525`
  - Fill: `rgba(74, 53, 37, 0.12)`
  - Vertex Handles: `8px x 8px` rounded squares with `#FDFBF7` fill and `#4A3525` border.
- **Change Mask Layer:**
  - Surface color: `#B84A27` (Burnt Terracotta) with blending mode `multiply` or opacity `0.75`.
- **HUD Instruments:**
  - Compass Rose: Positioned top-right, `#FDFBF7` card backing with `#4A3525` needle and degree indicator in JetBrains Mono.
  - Scale Bar: Standard imperial/metric toggle rendered in Sandstone / Espresso.
