# FireGuard Devpost Submission

## Inspiration

Wildfire response is a coordination problem before it is a map problem. A satellite hotspot can tell responders where heat was detected, but it does not answer the next operational questions: which populated zone is exposed, which shelters are open, which roads are constrained, and which route should evacuees take first.

FireGuard was inspired by that gap between detection and decision. We wanted the first high-risk signal to start an evacuation workflow automatically, gather source-backed context, and return a clear action an incident commander could inspect.

## What it does

FireGuard streams wildfire detections for a Williams Lake / Cariboo scenario, watches for high-FRP hotspots near evacuation zones, and starts the ADK intelligence flow when the threat threshold is met.

The ADK agent checks nearby evacuation zones, ESS shelters, road events, route safety, and fire context. It then produces an evacuation brief and pushes map annotations for the hotspot, affected zone, shelters, blockages, and evaluated routes.

The key output is not just "there is a fire." The key output is: who is affected, where they should go, which route is safest, what road constraints matter, and what action should happen now.

## How we built it

We built a FastAPI backend that creates Elasticsearch indexes, seeds packaged BC context, streams FIRMS replay events as NDJSON, and emits a narrow `threat` payload when a hotspot passes the configured threshold.

Elasticsearch is the geospatial evidence layer. FireGuard indexes FIRMS detections, evacuation zones, ESS shelters, road events, BCWS incidents, and BCWS perimeter shapes with stable `geo_point` and `geo_shape` mappings. The agent-facing FireGuard search tools query those indexes through the Elastic MCP server.

The intelligence runtime is Google ADK on Vertex AI Agent Runtime. FastAPI keeps a UI-compatible `/api/intelligence` contract for sessions, graph events, and chat history, while the actual agent execution is handled by the deployed Agent Runtime resource using Gemini 3.1 Pro.

The frontend is a React and Vite app with Mapbox GL JS. When the backend emits a threat, the UI opens the intelligence panel and passes the replay context into the ADK-backed route.

## Challenges we ran into

The hardest part was keeping the data contracts stable. Elasticsearch mappings reject later shape changes, so event payloads, location fields, weather fields, place fields, geometry fields, and route outputs had to stay consistent from ingestion through agent output.

Another challenge was making the workflow operationally disciplined. The route origin must be the evacuation zone centroid, not the hotspot. Shelters need to be checked by status before route selection. Road events need to be evaluated as constraints, not afterthoughts.

We also had to make the UI and agent route share one contract. The replay stream, threat payload, agent overlay, map annotation callback, action panel, and trace all needed to agree on the same state.

## Accomplishments that we're proud of

FireGuard connects detection to decision without an operator manually copying coordinates between systems.

We are proud of the automatic threat-to-agent handoff, the constrained evacuation tool sequence, the route what-if support, and the map annotation bridge that turns agent output into visible operational context.

We are also proud that the project has focused checks for the ADK route, Agent Runtime invocation, data contracts, and Vertex integration.

## What we learned

Agents work better when their tools reflect the operational question. For evacuation planning, the useful primitives are zone lookup, shelter status lookup, road-event lookup, route evaluation, map annotation, and structured completion.

We also learned that geospatial apps need stable payload shapes as much as they need good maps. A polished map can still fail the operator if the data contract changes midstream or if the route origin is ambiguous.

Finally, we learned that the trace matters. A judge or operator should be able to see the exact checks the agent performed before trusting the brief.

## What's next for Untitled

Next steps are to add routed driving directions, broaden the scenario set, add shelter capacity confirmation, strengthen action-card output, and extend the map overlay so route and zone recommendations stay visible after the agent finishes.

We would also add approval-gated notification actions, more regional datasets, and richer route alternatives for incidents where several corridors are constrained at once.

## Built with

Python, FastAPI, Pydantic, Elasticsearch, Google ADK, Vertex AI, React, Vite, TypeScript, Mapbox GL JS, NASA FIRMS, BCWS ArcGIS services, BC public emergency context snapshots, pytest.
