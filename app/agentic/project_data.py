from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .config import AppConfig
from .docker_sandbox import DockerSandboxManager

PROJECT_DATA_PATH = "/workspace/project_data"
PROJECT_DATA_VERSION = 2


@dataclass(frozen=True)
class FireGuardDataset:
    name: str
    suffix: str
    filename: str
    source_fields: list[str]
    description: str


@dataclass(frozen=True)
class LocalFireGuardDataset:
    name: str
    source_path: Path
    project_path: Path
    format: str
    description: str


FIREGUARD_DATASETS = [
    FireGuardDataset(
        name="firms",
        suffix="firms",
        filename="firms.ndjson",
        description="FIRMS satellite fire detections indexed by FireGuard.",
        source_fields=[
            "source",
            "acquired_at",
            "latitude",
            "longitude",
            "confidence",
            "frp",
            "brightness",
            "satellite",
            "instrument",
            "weather",
            "place",
        ],
    ),
    FireGuardDataset(
        name="bcws_incidents",
        suffix="bcws-incidents",
        filename="bcws_incidents.ndjson",
        description="BCWS incident context indexed by FireGuard.",
        source_fields=[
            "source",
            "fire_number",
            "incident_name",
            "fire_status",
            "fire_cause",
            "fire_type",
            "current_size_ha",
            "ignition_date",
            "fire_out_date",
            "geographic_description",
            "fire_url",
            "latitude",
            "longitude",
            "updated_at",
        ],
    ),
    FireGuardDataset(
        name="bcws_perimeters",
        suffix="bcws-perimeters",
        filename="bcws_perimeters.ndjson",
        description="BCWS fire perimeter context indexed by FireGuard.",
        source_fields=[
            "source",
            "fire_number",
            "fire_status",
            "fire_size_hectares",
            "track_date",
            "load_date",
            "fire_url",
            "feature_area_sqm",
            "feature_length_m",
            "updated_at",
            "geometry",
        ],
    ),
]

LOCAL_FIREGUARD_DATASETS = [
    LocalFireGuardDataset(
        name="bc_historical_fire_evacuation_zones",
        source_path=Path("data/public/bc/historical_fire_evacuation_zones_snapshot.json"),
        project_path=Path("data/public/bc/historical_fire_evacuation_zones_snapshot.json"),
        format="json",
        description="Historical BC fire evacuation zones snapshot for the Cariboo/Williams Lake scenario.",
    ),
    LocalFireGuardDataset(
        name="bc_official_policy_snippets",
        source_path=Path("data/public/bc/official_policy_snippets.json"),
        project_path=Path("data/public/bc/official_policy_snippets.json"),
        format="json",
        description="Official public safety policy snippets for the BC scenario.",
    ),
    LocalFireGuardDataset(
        name="bc_public_emergency_context",
        source_path=Path("data/public/bc/public_emergency_context_snapshot.json"),
        project_path=Path("data/public/bc/public_emergency_context_snapshot.json"),
        format="json",
        description="BC public emergency context, including evacuation orders and ESS facilities.",
    ),
    LocalFireGuardDataset(
        name="bc_cariboo_firms_snapshot",
        source_path=Path("data/replay/bc_cariboo/firms_snapshot.csv"),
        project_path=Path("data/replay/bc_cariboo/firms_snapshot.csv"),
        format="csv",
        description="FIRMS snapshot scoped to July 2024 Cariboo/Williams Lake replay.",
    ),
    LocalFireGuardDataset(
        name="bc_cariboo_firms_snapshot_metadata",
        source_path=Path("data/replay/bc_cariboo/firms_snapshot.metadata.json"),
        project_path=Path("data/replay/bc_cariboo/firms_snapshot.metadata.json"),
        format="json",
        description="Source metadata for the July 2024 Cariboo/Williams Lake FIRMS snapshot.",
    ),
    LocalFireGuardDataset(
        name="bc_cariboo_road_events",
        source_path=Path("data/replay/bc_cariboo/road_events_snapshot.json"),
        project_path=Path("data/replay/bc_cariboo/road_events_snapshot.json"),
        format="json",
        description="Road event snapshot for the July 2024 Cariboo/Williams Lake scenario.",
    ),
    LocalFireGuardDataset(
        name="bc_cariboo_weather",
        source_path=Path("data/replay/bc_cariboo/weather_snapshot.json"),
        project_path=Path("data/replay/bc_cariboo/weather_snapshot.json"),
        format="json",
        description="Weather snapshot for the July 2024 Cariboo/Williams Lake scenario.",
    ),
]


class ProjectDataBootstrapper:
    def __init__(self, config: AppConfig, sandbox_manager: DockerSandboxManager) -> None:
        self._config = config
        self._sandbox_manager = sandbox_manager

    @property
    def enabled(self) -> bool:
        return (
            self._config.fireguard_data_bootstrap_enabled
            and self._sandbox_manager.enabled
            and len(self._config.fireguard_elasticsearch_url.strip()) > 0
            and len(self._config.fireguard_elasticsearch_api_key.strip()) > 0
        )

    async def ensure_project_data(self, session_id: str) -> dict[str, Any]:
        if not self.enabled:
            return {
                "enabled": False,
                "scope": "fireguard",
                "path": PROJECT_DATA_PATH,
                "index_prefix": self._config.fireguard_elasticsearch_index_prefix,
            }
        existing = await self._existing_manifest(session_id)
        if existing is not None:
            return {**existing, "reused": True}

        with tempfile.TemporaryDirectory(prefix="fireguard-project-data-") as temp_name:
            export_dir = Path(temp_name)
            manifest = await self._export_fireguard(export_dir)
            await self._sandbox_manager.copy_path(
                session_id, export_dir, PROJECT_DATA_PATH, replace=True
            )
        return manifest

    async def _existing_manifest(self, session_id: str) -> dict[str, Any] | None:
        script = (
            "import json, pathlib\n"
            f"path = pathlib.Path({PROJECT_DATA_PATH!r}) / 'manifest.json'\n"
            "if not path.exists():\n"
            "    raise SystemExit(2)\n"
            "data = json.loads(path.read_text(encoding='utf-8'))\n"
            "if data.get('scope') != 'fireguard':\n"
            "    raise SystemExit(3)\n"
            f"if data.get('index_prefix') != {self._config.fireguard_elasticsearch_index_prefix!r}:\n"
            "    raise SystemExit(4)\n"
            "print(json.dumps(data))\n"
        )
        result = await self._sandbox_manager.exec(
            session_id, ["python", "-c", script], timeout_seconds=30
        )
        if result.get("returncode") != 0:
            return None
        stdout = result.get("stdout")
        if not isinstance(stdout, str) or len(stdout.strip()) == 0:
            return None
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict) or parsed.get("data_version") != PROJECT_DATA_VERSION:
            return None
        return parsed if isinstance(parsed, dict) else None

    async def _export_fireguard(self, export_dir: Path) -> dict[str, Any]:
        export_dir.mkdir(parents=True, exist_ok=True)
        datasets: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=None, headers=self._headers()) as client:
            base_url = self._base_url()
            for dataset in FIREGUARD_DATASETS:
                output_path = export_dir / dataset.filename
                stats = await self._export_dataset(client, base_url, dataset, output_path)
                datasets.append(stats)
        local_datasets = self._copy_local_datasets(export_dir)

        manifest = {
            "scope": "fireguard",
            "data_version": PROJECT_DATA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "path": PROJECT_DATA_PATH,
            "index_prefix": self._config.fireguard_elasticsearch_index_prefix,
            "elasticsearch": {"url": self._safe_url()},
            "limits": {
                "max_docs_per_index": self._config.fireguard_data_bootstrap_max_docs_per_index,
                "page_size": self._config.fireguard_data_bootstrap_page_size,
            },
            "datasets": datasets,
            "local_datasets": local_datasets,
            "notes": [
                "Files are newline-delimited JSON. Each row has _index, _id, and _source.",
                "Large datasets may be truncated; check each dataset.truncated flag.",
                "Local BC context files are copied under their manifest local_datasets paths.",
                "Use Python, pandas, polars, or duckdb in the sandbox to inspect these files.",
            ],
        }
        (export_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str), encoding="utf-8"
        )
        (export_dir / "README.md").write_text(_readme(datasets, local_datasets), encoding="utf-8")
        return manifest

    def _copy_local_datasets(self, export_dir: Path) -> list[dict[str, Any]]:
        copied: list[dict[str, Any]] = []
        for dataset in LOCAL_FIREGUARD_DATASETS:
            source = Path.cwd() / dataset.source_path
            target = export_dir / dataset.project_path
            available = source.exists()
            if available:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            copied.append(
                {
                    "name": dataset.name,
                    "description": dataset.description,
                    "file": str(dataset.project_path),
                    "format": dataset.format,
                    "source_path": str(dataset.source_path),
                    "bytes": source.stat().st_size if available else 0,
                    "available": available,
                }
            )
        return copied

    async def _export_dataset(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        dataset: FireGuardDataset,
        output_path: Path,
    ) -> dict[str, Any]:
        index = f"{self._config.fireguard_elasticsearch_index_prefix}-{dataset.suffix}"
        total = await self._count(client, base_url, index)
        max_docs = self._config.fireguard_data_bootstrap_max_docs_per_index
        exported = 0
        output_path.write_text("", encoding="utf-8")
        if total > 0:
            exported = await self._write_hits(client, base_url, index, dataset, output_path, max_docs)
        return {
            "name": dataset.name,
            "index": index,
            "description": dataset.description,
            "file": dataset.filename,
            "total_matches": total,
            "exported_docs": exported,
            "truncated": total > exported,
            "source_fields": dataset.source_fields,
        }

    async def _count(self, client: httpx.AsyncClient, base_url: str, index: str) -> int:
        response = await client.post(f"{base_url}/{index}/_count", json={"query": {"match_all": {}}})
        if response.status_code == 404:
            return 0
        response.raise_for_status()
        data = response.json()
        count = data.get("count") if isinstance(data, dict) else None
        return count if isinstance(count, int) else 0

    async def _write_hits(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        index: str,
        dataset: FireGuardDataset,
        output_path: Path,
        max_docs: int,
    ) -> int:
        page_size = min(self._config.fireguard_data_bootstrap_page_size, max_docs)
        exported = 0
        scroll_id: str | None = None
        try:
            response = await client.post(
                f"{base_url}/{index}/_search",
                params={"scroll": "2m"},
                json={
                    "size": page_size,
                    "query": {"match_all": {}},
                    "sort": ["_doc"],
                    "_source": {"includes": dataset.source_fields},
                },
            )
            if response.status_code == 404:
                return 0
            response.raise_for_status()
            data = response.json()
            scroll_id = data.get("_scroll_id") if isinstance(data, dict) else None
            while exported < max_docs:
                hits = _hits(data)
                if len(hits) == 0:
                    break
                with output_path.open("a", encoding="utf-8") as handle:
                    for hit in hits:
                        if exported >= max_docs:
                            break
                        handle.write(json.dumps(_export_row(hit), default=str, separators=(",", ":")))
                        handle.write("\n")
                        exported += 1
                if exported >= max_docs or scroll_id is None:
                    break
                response = await client.post(
                    f"{base_url}/_search/scroll",
                    json={"scroll": "2m", "scroll_id": scroll_id},
                )
                response.raise_for_status()
                data = response.json()
                scroll_id = data.get("_scroll_id") if isinstance(data, dict) else scroll_id
        finally:
            if scroll_id is not None:
                await client.request(
                    "DELETE",
                    f"{base_url}/_search/scroll",
                    json={"scroll_id": [scroll_id]},
                )
        return exported

    def _base_url(self) -> str:
        return self._config.fireguard_elasticsearch_url.rstrip("/")

    def _safe_url(self) -> str:
        return self._config.fireguard_elasticsearch_url.strip()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"ApiKey {self._config.fireguard_elasticsearch_api_key}"}


def _hits(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    hits = data.get("hits")
    if not isinstance(hits, dict):
        return []
    raw_hits = hits.get("hits")
    if not isinstance(raw_hits, list):
        return []
    return [hit for hit in raw_hits if isinstance(hit, dict)]


def _export_row(hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "_index": hit.get("_index"),
        "_id": hit.get("_id"),
        "_source": hit.get("_source") if isinstance(hit.get("_source"), dict) else {},
    }


def _readme(datasets: list[dict[str, Any]], local_datasets: list[dict[str, Any]]) -> str:
    lines = [
        "# FireGuard Data",
        "",
        "This directory was exported from FireGuard Elasticsearch indices during sandbox bootstrap.",
        "",
        "## Files",
        "",
        "- `manifest.json`: export metadata, counts, truncation flags, and field lists.",
    ]
    for dataset in datasets:
        lines.append(
            f"- `{dataset['file']}`: {dataset['name']} from `{dataset['index']}` "
            f"({dataset['exported_docs']}/{dataset['total_matches']} docs)."
        )
    if len(local_datasets) > 0:
        lines.extend(["", "## Local BC Context", ""])
        for dataset in local_datasets:
            status = "available" if dataset["available"] else "missing"
            lines.append(
                f"- `{dataset['file']}`: {dataset['name']} "
                f"({dataset['format']}, {dataset['bytes']} bytes, {status})."
            )
    lines.extend(
        [
            "",
            "## Quick Start",
            "",
            "```python",
            "import json, pathlib, pandas as pd",
            f"root = pathlib.Path({PROJECT_DATA_PATH!r})",
            "manifest = json.loads((root / 'manifest.json').read_text())",
            "firms = pd.read_json(root / 'firms.ndjson', lines=True)",
            "firms['_source'].iloc[0] if len(firms) else None",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"
