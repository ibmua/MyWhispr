from __future__ import annotations

import asyncio
import logging
import time
import uuid

log = logging.getLogger(__name__)


class Retranslator:
    """Manual batch retranscription of in-memory history against an alternate model."""

    def __init__(self, *, config, history, transcriber, primary_server, alt_server_factory) -> None:
        self.config = config
        self.history = history
        self.transcriber = transcriber
        self.primary_server = primary_server
        self.alt_server_factory = alt_server_factory
        self.task: asyncio.Task | None = None
        self.state: dict = {
            "active": False,
            "model": "",
            "done": 0,
            "total": 0,
            "stage": "idle",
            "error": "",
        }

    def is_running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def start(self, *, model: str, limit: int = 20, missing_only: bool = False) -> tuple[bool, str]:
        if self.is_running():
            return False, "retranslate already running"
        items = self.history.list()[:limit]
        if missing_only:
            items = [it for it in items if not self._has_completed_result(it, model)]
        if not items:
            return False, "no items to retranslate"
        models = self.config.get("models") or {}
        if model not in models:
            return False, f"model {model} not configured"
        self.state.update(
            active=True, model=model, done=0, total=len(items), stage="loading-model", error=""
        )
        self.task = asyncio.create_task(self._run(items, model))
        return True, "queued"

    def _has_completed_result(self, item, model: str) -> bool:
        for result in getattr(item, "alternates", []) or []:
            if result.get("model") == model and result.get("status") == "done" and result.get("text"):
                return True
        legacy = getattr(item, "alternate", {}) or {}
        return legacy.get("model") == model and legacy.get("status") == "done" and bool(legacy.get("text"))

    def _append_result(self, item, model: str) -> dict:
        now = time.time()
        result = {
            "id": uuid.uuid4().hex,
            "created_at": now,
            "updated_at": now,
            "model": model,
            "status": "running",
            "text": "",
            "raw_text": "",
            "generation_ms": 0,
            "error": "",
        }
        item.alternates.append(result)
        item.alternate = result
        return result

    def _update_result(self, item, result: dict, **fields) -> None:
        result.update(fields)
        result["updated_at"] = time.time()
        item.alternate = result

    async def _run(self, items, model: str) -> None:
        same_as_primary = (model == self.primary_server.loaded_model)
        server = self.primary_server if same_as_primary else self.alt_server_factory(model)
        try:
            ok = await server.ensure_ready(model)
            if not ok:
                self.state.update(active=False, stage="done", error=server.last_error or "alt server not ready")
                return
            self.state.update(stage="running")
            for idx, item in enumerate(items, start=1):
                if not item.audio_bytes:
                    continue
                result = self._append_result(item, model)
                try:
                    res = await self.transcriber.transcribe(
                        server,
                        item.audio_bytes,
                        language=item.language,
                        model=model,
                    )
                    generation_ms = max(0, int(round(res.elapsed_seconds * 1000)))
                    self._update_result(
                        item,
                        result,
                        status="done",
                        text=res.text,
                        raw_text=res.raw_text,
                        generation_ms=generation_ms,
                    )
                except Exception as e:
                    log.warning("retranslate item failed: %s", e)
                    self._update_result(item, result, status="error", error=str(e))
                self.state["done"] = idx
            self.state.update(stage="stopping-model")
        finally:
            if not same_as_primary:
                try:
                    await server.stop()
                except Exception:
                    log.exception("alt server stop failed")
            self.state.update(active=False, stage="done")
