from __future__ import annotations

import asyncio
import io
import logging
import os
import signal
import time
import wave
from pathlib import Path

log = logging.getLogger(__name__)


class Recorder:
    """Wraps `pw-record` writing a WAV file. mono 16k s16."""

    DEFAULT_TARGET = "@DEFAULT_AUDIO_SOURCE@"

    def __init__(self, recordings_dir: Path, target_provider=None) -> None:
        self.dir = recordings_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.proc: asyncio.subprocess.Process | None = None
        self.path: Path | None = None
        self.started_at: float = 0.0
        self._watchdog: asyncio.Task | None = None
        self._on_exit_error = None
        self._target_provider = target_provider or (lambda: self.DEFAULT_TARGET)

    async def start(self, on_unexpected_exit) -> bool:
        """Spawn pw-record. Returns True if process spawned successfully."""
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.path = self.dir / f"rec-{ts}-{int(time.time()*1000)%1000:03d}.raw"
        self._on_exit_error = on_unexpected_exit
        target = self._target_provider() or self.DEFAULT_TARGET
        try:
            self.proc = await asyncio.create_subprocess_exec(
                "pw-record",
                "--target", target,
                "--channels", "1",
                "--rate", "16000",
                "--format", "s16",
                "--container", "raw",
                str(self.path),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            log.error("pw-record not found: %s", e)
            return False
        self.started_at = time.monotonic()
        self._watchdog = asyncio.create_task(self._watch())
        return True

    async def _watch(self) -> None:
        assert self.proc is not None
        rc = await self.proc.wait()
        if rc != 0 and self._on_exit_error is not None:
            # Only treat as error if we did not stop it ourselves; stop() clears callback first.
            try:
                stderr = b""
                if self.proc.stderr is not None:
                    try:
                        stderr = await asyncio.wait_for(self.proc.stderr.read(2048), timeout=0.2)
                    except asyncio.TimeoutError:
                        pass
                log.error("pw-record exited rc=%s stderr=%r", rc, stderr[-400:])
                self._on_exit_error()
            except Exception:
                log.exception("recorder exit handler crashed")

    async def stop(self) -> Path | None:
        """Stop recording cleanly."""
        self._on_exit_error = None
        if self.proc is None:
            return self.path
        if self.proc.returncode is None:
            try:
                self.proc.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                log.warning("pw-record did not exit on SIGINT; terminating")
                try:
                    self.proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    self.proc.kill()
                    await self.proc.wait()
        if self._watchdog is not None:
            self._watchdog.cancel()
        return self.path

    def duration_seconds(self) -> float:
        if not self.started_at:
            return 0.0
        return max(0.0, time.monotonic() - self.started_at)

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def read_bytes(self) -> bytes:
        if self.path is None or not self.path.exists():
            return b""
        try:
            pcm = self.path.read_bytes()
        except Exception as e:
            log.warning("read recording failed: %s", e)
            return b""
        return self._wav_from_pcm(pcm)

    def _wav_from_pcm(self, pcm: bytes) -> bytes:
        if len(pcm) % 2:
            pcm = pcm[:-1]
        out = io.BytesIO()
        with wave.open(out, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm)
        return out.getvalue()

    def cleanup(self) -> None:
        if self.path is not None and self.path.exists():
            try:
                os.unlink(self.path)
            except OSError:
                pass
            self.path = None
