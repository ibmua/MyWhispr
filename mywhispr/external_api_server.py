from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

import aiohttp

from .model_specs import normalize_model_spec

log = logging.getLogger(__name__)


class ExternalApiServer:
    """OpenAI-compatible multipart transcription API adapter.

    This is not a local server process. It implements the same small contract as
    the local model supervisors so the daemon can switch model cards uniformly.
    """

    def __init__(self, model_specs: dict[str, Any], name: str = "primary-external") -> None:
        self.models = model_specs
        self.name = name
        self.loaded_model: str | None = None
        self.loaded_backend = "external_api"
        self.last_error = ""
        self._ready = asyncio.Event()
        self._inflight = 0
        self._last_used = time.monotonic()
        self._session: aiohttp.ClientSession | None = None

    def set_models(self, model_specs: dict[str, Any]) -> None:
        self.models = model_specs
        if self.loaded_model and self.loaded_model not in self.models:
            self.loaded_model = None
            self._ready.clear()

    def is_running(self) -> bool:
        return self.loaded_model is not None and self._ready.is_set()

    def status(self) -> dict[str, Any]:
        spec = self._spec(self.loaded_model)
        return {
            "name": self.name,
            "loaded_model": self.loaded_model,
            "backend": self.loaded_backend,
            "running": self.is_running(),
            "ready": self._ready.is_set(),
            "port": None,
            "last_error": self.last_error,
            "inflight": self._inflight,
            "endpoint": self._url(spec) if spec else "",
        }

    async def ensure_ready(self, model: str | None = None) -> bool:
        target = model or self.loaded_model
        if not target:
            self.last_error = "no model configured"
            return False
        if target not in self.models:
            self.last_error = f"unknown model {target!r}"
            return False
        spec = normalize_model_spec(target, self.models[target])
        if spec.get("backend") != "external_api":
            self.last_error = f"model {target!r} is not an external API model"
            return False
        if not self._url(spec):
            self.last_error = f"external API endpoint missing for {target!r}"
            return False
        if not str(spec.get("api_model") or "").strip():
            self.last_error = f"external API model id missing for {target!r}"
            return False
        if bool(spec.get("api_key_required", True)) and not self._api_key(spec):
            env_name = str(spec.get("api_key_env") or "").strip()
            suffix = f" or set {env_name}" if env_name else ""
            self.last_error = f"external API key missing for {target!r}{suffix}"
            return False
        self.loaded_model = target
        self.loaded_backend = "external_api"
        self.last_error = ""
        self._ready.set()
        self._last_used = time.monotonic()
        return True

    async def transcribe(
        self,
        model: str,
        wav_bytes: bytes,
        *,
        language: str,
        prompt: str = "",
        cancel_event: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        ok = await self.ensure_ready(model)
        if not ok:
            raise RuntimeError(self.last_error or "external API model not ready")
        spec = normalize_model_spec(model, self.models[model])
        self.acquire_slot()
        try:
            task = asyncio.create_task(self._post_transcription(spec, wav_bytes, language=language, prompt=prompt))
            if cancel_event is None:
                return await task
            cancel_task = asyncio.create_task(cancel_event.wait())
            try:
                done, _ = await asyncio.wait({task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
                if cancel_task in done and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    raise asyncio.CancelledError("external API transcription cancelled by caller")
                return task.result()
            finally:
                cancel_task.cancel()
        finally:
            self.release_slot()

    async def stop(self) -> None:
        self.loaded_model = None
        self._ready.clear()
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    def acquire_slot(self) -> None:
        self._inflight += 1

    def release_slot(self) -> None:
        self._inflight = max(0, self._inflight - 1)
        self._last_used = time.monotonic()

    def _spec(self, model: str | None) -> dict[str, Any] | None:
        if not model or model not in self.models:
            return None
        return normalize_model_spec(model, self.models[model])

    def _url(self, spec: dict[str, Any] | None) -> str:
        if not spec:
            return ""
        base = str(spec.get("api_base_url") or "").strip().rstrip("/")
        endpoint = str(spec.get("endpoint") or "").strip()
        if not base:
            return ""
        if not endpoint:
            endpoint = "/audio/transcriptions"
        return base + "/" + endpoint.lstrip("/")

    def _api_key(self, spec: dict[str, Any]) -> str:
        direct = str(spec.get("api_key") or "").strip()
        if direct:
            return direct
        env_name = str(spec.get("api_key_env") or "").strip()
        if env_name:
            env_value = os.environ.get(env_name, "").strip()
            if env_value:
                return env_value
        key_file = str(spec.get("api_key_file") or "").strip()
        if key_file:
            try:
                return Path(key_file).read_text().strip()
            except OSError:
                return ""
        return ""

    async def _session_get(self, spec: dict[str, Any]) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout_seconds = float(spec.get("timeout_seconds") or 120.0)
            timeout = aiohttp.ClientTimeout(total=timeout_seconds, sock_connect=20, sock_read=timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _post_transcription(
        self,
        spec: dict[str, Any],
        wav_bytes: bytes,
        *,
        language: str,
        prompt: str,
    ) -> dict[str, Any]:
        form = aiohttp.FormData()
        form.add_field("file", wav_bytes, filename="audio.wav", content_type="audio/wav")
        form.add_field("model", str(spec.get("api_model") or ""))
        if language and language != "auto" and bool(spec.get("send_language", True)):
            form.add_field(str(spec.get("language_field") or "language"), language)
        if prompt and bool(spec.get("send_prompt", True)):
            form.add_field(str(spec.get("prompt_field") or "prompt"), prompt)
        response_format = str(spec.get("response_format") or "verbose_json").strip()
        if response_format:
            form.add_field("response_format", response_format)
        extra_fields = spec.get("extra_fields") or {}
        if isinstance(extra_fields, dict):
            for key, value in extra_fields.items():
                if value is not None:
                    form.add_field(str(key), str(value))

        headers = {}
        configured_headers = spec.get("headers") or {}
        if isinstance(configured_headers, dict):
            headers.update({str(k): str(v) for k, v in configured_headers.items()})
        api_key = self._api_key(spec)
        if api_key:
            header = str(spec.get("auth_header") or "Authorization")
            template = str(spec.get("auth_header_value_template") or "Bearer {api_key}")
            headers[header] = template.replace("{api_key}", api_key)

        url = self._url(spec)
        session = await self._session_get(spec)
        started = time.monotonic()
        async with session.post(url, data=form, headers=headers) as resp:
            raw_body = await resp.text()
            if resp.status >= 400:
                message = raw_body.strip().replace("\n", " ")
                if len(message) > 240:
                    message = message[:237] + "..."
                raise RuntimeError(f"external API HTTP {resp.status}: {message or resp.reason}")
            try:
                data = await resp.json(content_type=None)
            except Exception as e:
                raise RuntimeError(f"external API returned non-JSON response: {raw_body[:160]}") from e
        elapsed = time.monotonic() - started
        if not isinstance(data, dict):
            raise RuntimeError("external API returned an unsupported JSON shape")
        text = str(data.get("text") or data.get("transcript") or data.get("transcription") or "").strip()
        segments = data.get("segments") if isinstance(data.get("segments"), list) else []
        return {
            "ok": True,
            "text": text,
            "segments": segments,
            "elapsed_seconds": elapsed,
            "raw_response": data,
        }
