from __future__ import annotations

import asyncio
import base64
import contextlib
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AppConfig


@dataclass
class SandboxInfo:
    session_id: str
    container_id: str
    container_name: str
    image: str
    timeout_seconds: int
    idle_timeout_seconds: int
    packages: list[str]
    leased_from_pool: bool = False


@dataclass
class WarmSandbox:
    container_id: str
    container_name: str
    created_at: float
    packages: list[str]


@dataclass
class DockerCommandResult:
    returncode: int
    stdout: str
    stderr: str


class DockerSandboxManager:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._infos: dict[str, SandboxInfo] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._created_at: dict[str, float] = {}
        self._last_used: dict[str, float] = {}
        self._warm_pool: list[WarmSandbox] = []
        self._pool_lock = asyncio.Lock()
        self._warming_count = 0
        self._idle_task: asyncio.Task[None] | None = None
        self._pool_task: asyncio.Task[None] | None = None
        self._closing = False

    @property
    def enabled(self) -> bool:
        return self._config.docker_sandbox_enabled

    async def start(self) -> None:
        if not self.enabled:
            return
        self._closing = False
        self._start_idle_reaper()
        self._schedule_pool_refill()

    async def ensure(self, session_id: str) -> SandboxInfo:
        if not self.enabled:
            raise RuntimeError("Docker sandbox is disabled")
        await self.start()
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            existing_info = self._infos.get(session_id)
            if existing_info is not None and await self._container_running(
                existing_info.container_id
            ):
                self._touch(session_id)
                return existing_info
            if existing_info is not None:
                await self._remove_container(existing_info.container_id)
                self._discard(session_id)

            packages = self._pip_packages()
            container_name = self._container_name(session_id)
            await self._remove_container(container_name)
            warm = await self._lease_warm_container(container_name)
            leased_from_pool = warm is not None
            container_id = (
                warm.container_id
                if warm is not None
                else await self._create_container(
                    container_name, session_id=session_id, warm_pool=False
                )
            )
            info = SandboxInfo(
                session_id=session_id,
                container_id=container_id,
                container_name=container_name,
                image=self._config.docker_sandbox_image,
                timeout_seconds=self._config.docker_sandbox_timeout_seconds,
                idle_timeout_seconds=self._config.docker_sandbox_idle_timeout_seconds,
                packages=packages,
                leased_from_pool=leased_from_pool,
            )
            self._infos[session_id] = info
            self._created_at[session_id] = time.monotonic()
            self._touch(session_id)
            try:
                if self._config.docker_sandbox_install_packages_on_start:
                    await self._install_packages(info)
            except Exception:
                await self._remove_container(container_id)
                self._discard(session_id)
                raise
            self._touch(session_id)
            self._schedule_pool_refill()
            return info

    async def exec(
        self,
        session_id: str,
        command: list[str],
        *,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        info = await self._sandbox(session_id)
        self._touch(session_id)
        result = await self._run_docker(
            ["exec", "--workdir", "/workspace", info.container_id, *command],
            timeout_seconds=timeout_seconds,
            check=False,
        )
        self._touch(session_id)
        return {
            "sandbox": info.__dict__,
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    async def write_file(self, session_id: str, path: str, content: str) -> dict[str, Any]:
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        script = (
            "import base64, pathlib\n"
            f"path = pathlib.Path({path!r})\n"
            "path.parent.mkdir(parents=True, exist_ok=True)\n"
            f"path.write_bytes(base64.b64decode({encoded!r}))\n"
            "print(str(path))\n"
        )
        result = await self.exec(session_id, ["python", "-c", script], timeout_seconds=60)
        return {**result, "path": path, "bytes": len(content.encode("utf-8"))}

    async def read_file(self, session_id: str, path: str, *, max_bytes: int) -> dict[str, Any]:
        script = (
            "import pathlib, sys\n"
            f"path = pathlib.Path({path!r})\n"
            f"sys.stdout.buffer.write(path.read_bytes()[:{max_bytes}])\n"
        )
        result = await self.exec(session_id, ["python", "-c", script], timeout_seconds=60)
        return {**result, "path": path, "max_bytes": max_bytes}

    async def export_asset(
        self, session_id: str, sandbox_path: str, assets_dir: Path
    ) -> dict[str, Any]:
        info = await self._sandbox(session_id)
        self._touch(session_id)
        filename = Path(sandbox_path).name
        unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        dest = assets_dir / unique_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        await self._run_docker(
            ["cp", f"{info.container_id}:{sandbox_path}", str(dest)],
            timeout_seconds=30,
        )
        self._touch(session_id)
        return {"saved_as": unique_name, "size": dest.stat().st_size}

    async def list_files(self, session_id: str, path: str, *, max_entries: int) -> dict[str, Any]:
        script = (
            "import json, pathlib\n"
            f"root = pathlib.Path({path!r})\n"
            "items = []\n"
            "iterator = root.rglob('*') if root.exists() else []\n"
            "for index, item in enumerate(iterator):\n"
            f"    if index >= {max_entries}: break\n"
            "    items.append({'path': str(item), 'is_dir': item.is_dir(), "
            "'size': item.stat().st_size if item.is_file() else None})\n"
            "print(json.dumps(items))\n"
        )
        result = await self.exec(session_id, ["python", "-c", script], timeout_seconds=60)
        return {**result, "path": path, "max_entries": max_entries}

    async def copy_path(
        self,
        session_id: str,
        source_path: Path,
        target_path: str,
        *,
        replace: bool = False,
    ) -> dict[str, Any]:
        info = await self._sandbox(session_id)
        self._touch(session_id)
        setup_script = (
            "import pathlib, shutil\n"
            f"path = pathlib.Path({target_path!r})\n"
            "if path.exists() and "
            f"{replace!r}"
            ":\n"
            "    shutil.rmtree(path) if path.is_dir() else path.unlink()\n"
            "path.mkdir(parents=True, exist_ok=True)\n"
        )
        await self.exec(session_id, ["python", "-c", setup_script], timeout_seconds=60)
        docker_source = f"{source_path}/." if source_path.is_dir() else str(source_path)
        result = await self._run_docker(
            ["cp", docker_source, f"{info.container_id}:{target_path}"],
            timeout_seconds=self._config.docker_sandbox_setup_timeout_seconds,
        )
        self._touch(session_id)
        return {
            "sandbox": info.__dict__,
            "source_path": str(source_path),
            "target_path": target_path,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    async def terminate(self, session_id: str) -> SandboxInfo | None:
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            info = self._infos.pop(session_id, None)
            self._created_at.pop(session_id, None)
            self._last_used.pop(session_id, None)
            if info is None:
                return None
            await self._remove_container(info.container_id)
            self._schedule_pool_refill()
            return info

    async def close(self) -> None:
        self._closing = True
        if self._idle_task is not None:
            self._idle_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._idle_task
        if self._pool_task is not None:
            self._pool_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pool_task
        await asyncio.gather(
            *(self.terminate(session_id) for session_id in list(self._infos)),
            return_exceptions=True,
        )
        await asyncio.gather(
            *(self._remove_container(warm.container_id) for warm in list(self._warm_pool)),
            return_exceptions=True,
        )
        self._warm_pool.clear()

    async def _sandbox(self, session_id: str) -> SandboxInfo:
        await self.ensure(session_id)
        info = self._infos.get(session_id)
        if info is None:
            raise RuntimeError("Docker sandbox is not available")
        return info

    async def _create_container(
        self, container_name: str, *, session_id: str | None, warm_pool: bool
    ) -> str:
        args = [
            "run",
            "--detach",
            "--name",
            container_name,
            "--label",
            "fireguard-intelligence.sandbox=1",
            "--label",
            f"fireguard-intelligence.session_id={session_id or ''}",
            "--label",
            f"fireguard-intelligence.pool={'warm' if warm_pool else 'leased'}",
            "--network",
            self._config.docker_sandbox_network,
            "--security-opt",
            "no-new-privileges",
            "--workdir",
            "/workspace",
            self._config.docker_sandbox_image,
            "sh",
            "-lc",
            "mkdir -p /workspace && tail -f /dev/null",
        ]
        result = await self._run_docker(
            args, timeout_seconds=self._config.docker_sandbox_setup_timeout_seconds
        )
        return result.stdout.strip()

    async def _install_packages(self, info: SandboxInfo) -> None:
        if len(info.packages) == 0:
            return
        await self._run_docker(
            [
                "exec",
                "--workdir",
                "/workspace",
                info.container_id,
                "python",
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-cache-dir",
                *info.packages,
            ],
            timeout_seconds=self._config.docker_sandbox_setup_timeout_seconds,
        )

    async def _container_running(self, container_id: str) -> bool:
        result = await self._run_docker(
            ["inspect", "--format", "{{.State.Running}}", container_id],
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"

    async def _remove_container(self, container_id_or_name: str) -> None:
        await self._run_docker(["rm", "--force", "--volumes", container_id_or_name], check=False)

    async def _rename_container(self, container_id: str, container_name: str) -> None:
        await self._run_docker(["rename", container_id, container_name])

    async def _run_docker(
        self,
        args: list[str],
        *,
        timeout_seconds: float | None = None,
        check: bool = True,
    ) -> DockerCommandResult:
        try:
            process = await asyncio.create_subprocess_exec(
                "docker",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Docker CLI is not available on PATH") from exc

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        except TimeoutError as exc:
            await self._kill_process(process)
            raise TimeoutError(f"docker command timed out after {timeout_seconds} seconds") from exc
        except asyncio.CancelledError:
            await self._kill_process(process)
            raise

        result = DockerCommandResult(
            returncode=process.returncode if process.returncode is not None else -1,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )
        if check and result.returncode != 0:
            details = _truncate(result.stderr.strip() or result.stdout.strip())
            raise RuntimeError(
                f"docker {' '.join(args[:2])} failed with exit code {result.returncode}: {details}"
            )
        return result

    async def _kill_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            process.kill()
        await process.communicate()

    def _start_idle_reaper(self) -> None:
        if self._idle_task is None or self._idle_task.done():
            self._idle_task = asyncio.create_task(self._reap_expired_containers())

    def _schedule_pool_refill(self) -> None:
        if self._closing or not self.enabled or self._config.docker_sandbox_pool_size == 0:
            return
        if self._pool_task is None or self._pool_task.done():
            self._pool_task = asyncio.create_task(self._refill_warm_pool())

    async def _refill_warm_pool(self) -> None:
        async with self._pool_lock:
            target = self._config.docker_sandbox_pool_size
            while len(self._warm_pool) + self._warming_count < target:
                self._warming_count += 1
                try:
                    packages = self._pip_packages()
                    container_name = self._warm_container_name()
                    await self._remove_container(container_name)
                    container_id = await self._create_container(
                        container_name, session_id=None, warm_pool=True
                    )
                    warm = WarmSandbox(
                        container_id=container_id,
                        container_name=container_name,
                        created_at=time.monotonic(),
                        packages=packages,
                    )
                    if self._config.docker_sandbox_install_packages_on_start:
                        info = SandboxInfo(
                            session_id="",
                            container_id=container_id,
                            container_name=container_name,
                            image=self._config.docker_sandbox_image,
                            timeout_seconds=self._config.docker_sandbox_timeout_seconds,
                            idle_timeout_seconds=self._config.docker_sandbox_idle_timeout_seconds,
                            packages=packages,
                            leased_from_pool=False,
                        )
                        await self._install_packages(info)
                    self._warm_pool.append(warm)
                finally:
                    self._warming_count -= 1

    async def _lease_warm_container(self, container_name: str) -> WarmSandbox | None:
        async with self._pool_lock:
            while len(self._warm_pool) > 0:
                warm = self._warm_pool.pop(0)
                if not await self._container_running(warm.container_id):
                    await self._remove_container(warm.container_id)
                    continue
                await self._rename_container(warm.container_id, container_name)
                warm.container_name = container_name
                return warm
        return None

    async def _reap_expired_containers(self) -> None:
        sleep_seconds = min(self._config.docker_sandbox_idle_timeout_seconds, 60)
        while True:
            await asyncio.sleep(sleep_seconds)
            now = time.monotonic()
            for session_id in list(self._infos):
                created_at = self._created_at.get(session_id, now)
                last_used = self._last_used.get(session_id, now)
                if (
                    now - created_at >= self._config.docker_sandbox_timeout_seconds
                    or now - last_used >= self._config.docker_sandbox_idle_timeout_seconds
                ):
                    await self.terminate(session_id)

    def _touch(self, session_id: str) -> None:
        self._last_used[session_id] = time.monotonic()

    def _discard(self, session_id: str) -> None:
        self._infos.pop(session_id, None)
        self._created_at.pop(session_id, None)
        self._last_used.pop(session_id, None)

    def _pip_packages(self) -> list[str]:
        return [
            package.strip()
            for package in self._config.docker_sandbox_pip_packages.split(",")
            if len(package.strip()) > 0
        ]

    def _container_name(self, session_id: str) -> str:
        prefix = _sanitize_container_name(self._config.docker_sandbox_container_prefix)
        suffix = _sanitize_container_name(session_id)
        return f"{prefix}-{suffix}"[:255]

    def _warm_container_name(self) -> str:
        prefix = _sanitize_container_name(self._config.docker_sandbox_container_prefix)
        suffix = uuid.uuid4().hex[:12]
        return f"{prefix}-warm-{suffix}"[:255]


def _sanitize_container_name(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-_.")
    if len(sanitized) == 0:
        return "sandbox"
    return sanitized


def _truncate(value: str, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."
