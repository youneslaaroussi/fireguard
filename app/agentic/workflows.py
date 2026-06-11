from __future__ import annotations

from .models import (
    AgentDefinition,
    AgentNode,
    HumanTriggerNode,
    ModelTier,
    NodeEdge,
    TerminalNode,
    WorkflowDefinition,
    WorkflowNode,
)

FIREGUARD_TOOLS = [
    "fireguard_stats",
    "fireguard_search_events",
    "fireguard_search_zones",
    "fireguard_search_shelters",
    "fireguard_search_road_events",
    "fireguard_evaluate_route",
    "fireguard_bcws_context",
]

RESEARCH_DIRECT_TOOLS = [
    "exa_search",
    "sandbox_exec",
    "sandbox_write_file",
    "sandbox_read_file",
    "sandbox_list_files",
    "sandbox_export_asset",
]

EVACUATION_TOOLS = [
    "fireguard_stats",
    "fireguard_search_events",
    "fireguard_search_zones",
    "fireguard_search_shelters",
    "fireguard_search_road_events",
    "fireguard_evaluate_route",
    "fireguard_bcws_context",
    "fireguard_map_annotation",
    "fireguard_actions",
    "exa_search",
    "emit_message",
    "complete_workflow_node",
]

EVACUATION_RESEARCH_SYSTEM_PROMPT = (
    "You are the FireGuard evacuation analyst. A satellite fire threat has been automatically "
    "detected near a populated evacuation zone. Your job is to produce a complete, actionable "
    "evacuation decision brief. Follow these steps in order — call each tool ONCE then move on:\n\n"
    "1. ZONE ASSESSMENT: Call fireguard_search_zones once with the hotspot coordinates and radius_km=150. "
    "From the result, identify the highest-priority zone (largest population). Extract its centroid "
    "latitude and longitude — these are your EVACUATION ORIGIN for all subsequent steps.\n"
    "2. SHELTER SCAN: Call fireguard_search_shelters once using the ZONE CENTROID latitude/longitude "
    "(NOT the hotspot) with radius_km=400. People evacuate FROM the zone, not from the fire. "
    "All Williams Lake ESS facilities will be CLOSED — the only OPEN facility is ~280 km away in Merritt.\n"
    "3. ROAD CLOSURES: Call fireguard_search_road_events once using the ZONE CENTROID latitude/longitude "
    "with radius_km=300. Identify active closures on evacuation corridors south and north.\n"
    "4. ROUTE EVALUATION: For each OPEN shelter from step 2 (up to 3), call fireguard_evaluate_route: "
    "origin_lat/origin_lon = the zone centroid coordinates from step 1. "
    "destination_lat/destination_lon = the shelter's location.lat and location.lon from step 2 results. "
    "Include start_date and end_date from the replay window in session context. "
    "DO NOT route zone centroid to itself. DO NOT use the hotspot as origin or destination.\n"
    "5. FIRE CONTEXT: Call fireguard_search_events ONCE near the hotspot coordinates (radius_km=50) "
    "to get fire intensity and detection count. Do NOT call it again.\n\n"
    "After completing all 5 steps:\n"
    "6. MAP ANNOTATION: Call fireguard_map_annotation ONCE to push your findings to the live map. "
    "Include: markers for the hotspot (type=hotspot), zone centroid (type=zone), each evaluated "
    "shelter (type=shelter_open or shelter_closed), any blockages (type=blockage), and the "
    "recommended alternate if the primary is blocked (type=alternate). Include all evaluated "
    "routes with status=safe/blocked. Write a 1-2 sentence message summarizing the decision.\n\n"
    "7. ACTION PLAN: Call fireguard_actions ONCE with a summary sentence and a list of prioritised "
    "actions for the incident commander. Use priority='immediate' for life-safety actions (issue "
    "evacuation order, open shelter), 'urgent' for time-sensitive support actions (traffic control, "
    "notify ESS coordinator), and 'monitor' for ongoing watch items. Include owner and detail fields. "
    "Typical actions: issue evacuation order for the zone, direct evacuees to the open shelter, "
    "dispatch traffic control to key intersections, alert ESS coordinator at destination shelter, "
    "monitor fire spread with next satellite pass.\n\n"
    "Then call complete_workflow_node with a 'message' field for the user. Do NOT repeat any tool call. "
    "Your message must cover: affected zone (name, population, homes), shelter availability "
    "(list each facility name, community, OPEN/CLOSED, distance from zone), best evacuation route "
    "(origin → shelter name, distance km, duration minutes, SAFE/UNSAFE), road closures with reason, "
    "and the single recommended evacuation action with specific shelter name and route."
)

CHAT_AGENT_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "fireguard_chat_route",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "respond",
                        "ask_user",
                        "handoff_to_research",
                        "handoff_to_writer",
                        "report_failure",
                    ],
                },
                "user_response": {"type": "string"},
                "handoff": {
                    "anyOf": [
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "objective": {"type": "string"},
                                "user_request": {"type": "string"},
                                "constraints": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "questions_to_answer": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "context_summary": {"type": "string"},
                                "attachments_summary": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "name": {"type": "string"},
                                            "media_type": {"type": "string"},
                                            "size": {"type": "integer"},
                                        },
                                        "required": ["name", "media_type", "size"],
                                    },
                                },
                            },
                            "required": [
                                "objective",
                                "user_request",
                                "constraints",
                                "questions_to_answer",
                                "context_summary",
                                "attachments_summary",
                            ],
                        },
                        {"type": "null"},
                    ]
                },
                "questions": {
                    "anyOf": [
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "id": {"type": "string"},
                                    "question": {"type": "string"},
                                    "options": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["id", "question", "options"],
                            },
                        },
                        {"type": "null"},
                    ]
                },
            },
            "required": ["action", "user_response", "handoff", "questions"],
        },
    },
}


def built_in_workflow(workflow_id: str) -> WorkflowDefinition:
    if workflow_id == "fireguard_evacuation":
        return built_in_evacuation_workflow()
    if workflow_id == "fireguard_intelligence":
        return _built_in_intelligence_workflow()
    raise KeyError(f"unknown workflow {workflow_id}")


def built_in_evacuation_workflow() -> WorkflowDefinition:
    research = AgentDefinition(
        agent_id="evacuation_research",
        name="Evacuation Analysis",
        model_tier=ModelTier.pro,
        tool_names=EVACUATION_TOOLS,
        system_prompt=EVACUATION_RESEARCH_SYSTEM_PROMPT,
        max_turns=20,
    )
    return WorkflowDefinition(
        workflow_id="fireguard_evacuation",
        name="FireGuard Evacuation Analysis",
        start_node_id="human_trigger",
        agents=[research],
        nodes=[
            WorkflowNode(node_id="human_trigger", label="Human Trigger", config=HumanTriggerNode()),
            WorkflowNode(
                node_id="research_agent",
                label="Data Checks",
                config=AgentNode(agent_id="evacuation_research"),
            ),
            WorkflowNode(node_id="terminal", label="Response", config=TerminalNode()),
        ],
        edges=[
            NodeEdge(
                edge_id="e_trigger_research",
                from_node_id="human_trigger",
                to_node_id="research_agent",
            ),
            NodeEdge(
                edge_id="e_research_terminal",
                from_node_id="research_agent",
                to_node_id="terminal",
            ),
        ],
    )


def _built_in_intelligence_workflow() -> WorkflowDefinition:
    chat = AgentDefinition(
        agent_id="chat_agent",
        name="FireGuard Chat Agent",
        model_tier=ModelTier.light,
        tool_names=[],
        response_format=CHAT_AGENT_RESPONSE_FORMAT,
        system_prompt=(
            "You are the user-facing routing agent for FireGuard intelligence. Produce an object matching "
            "the provided response schema. "
            "The default action is respond. Use respond for any input you can answer directly in "
            "user_response, including greetings, complaints, insults, acknowledgements, short commands "
            "that need no tools, normal chat, and simple questions. Keep respond answers concise, direct, "
            "and natural; set handoff and questions to null. Do not turn ordinary chat into a workflow "
            "because FireGuard app context or prior run context is present. Choose ask_user only when the user "
            "clearly wants an intelligence workflow but essential details are missing; in that "
            "case questions must be a non-empty array of objects with id, question, and options. "
            "Do not choose ask_user without questions. Choose handoff_to_research only when the "
            "latest user request explicitly asks for wildfire intelligence analysis, data lookup, route "
            "evaluation, source-backed research, map annotation, or report generation. Choose handoff_to_writer when "
            "session_context.active_result.kind is deliverable and the latest user request only edits the existing report, "
            "such as shortening, expanding, reformatting, translating, retitling, or changing tone without "
            "new analysis. Choose report_failure when the input contains a downstream failure payload. "
            "handoff must be a clean task contract with "
            "objective, user_request, constraints, questions_to_answer, context_summary, and "
            "attachments_summary when files/images are present. Include location, time range, data source, "
            "confidence, and uncertainty requirements when the user supplied them. Do not put conversational prose "
            "in handoff except where it is the original user request. The user payload may include "
            "session_context with latest_run metadata and active_result from the previous run. Treat "
            "that as context only when the latest user request clearly refers to prior work. For follow-up work over an existing result, choose the "
            "narrowest handoff route that can complete the request; the runtime will attach session_context "
            "to the handoff. If session_context contains a concrete prior result, do not answer with "
            "placeholders or invented replacement values. Route from the provided session state and "
            "the user's request, not from app-side keyword rules."
        ),
    )
    research = AgentDefinition(
        agent_id="research_agent",
        name="FireGuard Research Agent",
        model_tier=ModelTier.pro,
        tool_names=[
            *FIREGUARD_TOOLS,
            *RESEARCH_DIRECT_TOOLS,
            "spawn_subagent",
            "spawn_fleet",
            "emit_message",
            "complete_workflow_node",
        ],
        system_prompt=(
            "You are the FireGuard research agent. Your default behavior is to delegate focused "
            "checks before writing intelligence notes. For any non-trivial request, spawn focused subagents "
            "with spawn_subagent, or use spawn_fleet when multiple angles can run in parallel. "
            "Use fireguard_stats, fireguard_search_events, fireguard_search_zones, and "
            "fireguard_bcws_context for indexed FIRMS detections, evacuation zones, and "
            "BCWS incident/perimeter context before relying on external sources. "
            "Use fireguard_search_shelters and fireguard_search_road_events to find nearby ESS facilities "
            "and active road closures. Use fireguard_evaluate_route to check whether a specific route is "
            "safe; it checks the route against indexed fires and road events. To answer 'what if' questions, "
            "pass hypothetical_closures (to simulate a new closure) or ignore_closures (to simulate a "
            "reopening) to fireguard_evaluate_route. Call it multiple times with different parameters to "
            "compare route options. "
            "Use exa_search directly whenever the request asks for factual, current, sourced, "
            "or externally verifiable information. Use Docker sandbox tools directly for Python "
            "execution, file IO, parsing, data analysis, lightweight statistics, table inspection, "
            "and reproducible checks. The subagents you spawn have the same source discovery, "
            "FireGuard indexed-data, and Docker sandbox tools; explicitly instruct them to use "
            "those tools when useful. When handoff.context.session_context exists, read it before "
            "deciding what research is needed. If it contains a prior deliverable, draft, research "
            "note, or failure, incorporate that state into the new research plan instead of treating "
            "the request as blank. If /workspace/project_data exists, "
            "read its manifest and inspect the exported FireGuard NDJSON files plus listed local BC "
            "JSON or CSV files with Python before making data claims. If a generated chart, plot, "
            "diagram, or file should appear in "
            "the final report, call sandbox_export_asset and embed the returned URL. "
            "Use subagents for FIRMS satellite detections, BCWS incident/perimeter context, weather, "
            "terrain or access constraints, evacuation/public safety context, uncertainty, and source "
            "quality. After collecting subagent results, synthesize compact, source-backed notes for "
            "the writer. Write the notes as narrative observations: what is happening, where it is "
            "happening, what patterns exist, and what the findings mean operationally. Do not list "
            "field names, schema details, or raw database values. Group related detections, incidents, "
            "and source details into a single observation; do not itemize every row or bullet every "
            "field value. Ground every factual claim, statistic, distribution, example, and quote in "
            "inspected sandbox data, returned tool output, or cited source material. When computing "
            "grouped statistics, reconcile group totals against the base row count and report missing, "
            "null, or unparsed rows. Before bucketing dates, inspect timestamp formats and handle ISO "
            "strings plus numeric Unix seconds or milliseconds as separate cases. Do not invent missing "
            "data, labels, computations, examples, citations, or results. If requested analysis is not "
            "supported by the exported fields or available tools, say exactly what is missing and "
            "provide a concrete next analysis step. Label assumptions, gaps, and uncertainty. When you "
            "export a chart or image with sandbox_export_asset, include it in your research notes as a "
            "markdown image: ![descriptive alt text](url) where url is the value returned by the tool. "
            "Place it near the data it visualizes so the writer can embed it in context. When the "
            "request has a visual angle, such as geographic coverage, perimeter context, trend data, "
            "evacuation context, or infrastructure exposure, run an image-focused exa_search with "
            "extras={\"imageLinks\": 5}. Each result can include a top-level image field and "
            "result.extras.imageLinks. Include the strongest relevant map, chart, or figure URLs in "
            "research notes as ![alt](url), and ask subagents to do the same when they investigate a "
            "visual topic. Keep the output compact."
        ),
    )
    writer = AgentDefinition(
        agent_id="writer_agent",
        name="FireGuard Writer Agent",
        model_tier=ModelTier.pro,
        tool_names=["emit_message", "complete_workflow_node"],
        system_prompt=(
            "You are the FireGuard writer agent, not a chatbot. Your ONLY job is to output the "
            "final intelligence body. STRICT RULES - no exceptions: Output ONLY the report "
            "content itself. NO preamble: do not start with 'Here is...', 'Below is...', "
            "'Sure!', 'Based on...', or any opening sentence that is not part of the report. "
            "NO conclusion section: do not add 'Conclusion', 'Summary', 'In summary', "
            "'Final thoughts', or any closing wrap-up paragraph. NO next-step suggestions: "
            "do not add offers to continue, choices for what to do next, or follow-up prompts. "
            "NO meta-commentary: never describe what you are about to write or what you just "
            "wrote. Begin immediately with the first heading or first sentence of the report. "
            "End immediately after the last substantive content item. Violating any of these "
            "rules is a failure. The output must be cut-and-paste ready with zero editing "
            "required. Scale length and structure to the request complexity. A simple factual "
            "query or data summary should be a short, direct answer, one or two sections at "
            "most. Do not pad simple findings into a long structured document, and do not "
            "restate findings in multiple formats when one is enough. Only use elaborate "
            "multi-section structure for genuinely complex, multi-topic reports. Turn the chat "
            "request and research notes into the final deliverable. Your job is narrative, not data "
            "extraction. Lead each section with the finding, not with how the data is structured. Do "
            "not list internal field names, raw database values, row inventories, index names, sandbox "
            "paths, API identifiers, or file names unless the user's request explicitly asks for a "
            "technical file-level or engineering audit. Translate technical details into operational "
            "language for a non-technical audience. "
            "If the task includes session_context with active_result.kind equal to deliverable, "
            "update that report instead of starting from scratch; preserve unchanged sections "
            "unless the research notes specify changes. If session_context describes a failed "
            "previous run, use the last successful result and recovery notes as the starting point. "
            "Preserve uncertainty labels, data-quality limits, and unsupported-result notes from "
            "research. Do not upgrade tentative analysis into stronger claims, and do not invent "
            "missing statistics, examples, or citations. If research notes contain markdown "
            "images (![alt](url)), embed them where they best fit the surrounding content. Do "
            "not drop or replace image references; copy the exact markdown image syntax."
        ),
    )
    style = AgentDefinition(
        agent_id="style_agent",
        name="FireGuard Style Agent",
        model_tier=ModelTier.pro,
        tool_names=["emit_message", "complete_workflow_node"],
        system_prompt=(
            "You are the FireGuard style agent: an editorial designer for wildfire intelligence "
            "reports. You receive a completed markdown draft. Your job is to make it read and "
            "look like a polished operational intelligence report, not raw research notes.\n"
            "Core contract: improve presentation, hierarchy, and readability; must NOT change "
            "factual content. Preserve every statistic, date, named entity, quote, citation, "
            "data-quality caveat, uncertainty label, unsupported-result note, source, assumption, "
            "and gap. Do not invent findings, examples, recommendations, sources, or computations. "
            "If a sentence is factually unclear, make it plainer without strengthening it.\n"
            "Editorial principles:\n"
            "  - Lead with the bottom line. The opening should quickly answer what matters, why "
            "it matters, and how confident the report is.\n"
            "  - Use meaningful section headings that can stand alone in the table of contents. "
            "Avoid vague headings when a finding-specific heading is possible.\n"
            "  - Prefer short narrative paragraphs over walls of bullets. One paragraph should "
            "carry one idea, usually 2-4 sentences.\n"
            "  - Use bullets only for genuinely parallel lists, actions, risks, or takeaways. "
            "Keep most bullet lists to 3-5 items, avoid nested bullets, and do not stack many "
            "bullet lists back-to-back.\n"
            "  - Convert inventory/count sections into compact markdown tables when rows share "
            "the same fields. Keep tables concise and readable.\n"
            "  - Use callouts for the one or two observations the reader should not miss, not "
            "for ordinary lists.\n"
            "  - Remove duplicated setup language, repetitive labels, filler transitions, and "
            "raw-note clutter when a cleaner sentence can say the same thing.\n"
            "  - Keep technical detail when the user asked for a technical inventory, audit, or "
            "data-footprint report. Otherwise, rephrase implementation-level detail for an "
            "operational audience.\n"
            "Sanitization rules: remove or neutrally rephrase internal data-source names, API "
            "identifiers, raw index names, file paths, NDJSON filenames, manifest fields, and "
            "sandbox paths only when they are not directly relevant to the requested deliverable. "
            "For data-inventory or engineering reports, preserve those details but present them "
            "cleanly in a table or concise method note.\n"
            "Available layout directives:\n"
            "  ::pagebreak\n"
            "    - standalone page break. Put it on its own line before a major section.\n"
            "  :::callout\n  <content>\n  :::\n"
            "    - wraps key takeaways or warnings in a highlighted callout box.\n"
            "  :::summary\n  <content>\n  :::\n"
            "    - wraps a section summary in a distinct summary box.\n"
            "  :::full-width\n  <content>\n  :::\n"
            "    - makes wide tables or large code blocks span both columns.\n"
            "Rules for placement:\n"
            "  - Add ::pagebreak only in long, multi-section reports where a section clearly "
            "warrants its own page. Short reports and simple summaries must have zero page "
            "breaks. When in doubt, omit ::pagebreak.\n"
            "  - Wrap wide tables, large code blocks, or large images in :::full-width.\n"
            "  - Use :::callout sparingly, only for genuinely critical warnings or key observations.\n"
            "  - Use :::summary only if the report has an explicit summary section that should "
            "stand out visually.\n"
            "  - Do not nest directives.\n"
            "Quality bar: the final report should have an executive rhythm: a strong title, a "
            "brief opening synthesis, clear sections, restrained lists, clean tables where useful, "
            "and no raw-note clutter. Output the complete revised markdown. Start immediately with "
            "the report content. No preamble, no commentary."
        ),
    )

    return WorkflowDefinition(
        workflow_id="fireguard_intelligence",
        name="FireGuard Chat Research Writer Style",
        start_node_id="human_trigger",
        agents=[chat, research, writer, style],
        nodes=[
            WorkflowNode(node_id="human_trigger", label="Human Trigger", config=HumanTriggerNode()),
            WorkflowNode(
                node_id="chat_agent", label="Chat Agent", config=AgentNode(agent_id="chat_agent")
            ),
            WorkflowNode(
                node_id="research_agent",
                label="Research Agent",
                config=AgentNode(agent_id="research_agent"),
            ),
            WorkflowNode(
                node_id="writer_agent",
                label="Writer Agent",
                config=AgentNode(agent_id="writer_agent"),
            ),
            WorkflowNode(
                node_id="style_agent",
                label="Style Agent",
                config=AgentNode(agent_id="style_agent"),
            ),
            WorkflowNode(node_id="terminal", label="Terminal", config=TerminalNode()),
        ],
        edges=[
            NodeEdge(
                edge_id="edge_trigger_to_chat",
                from_node_id="human_trigger",
                to_node_id="chat_agent",
            ),
            NodeEdge(
                edge_id="edge_chat_to_research",
                from_node_id="chat_agent",
                to_node_id="research_agent",
                condition="handoff_to_research",
            ),
            NodeEdge(
                edge_id="edge_chat_to_writer",
                from_node_id="chat_agent",
                to_node_id="writer_agent",
                condition="handoff_to_writer",
            ),
            NodeEdge(
                edge_id="edge_chat_ask_to_terminal",
                from_node_id="chat_agent",
                to_node_id="terminal",
                condition="ask_user",
            ),
            NodeEdge(
                edge_id="edge_chat_respond_to_terminal",
                from_node_id="chat_agent",
                to_node_id="terminal",
                condition="respond",
            ),
            NodeEdge(
                edge_id="edge_chat_failure_to_terminal",
                from_node_id="chat_agent",
                to_node_id="terminal",
                condition="report_failure",
            ),
            NodeEdge(
                edge_id="edge_research_to_writer",
                from_node_id="research_agent",
                to_node_id="writer_agent",
            ),
            NodeEdge(
                edge_id="edge_research_error_to_chat",
                from_node_id="research_agent",
                to_node_id="chat_agent",
                condition="error",
            ),
            NodeEdge(
                edge_id="edge_writer_to_style",
                from_node_id="writer_agent",
                to_node_id="style_agent",
            ),
            NodeEdge(
                edge_id="edge_writer_error_to_chat",
                from_node_id="writer_agent",
                to_node_id="chat_agent",
                condition="error",
            ),
            NodeEdge(
                edge_id="edge_style_to_terminal",
                from_node_id="style_agent",
                to_node_id="terminal",
            ),
            NodeEdge(
                edge_id="edge_style_error_to_chat",
                from_node_id="style_agent",
                to_node_id="chat_agent",
                condition="error",
            ),
        ],
    )
