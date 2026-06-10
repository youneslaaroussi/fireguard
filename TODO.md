# TODO

## Critical — must ship before deadline

- [ ] **Frontend wiring: threat → evacuation workflow**
  - Restore `intelligencePrompt` state and `setView("intelligence")` in threat handler (App.tsx)
  - Pass `autoPrompt={intelligencePrompt}` + `workflowId="fireguard_evacuation"` to `AgenticIntelligenceApp`
  - Threat prompt should include: hotspot coords, zone name/population, date range, instruction to run full evacuation analysis

- [ ] **Add zone lat/lon centroid to threat payload** (main.py)
  - Current threat payload has zone `name/population/homes/distance_km` but no centroid
  - Add `latitude` and `longitude` to the zone object so agent can use them directly

- [ ] **Evacuation workflow in workflows.py** (Codex is on this)
  - `fireguard_evacuation` workflow: skips Chat Agent, Research → Writer → Style → Terminal
  - Specialized evacuation research system prompt with step-by-step instructions

- [ ] **Actions panel UI**
  - Agent emits structured decision via `emit_message` with `type: "evacuation_decision"`
  - Frontend renders action cards: 🔴 URGENT / 🟡 WARNING / 🟢 INFO / ⛔ BLOCKED
  - Each card: zone name, population, recommended action, route, shelter

- [ ] **Test full end-to-end flow**
  - Replay July 17–25 → threat fires on Williams Lake River Valley → agent auto-runs →
    finds all local shelters closed → recommends Merritt → produces brief
  - Test "what if Hwy 97 is blocked" hypothetical

## High value — do if time allows

- [ ] **Map overlays from agent decisions**
  - Zone polygons: red = evacuate order, yellow = alert
  - Route polyline: green = safe, red = unsafe
  - Shelter pins: green = open, grey = closed
  - Agent output includes polyline from `fireguard_evaluate_route` — use it

- [ ] **Elastic MCP badge / demo moment**
  - Current: all ES queries go through Elastic MCP Docker container (already wired in `_elastic_mcp_search`)
  - Add visible indicator in UI: "Powered by Elastic MCP" when queries run
  - Good for judges watching the demo

- [ ] **Google ADK integration**
  - ADK is in requirements.txt but vertex.py calls REST API directly
  - Either wire ADK properly or add a note in the README about why direct REST is used
  - Judges may check

- [ ] **Speed control on replay**
  - Current speed is hardcoded (14400 = 4h per second)
  - Add a UI control so demo presenter can speed up/slow down live

## Future (post-hackathon)

- [ ] **Google Routes API integration**
  - Currently using straight-line deterministic fallback (55 kph)
  - Google Routes API would give real driving directions + encoded polylines
  - Already have the old implementation in `/tmp/fireguard/apps/api/app/services/routes.py`
  - Needs GOOGLE_MAPS_API_KEY env var

- [ ] **Population notification tool**
  - Agent action: "send evacuation alert to all phones in zone X"
  - Could integrate Twilio or Google Cloud Pub/Sub
  - Demo value: agent doesn't just analyze, it acts

- [ ] **Multi-region scenarios**
  - Current data covers Williams Lake / Cariboo BC
  - Extend to other fire-prone regions: Fort McMurray, Kelowna, Northern California

- [ ] **Live mode (no replay)**
  - Pull NASA FIRMS NRT (near real-time) data for current active fires
  - Agent monitors continuously, triggers on new high-FRP detections
  - Real operational use case

- [ ] **Perimeter growth tracking**
  - Use BCWS perimeter polygons to track fire spread over time
  - Agent reasons about which zones will be threatened next based on perimeter expansion

- [ ] **Resource allocation**
  - Beyond routing: how many buses needed? Which routes need traffic control?
  - Integration with BC Emergency Management contacts

- [ ] **Multi-agent parallelism**
  - Spawn parallel subagents: one per zone, running route evaluation simultaneously
  - Current engine supports `spawn_fleet` — use it for large incidents

- [ ] **Confidence and uncertainty**
  - FIRMS confidence field (low/nominal/high) affects trigger threshold
  - Agent should communicate uncertainty: "2 high-confidence detections vs 8 nominal"

- [ ] **Historical incident database**
  - Index past BC wildfire events for agent to reference
  - "Similar fire in 2017 Spokin Lake took 3 days to reach Williams Lake"
