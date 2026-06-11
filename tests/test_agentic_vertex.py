from __future__ import annotations

from app.agentic.config import AppConfig
from app.agentic.models import ChatMessage, MessageRole, ModelTier, TokenUsage, ToolDefinition
from app.agentic.vertex import (
    _content_from_vertex_dict,
    _request_payload,
    _usage_from_response,
    _vertex_tool_calls,
)
from app.agentic.workflows import CHAT_AGENT_RESPONSE_FORMAT


def test_config_selects_vertex_from_google_project(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "fireguard-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-pro-preview")
    monkeypatch.delenv("FIREGUARD_INTELLIGENCE_PROVIDER", raising=False)

    config = AppConfig(_env_file=None)

    assert config.provider == "vertex"
    assert config.light_model == "gemini-3.1-pro-preview"
    assert config.pro_model == "gemini-3.1-pro-preview"


def test_only_vertex_provider_is_supported(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "fireguard-project")
    monkeypatch.setenv("FIREGUARD_INTELLIGENCE_PROVIDER", "vertex")

    config = AppConfig(_env_file=None)

    assert config.provider == "vertex"


def test_vertex_request_payload_maps_messages_tools_and_function_responses() -> None:
    payload = _request_payload(
        [
            ChatMessage(role=MessageRole.system, content="system instructions"),
            ChatMessage(role=MessageRole.user, content='{"prompt":"hello"}'),
            ChatMessage(
                role=MessageRole.assistant,
                content="",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "echo_json", "arguments": '{"value": 7}'},
                        "metadata": {"vertex_thought_signature": "YWJj"},
                    }
                ],
            ),
            ChatMessage(
                role=MessageRole.tool,
                content='{"ok":true}',
                tool_call_id="call_1",
            ),
        ],
        [
            ToolDefinition(
                name="echo_json",
                description="Return JSON.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "value": {"type": "integer", "minimum": 1},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "enabled": {"type": "boolean"},
                        },
                        "required": ["value"],
                        "additionalProperties": False,
                    },
            )
        ],
        1024,
    )

    assert payload["systemInstruction"]["parts"] == [{"text": "system instructions"}]
    assert payload["contents"][1]["parts"] == [
        {"functionCall": {"name": "echo_json", "args": {"value": 7}}, "thoughtSignature": "YWJj"}
    ]
    assert payload["contents"][2]["parts"] == [
        {"functionResponse": {"name": "echo_json", "response": {"ok": True}}}
    ]
    content = _content_from_vertex_dict(payload["contents"][1])
    assert content.parts is not None
    assert content.parts[0].thought_signature == b"abc"
    declaration = payload["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "echo_json"
    assert declaration["parameters"]["type"] == "OBJECT"
    assert declaration["parameters"]["properties"]["value"]["type"] == "INTEGER"
    assert declaration["parameters"]["properties"]["tags"]["type"] == "ARRAY"
    assert declaration["parameters"]["properties"]["tags"]["items"]["type"] == "STRING"
    assert declaration["parameters"]["properties"]["enabled"]["type"] == "BOOLEAN"
    assert "additionalProperties" not in declaration["parameters"]


def test_vertex_request_payload_maps_response_format_to_generation_config() -> None:
    payload = _request_payload(
        [ChatMessage(role=MessageRole.user, content="hello")],
        [],
        128,
        response_format=CHAT_AGENT_RESPONSE_FORMAT,
    )

    generation_config = payload["generationConfig"]
    assert generation_config["responseMimeType"] == "application/json"
    assert generation_config["responseSchema"]["type"] == "OBJECT"
    assert generation_config["responseSchema"]["properties"]["action"]["type"] == "STRING"
    assert generation_config["responseSchema"]["properties"]["handoff"]["nullable"] is True
    assert generation_config["responseSchema"]["properties"]["questions"]["nullable"] is True


def test_vertex_response_helpers_map_usage_and_tool_calls() -> None:
    usage = _usage_from_response(
        {
            "usageMetadata": {
                "promptTokenCount": 2,
                "candidatesTokenCount": 3,
                "totalTokenCount": 5,
            }
        },
        "gemini-3.1-pro-preview",
        ModelTier.light,
        "agent:chat_agent",
    )
    calls = _vertex_tool_calls([{"name": "echo_json", "args": {"value": 7}, "thought_signature": "YWJj"}])

    assert isinstance(usage, TokenUsage)
    assert usage.total_tokens == 5
    assert calls is not None
    assert len(calls) == 1
    assert calls[0]["id"].startswith("call_vertex_0_")
    assert calls[0]["type"] == "function"
    assert calls[0]["function"] == {"name": "echo_json", "arguments": '{"value": 7}'}
    assert calls[0]["metadata"] == {"vertex_thought_signature": "YWJj"}
