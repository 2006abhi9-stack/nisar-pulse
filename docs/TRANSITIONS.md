# Interaction Motion & Transition Specifications

## 1. Timing Curves & Mechanical Profiles
NISAR-Pulse avoids whimsical, bouncy animations. All UI motion adheres to snappy, mechanical deceleration profiles mimicking precision instrumentation dials and shutter gates.

- **Primary Easing Curve:** `cubic-bezier(0.22, 1, 0.36, 1)` (Precision Deceleration)
- **Standard Durations:**
  - Fast Interactive (Button active state, tooltips, tab indicator): `150ms`
  - Medium Structural (Drawer collapse/expand, modal fade, card reveal): `220ms`
  - Long Spatial (Leaflet map camera movement): `1000ms` (`1.0s`)

---

## 2. Component-Level Transitions

### 2.1 Collapsible Rails (Left & Right Drawers)
- Transition property: `transform, width, opacity`
- Timing: `220ms cubic-bezier(0.22, 1, 0.36, 1)`
- Visual behavior: Left rail slides out smoothly to `transform: translateX(-100%)` while keeping the collapse toggle trigger pinned to the canvas edge. On completion, Leaflet map canvas re-measures via `map.invalidateSize()`.

### 2.2 Leaflet Camera Transitions (`flyToBounds`)
- When a user clicks a satellite granule in the discovery rail:
  - Duration: `1.0s`
  - EaseLinearity: `0.25`
  - Padding: `[40, 40]` pixels to guarantee the swath polygon does not collide with the panel edges.

### 2.3 Modal Dialogs
- Backdrop: `opacity` transitions from `0` to `1` over `150ms`.
- Content Panel: `transform` scales from `scale(0.97)` to `scale(1)` with `opacity` from `0` to `1` over `200ms cubic-bezier(0.22, 1, 0.36, 1)`.

### 2.4 Button & Control Press States
- Press effect: `active:scale-[0.98]` over `80ms`.
- Hover color wash: `transition-colors duration-150 ease-out`.
