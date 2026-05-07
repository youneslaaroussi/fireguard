# FireGuard Demo Script

Target length: under 3 minutes.

## 0:00-0:20 Opening

During wildfires, the problem is not that there is no data. Fire data exists, road data exists, shelter data exists, and weather data exists. The problem is that they live in separate systems while humans coordinate under pressure.

## 0:20-0:45 Live Context

Fivetran ingests wildfire, road, and weather data into BigQuery. FireGuard syncs that operational feed into Elastic so the agent can reason over geospatial context instead of chat history.

Show the provider strip: Fivetran ingestion, Elastic memory, Gemini tool calls, and Arize Phoenix traces. Then show fire, road, shelter, and zone layers.

## 0:45-1:30 Agent Assessment

Click `Run Agent Assessment`.

The nearest route from Zone A looks fastest, but FireGuard rejects it because it intersects a road closure and a wildfire risk buffer. It also sees that the nearest shelter cannot absorb the full load.

## 1:30-2:10 Staged Plan

Show:

- Zone A evacuates now to Shelter B.
- Zone B waits 15 minutes to prevent a bottleneck.
- Zone C shelters in place while a dispatch task is created for a human dispatcher to assign accessible transport if available.

This is why FireGuard is an agent, not a dashboard. It sequences actions across residents, shelters, roads, and dispatch.

## 2:10-2:35 Approval And Execution

Click approve, then execute.

Show SMS, shelter webhook, road ops task, dispatch task, and action timeline.

## 2:35-3:00 Audit

Every action is auditable: source records, freshness, confidence, rejected options, Phoenix traces, eval checks, and human approval. FireGuard acts fast, but never invisibly.
