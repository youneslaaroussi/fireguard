from __future__ import annotations

import asyncio
from types import SimpleNamespace

import app.agent_runtime.tools as tools
import app.main as main


def test_bulk_omits_placeholder_api_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def capture_http(method, url, body=None, headers=None, timeout=300):
        captured["method"] = method
        captured["url"] = url
        captured["body"] = body
        captured["headers"] = headers
        captured["timeout"] = timeout
        return '{"errors":false,"items":[{"index":{"status":201}}]}'

    monkeypatch.setenv("ELASTICSEARCH_URL", "http://elasticsearch:9200")
    monkeypatch.setenv("ELASTICSEARCH_API_KEY", "no-auth-security-disabled")
    monkeypatch.setattr(main, "http", capture_http)

    assert main.bulk([("shelter-1", {"name": "Shelter"})], "fireguard-shelters") == 1

    assert captured["headers"] == {"Content-Type": "application/x-ndjson"}


def test_mcp_env_omits_placeholder_api_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class CaptureStdioContext:
        async def __aenter__(self):
            return object(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class CaptureClientSession:
        def __init__(self, read_stream, write_stream) -> None:
            del read_stream, write_stream

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def initialize(self) -> None:
            return None

        async def call_tool(self, name, kwargs):
            captured["tool_name"] = name
            captured["kwargs"] = kwargs
            return SimpleNamespace(
                content=[SimpleNamespace(text='{"hits":{"total":{"value":0},"hits":[]}}')]
            )

    def capture_stdio_client(server):
        captured["server"] = server
        return CaptureStdioContext()

    import shutil

    def which(name):
        if name == "docker":
            return None
        if name == "mcp-server-elasticsearch":
            return "/usr/local/bin/mcp-server-elasticsearch"
        return None

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(tools, "stdio_client", capture_stdio_client)
    monkeypatch.setattr(tools, "ClientSession", CaptureClientSession)
    monkeypatch.setenv("ES_API_KEY", "no-auth-security-disabled")
    monkeypatch.setenv("ELASTICSEARCH_API_KEY", "no-auth-security-disabled")

    result = asyncio.run(
        tools._elastic_mcp_search(
            "http://10.128.0.2:9200",
            "no-auth-security-disabled",
            "fireguard-shelters",
            {"query": {"match_all": {}}},
        )
    )

    server = captured["server"]
    assert result["hits"]["total"]["value"] == 0
    assert server.env["ES_URL"] == "http://10.128.0.2:9200"
    assert "ES_API_KEY" not in server.env
    assert "ELASTICSEARCH_API_KEY" not in server.env


def test_mcp_text_fragments_are_parsed_as_hits() -> None:
    result = SimpleNamespace(
        content=[
            SimpleNamespace(text="Total results: 1, showing 1 from position 0"),
            SimpleNamespace(
                text=(
                    'facility_id: "BC_ESS_133"\n'
                    'name: "100 Mile Community Hall"\n'
                    'status: "CLOSED"\n'
                    'location: {"lat":51.644337,"lon":-121.295112}'
                )
            ),
        ]
    )

    parsed = tools._mcp_tool_result_object(result)

    assert parsed["hits"]["total"]["value"] == 1
    assert parsed["hits"]["hits"] == [
        {
            "_source": {
                "facility_id": "BC_ESS_133",
                "name": "100 Mile Community Hall",
                "status": "CLOSED",
                "location": {"lat": 51.644337, "lon": -121.295112},
            }
        }
    ]
