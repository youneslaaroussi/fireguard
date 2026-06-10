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

## The Demo Narrative

**Event**: Williams Lake River Valley wildfire, July 21, 2024, British Columbia.

A real wildfire that forced the evacuation of part of the City of Williams Lake.
Real coordination failures happened. This is what FireGuard would have done differently.

**Demo flow**:

1. Operator opens FireGuard. The map shows the Williams Lake / Cariboo region.
2. Hit REPLAY. Real NASA FIRMS satellite hotspot data streams in from July 17–25, 2024.
   Fire detections appear on the map as they would have arrived in near-real-time.
3. July 21: fire intensity near Williams Lake crosses the FRP threshold (≥ 50 MW within 150 km
   of a populated evacuation zone). The threat chip flashes.
4. The agent auto-triggers. The intelligence panel opens. The evacuation workflow runs:
   - Scans 3 evacuation zones by population priority
   - Finds all Williams Lake ESS facilities: **ALL CLOSED**
   - Finds Railyard Mall in Merritt (200 km south): **OPEN** — only option in 300 km
   - Evaluates route: Williams Lake → Merritt via Hwy 97 South — clear, 2.5 h
   - Notes Little Lake / Quesnel River Road closure (washout, no detour)
5. Agent produces structured evacuation brief + action cards:
   - 🔴 URGENT: Evacuate Williams Lake River Valley (1,548 people) → Merritt via Hwy 97 South
   - 🟡 WARNING: Alert Spokin Lake Road (1,292 people, 1,061 homes) — prepare order
   - 🟢 INFO: Browntop Mountain (18 people) — self-evacuate advisory
6. Judge asks: "What if Highway 97 South is also blocked?"
   Agent re-runs `fireguard_evaluate_route` with a hypothetical closure injected, finds the
   Quesnel alternative (north, 120 km), produces updated brief.

**The story for judges**: in the real July 2024 event, coordination was slow. Families didn't
know where to go. Shelters weren't pre-confirmed. FireGuard would have answered those questions
in under 2 minutes, automatically, the moment the satellite data came in.

---

## Why This Wins

**Elastic track requirements:**
- Elastic MCP server integration ✓ (all agent ES queries go through MCP Docker container)
- Meaningful use of Elasticsearch (geo_distance, geo_shape, multi-index queries)
- Real data indexed into ES (NASA FIRMS, BCWS incidents/perimeters, evac zones, shelters, road events)

**Google Cloud requirements:**
- Gemini via Vertex AI (production model, not OpenAI)
- Google ADK in requirements.txt (used or easily demonstrable)
- Real infrastructure: Cloud Run / GCP deployment ready (infra/ directory)

**What separates this from a chatbot with a map:**
- Server-side paced replay — data arrives in simulated real-time, not pre-loaded animation
- Inline threat trigger — fires at the correct moment during replay, not post-hoc
- Agent makes actual decisions (zone priority, route safety, shelter availability)
- "What if" hypotheticals — operator injects new constraints, agent re-plans live
- All data is real: NASA FIRMS API, BC government open data, DriveBC road events

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
| AI | Vertex AI (Gemini 1.5 Pro) via custom HTTP client |
| Agent framework | Custom agentic engine (workflows.py, vertex.py) + Google ADK |
| Frontend | React + Vite + TypeScript + Mapbox GL JS |
| Infra | GCP Cloud Run, Docker |

---

## Workflows

### `fireguard_intelligence` (chat)
Human Trigger → Chat Agent → Research Agent → Writer Agent → Style Agent → Terminal

Used for: operator-initiated questions and analysis.

### `fireguard_evacuation` (auto-trigger)
Human Trigger → Research Agent → Writer Agent → Style Agent → Terminal

Used for: automatic threat trigger from replay. Skips chat routing, goes straight to analysis.
Research agent is pre-configured with evacuation analysis instructions.

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
| `fireguard_stats` | Index counts and time bounds |
| `exa_search` | Live web research |
| `sandbox_exec` | Python computation in Docker sandbox |

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
  agentic/
    tools.py           — All agent tool implementations
    workflows.py       — Workflow definitions (intelligence + evacuation)
    vertex.py          — Vertex AI HTTP client (streamGenerateContent)
    engine.py          — Agentic engine runtime
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
