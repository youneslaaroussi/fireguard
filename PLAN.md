# FireGuard — Project Plan

## What This Is

FireGuard is an AI-powered wildfire evacuation coordination platform built for the
**Google Cloud Rapid Agent Hackathon (Elastic track)**, deadline June 11, 2026 at 6PM ADT.

The core idea: when a wildfire threat is detected near a populated evacuation zone, an AI agent
automatically triggers and produces a complete evacuation decision — which zones to evacuate in
what order, which shelters are actually open, which routes are safe, and what actions the incident
commander should take right now. The agent can then answer "what if" questions live (what if
Highway 97 is blocked? what if Railyard Mall reaches capacity?).

This is not a data visualization tool. The agent makes decisions.

---

## The Real Event

**Williams Lake River Valley wildfire — July 21, 2024**

- **Ignition**: ~5:45 PM, July 21, 2024. A tree fell on power lines on the southwest outskirts of the city.
- **Behavior**: Fast-moving. Burned straight to the city boundary before crews stopped it. Mayor: *"dodged a potential disaster."* *"a close call."*
- **Size**: 40 hectares, held at the city boundary by large airtankers + water skimmers on Williams Lake (the lake body).
- **Emergency declared**: Same evening, July 21. Local state of emergency.
- **Evacuation type**: Alert (be ready to leave), not a full mandatory order. River Valley Road corridor told to avoid the area.
- **Shelters activated for Williams Lake**: None named publicly — fire was contained before mass displacement occurred.
- **Highway 97**: Not closed near Williams Lake. Main artery stayed open.
- **Highway 1 (Spences Bridge–Cache Creek)**: CLOSED July 22 due to concurrent Shetland Creek fire — complicates southbound routes toward Merritt/Vancouver.
- **Alert lifted**: Approximately July 26–28, 2024.

**Concurrent fires burning the same weekend:**
- **Antler Creek wildfire** (90 km NE, Barkerville area): Started July 20. 3,400 ha by July 22, grew to 14,000 ha Groundhog Complex. Mandatory evacuation orders for 431 parcels, District of Wells (1,000 residents). Evacuees sent to **Quesnel**. Highway 26 closed.
- **Shetland Creek wildfire** (Spences Bridge): 17,000–22,000 ha. Highway 1 closed. 6+ homes destroyed.
- **324 total active fires** in BC on July 22, 2024.

**Why this is the right scenario for the walkthrough**: The Williams Lake fire was held at 40 ha — but
it burned to the city boundary in under an hour after ignition. One unfavorable wind shift and
it's inside the residential grid. The mayor called it a near-miss. At that moment of maximum
threat (fire at the boundary, alert issued), human coordinators would have needed to answer:
which shelter do we send 1,500 people to? All five Williams Lake ESS facilities are closed.
The nearest open facility is 200 km away. The main southern highway has a concurrent closure.
Quesnel is already receiving evacuees from a different fire. That coordination problem is exactly
what FireGuard solves — automatically, in under 2 minutes, from satellite data alone.

---

## The Demo Narrative

**Premise**: It's July 21, 2024. FireGuard is running. The satellite passes overhead.

1. Operator opens FireGuard. Map centered on Williams Lake / Cariboo, BC.
2. Hit **REPLAY**. Real NASA FIRMS satellite hotspot data streams in, July 17–25, 2024.
   Detections appear on the map as they arrived in near-live cadence.
3. July 21, ~6 PM: A cluster of high-FRP detections appears southwest of Williams Lake.
   Fire intensity crosses threshold (≥ 50 MW within 150 km of the Williams Lake River Valley zone centroid).
   **Threat chip flashes. View auto-switches to intelligence panel.**
4. Agent auto-triggers `fireguard_evacuation` workflow — no human click required:
   - **Zone scan**: Williams Lake River Valley → 1,548 people, 618 homes — **PRIORITY 1**
   - **Shelter scan**: Williams Lake × 5 — **ALL CLOSED**. 100 Mile House × 3 — **ALL CLOSED**. Quesnel — **CLOSED**. Railyard Mall Merritt — **OPEN** ← only option.
   - **Road events**: Little Lake / Quesnel River Rd — closed (washout, no detour). Hwy 1 at Spences Bridge — concurrent closure.
   - **Route eval**: Williams Lake → Merritt via Hwy 97 South — 200 km, ~2.5 h, clears fire buffer — **SAFE**
   - **Route eval**: Williams Lake → Quesnel via Hwy 97 North — 120 km, ~1.5 h — but Quesnel absorbing Antler Creek evacuees.
5. Agent produces evacuation brief + action cards:
   - 🔴 URGENT: Evacuate Williams Lake River Valley (1,548 ppl) → Railyard Mall, Merritt via Hwy 97 South
   - 🟡 WARNING: Spokin Lake Road (1,292 ppl, 1,061 homes) — prepare order now
   - ⚠️ CAPACITY NOTE: Quesnel receiving Antler Creek evacuees — confirm capacity before routing north
   - ⛔ ALL LOCAL SHELTERS CLOSED — do not direct evacuees to any Williams Lake ESS facility
   - 🚧 CLOSURES: Little Lake / Quesnel River Rd (washout) · Hwy 1 at Spences Bridge (Shetland Creek fire)
6. Judge: *"What if Highway 97 South is also blocked?"*
   Agent calls `fireguard_evaluate_route` with `hypothetical_closures` injected on Hwy 97 South,
   re-evaluates, surfaces Quesnel as fallback with capacity caveat, recommends confirming before routing.

**The line for judges**: *"The Williams Lake mayor called this a near-miss. FireGuard had the
evacuation plan — routes, shelters, closures, zone priorities — before the fire crossed the city
boundary. Every local shelter was closed. The only open facility was 200 km away. Two concurrent
road closures affected the route network. Quesnel had a capacity problem from a different fire.
A human coordinator would need hours to piece this together. The agent did it in under two minutes,
automatically, the moment the satellite data came in."*

---

## Why This Wins

**Elastic track requirements:**
- Elastic MCP server integration for agent-facing ES queries
- Meaningful use of Elasticsearch: `geo_distance`, `geo_shape`, and multi-index queries
- NASA FIRMS, BCWS incidents/perimeters, evacuation zones, shelters, and road events indexed into ES

**Google Cloud requirements:**
- Gemini 3.1 Pro through Vertex AI
- Google ADK on Vertex AI Agent Runtime
- Cloud Run / GCP deployment path in `infra/`

**What separates this from a chatbot with a map:**
- Server-side paced replay — data arrives as the incident window advances, not as a pre-loaded animation
- Inline threat trigger — fires at the correct moment during replay, not post-hoc
- Agent makes actual decisions (zone priority, route safety, shelter availability)
- "What if" hypotheticals — operator injects new constraints, agent re-plans live
- Source-backed data: NASA FIRMS API, BC government open data, DriveBC road events

**Judges remember:**
1. The moment the threat chip flashes and the agent kicks off automatically
2. Finding out all local shelters are closed and the agent adapts
3. The "what if Highway 97 is blocked" live re-plan

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Data | NASA FIRMS API (VIIRS/MODIS SP historical archive) |
| Storage | Elasticsearch (local + cloud) |
| ES integration | Elastic MCP server (Docker, stdio transport) |
| Backend | FastAPI (Python), uvicorn |
| AI | Vertex AI Agent Runtime with Gemini 3.1 Pro Preview |
| Agent framework | Google ADK agent behind the Agent Runtime API |
| Frontend | React + Vite + TypeScript + Mapbox GL JS |
| Infra | GCP Cloud Run, Docker |

---

## Workflows

### `fireguard_adk` (chat)
Human Trigger → Data Checks → ADK Agent → Response

Used for: operator-initiated questions and analysis.

### `fireguard_adk` (auto-trigger)
Human Trigger → Data Checks → ADK Agent → Response

Used for: automatic threat trigger from replay. The Data Checks phase runs FireGuard evidence tools through Elastic MCP, then the ADK agent writes the evacuation brief from the compact evidence package.

---

## Agent Tools

| Tool | Purpose |
|------|---------|
| `fireguard_search_zones` | Evacuation zones by location/radius |
| `fireguard_search_shelters` | ESS facilities, filter by status (OPEN/CLOSED) |
| `fireguard_search_road_events` | DriveBC road closures near a point |
| `fireguard_evaluate_route` | Route safety: checks against fires + closures. Supports `hypothetical_closures` and `ignore_closures` for what-if analysis. |
| `fireguard_search_events` | FIRMS satellite detections by location/time |
| `fireguard_bcws_context` | BCWS official incidents + fire perimeters |
| `fireguard_map_annotation` | Markers and route overlays for the map |
| `fireguard_actions` | Structured incident commander action plan |

---

## Data Seeded in Elasticsearch

| Index | Contents |
|-------|---------|
| `fireguard-firms` | NASA FIRMS satellite hotspot detections (live via API) |
| `fireguard-bcws-incidents` | BCWS active fire incidents |
| `fireguard-bcws-perimeters` | BCWS fire perimeters (geo_shape) |
| `fireguard-zones` | 3 BC evacuation zones with GeoJSON polygons |
| `fireguard-shelters` | 10 ESS facilities (Williams Lake × 5, 100 Mile House × 3, Quesnel × 1, Merritt × 1) |
| `fireguard-road-events` | DriveBC road closures (Little Lake / Quesnel River Road) |

---

## Replay Scenario

**Area**: 52.5°N, 120.0°W, radius 400 km (covers Williams Lake / Cariboo)
**Dates**: July 17–25, 2024
**Sources**: VIIRS_NOAA20_SP, VIIRS_SNPP_SP, MODIS_SP (VIIRS_NOAA21_SP excluded — HTTP 400 for this date range)
**Trigger threshold**: FRP ≥ 50 MW within 150 km of a zone centroid
**Trigger zone**: Williams Lake River Valley (1,548 population, 618 homes)

---

## Key Files

```
app/
  main.py              — FastAPI backend, replay_lines generator, threat trigger logic
  geo.py               — Geospatial utilities (haversine, polyline distance)
  agent_runtime/
    api.py             — UI-compatible route backed by Agent Runtime
    fireguard_agent.py — Google ADK agent definition
web/
  src/
    ui/
      App.tsx          — Main app, replay state, threat handler, view switching
      MapPanel.tsx     — Mapbox map with overlays
      Timeline.tsx     — Replay timeline + progress
      EventStream.tsx  — Live event feed
    intelligence/
      App.tsx          — Intelligence panel, workflow runner
data/
  public/bc/
    historical_fire_evacuation_zones_snapshot.json
    public_emergency_context_snapshot.json
  replay/bc_cariboo/
    road_events_snapshot.json
```
