from __future__ import annotations

import asyncio
import io
import logging
import wave
from dataclasses import dataclass, field

import aiohttp

from . import hallucination_filter, text_cleanup
from .model_specs import model_backend

log = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    text: str
    raw_text: str
    segments: list[dict] = field(default_factory=list)
    model: str = ""
    elapsed_seconds: float = 0.0


SILENCE_PCM_SAMPLES_PER_SECOND = 16000  # 16 kHz mono


def with_leading_silence(wav: bytes, seconds: float) -> bytes:
    if seconds <= 0:
        return wav
    try:
        with wave.open(io.BytesIO(wav), "rb") as src:
            channels = src.getnchannels()
            sample_width = src.getsampwidth()
            frame_rate = src.getframerate()
            frames = src.readframes(src.getnframes())
        silence_frames = int(frame_rate * seconds)
        silence = bytes(silence_frames * channels * sample_width)
        out = io.BytesIO()
        with wave.open(out, "wb") as dst:
            dst.setnchannels(channels)
            dst.setsampwidth(sample_width)
            dst.setframerate(frame_rate)
            dst.writeframes(silence + frames)
        return out.getvalue()
    except (EOFError, wave.Error):
        log.warning("failed to add leading silence to WAV", exc_info=True)
        return wav


class Transcriber:
    def __init__(self, config) -> None:
        self.config = config
        self._session: aiohttp.ClientSession | None = None

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=600)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    def _build_prompt(self, language: str) -> str:
        cw = self.config.get("custom_words") or []
        prompts = self.config.get("language_prompts") or {}
        prompt = prompts.get(language, "")
        if cw:
            prompt = (prompt + "\nGlossary: " + ", ".join(cw)).strip()
        return prompt

    async def transcribe(
        self,
        server,
        wav_bytes: bytes,
        *,
        language: str,
        model: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> TranscriptionResult:
        if not wav_bytes:
            return TranscriptionResult(text="", raw_text="")
        target_model = model or server.loaded_model or self.config.get("default_model")
        ok = await server.ensure_ready(target_model)
        if not ok:
            raise RuntimeError(f"whisper server not ready: {server.last_error}")
        pad = self.config.get("snapshot_leading_silence_seconds", 0.25)
        body_bytes = with_leading_silence(wav_bytes, pad)
        prompt = self._build_prompt(language)
        backend = model_backend(self.config.get("models") or {}, target_model)
        if backend != "whisper.cpp":
            import time as _t

            t0 = _t.monotonic()
            data = await server.transcribe(
                target_model,
                body_bytes,
                language=language,
                prompt=prompt,
                cancel_event=cancel_event,
            )
            elapsed = _t.monotonic() - t0
            elapsed = float(data.get("elapsed_seconds") or elapsed)
            segments = data.get("segments") or []
            raw = text_cleanup.text_from_segments(
                segments, fallback=data.get("text") or ""
            ).strip()
            cleaned = self._clean(raw, wav_bytes=wav_bytes, language=language)
            return TranscriptionResult(
                text=cleaned,
                raw_text=raw,
                segments=segments,
                model=target_model or "",
                elapsed_seconds=elapsed,
            )
        form = aiohttp.FormData()
        form.add_field("file", body_bytes, filename="audio.wav", content_type="audio/wav")
        form.add_field("language", language or "auto")
        form.add_field("prompt", prompt)
        form.add_field("temperature", "0.0")
        form.add_field("response_format", "verbose_json")
        url = server.base_url + "/inference"
        server.acquire_slot()
        import time as _t

        elapsed = 0.0
        try:
            session = await self._session_get()

            async def _do() -> dict:
                nonlocal elapsed
                t0 = _t.monotonic()
                async with session.post(url, data=form) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
                elapsed = _t.monotonic() - t0
                return data

            if cancel_event is not None:
                task = asyncio.create_task(_do())
                cancel_task = asyncio.create_task(cancel_event.wait())
                done, _ = await asyncio.wait(
                    {task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if cancel_task in done and not task.done():
                    task.cancel()
                    try:
                        await task
                    except Exception:
                        pass
                    raise asyncio.CancelledError("transcription cancelled by caller")
                cancel_task.cancel()
                data = task.result()
            else:
                data = await _do()
        finally:
            server.release_slot()
        segments = data.get("segments") or []
        raw = text_cleanup.text_from_segments(
            segments, fallback=data.get("text") or ""
        ).strip()
        cleaned = self._clean(raw, wav_bytes=wav_bytes, language=language)
        return TranscriptionResult(
            text=cleaned,
            raw_text=raw,
            segments=segments,
            model=target_model or "",
            elapsed_seconds=elapsed,
        )

    def _clean(self, raw_text: str, *, wav_bytes: bytes, language: str) -> str:
        text = text_cleanup.collapse_whitespace(raw_text)
        hf = self.config.get("hallucination_filter") or {}
        if hf.get("enabled", True):
            tail_seconds = 1.0
            sr = SILENCE_PCM_SAMPLES_PER_SECOND
            tail_pcm = b""
            if len(wav_bytes) > 44:
                pcm = wav_bytes[44:]
                tail_pcm = pcm[-int(tail_seconds * sr * 2) :]
            text = hallucination_filter.apply(
                text,
                tail_audio_pcm=tail_pcm,
                language=language,
                enabled=True,
                silence_rms_threshold=float(hf.get("silence_rms_threshold", 90)),
                phrases=hf.get("phrases") or {},
                always_strip_phrases=hf.get("always_strip_phrases") or [],
            )
        return text_cleanup.finalize(
            text, append_trailing_space=bool(self.config.get("append_trailing_space", True))
        )
