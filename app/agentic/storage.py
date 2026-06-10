from __future__ import annotations

import asyncio
import json
import shutil
from collections import defaultdict
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from .config import AppConfig
from .models import (
    ChatMessage,
    Checkpoint,
    SessionRecord,
    StreamEvent,
    TraceEvent,
    WorkflowRun,
)


class FileStore:
    def __init__(self, config: AppConfig) -> None:
        self.root = config.state_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        path = self.root / "sessions" / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def run_dir(self, session_id: str, run_id: str) -> Path:
        path = self.session_dir(session_id) / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def agent_dir(self, session_id: str, agent_id: str) -> Path:
        path = self.session_dir(session_id) / "agents" / agent_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def assets_dir(self, session_id: str) -> Path:
        path = self.session_dir(session_id) / "assets"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_session(self, session: SessionRecord) -> None:
        (self.session_dir(session.session_id) / "session.json").write_text(
            session.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def load_session(self, session_id: str) -> SessionRecord:
        path = self.session_dir(session_id) / "session.json"
        if not path.exists():
            raise FileNotFoundError(f"session {session_id} does not exist")
        return SessionRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list_sessions(self) -> list[SessionRecord]:
        sessions_root = self.root / "sessions"
        if not sessions_root.exists():
            return []
        sessions: list[SessionRecord] = []
        for path in sessions_root.iterdir():
            session_path = path / "session.json"
            if session_path.exists():
                sessions.append(SessionRecord.model_validate_json(session_path.read_text(encoding="utf-8")))
        return sorted(sessions, key=lambda session: session.updated_at, reverse=True)

    def save_run(self, run: WorkflowRun) -> None:
        path = self.run_dir(run.session_id, run.run_id) / "state.json"
        path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        workflow_path = self.run_dir(run.session_id, run.run_id) / "workflow.json"
        workflow_path.write_text(run.workflow.model_dump_json(indent=2), encoding="utf-8")

    def load_run(self, session_id: str, run_id: str) -> WorkflowRun:
        path = self.run_dir(session_id, run_id) / "state.json"
        if not path.exists():
            raise FileNotFoundError(f"run {run_id} does not exist for session {session_id}")
        return WorkflowRun.model_validate_json(path.read_text(encoding="utf-8"))

    def list_runs(self, session_id: str) -> list[WorkflowRun]:
        runs_root = self.session_dir(session_id) / "runs"
        if not runs_root.exists():
            return []
        runs: list[WorkflowRun] = []
        for path in runs_root.iterdir():
            state_path = path / "state.json"
            if state_path.exists():
                runs.append(WorkflowRun.model_validate_json(state_path.read_text(encoding="utf-8")))
        return sorted(runs, key=lambda run: run.updated_at, reverse=True)

    def latest_run(self, session_id: str) -> WorkflowRun | None:
        runs = self.list_runs(session_id)
        if len(runs) == 0:
            return None
        return runs[0]

    def append_event(self, event: StreamEvent) -> None:
        self._append_jsonl(self.run_dir(event.session_id, event.run_id) / "events.jsonl", event.model_dump(mode="json"))

    def read_events(self, session_id: str, run_id: str) -> list[StreamEvent]:
        return [
            StreamEvent.model_validate(item)
            for item in self._read_jsonl(self.run_dir(session_id, run_id) / "events.jsonl")
        ]

    def append_trace(self, event: TraceEvent) -> None:
        if event.run_id is None:
            path = self.session_dir(event.session_id) / "trace.jsonl"
        else:
            path = self.run_dir(event.session_id, event.run_id) / "trace.jsonl"
        self._append_jsonl(path, event.model_dump(mode="json"))

    def append_history(self, session_id: str, run_id: str, agent_id: str, message: ChatMessage) -> None:
        entry = {"run_id": run_id, **message.model_dump(mode="json")}
        self._append_jsonl(self.agent_dir(session_id, agent_id) / "history.jsonl", entry)
        self._append_jsonl(self.run_dir(session_id, run_id) / "history.jsonl", {"agent_id": agent_id, **entry})

    def read_agent_history(self, session_id: str, agent_id: str) -> list[dict[str, Any]]:
        return self._read_jsonl(self.agent_dir(session_id, agent_id) / "history.jsonl")

    def read_run_history(self, session_id: str, run_id: str) -> list[dict[str, Any]]:
        return self._read_jsonl(self.run_dir(session_id, run_id) / "history.jsonl")

    def read_run_trace(self, session_id: str, run_id: str) -> list[dict[str, Any]]:
        return self._read_jsonl(self.run_dir(session_id, run_id) / "trace.jsonl")

    def write_checkpoint(self, checkpoint: Checkpoint) -> None:
        checkpoints_dir = self.run_dir(checkpoint.session_id, checkpoint.run_id) / "checkpoints"
        checkpoints_dir.mkdir(parents=True, exist_ok=True)
        (checkpoints_dir / f"{checkpoint.checkpoint_id}.json").write_text(
            checkpoint.model_dump_json(indent=2),
            encoding="utf-8",
        )
        index_path = self.run_dir(checkpoint.session_id, checkpoint.run_id) / "checkpoints.jsonl"
        self._append_jsonl(index_path, checkpoint.model_dump(mode="json"))

    def load_checkpoint(self, session_id: str, run_id: str, checkpoint_id: str) -> Checkpoint:
        path = self.run_dir(session_id, run_id) / "checkpoints" / f"{checkpoint_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"checkpoint {checkpoint_id} does not exist for run {run_id}")
        return Checkpoint.model_validate_json(path.read_text(encoding="utf-8"))

    def latest_checkpoint(self, session_id: str, run_id: str) -> Checkpoint:
        index_path = self.run_dir(session_id, run_id) / "checkpoints.jsonl"
        checkpoints = self._read_jsonl(index_path)
        if len(checkpoints) == 0:
            raise FileNotFoundError(f"run {run_id} has no checkpoints")
        return Checkpoint.model_validate(checkpoints[-1])

    def checkpoint_for_event(self, session_id: str, run_id: str, event_id: str) -> Checkpoint:
        index_path = self.run_dir(session_id, run_id) / "checkpoints.jsonl"
        checkpoints = self._read_jsonl(index_path)
        for item in reversed(checkpoints):
            if item.get("event_id") == event_id:
                return Checkpoint.model_validate(item)
        events = self.read_events(session_id, run_id)
        event_positions = {event.event_id: index for index, event in enumerate(events)}
        target_position = event_positions.get(event_id)
        if target_position is None:
            raise FileNotFoundError(f"event {event_id} has no checkpoint for run {run_id}")

        positioned: list[tuple[int, dict[str, Any]]] = []
        for item in checkpoints:
            checkpoint_event_id = item.get("event_id")
            if not isinstance(checkpoint_event_id, str):
                continue
            checkpoint_position = event_positions.get(checkpoint_event_id)
            if checkpoint_position is None:
                continue
            positioned.append((checkpoint_position, item))

        following = [
            (position, item) for position, item in positioned if position >= target_position
        ]
        if len(following) > 0:
            return Checkpoint.model_validate(min(following, key=lambda entry: entry[0])[1])
        previous = [
            (position, item) for position, item in positioned if position <= target_position
        ]
        if len(previous) > 0:
            return Checkpoint.model_validate(max(previous, key=lambda entry: entry[0])[1])
        raise FileNotFoundError(f"event {event_id} has no checkpoint for run {run_id}")

    def delete_state(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=str, separators=(",", ":")))
            handle.write("\n")

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[tuple[str, str], set[asyncio.Queue[StreamEvent | None]]] = defaultdict(set)

    async def publish(self, event: StreamEvent) -> None:
        key = (event.session_id, event.run_id)
        for queue in list(self._subscribers[key]):
            await queue.put(event)

    async def subscribe(self, session_id: str, run_id: str) -> AsyncIterator[StreamEvent]:
        key = (session_id, run_id)
        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        self._subscribers[key].add(queue)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            self._subscribers[key].discard(queue)

    async def close(self) -> None:
        for queues in self._subscribers.values():
            for queue in queues:
                await queue.put(None)
