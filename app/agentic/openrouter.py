from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from .config import AppConfig
from .models import ChatMessage, MessageRole, ModelTier, TokenUsage, ToolDefinition

RetryEmitter = Callable[[dict[str, Any]], Awaitable[None]]


class OpenRouterError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ChatDelta:
    content: str


@dataclass(frozen=True, slots=True)
class ChatComplete:
    message: ChatMessage
    usage: TokenUsage | None


StreamChunk = ChatDelta | ChatComplete | TokenUsage


class OpenRouterClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            timeout=httpx.Timeout(config.http_timeout_seconds),
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    def model_for_tier(self, tier: ModelTier) -> str:
        if tier == ModelTier.light:
            return self._config.light_model
        return self._config.pro_model

    async def stream_chat(
        self,
        *,
        messages: list[ChatMessage],
        tools: list[ToolDefinition],
        model_tier: ModelTier,
        call_type: str,
        emit_retry: RetryEmitter,
        response_format: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        if len(self._config.api_key.strip()) == 0:
            raise OpenRouterError(
                "FIREGUARD_INTELLIGENCE_API_KEY must be set before running model-backed workflows",
                status_code=401,
            )
        model = self.model_for_tier(model_tier)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [_message_payload(message) for message in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_completion_tokens": self._config.max_completion_tokens,
        }
        if len(tools) > 0:
            payload["tools"] = [_tool_payload(tool) for tool in tools]
            payload["tool_choice"] = "auto"
        if response_format is not None:
            payload["response_format"] = response_format
        attempt = 1
        while True:
            try:
                async for chunk in self._stream_once(
                    payload=payload,
                    model=model,
                    model_tier=model_tier,
                    call_type=call_type,
                ):
                    yield chunk
                return
            except Exception as exc:
                retry = self._retry_delay(exc, attempt)
                if retry is None:
                    raise
                await emit_retry(
                    {
                        "attempt": attempt,
                        "next_attempt": attempt + 1,
                        "wait_seconds": retry,
                        "error": str(exc),
                        "status_code": getattr(exc, "status_code", None),
                    }
                )
                await asyncio.sleep(retry)
                attempt += 1

    async def _stream_once(
        self,
        *,
        payload: dict[str, Any],
        model: str,
        model_tier: ModelTier,
        call_type: str,
    ) -> AsyncIterator[StreamChunk]:
        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        usage: TokenUsage | None = None
        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code >= 400:
                    text = await response.aread()
                    raise OpenRouterError(
                        f"OpenRouter returned HTTP {response.status_code}: {text.decode(errors='replace')[:1000]}",
                        status_code=response.status_code,
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line.removeprefix("data: ")
                    if raw == "[DONE]":
                        break
                    data = json.loads(raw)
                    chunk_usage = _usage_from_response(data, model, model_tier, call_type)
                    if chunk_usage is not None:
                        usage = chunk_usage
                        yield chunk_usage
                    for delta in _content_deltas(data):
                        content_parts.append(delta)
                        yield ChatDelta(delta)
                    _apply_tool_call_deltas(data, tool_calls)
        except httpx.TimeoutException as exc:
            raise OpenRouterError("OpenRouter request timed out") from exc
        except httpx.HTTPError as exc:
            raise OpenRouterError(f"OpenRouter request failed: {exc}") from exc
        message = ChatMessage(
            role=MessageRole.assistant,
            content="".join(content_parts),
            tool_calls=_final_tool_calls(tool_calls),
        )
        yield ChatComplete(message=message, usage=usage)

    def _retry_delay(self, exc: Exception, attempt: int) -> float | None:
        if attempt >= self._config.max_retries:
            return None
        if (
            isinstance(exc, OpenRouterError)
            and exc.status_code is not None
            and exc.status_code != 429
            and exc.status_code < 500
        ):
            return None
        base = min(
            self._config.retry_max_seconds,
            self._config.retry_base_seconds * (2 ** (attempt - 1)),
        )
        return min(self._config.retry_max_seconds, base + random.uniform(0, base * 0.25))


def retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    stripped = value.strip()
    if len(stripped) == 0:
        return None
    try:
        seconds = float(stripped)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(stripped)
        except (TypeError, ValueError):
            return None
        return max(0.0, (parsed.timestamp()))
    return max(0.0, seconds)


def _message_payload(message: ChatMessage) -> dict[str, Any]:
    content: Any = message.content
    content_parts = message.metadata.get("openai_content_parts")
    if isinstance(content_parts, list) and len(content_parts) > 0:
        content = content_parts
    payload: dict[str, Any] = {"role": message.role.value, "content": content}
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_calls is not None:
        payload["tool_calls"] = message.tool_calls
    return payload


def _tool_payload(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _usage_from_response(
    data: dict[str, Any],
    model: str,
    model_tier: ModelTier,
    call_type: str,
) -> TokenUsage | None:
    raw = data.get("usage")
    if not isinstance(raw, dict):
        return None
    completion_details = raw.get("completion_tokens_details")
    prompt_details = raw.get("prompt_tokens_details")
    return TokenUsage(
        model=str(data.get("model") or model),
        model_tier=model_tier,
        call_type=call_type,
        prompt_tokens=_int_or_none(raw.get("prompt_tokens")),
        completion_tokens=_int_or_none(raw.get("completion_tokens")),
        total_tokens=_int_or_none(raw.get("total_tokens")),
        reasoning_tokens=_nested_int(completion_details, "reasoning_tokens"),
        cached_tokens=_nested_int(prompt_details, "cached_tokens"),
        cost=_float_or_none(raw.get("cost")),
    )


def _content_deltas(data: dict[str, Any]) -> list[str]:
    choices = data.get("choices")
    if not isinstance(choices, list):
        return []
    deltas: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        content = delta.get("content")
        if isinstance(content, str) and len(content) > 0:
            deltas.append(content)
    return deltas


def _apply_tool_call_deltas(data: dict[str, Any], tool_calls: dict[int, dict[str, Any]]) -> None:
    choices = data.get("choices")
    if not isinstance(choices, list):
        return
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        raw_calls = delta.get("tool_calls")
        if raw_calls is None:
            continue
        if not isinstance(raw_calls, list):
            raise RuntimeError("OpenRouter delta.tool_calls must be a list")
        for raw_call in raw_calls:
            if not isinstance(raw_call, dict):
                raise RuntimeError("OpenRouter delta.tool_calls entries must be objects")
            index = raw_call.get("index")
            if not isinstance(index, int):
                raise RuntimeError("OpenRouter streamed tool call index must be an integer")
            current = tool_calls.setdefault(index, {"type": "function", "function": {"name": "", "arguments": ""}})
            call_id = raw_call.get("id")
            if isinstance(call_id, str):
                current["id"] = call_id
            function = raw_call.get("function")
            if isinstance(function, dict):
                current_function = current["function"]
                name = function.get("name")
                if isinstance(name, str):
                    current_function["name"] += name
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    current_function["arguments"] += arguments


def _final_tool_calls(tool_calls: dict[int, dict[str, Any]]) -> list[dict[str, Any]] | None:
    if len(tool_calls) == 0:
        return None
    final: list[dict[str, Any]] = []
    for index in sorted(tool_calls):
        call = tool_calls[index]
        if "id" not in call:
            call["id"] = f"call_{index}"
        final.append(call)
    return final


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _nested_int(value: Any, key: str) -> int | None:
    if not isinstance(value, dict):
        return None
    return _int_or_none(value.get(key))
