from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.agentic.config import AppConfig
from app.agentic.project_data import (
    FIREGUARD_DATASETS,
    PROJECT_DATA_PATH,
    ProjectDataBootstrapper,
)


class ScriptedResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"unexpected status {self.status_code}")


class ScriptedElasticClient:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []

    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> ScriptedResponse:
        self.posts.append({"url": url, "json": json, "params": params})
        if url.endswith("/_count"):
            return ScriptedResponse(200, {"count": 2})
        if url.endswith("/_search"):
            return ScriptedResponse(
                200,
                {
                    "_scroll_id": "scroll_1",
                    "hits": {
                        "hits": [
                            {
                                "_index": "fireguard-firms",
                                "_id": "one",
                                "_source": {"source": "viirs", "latitude": 49.1},
                            },
                            {
                                "_index": "fireguard-firms",
                                "_id": "two",
                                "_source": {"source": "modis", "latitude": 49.2},
                            },
                        ]
                    },
                },
            )
        if url.endswith("/_search/scroll"):
            return ScriptedResponse(200, {"_scroll_id": "scroll_1", "hits": {"hits": []}})
        raise AssertionError(f"unexpected POST {url}")

    async def request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> ScriptedResponse:
        self.requests.append({"method": method, "url": url, "json": json})
        return ScriptedResponse(200, {})


class ScriptedSandbox:
    enabled = True

    def __init__(self, existing_stdout: str = "", existing_returncode: int = 2) -> None:
        self.existing_stdout = existing_stdout
        self.existing_returncode = existing_returncode
        self.exec_calls: list[dict[str, Any]] = []
        self.copy_calls: list[dict[str, Any]] = []

    async def exec(
        self,
        session_id: str,
        command: list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.exec_calls.append(
            {
                "session_id": session_id,
                "command": command,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"returncode": self.existing_returncode, "stdout": self.existing_stdout}

    async def copy_path(
        self,
        session_id: str,
        source_path: Path,
        destination_path: str,
        *,
        replace: bool = False,
    ) -> dict[str, Any]:
        manifest_path = source_path / "manifest.json"
        readme_path = source_path / "README.md"
        self.copy_calls.append(
            {
                "session_id": session_id,
                "destination_path": destination_path,
                "replace": replace,
                "manifest": json.loads(manifest_path.read_text(encoding="utf-8")),
                "readme": readme_path.read_text(encoding="utf-8"),
            }
        )
        return {"copied": True}


class ExportingBootstrapper(ProjectDataBootstrapper):
    async def _export_fireguard(self, export_dir: Path) -> dict[str, Any]:
        manifest = {
            "scope": "fireguard",
            "path": PROJECT_DATA_PATH,
            "index_prefix": self._config.fireguard_elasticsearch_index_prefix,
            "datasets": [],
        }
        (export_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (export_dir / "README.md").write_text("# FireGuard Data\n", encoding="utf-8")
        return manifest


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        state_dir=tmp_path,
        api_key="test-key",
        fireguard_elasticsearch_url="http://elastic.invalid",
        fireguard_elasticsearch_api_key="test-key",
        fireguard_data_bootstrap_max_docs_per_index=1,
        fireguard_data_bootstrap_page_size=50,
    )


def test_project_data_export_dataset_writes_limited_ndjson_and_stats(tmp_path: Path) -> None:
    async def exercise() -> None:
        bootstrapper = ProjectDataBootstrapper(_config(tmp_path), ScriptedSandbox())  # type: ignore[arg-type]
        client = ScriptedElasticClient()
        output_path = tmp_path / "firms.ndjson"

        stats = await bootstrapper._export_dataset(
            client,
            "http://elastic.invalid",
            FIREGUARD_DATASETS[0],
            output_path,
        )

        rows = [
            json.loads(line)
            for line in output_path.read_text(encoding="utf-8").splitlines()
        ]
        assert stats["name"] == "firms"
        assert stats["index"] == "fireguard-firms"
        assert stats["total_matches"] == 2
        assert stats["exported_docs"] == 1
        assert stats["truncated"] is True
        assert stats["source_fields"] == FIREGUARD_DATASETS[0].source_fields
        assert rows == [
            {
                "_index": "fireguard-firms",
                "_id": "one",
                "_source": {"source": "viirs", "latitude": 49.1},
            }
        ]
        assert client.posts[0]["url"].endswith("/fireguard-firms/_count")
        assert client.posts[0]["json"] == {"query": {"match_all": {}}}
        assert client.posts[1]["json"]["size"] == 1
        assert client.posts[1]["json"]["_source"] == {
            "includes": FIREGUARD_DATASETS[0].source_fields
        }
        assert client.requests == [
            {
                "method": "DELETE",
                "url": "http://elastic.invalid/_search/scroll",
                "json": {"scroll_id": ["scroll_1"]},
            }
        ]

    asyncio.run(exercise())


def test_project_data_bootstrap_reuses_existing_manifest(tmp_path: Path) -> None:
    async def exercise() -> None:
        existing = {
            "scope": "fireguard",
            "path": PROJECT_DATA_PATH,
            "index_prefix": "fireguard",
            "datasets": [],
        }
        sandbox = ScriptedSandbox(existing_stdout=json.dumps(existing), existing_returncode=0)
        bootstrapper = ProjectDataBootstrapper(_config(tmp_path), sandbox)  # type: ignore[arg-type]

        manifest = await bootstrapper.ensure_project_data("ses_test")

        assert manifest == {**existing, "reused": True}
        assert len(sandbox.exec_calls) == 1
        assert sandbox.copy_calls == []

    asyncio.run(exercise())


def test_project_data_bootstrap_copies_export_to_sandbox(tmp_path: Path) -> None:
    async def exercise() -> None:
        sandbox = ScriptedSandbox()
        bootstrapper = ExportingBootstrapper(_config(tmp_path), sandbox)  # type: ignore[arg-type]

        manifest = await bootstrapper.ensure_project_data("ses_test")

        assert manifest == {
            "scope": "fireguard",
            "path": PROJECT_DATA_PATH,
            "index_prefix": "fireguard",
            "datasets": [],
        }
        assert len(sandbox.copy_calls) == 1
        assert sandbox.copy_calls[0]["session_id"] == "ses_test"
        assert sandbox.copy_calls[0]["destination_path"] == PROJECT_DATA_PATH
        assert sandbox.copy_calls[0]["replace"] is True
        assert sandbox.copy_calls[0]["manifest"] == manifest
        assert sandbox.copy_calls[0]["readme"] == "# FireGuard Data\n"

    asyncio.run(exercise())
