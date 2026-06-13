from __future__ import annotations

import asyncio
import io
import logging
import os
import signal
import sys
import time
import wave
from pathlib import Path

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


class _RecorderBase:
    """Shared file protocol: raw mono 16 kHz s16 PCM appended to self.path."""

    DEFAULT_TARGET = "@DEFAULT_AUDIO_SOURCE@"

    def __init__(self, recordings_dir: Path, target_provider=None) -> None:
        self.dir = recordings_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path: Path | None = None
        self.started_at: float = 0.0
        self._on_exit_error = None
        self._target_provider = target_provider or (lambda: self.DEFAULT_TARGET)

    def _new_path(self) -> Path:
        ts = time.strftime("%Y%m%d-%H%M%S")
        return self.dir / f"rec-{ts}-{int(time.time()*1000)%1000:03d}.raw"

    def duration_seconds(self) -> float:
        if not self.started_at:
            return 0.0
        return max(0.0, time.monotonic() - self.started_at)

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
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm)
        return out.getvalue()

    def cleanup(self) -> None:
        if self.path is not None and self.path.exists():
            try:
                os.unlink(self.path)
            except OSError:
                pass
            self.path = None


class PwRecordRecorder(_RecorderBase):
    """Wraps `pw-record` writing raw PCM. mono 16k s16."""

    def __init__(self, recordings_dir: Path, target_provider=None) -> None:
        super().__init__(recordings_dir, target_provider)
        self.proc: asyncio.subprocess.Process | None = None
        self._watchdog: asyncio.Task | None = None

    async def start(self, on_unexpected_exit) -> bool:
        """Spawn pw-record. Returns True if process spawned successfully."""
        self.path = self._new_path()
        self._on_exit_error = on_unexpected_exit
        target = self._target_provider() or self.DEFAULT_TARGET
        try:
            self.proc = await asyncio.create_subprocess_exec(
                "pw-record",
                "--target", target,
                "--channels", "1",
                "--rate", str(SAMPLE_RATE),
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

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None


class SoundDeviceRecorder(_RecorderBase):
    """In-process capture via the sounddevice (PortAudio/WASAPI) library.

    Appends raw mono 16 kHz s16 PCM to a file from the PortAudio callback
    thread so live-preview reads see the same growing file pw-record writes
    on Linux.
    """

    def __init__(self, recordings_dir: Path, target_provider=None) -> None:
        super().__init__(recordings_dir, target_provider)
        self._stream = None
        self._file = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _resolve_device(self, target: str):
        import sounddevice as sd

        target = (target or "").strip()
        if not target or target == self.DEFAULT_TARGET:
            return None  # PortAudio default input device
        wanted = target.lower()
        hostapis = sd.query_hostapis()

        def api_rank(api_index: int) -> int:
            # Prefer WASAPI (full names, active endpoints), then DirectSound,
            # then MME; raw WDM-KS pins last.
            try:
                name = str(hostapis[api_index].get("name", "")).lower()
            except (IndexError, TypeError):
                return 9
            if "wasapi" in name:
                return 0
            if "directsound" in name:
                return 1
            if "mme" in name:
                return 2
            return 3

        best: tuple[int, int] | None = None
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) <= 0:
                continue
            if wanted not in str(dev.get("name", "")).lower():
                continue
            rank = api_rank(int(dev.get("hostapi", -1)))
            if best is None or rank < best[0]:
                best = (rank, idx)
        if best is not None:
            return best[1]
        log.warning("audio input %r not found; using default device", target)
        return None

    async def start(self, on_unexpected_exit) -> bool:
        try:
            import sounddevice as sd
        except Exception as e:
            log.error("sounddevice not available: %s", e)
            return False
        self.path = self._new_path()
        self._on_exit_error = on_unexpected_exit
        self._loop = asyncio.get_event_loop()
        device = self._resolve_device(self._target_provider())
        try:
            self._file = open(self.path, "ab")

            def _callback(indata, _frames, _time, status):
                if status and status.input_overflow:
                    log.debug("audio input overflow")
                f = self._file
                if f is not None:
                    try:
                        f.write(bytes(indata))
                        f.flush()
                    except ValueError:
                        pass  # closed during stop

            def _finished():
                cb = self._on_exit_error
                if cb is not None and self._loop is not None:
                    log.error("audio input stream stopped unexpectedly")
                    self._loop.call_soon_threadsafe(cb)

            self._stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=device,
                callback=_callback,
                finished_callback=_finished,
            )
            self._stream.start()
        except Exception as e:
            log.error("audio capture failed to start: %s", e)
            self._close_file()
            self._stream = None
            return False
        self.started_at = time.monotonic()
        return True

    def _close_file(self) -> None:
        f, self._file = self._file, None
        if f is not None:
            try:
                f.close()
            except Exception:
                pass

    async def stop(self) -> Path | None:
        self._on_exit_error = None
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                await asyncio.to_thread(stream.stop)
                stream.close()
            except Exception:
                log.exception("audio stream stop failed")
        self._close_file()
        return self.path

    def is_running(self) -> bool:
        return self._stream is not None and bool(getattr(self._stream, "active", False))


Recorder = SoundDeviceRecorder if sys.platform == "win32" else PwRecordRecorder
