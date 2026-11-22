# Button Component Specifications & States

## 1. Overview & Sizing Metrics
All button components adhere to exact tactile dimensions, strict borders, and `6px` corner radii. Text is rendered in `Space Grotesk` Medium (500) or SemiBold (600).

- **Standard Size (Medium):** Height `36px`, padding `0 14px`, text `13px / 1.2`.
- **Compact Size (Small):** Height `28px`, padding `0 10px`, text `12px / 1.2`.
- **Large Action Size:** Height `44px`, padding `0 20px`, text `14px / 1.2`.
- **HUD Icon Size:** `32px x 32px`, square, centered icon.

---

## 2. Style Variants

### 2.1 Primary Action Button
- **Default:** Background `#4A3525` (Deep Espresso Brown), text `#FDFBF7`, border `1px solid #36261A`, border-radius `6px`.
- **Hover:** Background `#634832` (Roasted Umber), border `1px solid #4A3525`.
- **Active:** Scale `scale(0.98)`, background `#36261A`.
- **Disabled:** Background `#D8C9B5`, text `#8C7B6D`, cursor `not-allowed`, opacity `0.65`.
- **Loading:** Preserves exact fixed width, shows centered warm-sand spinner with muted text.

### 2.2 Secondary Action Button
- **Default:** Background `#FDFBF7` (Alabaster Cream), text `#231810`, border `1px solid #C8B69E`, border-radius `6px`.
- **Hover:** Background `#EAE0D0` (Warm Oat), border `1px solid #B8A58D`.
- **Active:** Scale `scale(0.98)`, background `#DFD4C2`.
- **Disabled:** Background `#F5EFE6`, text `#A09081`, border `1px solid #E5D9C8`, cursor `not-allowed`.

### 2.3 Alert / Anomaly Button
- **Default:** Background `rgba(184, 74, 39, 0.12)` (Terracotta Tint), text `#B84A27`, border `1px solid #B84A27`.
- **Hover:** Background `rgba(184, 74, 39, 0.22)`.
- **Active:** Scale `scale(0.98)`, background `rgba(184, 74, 39, 0.30)`.
- **Disabled:** Opacity `0.4`, cursor `not-allowed`.

### 2.4 HUD Floating Map Icon Button
- **Default:** Background `rgba(253, 251, 247, 0.92)` (Alabaster Glass), border `1px solid #D8C9B5`, text `#4A3525`, box-shadow `0 2px 6px rgba(74, 53, 37, 0.12)`.
- **Hover:** Background `#FDFBF7`, text `#231810`, border `1px solid #B8A58D`.
- **Active:** Scale `scale(0.95)`, background `#EAE0D0`.
- **Active Toggle State:** Background `#4A3525`, text `#FDFBF7`, border `1px solid #231810`.
