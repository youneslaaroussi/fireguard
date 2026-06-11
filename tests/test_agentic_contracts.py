from __future__ import annotations

from app.agentic.engine import RESEARCH_CHILD_TOOLS, _research_child_system_prompt
from app.agentic.models import AgentNode, ModelTier, NodeKind, WorkflowNode
from app.agentic.workflows import (
    CHAT_AGENT_RESPONSE_FORMAT,
    FIREGUARD_TOOLS,
    RESEARCH_DIRECT_TOOLS,
    built_in_workflow,
)


def test_builtin_workflow_uses_fireguard_pipeline() -> None:
    workflow = built_in_workflow("fireguard_intelligence")

    assert workflow.start_node_id == "human_trigger"
    assert [node.node_id for node in workflow.nodes] == [
        "human_trigger",
        "chat_agent",
        "research_agent",
        "writer_agent",
        "style_agent",
        "terminal",
    ]
    assert any(
        edge.from_node_id == "chat_agent" and edge.condition == "handoff_to_research"
        for edge in workflow.edges
    )
    assert any(
        edge.from_node_id == "chat_agent"
        and edge.to_node_id == "writer_agent"
        and edge.condition == "handoff_to_writer"
        for edge in workflow.edges
    )
    assert any(edge.from_node_id == "chat_agent" and edge.condition == "ask_user" for edge in workflow.edges)
    assert any(edge.from_node_id == "chat_agent" and edge.condition == "respond" for edge in workflow.edges)
    assert any(edge.from_node_id == "research_agent" and edge.condition == "error" for edge in workflow.edges)
    assert any(edge.from_node_id == "writer_agent" and edge.condition == "error" for edge in workflow.edges)
    assert any(edge.from_node_id == "writer_agent" and edge.to_node_id == "style_agent" for edge in workflow.edges)
    assert any(edge.from_node_id == "style_agent" and edge.to_node_id == "terminal" for edge in workflow.edges)
    assert any(edge.from_node_id == "style_agent" and edge.condition == "error" for edge in workflow.edges)

    chat_agent = next(agent for agent in workflow.agents if agent.agent_id == "chat_agent")
    assert "ask_user" not in chat_agent.tool_names
    assert chat_agent.response_format == CHAT_AGENT_RESPONSE_FORMAT
    assert chat_agent.response_format["type"] == "json_schema"
    assert chat_agent.response_format["json_schema"]["strict"] is True
    assert "FireGuard intelligence" in chat_agent.system_prompt
    assert "session_context" in chat_agent.system_prompt
    assert "handoff_to_writer" in chat_agent.system_prompt
    assert "The default action is respond" in chat_agent.system_prompt
    assert "any input you can answer directly" in chat_agent.system_prompt
    assert "Do not turn ordinary chat into a workflow" in chat_agent.system_prompt
    assert "latest user request explicitly asks" in chat_agent.system_prompt
    assert "clearly refers to prior work" in chat_agent.system_prompt
    assert "app-side keyword rules" in chat_agent.system_prompt

    research_agent = next(agent for agent in workflow.agents if agent.agent_id == "research_agent")
    for tool_name in FIREGUARD_TOOLS:
        assert tool_name in research_agent.tool_names
        assert tool_name in RESEARCH_CHILD_TOOLS
    for tool_name in RESEARCH_DIRECT_TOOLS:
        assert tool_name in research_agent.tool_names
        assert tool_name in RESEARCH_CHILD_TOOLS
    assert "spawn_subagent" in research_agent.tool_names
    assert "spawn_fleet" in research_agent.tool_names
    assert "FIRMS" in research_agent.system_prompt
    assert "BCWS" in research_agent.system_prompt
    assert "Use exa_search directly" in research_agent.system_prompt
    assert "/workspace/project_data" in research_agent.system_prompt
    assert "handoff.context.session_context" in research_agent.system_prompt
    assert "narrative observations" in research_agent.system_prompt
    assert "Do not list field names" in research_agent.system_prompt
    assert "reconcile group totals" in research_agent.system_prompt
    assert "timestamp formats" in research_agent.system_prompt
    assert "Do not invent missing data" in research_agent.system_prompt
    assert "markdown image" in research_agent.system_prompt
    assert 'extras={"imageLinks": 5}' in research_agent.system_prompt
    assert "map, chart, or figure URLs" in research_agent.system_prompt

    writer_agent = next(agent for agent in workflow.agents if agent.agent_id == "writer_agent")
    assert "not a chatbot" in writer_agent.system_prompt
    assert "final intelligence" in writer_agent.system_prompt
    assert "STRICT RULES" in writer_agent.system_prompt
    assert "NO preamble" in writer_agent.system_prompt
    assert "Scale length and structure" in writer_agent.system_prompt
    assert "narrative, not data extraction" in writer_agent.system_prompt
    assert "non-technical audience" in writer_agent.system_prompt
    assert "active_result.kind equal to deliverable" in writer_agent.system_prompt
    assert "Do not upgrade tentative analysis" in writer_agent.system_prompt
    assert "markdown images" in writer_agent.system_prompt

    style_agent = next(agent for agent in workflow.agents if agent.agent_id == "style_agent")
    assert style_agent.model_tier == ModelTier.pro
    assert "editorial designer" in style_agent.system_prompt
    assert "layout directives" in style_agent.system_prompt
    assert "must NOT change factual content" in style_agent.system_prompt
    assert "::pagebreak" in style_agent.system_prompt
    assert "No preamble, no commentary" in style_agent.system_prompt
    assert "complete_workflow_node" in style_agent.tool_names


def test_workflow_node_discriminates_agent_config() -> None:
    node = WorkflowNode.model_validate(
        {
            "node_id": "agent",
            "label": "Agent",
            "config": {"kind": "agent", "agent_id": "researcher"},
        }
    )

    assert isinstance(node.config, AgentNode)
    assert node.config.kind == NodeKind.agent


def test_research_child_policy_includes_fireguard_tools() -> None:
    prompt = _research_child_system_prompt("Use internal knowledge only. Do not browse.")

    assert "fireguard_stats" in prompt
    assert "fireguard_search_events" in prompt
    assert "fireguard_bcws_context" in prompt
    assert "/workspace/project_data" in prompt
    assert "MUST call exa_search at least once" in prompt
    assert "MUST call sandbox_exec at least once" in prompt
    assert "sandbox_export_asset" in prompt
