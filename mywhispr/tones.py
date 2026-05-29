from __future__ import annotations

import asyncio
import logging
import math
import subprocess
import struct
import wave
from pathlib import Path

log = logging.getLogger(__name__)


def _tone_wav(path: Path, freq: float, duration_s: float, *, volume: float = 0.25) -> None:
    sr = 44100
    n = int(sr * duration_s)
    fade = max(1, min(int(sr * 0.004), n // 4))
    frames = bytearray()
    for i in range(n):
        env = 1.0
        if i < fade:
            env = i / fade
        elif i > n - fade:
            env = (n - i) / fade
        s = int(volume * env * 32767 * math.sin(2 * math.pi * freq * i / sr))
        frames += struct.pack("<h", s)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(frames))


class Tones:
    def __init__(self, runtime_dir: Path, enabled: bool = True, volume: float = 0.85) -> None:
        self.dir = runtime_dir / "cues"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.enabled = enabled
        self.volume = self._clamp_volume(volume)
        self.start = self.dir / "start.wav"
        self.stop = self.dir / "stop.wav"
        self.error = self.dir / "error.wav"
        self._ensure()

    def _clamp_volume(self, volume: float) -> float:
        try:
            value = float(volume)
        except Exception:
            value = 0.85
        return max(0.0, min(1.0, value))

    def _ensure(self) -> None:
        # Regenerate on startup/config change so cue timing/volume applies immediately.
        _tone_wav(self.start, 1040.0, 0.035, volume=0.50 * self.volume)
        _tone_wav(self.stop, 660.0, 0.12, volume=0.45 * self.volume)
        _tone_wav(self.error, 220.0, 0.20, volume=0.55 * self.volume)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def set_volume(self, volume: float) -> None:
        next_volume = self._clamp_volume(volume)
        if next_volume == self.volume:
            return
        self.volume = next_volume
        self._ensure()

    def configure(self, *, enabled: bool, volume: float) -> None:
        self.enabled = enabled
        self.set_volume(volume)

    def _play(self, path: Path) -> None:
        if not self.enabled:
            return
        try:
            subprocess.Popen(
                ["pw-play", str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            log.warning("cue play failed (%s): %s", path.name, e)

    def play_start(self) -> None:
        # Spawn synchronously so the cue is the first real side effect of start.
        self._play(self.start)

    def play_stop(self) -> None:
        self._play(self.stop)

    def play_error(self) -> None:
        self._play(self.error)

    async def _spawn(self, path: Path) -> None:
        if not self.enabled:
            return
        try:
            await asyncio.create_subprocess_exec(
                "pw-play", str(path),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except Exception as e:
            log.warning("cue play failed (%s): %s", path.name, e)
