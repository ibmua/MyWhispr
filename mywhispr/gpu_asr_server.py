from __future__ import annotations

import asyncio
import base64
import json
import locale
import logging
import os
import signal
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

from .model_specs import normalize_model_spec, resolve_project_python

log = logging.getLogger(__name__)


def _worker_json_fallback_encodings() -> list[str]:
    encodings = [
        locale.getpreferredencoding(False),
        "mbcs" if sys.platform == "win32" else "",
        "cp1251",
        "cp866",
        "cp1252",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for enc in encodings:
        if not enc:
            continue
        key = enc.lower().replace("_", "-")
        if key in {"utf-8", "utf8"} or key in seen:
            continue
        seen.add(key)
        out.append(enc)
    return out


def _decode_worker_json_line(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as utf8_error:
        for enc in _worker_json_fallback_encodings():
            try:
                text = raw.decode(enc)
            except (LookupError, UnicodeDecodeError):
                continue
            log.warning("GPU ASR worker emitted non-UTF-8 JSON; decoded as %s", enc)
            return text
        preview = raw[:160].decode("ascii", "backslashreplace")
        raise RuntimeError(
            f"GPU ASR worker emitted non-UTF-8 JSON: {utf8_error}; raw={preview!r}"
        ) from utf8_error


class GpuAsrServer:
    """Supervises one optional GPU ASR worker process.

    Heavy Torch/Transformers/NeMo/Qwen imports live in the child process so the
    hotkey daemon remains small and model unload reliably returns VRAM.
    """

    def __init__(
        self,
        model_specs: dict[str, Any],
        python: str = "",
        startup_timeout: float = 300.0,
        idle_shutdown_seconds: float = 0.0,
        transcription_timeout: float = 600.0,
        name: str = "primary-gpu",
    ) -> None:
        self.models = model_specs
        self.default_python = python or sys.executable
        self._running_python = ""
        self.startup_timeout = startup_timeout
        self.idle_shutdown_seconds = idle_shutdown_seconds
        self.transcription_timeout = transcription_timeout
        self.name = name
        self.proc: asyncio.subprocess.Process | None = None
        self.loaded_model: str | None = None
        self.loaded_backend: str = ""
        self.device_report: dict[str, Any] = {}
        self._ready = asyncio.Event()
        self._start_lock = asyncio.Lock()
        self._rpc_lock = asyncio.Lock()
        self._last_used = time.monotonic()
        self._stderr_tail: deque[str] = deque(maxlen=40)
        self._stderr_task: asyncio.Task | None = None
        self._idle_task: asyncio.Task | None = None
        self._inflight = 0
        self.last_error = ""

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "loaded_model": self.loaded_model,
            "backend": self.loaded_backend,
            "running": self.is_running(),
            "ready": self._ready.is_set(),
            "port": None,
            "last_error": self.last_error,
            "inflight": self._inflight,
            "device_report": self.device_report,
        }

    async def ensure_ready(self, model: str | None = None) -> bool:
        target = model or self.loaded_model
        if not target:
            self.last_error = "no model configured"
            return False
        if target not in self.models:
            self.last_error = f"unknown model {target!r}"
            return False
        target_python = self._python_for_model(target)
        async with self._start_lock:
            if self.is_running() and self._running_python != target_python:
                await self._stop_locked()
            if not self.is_running():
                ok = await self._spawn_locked(target_python)
                if not ok:
                    return False
            if self.loaded_model == target and self._ready.is_set():
                self._last_used = time.monotonic()
                return True
            try:
                reply = await asyncio.wait_for(
                    self._request(
                        {
                            "cmd": "warm",
                            "model": target,
                            "spec": normalize_model_spec(target, self.models[target]),
                        }
                    ),
                    timeout=self.startup_timeout,
                )
            except asyncio.TimeoutError:
                self.last_error = f"GPU ASR startup timeout {self.startup_timeout}s"
                await self._stop_locked()
                return False
            except Exception as e:
                self.last_error = str(e)
                await self._stop_locked()
                return False
            if not reply.get("ok"):
                self.last_error = str(reply.get("error") or "GPU ASR worker failed")
                self._ready.clear()
                return False
            self.loaded_model = target
            self.loaded_backend = str(reply.get("backend") or "")
            self.device_report = reply.get("device_report") or {}
            self.last_error = ""
            self._ready.set()
            self._last_used = time.monotonic()
            self._ensure_idle_watcher()
            return True

    async def transcribe(
        self,
        model: str,
        wav_bytes: bytes,
        *,
        language: str,
        cancel_event: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        ok = await self.ensure_ready(model)
        if not ok:
            raise RuntimeError(self.last_error or "GPU ASR worker not ready")
        request = {
            "cmd": "transcribe",
            "model": model,
            "spec": normalize_model_spec(model, self.models[model]),
            "language": language,
            "wav_b64": base64.b64encode(wav_bytes).decode("ascii"),
        }
        self.acquire_slot()
        release_in_finally = True
        try:
            if cancel_event is None:
                try:
                    reply = await asyncio.wait_for(
                        self._request(request),
                        timeout=self.transcription_timeout,
                    )
                except asyncio.TimeoutError as e:
                    await self.stop()
                    raise RuntimeError(
                        f"GPU ASR transcription timeout {self.transcription_timeout}s"
                    ) from e
                except Exception as e:
                    if not self._worker_lost(e):
                        raise
                    log.warning("GPU ASR worker disconnected during transcription name=%s: %s", self.name, self._error_text(e))
                    await self.stop()
                    ok = await self.ensure_ready(model)
                    if not ok:
                        raise RuntimeError(self.last_error or "GPU ASR worker restart failed") from e
                    try:
                        reply = await asyncio.wait_for(
                            self._request(request),
                            timeout=self.transcription_timeout,
                        )
                    except asyncio.TimeoutError as retry_e:
                        await self.stop()
                        raise RuntimeError(
                            f"GPU ASR transcription timeout {self.transcription_timeout}s"
                        ) from retry_e
            else:
                task = asyncio.create_task(self._request(request))
                cancel_task = asyncio.create_task(cancel_event.wait())
                try:
                    done, _ = await asyncio.wait(
                        {task, cancel_task},
                        timeout=self.transcription_timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        task.cancel()
                        await self.stop()
                        raise RuntimeError(
                            f"GPU ASR transcription timeout {self.transcription_timeout}s"
                        )
                    if cancel_task in done and not task.done():
                        release_in_finally = False
                        task.add_done_callback(self._finish_detached_request)
                        raise asyncio.CancelledError("GPU ASR transcription cancelled by caller")
                    reply = task.result()
                finally:
                    cancel_task.cancel()
            if not reply.get("ok"):
                raise RuntimeError(str(reply.get("error") or "GPU ASR transcription failed"))
            return reply
        finally:
            if release_in_finally:
                self.release_slot()

    async def stop(self) -> None:
        async with self._start_lock:
            await self._stop_locked()

    def _python_for_model(self, model: str) -> str:
        spec = normalize_model_spec(model, self.models.get(model))
        candidates = [
            str(spec.get("python") or ""),
            str(spec.get("gpu_asr_python") or ""),
            str(self.default_python or ""),
        ]
        first: Path | None = None
        for cand in candidates:
            if not cand:
                continue
            exe = self._resolve_python(cand)
            if first is None:
                first = exe
            if exe.is_file():
                if cand != candidates[0] and candidates[0]:
                    log.warning(
                        "model %s python %r not found; using %s", model, candidates[0], exe
                    )
                return str(exe)
        return str(first or sys.executable)

    def set_default_python(self, python: str) -> None:
        self.default_python = python or sys.executable

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def _resolve_python(self, python: str) -> Path:
        return resolve_project_python(python, self._project_root())

    async def _spawn_locked(self, python: str | Path) -> bool:
        self._ready.clear()
        self.last_error = ""
        self.loaded_model = None
        self.loaded_backend = ""
        self.device_report = {}
        root = self._project_root()
        env = os.environ.copy()
        env.setdefault("HF_HUB_OFFLINE", "1")
        env.setdefault("TRANSFORMERS_OFFLINE", "1")
        # Worker protocol is UTF-8 JSON lines; override any inherited Windows
        # ANSI-codepage setting so non-ASCII transcripts do not break RPC.
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        exe = self._resolve_python(str(python))
        if not exe.is_file():
            self.last_error = f"python missing: {exe}"
            return False
        args = [str(exe), "-m", "mywhispr.gpu_asr_worker"]
        log.info("starting GPU ASR worker name=%s python=%s", self.name, exe)
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(root),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            self.last_error = f"python missing: {exe}: {e}"
            return False
        self._running_python = str(exe)
        self._stderr_tail.clear()
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        return True

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.proc is None or self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("GPU ASR worker is not running")
        if self.proc.returncode is not None:
            raise RuntimeError(f"GPU ASR worker exited rc={self.proc.returncode}: {self._tail_text()}")
        async with self._rpc_lock:
            line = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
            self.proc.stdin.write(line)
            await self.proc.stdin.drain()
            raw = await self.proc.stdout.readline()
            if not raw:
                raise RuntimeError(f"GPU ASR worker closed stdout: {self._tail_text()}")
            self._last_used = time.monotonic()
            return json.loads(_decode_worker_json_line(raw))

    def _finish_detached_request(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.warning("detached GPU ASR request failed name=%s: %s", self.name, self._error_text(e))
        finally:
            self.release_slot()

    def _error_text(self, exc: BaseException) -> str:
        text = str(exc)
        return f"{type(exc).__name__}: {text}" if text else type(exc).__name__

    def _worker_lost(self, exc: BaseException) -> bool:
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return True
        text = str(exc)
        return (
            "GPU ASR worker is not running" in text
            or "GPU ASR worker exited" in text
            or "GPU ASR worker closed stdout" in text
        )

    async def _drain_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        try:
            while True:
                line = await self.proc.stderr.readline()
                if not line:
                    break
                txt = line.decode("utf-8", "replace").rstrip()
                self._stderr_tail.append(txt)
                log.debug("GPU ASR worker stderr name=%s: %s", self.name, txt)
        except Exception:
            log.exception("GPU ASR worker stderr drain failed")
        if self.proc is not None:
            try:
                await self.proc.wait()
            except Exception:
                pass
            if self.proc.returncode not in (0, None):
                self.last_error = f"GPU ASR worker exited rc={self.proc.returncode}: {self._tail_text()}"
                log.warning(self.last_error)
        self._ready.clear()

    async def _stop_locked(self) -> None:
        if self.proc is None:
            self._ready.clear()
            self.loaded_model = None
            self.loaded_backend = ""
            self.device_report = {}
            return
        proc = self.proc
        if proc.returncode is None:
            try:
                if proc.stdin is not None:
                    proc.stdin.write(b'{"cmd":"stop"}\n')
                    await proc.stdin.drain()
                    await asyncio.wait_for(proc.wait(), timeout=4.0)
            except Exception:
                try:
                    proc.send_signal(signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=4.0)
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        pass
        self.proc = None
        self._ready.clear()
        self.loaded_model = None
        self.loaded_backend = ""
        self._running_python = ""
        self.device_report = {}
        if self._stderr_task is not None:
            self._stderr_task.cancel()

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
                    log.info("GPU ASR worker idle shutdown name=%s after %.0fs", self.name, idle)
                    await self.stop()
                    return
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("GPU ASR idle watcher crashed")

    def _tail_text(self) -> str:
        return " | ".join(list(self._stderr_tail)[-6:])

    def acquire_slot(self) -> None:
        self._inflight += 1
        self._last_used = time.monotonic()

    def release_slot(self) -> None:
        self._inflight = max(0, self._inflight - 1)
        self._last_used = time.monotonic()
