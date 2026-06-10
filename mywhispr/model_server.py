from __future__ import annotations

import asyncio
from typing import Any

from .external_api_server import ExternalApiServer
from .gpu_asr_server import GpuAsrServer
from .model_specs import is_external_api_model, is_gpu_model, normalize_model_spec
from .whisper_server import WhisperServer


class ModelServer:
    """Routes configured ASR models to whisper.cpp or a GPU worker."""

    def __init__(
        self,
        *,
        binary: str,
        host: str,
        port: int,
        model_specs: dict[str, Any],
        gpu_python: str = "",
        startup_timeout: float = 180.0,
        idle_shutdown_seconds: float = 0.0,
        name: str = "primary",
    ) -> None:
        self.models = model_specs
        self.name = name
        self._last_error = ""
        self.whisper = WhisperServer(
            binary=binary,
            host=host,
            port=port,
            model_paths=model_specs,
            startup_timeout=startup_timeout,
            idle_shutdown_seconds=idle_shutdown_seconds,
            name=f"{name}-whisper",
        )
        self.gpu = GpuAsrServer(
            model_specs=model_specs,
            python=gpu_python,
            startup_timeout=max(startup_timeout, 300.0),
            idle_shutdown_seconds=idle_shutdown_seconds,
            name=f"{name}-gpu",
        )
        self.external = ExternalApiServer(model_specs=model_specs, name=f"{name}-external")
        self._active = "whisper.cpp"

    @property
    def base_url(self) -> str:
        return self.whisper.base_url

    @property
    def loaded_model(self) -> str | None:
        if self._active == "gpu":
            return self.gpu.loaded_model
        if self._active == "external_api":
            return self.external.loaded_model
        return self.whisper.loaded_model

    @property
    def last_error(self) -> str:
        if self._last_error:
            return self._last_error
        if self._active == "gpu":
            return self.gpu.last_error
        if self._active == "external_api":
            return self.external.last_error
        return self.whisper.last_error

    @last_error.setter
    def last_error(self, value: str) -> None:
        self._last_error = value
        self.whisper.last_error = value
        self.gpu.last_error = value
        self.external.last_error = value

    def _spec(self, model: str | None) -> dict[str, Any] | None:
        if not model or model not in self.models:
            return None
        return normalize_model_spec(model, self.models[model])

    def _is_gpu(self, model: str | None) -> bool:
        spec = self._spec(model)
        return bool(spec and is_gpu_model(spec))

    def _is_external(self, model: str | None) -> bool:
        spec = self._spec(model)
        return bool(spec and is_external_api_model(spec))

    def is_running(self) -> bool:
        if self._active == "gpu":
            return self.gpu.is_running()
        if self._active == "external_api":
            return self.external.is_running()
        return self.whisper.is_running()

    def status(self) -> dict[str, Any]:
        if self._active == "gpu":
            active = self.gpu.status()
        elif self._active == "external_api":
            active = self.external.status()
        else:
            active = self.whisper.status()
        return {
            **active,
            "name": self.name,
            "active_backend": self._active,
            "whisper": self.whisper.status(),
            "gpu": self.gpu.status(),
            "external": self.external.status(),
        }

    def set_models(self, model_specs: dict[str, Any]) -> None:
        self.models = model_specs
        self.whisper.models = model_specs
        self.gpu.models = model_specs
        self.external.set_models(model_specs)

    def set_gpu_python(self, python: str) -> None:
        self.gpu.set_default_python(python)

    def set_whisper_binary(self, binary: str) -> None:
        self.whisper.binary = binary

    def set_idle_shutdown_seconds(self, seconds: float) -> None:
        self.whisper.idle_shutdown_seconds = seconds
        self.gpu.idle_shutdown_seconds = seconds

    def supports_live_preview(self, model: str | None = None) -> bool:
        target = model or self.loaded_model
        spec = self._spec(target)
        if spec is None:
            return True
        return bool(spec.get("live_preview", spec.get("backend") == "whisper.cpp"))

    async def ensure_ready(self, model: str | None = None) -> bool:
        target = model or self.loaded_model or next(iter(self.models), None)
        if not target:
            self.last_error = "no model configured"
            return False
        self._last_error = ""
        if self._is_gpu(target):
            if self.whisper.is_running():
                await self.whisper.stop()
            if self.external.is_running():
                await self.external.stop()
            self._active = "gpu"
            return await self.gpu.ensure_ready(target)
        if self._is_external(target):
            if self.whisper.is_running():
                await self.whisper.stop()
            if self.gpu.is_running():
                await self.gpu.stop()
            self._active = "external_api"
            return await self.external.ensure_ready(target)
        if self.gpu.is_running():
            await self.gpu.stop()
        if self.external.is_running():
            await self.external.stop()
        self._active = "whisper.cpp"
        return await self.whisper.ensure_ready(target)

    async def transcribe(
        self,
        model: str,
        wav_bytes: bytes,
        *,
        language: str,
        prompt: str = "",
        cancel_event: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        if self._is_gpu(model):
            self._active = "gpu"
            return await self.gpu.transcribe(
                model,
                wav_bytes,
                language=language,
                cancel_event=cancel_event,
            )
        if self._is_external(model):
            self._active = "external_api"
            return await self.external.transcribe(
                model,
                wav_bytes,
                language=language,
                prompt=prompt,
                cancel_event=cancel_event,
            )
        raise RuntimeError(f"model {model!r} is not a routed worker model")

    async def stop(self) -> None:
        await self.whisper.stop()
        await self.gpu.stop()
        await self.external.stop()

    def acquire_slot(self) -> None:
        self.whisper.acquire_slot()

    def release_slot(self) -> None:
        self.whisper.release_slot()
