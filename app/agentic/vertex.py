from __future__ import annotations

import asyncio
import base64
import json
import random
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import AppConfig
from .models import ChatMessage, MessageRole, ModelTier, TokenUsage, ToolDefinition
from .openrouter import ChatComplete, ChatDelta, RetryEmitter, StreamChunk


class VertexAIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class VertexAIClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(config.http_timeout_seconds))

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
        del response_format
        if len(self._config.google_cloud_project.strip()) == 0:
            raise VertexAIError(
                "GOOGLE_CLOUD_PROJECT must be set before running Vertex workflows",
                status_code=401,
            )
        model = self.model_for_tier(model_tier)
        payload = _request_payload(messages, tools, self._config.max_completion_tokens)
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
        token = await _gcloud_access_token()
        content_parts: list[str] = []
        function_calls: list[dict[str, Any]] = []
        usage: TokenUsage | None = None
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            async with self._client.stream(
                "POST",
                self._endpoint(model),
                params={"alt": "sse"},
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    text = await response.aread()
                    raise VertexAIError(
                        f"Vertex AI returned HTTP {response.status_code}: {text.decode(errors='replace')[:1000]}",
                        status_code=response.status_code,
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = json.loads(line.removeprefix("data: "))
                    chunk_usage = _usage_from_response(data, model, model_tier, call_type)
                    if chunk_usage is not None:
                        usage = chunk_usage
                        yield chunk_usage
                    for text in _text_parts(data):
                        content_parts.append(text)
                        yield ChatDelta(text)
                    function_calls.extend(_function_calls(data))
        except httpx.TimeoutException as exc:
            raise VertexAIError("Vertex AI request timed out") from exc
        except httpx.HTTPError as exc:
            raise VertexAIError(f"Vertex AI request failed: {exc}") from exc
        message = ChatMessage(
            role=MessageRole.assistant,
            content="".join(content_parts),
            tool_calls=_openai_tool_calls(function_calls),
        )
        yield ChatComplete(message=message, usage=usage)

    def _endpoint(self, model: str) -> str:
        location = self._config.google_cloud_location.strip()
        project = self._config.google_cloud_project.strip()
        host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
        return (
            f"https://{host}/v1/projects/{project}/locations/{location}/"
            f"publishers/google/models/{model}:streamGenerateContent"
        )

    def _retry_delay(self, exc: Exception, attempt: int) -> float | None:
        if attempt >= self._config.max_retries:
            return None
        if (
            isinstance(exc, VertexAIError)
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


async def _gcloud_access_token() -> str:
    token = await asyncio.to_thread(_application_default_token)
    if token is not None:
        return token
    try:
        process = await asyncio.create_subprocess_exec(
            "gcloud",
            "auth",
            "print-access-token",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise VertexAIError(f"gcloud access token command failed: {exc}") from exc
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    if process.returncode != 0:
        message = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        raise VertexAIError(f"gcloud access token command failed: {message}")
    token = stdout.decode().strip()
    if len(token) == 0:
        raise VertexAIError("gcloud access token command returned an empty token")
    return token


def _application_default_token() -> str | None:
    try:
        import google.auth  # type: ignore[import-untyped]
        from google.auth.transport.requests import Request  # type: ignore[import-untyped]
    except Exception:
        return None
    try:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(Request())
    except Exception:
        return None
    token = getattr(credentials, "token", None)
    return token if isinstance(token, str) and len(token.strip()) > 0 else None


def _request_payload(
    messages: list[ChatMessage], tools: list[ToolDefinition], max_output_tokens: int
) -> dict[str, Any]:
    system_parts: list[dict[str, Any]] = []
    contents: list[dict[str, Any]] = []
    function_names: dict[str, str] = {}
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role == MessageRole.system:
            system_parts.append({"text": message.content})
            index += 1
            continue
        if message.role == MessageRole.tool:
            parts: list[dict[str, Any]] = []
            while index < len(messages) and messages[index].role == MessageRole.tool:
                parts.append(_function_response_part(messages[index], function_names))
                index += 1
            contents.append({"role": "user", "parts": parts})
            continue
        contents.append(_content_for_message(message, function_names))
        index += 1

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_output_tokens},
    }
    if len(system_parts) > 0:
        payload["systemInstruction"] = {"parts": system_parts}
    if len(tools) > 0:
        payload["tools"] = [
            {"functionDeclarations": [_function_declaration(tool) for tool in tools]}
        ]
        payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
    return payload


def _content_for_message(
    message: ChatMessage, function_names: dict[str, str]
) -> dict[str, Any]:
    if message.role == MessageRole.user:
        return {"role": "user", "parts": _user_parts(message)}
    if message.role == MessageRole.assistant:
        parts: list[dict[str, Any]] = []
        if len(message.content.strip()) > 0:
            parts.append({"text": message.content})
        if message.tool_calls is not None:
            for raw_call in message.tool_calls:
                part = _function_call_part(raw_call)
                parts.append(part)
                call_id = raw_call.get("id")
                name = part["functionCall"]["name"]
                if isinstance(call_id, str):
                    function_names[call_id] = name
        if len(parts) == 0:
            parts.append({"text": ""})
        return {"role": "model", "parts": parts}
    return {"role": "user", "parts": [{"text": message.content}]}


def _user_parts(message: ChatMessage) -> list[dict[str, Any]]:
    content_parts = message.metadata.get("openai_content_parts")
    if not isinstance(content_parts, list) or len(content_parts) == 0:
        return [{"text": message.content}]
    parts: list[dict[str, Any]] = []
    for item in content_parts:
        if not isinstance(item, dict):
            continue
        converted = _native_part(item)
        if converted is not None:
            parts.append(converted)
    return parts if len(parts) > 0 else [{"text": message.content}]


def _native_part(item: dict[str, Any]) -> dict[str, Any] | None:
    if item.get("type") == "text":
        text = item.get("text")
        return {"text": text} if isinstance(text, str) else None
    if item.get("type") == "image_url":
        url = item.get("image_url", {}).get("url") if isinstance(item.get("image_url"), dict) else None
        return _inline_data_part(url)
    if item.get("type") == "file":
        file_payload = item.get("file")
        if isinstance(file_payload, dict):
            data_url = file_payload.get("file_data")
            return _inline_data_part(data_url)
    return None


def _inline_data_part(data_url: Any) -> dict[str, Any] | None:
    if not isinstance(data_url, str) or not data_url.startswith("data:") or "," not in data_url:
        return None
    header, encoded = data_url.split(",", 1)
    media_type = header.removeprefix("data:").split(";", 1)[0] or "application/octet-stream"
    if ";base64" not in header:
        encoded = base64.b64encode(encoded.encode("utf-8")).decode("ascii")
    return {"inlineData": {"mimeType": media_type, "data": encoded}}


def _function_call_part(raw_call: dict[str, Any]) -> dict[str, Any]:
    function = raw_call.get("function")
    if not isinstance(function, dict):
        raise VertexAIError("tool call function must be an object")
    name = function.get("name")
    arguments = function.get("arguments")
    if not isinstance(name, str) or len(name.strip()) == 0:
        raise VertexAIError("tool call function.name must be a non-empty string")
    try:
        args = json.loads(arguments) if isinstance(arguments, str) and len(arguments.strip()) > 0 else {}
    except json.JSONDecodeError as exc:
        raise VertexAIError(f"tool call arguments are not valid JSON: {exc}") from exc
    if not isinstance(args, dict):
        raise VertexAIError("tool call arguments must decode to an object")
    return {"functionCall": {"name": name, "args": args}}


def _function_response_part(
    message: ChatMessage, function_names: dict[str, str]
) -> dict[str, Any]:
    name = function_names.get(message.tool_call_id or "", "tool_result")
    try:
        response = json.loads(message.content)
    except json.JSONDecodeError:
        response = {"content": message.content}
    if not isinstance(response, dict):
        response = {"content": response}
    return {"functionResponse": {"name": name, "response": response}}


def _function_declaration(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": _schema_for_vertex(tool.parameters),
    }


def _schema_for_vertex(schema: Any) -> Any:
    if isinstance(schema, list):
        return [_schema_for_vertex(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    allowed = {
        "type",
        "description",
        "properties",
        "required",
        "items",
        "enum",
        "minimum",
        "maximum",
        "format",
        "nullable",
        "default",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
    }
    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in allowed:
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned[key] = {
                name: _schema_for_vertex(property_schema)
                for name, property_schema in value.items()
                if isinstance(name, str)
            }
            continue
        if key == "type" and isinstance(value, str):
            cleaned[key] = _vertex_schema_type(value)
            continue
        cleaned[key] = _schema_for_vertex(value)
    return cleaned


def _vertex_schema_type(value: str) -> str:
    type_map = {
        "array": "ARRAY",
        "boolean": "BOOLEAN",
        "integer": "INTEGER",
        "number": "NUMBER",
        "object": "OBJECT",
        "string": "STRING",
    }
    return type_map.get(value.lower(), value)


def _usage_from_response(
    data: dict[str, Any],
    model: str,
    model_tier: ModelTier,
    call_type: str,
) -> TokenUsage | None:
    raw = data.get("usageMetadata")
    if not isinstance(raw, dict):
        return None
    return TokenUsage(
        model=model,
        model_tier=model_tier,
        call_type=call_type,
        prompt_tokens=_int_or_none(raw.get("promptTokenCount")),
        completion_tokens=_int_or_none(raw.get("candidatesTokenCount")),
        total_tokens=_int_or_none(raw.get("totalTokenCount")),
        cached_tokens=_int_or_none(raw.get("cachedContentTokenCount")),
    )


def _text_parts(data: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for part in _response_parts(data):
        text = part.get("text")
        if isinstance(text, str) and len(text) > 0:
            texts.append(text)
    return texts


def _function_calls(data: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for part in _response_parts(data):
        call = part.get("functionCall")
        if isinstance(call, dict):
            calls.append(call)
    return calls


def _response_parts(data: dict[str, Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        return parts
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        raw_parts = content.get("parts") if isinstance(content, dict) else None
        if isinstance(raw_parts, list):
            parts.extend(part for part in raw_parts if isinstance(part, dict))
    return parts


def _openai_tool_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if len(calls) == 0:
        return None
    out: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        name = call.get("name")
        args = call.get("args", {})
        if not isinstance(name, str) or len(name.strip()) == 0:
            continue
        out.append(
            {
                "id": f"call_vertex_{index}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args if isinstance(args, dict) else {})},
            }
        )
    return out if len(out) > 0 else None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
