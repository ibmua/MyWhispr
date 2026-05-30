from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from . import hallucination_filter
from . import paste as paste_mod
from . import text_cleanup

log = logging.getLogger(__name__)


@dataclass
class _Snapshot:
    text: str
    when: float


class StreamingSession:
    """One streaming session per recording. Reads WAV bytes from a producer
    callable, requests periodic transcriptions, and pushes confirmed text into
    the focused app via backspace+paste rewrites.

    Heavily defensive: bounded rewrites, initial commit confirmation, cancel on
    release. If `app_output_enabled` is False, this entire module is dormant.
    """

    def __init__(
        self,
        *,
        config,
        transcriber,
        server,
        language_provider,
        wav_provider,
        on_preview,
        loop: asyncio.AbstractEventLoop,
        app_output_allowed_provider=None,
    ) -> None:
        self.config = config
        self.transcriber = transcriber
        self.server = server
        self.language_provider = language_provider
        self.app_output_allowed_provider = app_output_allowed_provider or (lambda: True)
        self.wav_provider = wav_provider
        self.on_preview = on_preview
        self.loop = loop
        self.task: asyncio.Task | None = None
        self.cancel = asyncio.Event()
        self.committed_text = ""  # what's already in the focused app
        self.latest_preview = ""
        self.confirmation_counts: dict[str, int] = {}
        self.freeze_counts: dict[str, int] = {}
        self.app_output_started = False
        self.frozen_text = ""
        self._last_pcm_len = 0
        self._last_loud_rms = 0.0
        self._tick_lock = asyncio.Lock()
        self._language_generation = 0
        self._force_next_rewrite = False
        self._force_full_snapshot = False
        self._rerun_after_current = False

    @property
    def settings(self) -> dict:
        return self.config.get("streaming") or {}

    def _app_output_enabled(self) -> bool:
        return bool(self.settings.get("app_output_enabled", False)) and bool(self.app_output_allowed_provider())

    def start(self) -> None:
        self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.cancel.set()
        if self.task is not None:
            try:
                join = float(self.settings.get("cancel_streaming_join_timeout", 1.0))
                await asyncio.wait_for(self.task, timeout=join)
            except asyncio.TimeoutError:
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            except asyncio.CancelledError:
                # A cancelled preview request is the expected release path.
                pass

    async def _run(self) -> None:
        s = self.settings
        initial_delay = float(s.get("initial_delay_seconds", 1.2))
        interval = float(s.get("interval_seconds", 0.8))
        try:
            await asyncio.wait_for(self.cancel.wait(), timeout=initial_delay)
            return
        except asyncio.TimeoutError:
            pass
        while not self.cancel.is_set():
            try:
                await self._tick_guarded()
            except asyncio.CancelledError:
                return
            except Exception:
                log.exception("streaming tick failed")
            try:
                await asyncio.wait_for(self.cancel.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                continue

    def language_switched(self) -> None:
        self._language_generation += 1
        self.confirmation_counts.clear()
        self.freeze_counts.clear()
        self.frozen_text = ""
        self._last_pcm_len = 0
        self._force_next_rewrite = True
        self._force_full_snapshot = True
        self.kick(force=True)

    async def clear_committed_from_app(self) -> bool:
        if not self.committed_text:
            return True
        max_rewrite = int(self.settings.get("max_rewrite_chars", 180))
        ok = await paste_mod.stream_replace(
            previous=self.committed_text,
            new="",
            settle_seconds=float(self.config.get("clipboard_settle_seconds", 0.03)),
            max_rewrite_chars=max_rewrite,
            consume_timeout=float(self.config.get("clipboard_paste_consume_timeout_seconds", 0.8)),
            key_delay_ms=int(self.config.get("paste_key_delay_ms", 18)),
        )
        if ok:
            self.committed_text = ""
            self.app_output_started = False
            self.frozen_text = ""
            self.confirmation_counts.clear()
            self.freeze_counts.clear()
        return ok

    def kick(self, *, force: bool = False) -> None:
        if not self.cancel.is_set():
            asyncio.create_task(self._tick_guarded(force=force))

    async def _tick_guarded(self, *, force: bool = False) -> None:
        if self._tick_lock.locked():
            if force:
                self._rerun_after_current = True
            return
        async with self._tick_lock:
            await self._tick(force=force)
            while self._rerun_after_current and not self.cancel.is_set():
                self._rerun_after_current = False
                await self._tick(force=True)

    async def _tick(self, *, force: bool = False) -> None:
        if hasattr(self.server, "supports_live_preview") and not self.server.supports_live_preview():
            return
        wav = self.wav_provider()
        if not wav:
            return
        if force or self._force_full_snapshot:
            self._last_pcm_len = len(self._pcm(wav))
            self._force_full_snapshot = False
        elif self._should_skip_snapshot(wav):
            return
        lang = self.language_provider()
        generation = self._language_generation
        try:
            res = await self.transcriber.transcribe(
                self.server,
                wav,
                language=lang,
                cancel_event=self.cancel,
            )
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.warning("preview transcribe failed: %s", e)
            return
        if generation != self._language_generation:
            return
        text = text_cleanup.collapse_whitespace(res.text)
        self.latest_preview = text
        try:
            self.on_preview(text)
        except Exception:
            log.exception("on_preview callback failed")
        if self._app_output_enabled():
            await self._maybe_commit_to_app(res, wav)

    def _pcm(self, wav: bytes) -> bytes:
        return wav[44:] if len(wav) > 44 else b""

    def _duration_seconds(self, wav: bytes) -> float:
        return len(self._pcm(wav)) / 32000.0

    def _rms_tail(self, wav: bytes, seconds: float) -> float:
        pcm = self._pcm(wav)
        if not pcm:
            return 0.0
        n = max(2, int(seconds * 16000) * 2)
        return hallucination_filter.rms_int16(pcm[-n:])

    def _should_skip_snapshot(self, wav: bytes) -> bool:
        s = self.settings
        if not self._app_output_enabled() and (self.config.get("live_preview") or {}).get("enabled", True):
            return False
        min_rms = float(s.get("new_audio_gate_min_rms", 50.0))
        pcm = self._pcm(wav)
        new_pcm = pcm[self._last_pcm_len :]
        self._last_pcm_len = len(pcm)
        if not new_pcm:
            return True
        rms = hallucination_filter.rms_int16(new_pcm)
        if rms > self._last_loud_rms:
            self._last_loud_rms = rms
        # Do not spend Whisper requests on initial silence; once we have text,
        # quiet snapshots can still be useful for the pause gate.
        if not self.latest_preview and rms < min_rms:
            return True
        return False

    def _pause_gate_open(self, wav: bytes) -> bool:
        s = self.settings
        if not bool(s.get("pause_gate_enabled", True)):
            return True
        tail_seconds = float(s.get("pause_gate_min_silence_seconds", 0.25))
        max_rms = float(s.get("pause_gate_max_rms", 90.0))
        ratio = float(s.get("pause_gate_relative_rms_ratio", 0.45))
        tail = self._rms_tail(wav, tail_seconds)
        relative_limit = self._last_loud_rms * ratio if self._last_loud_rms > 0 else max_rms
        return tail <= max(max_rms, relative_limit)

    def _stable_text(self, res, wav: bytes) -> str:
        s = self.settings
        stable_lag = float(s.get("stable_lag_seconds", 0.65))
        cutoff = max(0.0, self._duration_seconds(wav) - stable_lag)
        parts: list[str] = []
        for seg in res.segments or []:
            try:
                end = float(seg.get("end", 0.0))
            except Exception:
                continue
            if end <= cutoff:
                parts.append(str(seg.get("text") or ""))
        stable = text_cleanup.collapse_whitespace(" ".join(parts))
        if stable:
            return stable
        # Fallback for server responses without useful segment timing.
        words = text_cleanup.collapse_whitespace(res.text).split()
        if len(words) <= 1:
            return ""
        return " ".join(words[:-1])

    def _apply_frozen_prefix(self, stable: str) -> str:
        if not self.frozen_text:
            return stable
        if stable.startswith(self.frozen_text):
            return stable
        # The model is trying to rewrite text that has already crystallized.
        # Skip this tick and let later/final hypotheses converge.
        log.info("stream frozen prefix protected chars=%d", len(self.frozen_text))
        return ""

    def _maybe_freeze(self) -> None:
        s = self.settings
        if not bool(s.get("crystallization_enabled", True)):
            return
        if not self.committed_text or self.committed_text == self.frozen_text:
            return
        required = int(s.get("crystallization_required_updates", 2))
        self.freeze_counts[self.committed_text] = self.freeze_counts.get(self.committed_text, 0) + 1
        if self.freeze_counts[self.committed_text] >= required:
            self.frozen_text = self.committed_text

    async def _maybe_commit_to_app(self, res, wav: bytes) -> None:
        """Commit only the stable, repeatedly-seen prefix; cap destructive rewrites."""
        s = self.settings
        max_rewrite = int(s.get("max_rewrite_chars", 180))
        init_conf = int(s.get("initial_commit_confirmations", 2))
        rewrite_conf = int(s.get("rewrite_backspace_confirmations", 2))
        if not self._pause_gate_open(wav):
            return
        stable = self._stable_text(res, wav)
        stable = self._apply_frozen_prefix(stable)
        if not stable:
            return
        if self.frozen_text and len(stable) < len(self.frozen_text):
            return
        key = stable
        self.confirmation_counts[key] = self.confirmation_counts.get(key, 0) + 1
        required = init_conf if not self.app_output_started else rewrite_conf
        if self._force_next_rewrite:
            required = 1
        # Stable strings that share a prefix with already-committed text are
        # additions and only need init_conf; full divergent rewrites need rewrite_conf.
        if stable.startswith(self.committed_text):
            required = init_conf if not self.app_output_started else 1
        if self.confirmation_counts[key] < required:
            return
        if stable == self.committed_text:
            return
        ok = await paste_mod.stream_replace(
            previous=self.committed_text,
            new=stable,
            settle_seconds=float(self.config.get("clipboard_settle_seconds", 0.03)),
            max_rewrite_chars=max_rewrite,
            consume_timeout=float(self.config.get("clipboard_paste_consume_timeout_seconds", 0.8)),
            key_delay_ms=int(self.config.get("paste_key_delay_ms", 18)),
            type_key_delay_ms=int(self.config.get("type_key_delay_ms", paste_mod.DEFAULT_TYPE_KEY_DELAY_MS)),
            direct_type_max_chars=int(self.config.get("direct_type_max_chars", 240)),
            direct_type_ascii_only=bool(self.config.get("direct_type_ascii_only", True)),
        )
        if not ok:
            log.warning("stream rewrite refused; leaving committed text untouched")
            return
        self.committed_text = stable
        self.app_output_started = True
        self._force_next_rewrite = False
        self._maybe_freeze()

    def divergence_from_final(self, final_text: str) -> int:
        """Return number of trailing chars to backspace if final replaces stream."""
        i = 0
        n = min(len(self.committed_text), len(final_text))
        while i < n and self.committed_text[i] == final_text[i]:
            i += 1
        return len(self.committed_text) - i
