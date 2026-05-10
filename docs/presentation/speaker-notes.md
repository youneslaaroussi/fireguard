# FireGuard Presentation Speaker Notes

Target runtime: 2:30-3:00.

## 1. FireGuard

FireGuard is a wildfire evacuation orchestration agent. It turns real wildfire, road, weather, shelter, and zone context into a staged plan that stays under human approval.

## 2. Coordination Gap

The problem is not that emergency data does not exist. Fire detections, road closures, weather, shelter context, and zone data usually live in separate systems. FireGuard is the coordination layer.

## 3. Signal To Action

Fivetran brings source feeds into BigQuery. Elastic indexes the operational memory. Routes and risk services create safe primitives. Gemini selects the plan. Validators enforce safety. The commander approves. Then actions execute and every step is traced.

## 4. Route Rejection

The key demo moment is route rejection. The obvious path is fastest, but it crosses operational constraints. FireGuard chooses a safer alternate path and stages the evacuation instead of blindly optimizing for travel time.

## 5. Gemini And Validators

Gemini is used for strategy composition: sequencing, timing, tradeoffs, messages, and rejected alternatives. Deterministic code owns geometry, route safety, evidence requirements, freshness checks, approvals, and allowlists.

## 6. Provider Proof

Each provider does actual work. Fivetran ingests feeds. Elastic retrieves geospatial evidence. Vertex/Gemini selects the plan. Phoenix/Arize records traces. Twilio sends the test SMS. Google Cloud hosts the app and API.

## 7. Approval

The agent prepares action bundles, but public-facing actions cannot execute until a human approves them. In the demo, approval sends a test SMS and creates operational task records.

## 8. Close

FireGuard turns fragmented emergency signals into coordinated action. The value is not another map; it is the loop from real data to validated plan to approved execution to audit trail.
