from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from collections import deque
from pathlib import Path

from .model_specs import normalize_model_spec

log = logging.getLogger(__name__)


class WhisperServer:
    """Supervises one whisper.cpp server process bound to 127.0.0.1."""

    def __init__(
        self,
        binary: str,
        host: str,
        port: int,
        model_paths: dict[str, str],
        startup_timeout: float = 180.0,
        idle_shutdown_seconds: float = 0.0,
        name: str = "primary",
    ) -> None:
        self.binary = binary
        self.host = host
        self.port = port
        self.models = model_paths
        self.startup_timeout = startup_timeout
        self.idle_shutdown_seconds = idle_shutdown_seconds
        self.name = name
        self.proc: asyncio.subprocess.Process | None = None
        self.loaded_model: str | None = None
        self._ready = asyncio.Event()
        self._start_lock = asyncio.Lock()
        self._last_used = time.monotonic()
        self._stderr_tail: deque[str] = deque(maxlen=40)
        self._stderr_task: asyncio.Task | None = None
        self._idle_task: asyncio.Task | None = None
        self._inflight: int = 0
        self.last_error: str = ""

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def status(self) -> dict:
        return {
            "name": self.name,
            "loaded_model": self.loaded_model,
            "running": self.is_running(),
            "ready": self._ready.is_set(),
            "port": self.port,
            "last_error": self.last_error,
            "inflight": self._inflight,
        }

    async def ensure_ready(self, model: str | None = None) -> bool:
        """Start (or restart for a different model) and wait for readiness."""
        target = model or self.loaded_model or next(iter(self.models), None)
        if not target:
            self.last_error = "no model configured"
            return False
        async with self._start_lock:
            if self.is_running() and self.loaded_model == target and self._ready.is_set():
                self._last_used = time.monotonic()
                return True
            if self.is_running() and self.loaded_model != target:
                await self._stop_locked()
            if not self.is_running():
                ok = await self._spawn_locked(target)
                if not ok:
                    return False
            try:
                ready = await asyncio.wait_for(self._wait_ready_or_exit(), timeout=self.startup_timeout)
            except asyncio.TimeoutError:
                log.error("whisper-server startup timed out after %ss", self.startup_timeout)
                self.last_error = f"startup timeout {self.startup_timeout}s"
                await self._stop_locked()
                return False
            if not ready:
                if not self.last_error:
                    self.last_error = f"server exited before ready rc={self.proc.returncode if self.proc else '?'}"
                await self._stop_locked()
                return False
            self._last_used = time.monotonic()
            self._ensure_idle_watcher()
            return True

    async def _wait_ready_or_exit(self) -> bool:
        while True:
            if self._ready.is_set():
                return True
            if await self._health_ready():
                self._ready.set()
                log.info("whisper-server ready name=%s source=health", self.name)
                return True
            if self.proc is None:
                return False
            if self.proc.returncode is not None:
                return False
            await asyncio.sleep(0.2)

    async def _health_ready(self) -> bool:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=0.5,
            )
        except Exception:
            return False
        try:
            request = (
                f"GET /health HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            writer.write(request)
            await writer.drain()
            data = await asyncio.wait_for(reader.read(256), timeout=0.8)
            first = data.split(b"\r\n", 1)[0]
            return b" 200 " in first or first.endswith(b" 200 OK")
        except Exception:
            return False
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _spawn_locked(self, model: str) -> bool:
        spec = normalize_model_spec(model, self.models.get(model))
        if spec.get("backend") != "whisper.cpp":
            self.last_error = f"model {model!r} is not a whisper.cpp model"
            log.error(self.last_error)
            return False
        model_path = spec.get("path")
        if not model_path or not Path(model_path).is_file():
            self.last_error = f"model file missing: {model} -> {model_path}"
            log.error(self.last_error)
            return False
        self._ready.clear()
        self.last_error = ""
        self.loaded_model = model
        args = [
            self.binary,
            "-m", model_path,
            "--host", self.host,
            "--port", str(self.port),
            "-t", str(max(1, (os.cpu_count() or 4) // 2)),
        ]
        log.info("starting whisper-server name=%s port=%s model=%s", self.name, self.port, model)
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            self.last_error = f"binary missing: {e}"
            log.error(self.last_error)
            return False
        self._stderr_tail.clear()
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        return True

    async def _drain_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        try:
            while True:
                line = await self.proc.stderr.readline()
                if not line:
                    break
                txt = line.decode("utf-8", "replace").rstrip()
                self._stderr_tail.append(txt)
                if not self._ready.is_set() and (
                    "is listening" in txt
                    or "server is listening" in txt
                    or "HTTP server listening" in txt
                ):
                    self._ready.set()
                    log.info("whisper-server ready name=%s", self.name)
        except Exception:
            log.exception("stderr drain failed")
        # When stderr closes, the process is gone.
        if self.proc is not None:
            try:
                await self.proc.wait()
            except Exception:
                pass
            log.warning(
                "whisper-server exited name=%s rc=%s tail=%s",
                self.name,
                self.proc.returncode,
                list(self._stderr_tail)[-4:],
            )
            if not self._ready.is_set():
                tail = " | ".join(list(self._stderr_tail)[-4:])
                self.last_error = f"server exited before ready rc={self.proc.returncode}: {tail}"
        self._ready.clear()

    def _ensure_idle_watcher(self) -> None:
        if self._idle_task and not self._idle_task.done():
            return
        self._idle_task = asyncio.create_task(self._idle_watch())

    async def _idle_watch(self) -> None:
        try:
            while self.is_running():
                await asyncio.sleep(5)
                if self.idle_shutdown_seconds <= 0:
                    continue
                if self._inflight > 0:
                    continue
                idle = time.monotonic() - self._last_used
                if idle >= self.idle_shutdown_seconds:
                    log.info("whisper-server idle shutdown name=%s after %.0fs", self.name, idle)
                    await self.stop()
                    return
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("idle watcher crashed")

    async def stop(self) -> None:
        async with self._start_lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        if self.proc is None or self.proc.returncode is not None:
            self.proc = None
            self._ready.clear()
            return
        log.info("stopping whisper-server name=%s", self.name)
        try:
            self.proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(self.proc.wait(), timeout=4.0)
        except asyncio.TimeoutError:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
        self.proc = None
        self._ready.clear()
        if self._stderr_task is not None:
            self._stderr_task.cancel()

    def mark_used(self) -> None:
        self._last_used = time.monotonic()

    def acquire_slot(self) -> None:
        self._inflight += 1
        self.mark_used()

    def release_slot(self) -> None:
        self._inflight = max(0, self._inflight - 1)
        self.mark_used()
