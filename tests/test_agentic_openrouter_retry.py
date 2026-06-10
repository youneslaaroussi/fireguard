from __future__ import annotations

import asyncio

from app.agentic.config import AppConfig
from app.agentic.models import ChatMessage, MessageRole, ModelTier
from app.agentic.openrouter import ChatComplete, OpenRouterClient, OpenRouterError


def test_openrouter_retry_policy_retries_rate_limits_and_server_errors() -> None:
    client = OpenRouterClient(AppConfig(api_key="test-key", max_retries=3))

    try:
        assert client._retry_delay(OpenRouterError("limited", status_code=429), 1) is not None
        assert client._retry_delay(OpenRouterError("server", status_code=500), 1) is not None
        assert client._retry_delay(OpenRouterError("bad", status_code=400), 1) is None
        assert client._retry_delay(OpenRouterError("limited", status_code=429), 3) is None
    finally:
        asyncio.run(client.close())


def test_stream_chat_sends_response_format() -> None:
    async def exercise() -> None:
        client = OpenRouterClient(AppConfig(api_key="test-key"))
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "route",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"action": {"type": "string"}},
                    "required": ["action"],
                },
            },
        }
        captured: dict[str, object] = {}

        async def stream_once(**kwargs: object):
            captured.update(kwargs)
            yield ChatComplete(
                message=ChatMessage(role=MessageRole.assistant, content='{"action":"respond"}'),
                usage=None,
            )

        async def emit_retry(_data: dict[str, object]) -> None:
            return None

        client._stream_once = stream_once  # type: ignore[method-assign]
        try:
            chunks = [
                chunk
                async for chunk in client.stream_chat(
                    messages=[ChatMessage(role=MessageRole.user, content="hi")],
                    tools=[],
                    model_tier=ModelTier.light,
                    call_type="test",
                    emit_retry=emit_retry,
                    response_format=response_format,
                )
            ]

            assert len(chunks) == 1
            payload = captured["payload"]
            assert isinstance(payload, dict)
            assert payload["response_format"] == response_format
        finally:
            await client.close()

    asyncio.run(exercise())
