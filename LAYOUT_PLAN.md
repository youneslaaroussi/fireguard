# FireGuard UI Layout Plan
## Reference: Palantir Gotham military ops dashboard

---

## Current problems

- Full-screen map with floating panels glued on top — no real structure
- Everything is the same dark navy — no surface hierarchy
- Glowing dots, gradient header, cyan borders — toy aesthetic
- Monospace everywhere — dense but unreadable
- No left sidebar — no persistent context panel
- Status communicated by color dots and chip animations, not data

---

## Target layout

```
┌──────────────────────────────────────────────────────────────────┐
│ HEADER — 28px flat bar                                           │
│ [🔥 FIREGUARD] › [Replay: Jul 17–25 2024]     [IDLE] [THREAT]   │
├───────────────┬──────────────────────────┬───────────────────────┤
│ LEFT SIDEBAR  │ CENTER PANEL             │ MAP                   │
│ 200px         │ flex-1                   │ 380px fixed           │
│               │                          │                       │
│ ▾ Context     │ Timeline bar (full-w)    │ [Mapbox dark]         │
│   incidents   │ ──────────────────────── │                       │
│   perimeters  │ Event feed table         │ unit markers          │
│   evac zones  │ (dense rows, sortable)   │ connecting lines      │
│               │                          │                       │
│ ▾ Sources     │ ──────────────────────── │                       │
│  [■] VIIRS    │ Threat panel             │                       │
│  [■] MODIS    │ (appears on threat)      │                       │
│  [■] BCWS     │                          │                       │
│               │                          │                       │
│ ▾ Replay      │                          │                       │
│  start/end    │                          │                       │
│  speed        │                          │                       │
└───────────────┴──────────────────────────┴───────────────────────┘
│ AGENT BAR — bottom full-width, 44px                              │
└──────────────────────────────────────────────────────────────────┘
```

---

## Design tokens

| Token | Value |
|---|---|
| App bg | `#0d1117` |
| Panel surface | `#111820` |
| Panel border | `rgba(255,255,255,0.07)` |
| Header bg | `#111820` |
| Row hover | `rgba(255,255,255,0.04)` |
| Selected row | left 2px solid `#3b82f6` + `rgba(59,130,246,0.12)` bg |
| Text primary | `#e2e8f0` |
| Text secondary | `#9ab0c4` |
| Text muted / labels | `#4b5563` (uppercase, 0.08em spacing) |
| Data values | `#c8d6e0`, `'Courier New', monospace` |
| Label font | Inter, system-ui |
| Border radius | 0 (nothing rounded except circles/dots) |

### Status color squares (not dots, not glows — flat solid fill)
| Status | Color |
|---|---|
| Critical / threat | `#e5484d` |
| Warning / amber | `#f59e0b` |
| OK / active | `#22c55e` |
| Info / blue | `#3b82f6` |
| Muted / offline | `#374151` |

---

## Header (28px)

```
[flame icon] FIREGUARD  ›  Replay Jul 17–25 2024        [■ IDLE]  [■ THREAT: Williams Lake]
```

- Flat `#111820` bg, 1px bottom border `rgba(255,255,255,0.08)`
- Breadcrumb with `›` separators, muted text `#4b5563`
- Status chips: `border-radius:0`, solid left-border accent (2px), no glow
- IDLE chip: left border `#374151`, text `#4b5563`
- ACQUIRING chip: left border `#22c55e`, text `#22c55e`, bg `rgba(34,197,94,0.07)`
- THREAT chip: left border `#e5484d`, text `#e5484d`, bg `rgba(229,72,77,0.08)`

---

## Left Sidebar (200px, fixed height, scrollable)

Section headers:
- 9px uppercase, `#4b5563`, 0.1em spacing, 24px row height
- Collapse triangle left of text

Tree rows (20px height):
- `[■■]` 2×2 status grid — each cell 10×10px, 1px gap, no border-radius
- Label 10px `#c8d6e0`
- Indent children 12px

Data rows:
- Count badge: `#4b5563` bg-less, right-aligned
- Source pills: `[V20] [V21] [MOD]` — flat, 9px, color per source, no border-radius

---

## Center Panel (flex-1)

### Timeline (full-width inside center)
- Height: 36px
- Track: `rgba(255,255,255,0.08)` line, 2px
- Elapsed fill: `#1d4ed8` → `#f97316` gradient, no glow
- Playhead diamond: `#f97316`, no box-shadow
- Status text: 8px `#4b5563`
- REPLAY button: right edge, 28px tall, flat, `#22c55e` text

### Event feed table
- Header row: 9px uppercase `#4b5563`, 22px tall, `rgba(255,255,255,0.04)` bg
- Data rows: 22px tall
  - TIME column: `#4b5563` monospace
  - SRC column: `#3b82f6` monospace, fixed 40px
  - COORD: `#374151` monospace
  - FRP: `rgba(249,115,22,0.8)` — only shown when present
  - INCIDENT: `rgba(229,72,77,0.7)` — overflow ellipsis
- Row divider: 1px `rgba(255,255,255,0.05)`
- Row hover: `rgba(255,255,255,0.03)`
- Counter row: 9px `#374151` at bottom

### Threat panel (replaces event feed when threat detected)
- Same surface `#111820`, 1px border `rgba(229,72,77,0.25)`
- Left accent bar: 3px solid `#e5484d`
- Rows: FRP / CONFIDENCE / DISTANCE / ZONE / POPULATION — key `#4b5563` / val `#c8d6e0`
- [OPEN INTELLIGENCE] button: flat, border `rgba(229,72,77,0.35)`, text `#e5484d`

---

## Map Panel (380px fixed right)

- Pure Mapbox — no legend overlay inside
- Map legend moves to bottom of left sidebar
- Navigation controls top-right (already there)
- Markers: white rounded-rect labels (flat, 2px radius, dark bg)

---

## Agent bar (bottom, full-width, 44px collapsed)

- Flat `rgba(13,17,23,0.97)` bg, 1px top border `rgba(255,255,255,0.08)`
- Session chips row: flat, `rgba(255,255,255,0.07)` border
- Input: plain text, `#c8d6e0`
- Send button: flat, no bg, right edge
- Active state: top border `rgba(34,197,94,0.3)` only — no glow

---

## What does NOT change

- All React component logic, state, API calls
- Map layers, GeoJSON sources, Mapbox setup
- Enhance overlay animation (stays as-is)
- Agent intelligence overlay panel
- Timeline logic / tick calculation
- Event stream data feed

---

## Files to touch

| File | What changes |
|---|---|
| `web/src/styles.css` | Full rewrite — new tokens, layout grid, all components |
| `web/src/ui/App.tsx` | Shell div gets new 3-column grid layout |
| `web/src/ui/MapPanel.tsx` | Remove map legend (moves to sidebar), panel is now right column |
| `web/src/ui/EventStream.tsx` | Table layout instead of floating overlay |
| `web/src/ui/Timeline.tsx` | Adjust to sit inside center panel, not header |
| `web/src/ui/StatsStrip.tsx` | Move to left sidebar as source tree rows |
| `web/src/ui/Controls.tsx` | Move into left sidebar sections (replay params) |
| `web/index.html` | Add Inter font via fontsource or link |
