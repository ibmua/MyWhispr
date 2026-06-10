"""Daemon-side manager for Hugging Face model weight downloads.

Spawns ``python -m mywhispr.hf_download`` with the model's python (the GPU
venv has huggingface_hub) and tracks per-model progress for the web UI.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable

from .model_specs import resolve_project_python, whisper_cpp_download_url

log = logging.getLogger(__name__)


class ModelDownloadManager:
    def __init__(
        self,
        *,
        root: Path,
        python_resolver: Callable[[dict[str, Any]], str],
        on_complete: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self.root = root
        self._python_resolver = python_resolver
        self._on_complete = on_complete
        self._tasks: dict[str, asyncio.Task] = {}
        self._status: dict[str, dict[str, Any]] = {}

    def _resolve_python(self, python: str) -> Path:
        return resolve_project_python(python, self.root)

    def status_for(self, name: str) -> dict[str, Any] | None:
        return self._status.get(name)

    def is_downloading(self, name: str) -> bool:
        task = self._tasks.get(name)
        return task is not None and not task.done()

    def _resolve_target_path(self, path: str) -> Path:
        dest = Path(path)
        if not dest.is_absolute():
            dest = (self.root / dest).resolve()
        return dest

    async def start(self, name: str, spec: dict[str, Any]) -> tuple[bool, str]:
        if self.is_downloading(name):
            return True, "already downloading"
        repo_id = str(spec.get("repo_id") or "").strip()
        url = ""
        target_path = ""
        if spec.get("backend") == "whisper.cpp":
            url = whisper_cpp_download_url(spec)
            target_path = str(spec.get("path") or "").strip()
            if not target_path:
                return False, "model has no path to download"
            if not url:
                return False, "model has no download_url"
            exe = Path(sys.executable)
            dest = self._resolve_target_path(target_path)
            args = [str(exe), "-m", "mywhispr.file_download", url, str(dest)]
        else:
            if not repo_id:
                return False, "model has no repo_id to download"
            exe = self._resolve_python(self._python_resolver(spec))
            args = [str(exe), "-m", "mywhispr.hf_download", repo_id]
            for pattern in spec.get("download_exclude") or []:
                args += ["--exclude", str(pattern)]
        if not exe.exists():
            return False, f"python not found: {exe}"
        env = os.environ.copy()
        env.pop("HF_HUB_OFFLINE", None)
        env.pop("TRANSFORMERS_OFFLINE", None)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(self.root),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            return False, f"failed to start downloader: {e}"
        self._status[name] = {
            "state": "downloading",
            "repo_id": repo_id,
            "download_url": url,
            "target_path": target_path,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "error": "",
            "started_at": time.time(),
        }
        self._tasks[name] = asyncio.create_task(self._run(name, proc))
        log.info("model download started name=%s repo=%s url=%s python=%s", name, repo_id, url, exe)
        return True, "download started"

    async def _run(self, name: str, proc: asyncio.subprocess.Process) -> None:
        status = self._status[name]
        stderr_tail: deque[str] = deque(maxlen=30)

        async def drain_stderr() -> None:
            assert proc.stderr is not None
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                stderr_tail.append(line.decode("utf-8", "replace").rstrip())

        stderr_task = asyncio.create_task(drain_stderr())
        failed_message = ""
        try:
            assert proc.stdout is not None
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                try:
                    msg = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                event = msg.get("event")
                if event == "total":
                    status["total_bytes"] = int(msg.get("total_bytes") or 0)
                elif event in ("progress", "done"):
                    status["downloaded_bytes"] = int(
                        msg.get("downloaded_bytes") or status["downloaded_bytes"]
                    )
                elif event == "error":
                    failed_message = str(msg.get("message") or "download failed")
            rc = await proc.wait()
        except asyncio.CancelledError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            status["state"] = "error"
            status["error"] = "download cancelled"
            raise
        finally:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(stderr_task, 3.0)
        if rc == 0 and not failed_message:
            status["state"] = "done"
            log.info("model download finished name=%s", name)
            if self._on_complete is not None:
                try:
                    await self._on_complete(name)
                except Exception:
                    log.exception("post-download apply failed name=%s", name)
        else:
            status["state"] = "error"
            status["error"] = failed_message or "; ".join(list(stderr_tail)[-3:]) or f"downloader exited rc={rc}"
            log.error("model download failed name=%s: %s", name, status["error"])
