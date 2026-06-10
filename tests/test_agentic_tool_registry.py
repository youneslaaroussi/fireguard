from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.agentic.models import ToolInvocation
from app.agentic.tools import build_base_tool_registry
import app.agentic.tools as tools_module


class ScriptedSandbox:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def exec(
        self,
        session_id: str,
        command: list[str],
        *,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "tool": "exec",
                "session_id": session_id,
                "command": command,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"ran": command, "timeout_seconds": timeout_seconds}

    async def write_file(self, session_id: str, path: str, content: str) -> dict[str, Any]:
        self.calls.append(
            {
                "tool": "write_file",
                "session_id": session_id,
                "path": path,
                "content": content,
            }
        )
        return {"path": path, "bytes": len(content.encode("utf-8"))}

    async def read_file(self, session_id: str, path: str, *, max_bytes: int) -> dict[str, Any]:
        self.calls.append(
            {
                "tool": "read_file",
                "session_id": session_id,
                "path": path,
                "max_bytes": max_bytes,
            }
        )
        return {"path": path, "content": "hello"}

    async def export_asset(
        self, session_id: str, sandbox_path: str, assets_dir: Path
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "tool": "export_asset",
                "session_id": session_id,
                "sandbox_path": sandbox_path,
                "assets_dir": assets_dir,
            }
        )
        assets_dir.mkdir(parents=True, exist_ok=True)
        return {"saved_as": "plot.png", "size": 42}

    async def list_files(self, session_id: str, path: str, *, max_entries: int) -> dict[str, Any]:
        self.calls.append(
            {
                "tool": "list_files",
                "session_id": session_id,
                "path": path,
                "max_entries": max_entries,
            }
        )
        return {"path": path, "entries": ["a.txt"]}


def _invocation(
    tool_name: str,
    args: dict[str, Any] | None = None,
    *,
    invocation_id: str | None = None,
) -> ToolInvocation:
    return ToolInvocation(
        invocation_id=invocation_id or f"call_{tool_name}",
        tool_name=tool_name,
        session_id="ses_test",
        run_id="run_test",
        node_id="node_test",
        agent_id="agent_test",
        args=args or {},
    )


def test_base_registry_exposes_shared_workflow_tools() -> None:
    registry = build_base_tool_registry(default_timeout_seconds=5, max_parallel_tools=4)

    definitions = registry.available_tools(
        ["emit_message", "complete_workflow_node", "request_approval", "echo_json"]
    )

    assert [definition.name for definition in definitions] == [
        "emit_message",
        "complete_workflow_node",
        "request_approval",
        "echo_json",
    ]


def test_workflow_control_tools_return_structured_payloads() -> None:
    async def exercise() -> None:
        registry = build_base_tool_registry(default_timeout_seconds=5, max_parallel_tools=4)
        results = await registry.run_tools(
            [
                _invocation("emit_message", {"message": "hello"}),
                _invocation("complete_workflow_node", {"payload": {"ok": True}}),
                _invocation("request_approval", {"reason": "check"}),
                _invocation("echo_json", {"nested": {"value": 1}}),
            ]
        )

        assert [result.ok for result in results] == [True, True, True, True]
        assert results[0].output == {"message": "hello"}
        assert results[1].output == {"completed": True, "payload": {"payload": {"ok": True}}}
        assert results[2].output == {
            "approval_requested": True,
            "payload": {"reason": "check"},
        }
        assert results[3].output == {"json": {"nested": {"value": 1}}}

    asyncio.run(exercise())


def test_tool_results_are_reused_by_invocation_id() -> None:
    async def exercise() -> None:
        registry = build_base_tool_registry(default_timeout_seconds=5, max_parallel_tools=4)
        first = (
            await registry.run_tools(
                [_invocation("echo_json", {"value": "first"}, invocation_id="same_call")]
            )
        )[0]
        second = (
            await registry.run_tools(
                [_invocation("echo_json", {"value": "second"}, invocation_id="same_call")]
            )
        )[0]

        assert first.output == {"json": {"value": "first"}}
        assert second.output == first.output

    asyncio.run(exercise())


def test_sandbox_tools_delegate_to_sandbox_manager(tmp_path: Path) -> None:
    async def exercise() -> None:
        sandbox = ScriptedSandbox()
        registry = build_base_tool_registry(
            default_timeout_seconds=5,
            max_parallel_tools=4,
            sandbox_manager=sandbox,
            assets_dir_fn=lambda session_id: tmp_path / session_id / "assets",
        )
        results = await registry.run_tools(
            [
                _invocation(
                    "sandbox_exec",
                    {"command": ["python", "-c", "print(1)"], "timeout_seconds": 2},
                ),
                _invocation(
                    "sandbox_write_file",
                    {"path": "/workspace/a.txt", "content": "hello"},
                ),
                _invocation("sandbox_read_file", {"path": "/workspace/a.txt", "max_bytes": 10}),
                _invocation("sandbox_export_asset", {"path": "/workspace/plot.png"}),
                _invocation("sandbox_list_files", {"path": "/workspace", "max_entries": 5}),
            ]
        )

        assert [result.ok for result in results] == [True, True, True, True, True]
        assert results[0].output == {
            "ran": ["python", "-c", "print(1)"],
            "timeout_seconds": 2.0,
        }
        assert results[1].output == {"path": "/workspace/a.txt", "bytes": 5}
        assert results[2].output == {"path": "/workspace/a.txt", "content": "hello"}
        assert results[3].output == {
            "url": "/api/intelligence/sessions/ses_test/assets/plot.png",
            "filename": "plot.png",
            "content_type": "image/png",
            "size": 42,
        }
        assert results[4].output == {"path": "/workspace", "entries": ["a.txt"]}
        assert [call["tool"] for call in sandbox.calls] == [
            "exec",
            "write_file",
            "read_file",
            "export_asset",
            "list_files",
        ]
        export_tool = next(
            definition
            for definition in registry.available_tools(["sandbox_export_asset"])
            if definition.name == "sandbox_export_asset"
        )
        assert "![alt text](url)" in export_tool.description
        assert "[label](url)" in export_tool.description
        assert sandbox.calls[0]["timeout_seconds"] == 2.0
        assert sandbox.calls[2]["max_bytes"] == 10
        assert sandbox.calls[3]["sandbox_path"] == "/workspace/plot.png"
        assert sandbox.calls[3]["assets_dir"] == tmp_path / "ses_test" / "assets"
        assert sandbox.calls[4]["max_entries"] == 5

    asyncio.run(exercise())


def test_exa_search_without_key_returns_failed_tool_result() -> None:
    async def exercise() -> None:
        registry = build_base_tool_registry(default_timeout_seconds=5, max_parallel_tools=4)
        result = (
            await registry.run_tools([_invocation("exa_search", {"query": "wildfire"})])
        )[0]

        assert result.ok is False
        assert result.output == {
            "error": "EXA_API_KEY is not configured",
            "tool_name": "exa_search",
        }

    asyncio.run(exercise())


def test_exa_search_passes_extras_for_image_links(monkeypatch: pytest.MonkeyPatch) -> None:
    posts: list[dict[str, Any]] = []

    class ScriptedExaResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"results": [{"title": "FireGuard map"}]}

    class ScriptedExaClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self) -> ScriptedExaClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, Any],
        ) -> ScriptedExaResponse:
            posts.append({"url": url, "headers": headers, "json": json})
            return ScriptedExaResponse()

    async def exercise() -> None:
        monkeypatch.setattr(tools_module.httpx, "AsyncClient", ScriptedExaClient)
        registry = build_base_tool_registry(
            default_timeout_seconds=5,
            max_parallel_tools=4,
            exa_api_key="test-key",
            exa_base_url="https://exa.test",
        )
        definition = registry.available_tools(["exa_search"])[0]
        assert "extras" in definition.parameters["properties"]

        result = (
            await registry.run_tools(
                [
                    _invocation(
                        "exa_search",
                        {
                            "query": "wildfire perimeter map",
                            "extras": {"imageLinks": 5},
                            "contents": {"summary": True},
                        },
                    )
                ]
            )
        )[0]

        assert result.ok is True
        assert posts[0]["url"] == "https://exa.test/search"
        assert posts[0]["json"]["extras"] == {"imageLinks": 5}
        assert result.output["request"]["extras"] == {"imageLinks": 5}

    asyncio.run(exercise())


def test_exa_search_uses_bounded_default_contents(monkeypatch: pytest.MonkeyPatch) -> None:
    posts: list[dict[str, Any]] = []

    class ScriptedExaResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"results": []}

    class ScriptedExaClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self) -> ScriptedExaClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, Any],
        ) -> ScriptedExaResponse:
            posts.append({"url": url, "headers": headers, "json": json})
            return ScriptedExaResponse()

    async def exercise() -> None:
        monkeypatch.setattr(tools_module.httpx, "AsyncClient", ScriptedExaClient)
        registry = build_base_tool_registry(
            default_timeout_seconds=5,
            max_parallel_tools=4,
            exa_api_key="test-key",
            exa_base_url="https://exa.test",
        )

        result = (
            await registry.run_tools([_invocation("exa_search", {"query": "wildfire"})])
        )[0]

        assert result.ok is True
        assert posts[0]["json"]["contents"] == {
            "text": {"maxCharacters": 2000},
            "highlights": {"numSentences": 3, "highlightsPerUrl": 3},
            "summary": True,
        }
        assert result.output["request"]["contents"] == posts[0]["json"]["contents"]

    asyncio.run(exercise())
