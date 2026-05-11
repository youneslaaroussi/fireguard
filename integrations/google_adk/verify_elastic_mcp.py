from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from fireguard_agent.agent import _load_elastic_mcp_toolset


class _ReadonlyContextStub:
    invocation_id = "fireguard-elastic-mcp-verification"

    def get_credential(self, _key: str):
        return None


def _transport() -> str:
    if os.environ.get("FIREGUARD_ELASTIC_MCP_URL"):
        return "streamable_http"
    if os.environ.get("FIREGUARD_ELASTIC_MCP_ENABLED"):
        return "stdio"
    return "not_configured"


async def main() -> int:
    load_dotenv(Path(__file__).resolve().parent / "fireguard_agent" / ".env")
    toolset = _load_elastic_mcp_toolset()
    if toolset is None:
        print(json.dumps({
            "status": "not_configured",
            "transport": _transport(),
            "message": "Set FIREGUARD_ELASTIC_MCP_URL or FIREGUARD_ELASTIC_MCP_ENABLED=true.",
        }, indent=2))
        return 2

    try:
        tools = await toolset.get_tools_with_prefix(readonly_context=_ReadonlyContextStub())
        result = {
            "status": "ok",
            "transport": _transport(),
            "tool_count": len(tools),
            "tools": [tool.name for tool in tools],
        }
        if os.environ.get("FIREGUARD_ELASTIC_MCP_VERIFY_CALL", "").lower() in {"1", "true", "yes"}:
            headers = None
            header_provider = getattr(toolset, "_header_provider", None)
            if header_provider:
                headers = header_provider(_ReadonlyContextStub())
            session = await toolset._mcp_session_manager.create_session(headers=headers)
            index_pattern = os.environ.get("FIREGUARD_ELASTIC_MCP_INDEX_PATTERN", "fire*")
            call = await session.call_tool(
                "list_indices",
                arguments={"index_pattern": index_pattern},
            )
            result["verification_call"] = {
                "tool": "elastic_mcp_list_indices",
                "index_pattern": index_pattern,
                "result": call.model_dump(exclude_none=True, mode="json"),
            }
        print(json.dumps({
            **result,
        }, indent=2))
        return 0
    finally:
        await toolset.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
