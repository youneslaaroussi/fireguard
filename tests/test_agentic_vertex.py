from __future__ import annotations

from app.agentic.config import AppConfig
from app.agentic.models import ChatMessage, MessageRole, ModelTier, TokenUsage, ToolDefinition
from app.agentic.vertex import (
    _openai_tool_calls,
    _request_payload,
    _usage_from_response,
)


def test_config_selects_vertex_from_google_project(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "fireguard-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-pro-preview")
    monkeypatch.delenv("FIREGUARD_INTELLIGENCE_PROVIDER", raising=False)
    monkeypatch.delenv("FIREGUARD_INTELLIGENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    config = AppConfig(_env_file=None)

    assert config.provider == "vertex"
    assert config.light_model == "gemini-3.1-pro-preview"
    assert config.pro_model == "gemini-3.1-pro-preview"


def test_explicit_openrouter_provider_keeps_openrouter(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "fireguard-project")
    monkeypatch.setenv("FIREGUARD_INTELLIGENCE_PROVIDER", "openrouter")
    monkeypatch.delenv("FIREGUARD_INTELLIGENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    config = AppConfig(_env_file=None)

    assert config.provider == "openrouter"


def test_source_openai_provider_value_is_supported(monkeypatch) -> None:
    monkeypatch.setenv("FIREGUARD_INTELLIGENCE_PROVIDER", "openai")
    monkeypatch.setenv("FIREGUARD_INTELLIGENCE_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("FIREGUARD_INTELLIGENCE_API_KEY", "test-key")

    config = AppConfig(_env_file=None)

    assert config.provider == "openai"
    assert config.base_url == "https://api.openai.com/v1"


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
        {"functionCall": {"name": "echo_json", "args": {"value": 7}}}
    ]
    assert payload["contents"][2]["parts"] == [
        {"functionResponse": {"name": "echo_json", "response": {"ok": True}}}
    ]
    declaration = payload["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "echo_json"
    assert declaration["parameters"]["type"] == "OBJECT"
    assert declaration["parameters"]["properties"]["value"]["type"] == "INTEGER"
    assert declaration["parameters"]["properties"]["tags"]["type"] == "ARRAY"
    assert declaration["parameters"]["properties"]["tags"]["items"]["type"] == "STRING"
    assert declaration["parameters"]["properties"]["enabled"]["type"] == "BOOLEAN"
    assert "additionalProperties" not in declaration["parameters"]


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
    calls = _openai_tool_calls([{"name": "echo_json", "args": {"value": 7}}])

    assert isinstance(usage, TokenUsage)
    assert usage.total_tokens == 5
    assert calls == [
        {
            "id": "call_vertex_0",
            "type": "function",
            "function": {"name": "echo_json", "arguments": '{"value": 7}'},
        }
    ]
