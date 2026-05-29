from __future__ import annotations

import logging
import time
from pathlib import Path

from aiohttp import web

from . import audio_sources
from .model_specs import public_model_card

log = logging.getLogger(__name__)


def build_app(daemon, webui_dir: Path) -> web.Application:
    app = web.Application()
    app["daemon"] = daemon

    async def serve_index(_request):
        return web.FileResponse(webui_dir / "index.html")

    async def api_status(_request):
        return web.json_response(daemon.status_snapshot())

    async def api_history(_request):
        items = [it.public_dict() for it in daemon.history.list()]
        return web.json_response({"items": items})

    async def api_history_audio(request):
        item_id = request.match_info["id"]
        item = daemon.history.get(item_id)
        if item is None or not item.audio_bytes:
            raise web.HTTPNotFound()
        return web.Response(
            body=item.audio_bytes,
            headers={"Content-Type": "audio/wav", "Cache-Control": "no-store"},
        )

    async def api_history_clear(_request):
        daemon.history.clear()
        return web.json_response({"ok": True})

    async def api_history_retranslate(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        model = body.get("model") or daemon.config.get("default_model")
        limit = int(body.get("limit") or 20)
        missing_only = bool(body.get("missing_only", False))
        ok, reason = await daemon.start_retranslate(model=model, limit=limit, missing_only=missing_only)
        return web.json_response({"ok": ok, "reason": reason, "state": "queued" if ok else "rejected"})

    async def api_model_warm(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        model = body.get("model") or daemon.config.get("default_model")
        models = daemon.config.get("models") or {}
        if model not in models:
            return web.json_response(
                {"ok": False, "model": model, "last_error": f"unknown model {model!r}"},
                status=400,
            )
        daemon.config.set("default_model", model)
        ok = await daemon.warm_model(model)
        return web.json_response({"ok": ok, "model": model, "last_error": daemon.primary_server.last_error})

    async def api_models(_request):
        models = daemon.config.get("models") or {}
        default_model = daemon.config.get("default_model")
        loaded_model = daemon.primary_server.loaded_model
        items = []
        for name, raw_model in models.items():
            card = public_model_card(name, raw_model)
            items.append({
                **card,
                "default": name == default_model,
                "loaded": name == loaded_model,
                "running": name == loaded_model and daemon.primary_server.is_running(),
            })
        return web.json_response({
            "items": items,
            "default_model": default_model,
            "loaded_model": loaded_model,
            "server": daemon.primary_server.status(),
        })

    async def api_model_unload(_request):
        await daemon.unload_model()
        return web.json_response({"ok": True})

    async def api_recording_stop(_request):
        ok = await daemon.force_stop()
        return web.json_response({"ok": ok, "state": daemon.state.value})

    async def api_config_read(_request):
        return web.json_response(daemon.config.snapshot())

    async def api_config_write(request):
        key = request.match_info["key"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)
        if "value" not in body:
            return web.json_response({"ok": False, "reason": "missing 'value'"}, status=400)
        try:
            daemon.config.set(key, body["value"])
        except Exception as e:
            return web.json_response({"ok": False, "reason": str(e)}, status=400)
        return web.json_response({"ok": True, "key": key, "value": daemon.config.get(key)})

    async def api_config_custom_words(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)
        words = body.get("words")
        if not isinstance(words, list):
            return web.json_response({"ok": False, "reason": "words must be a list"}, status=400)
        daemon.config.set("custom_words", [str(w) for w in words])
        return web.json_response({"ok": True, "count": len(words)})

    async def api_audio_sources(_request):
        try:
            items = await audio_sources.list_sources()
        except Exception as e:
            log.warning("audio source listing failed: %s", e)
            items = []
        selected = (daemon.config.get("audio_input_device") or "").strip()
        return web.json_response({
            "items": items,
            "selected": selected,
            "default_target": "@DEFAULT_AUDIO_SOURCE@",
        })

    async def api_shortcuts(_request):
        return web.json_response(await daemon.shortcut_snapshot())

    async def api_shortcut_update(request):
        trigger = request.match_info["trigger"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)
        try:
            ok, reason, detail = await daemon.update_shortcut(trigger, body)
        except Exception as e:
            log.exception("shortcut update failed")
            return web.json_response({"ok": False, "reason": str(e)}, status=500)
        status = 200 if ok else 409
        return web.json_response({"ok": ok, "reason": reason, **detail}, status=status)

    async def api_shortcut_combo_update(request):
        trigger = request.match_info["trigger"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)
        try:
            ok, reason, detail = await daemon.update_combo_shortcuts(trigger, body)
        except Exception as e:
            log.exception("combo shortcut update failed")
            return web.json_response({"ok": False, "reason": str(e)}, status=500)
        status = 200 if ok else 409
        return web.json_response({"ok": ok, "reason": reason, **detail}, status=status)

    async def api_shortcut_delete(request):
        trigger = request.match_info["trigger"]
        try:
            ok, reason = await daemon.delete_shortcut(trigger)
        except Exception as e:
            log.exception("shortcut delete failed")
            return web.json_response({"ok": False, "reason": str(e)}, status=500)
        return web.json_response({"ok": ok, "reason": reason}, status=200 if ok else 409)

    app.router.add_get("/", serve_index)
    app.router.add_static("/static/", path=str(webui_dir), show_index=False)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/history", api_history)
    app.router.add_get("/api/history/{id}/audio", api_history_audio)
    app.router.add_post("/api/history/clear", api_history_clear)
    app.router.add_post("/api/history/retranslate", api_history_retranslate)
    app.router.add_post("/api/model/warm", api_model_warm)
    app.router.add_get("/api/models", api_models)
    app.router.add_post("/api/model/unload", api_model_unload)
    app.router.add_post("/api/recording/stop", api_recording_stop)
    app.router.add_get("/api/config", api_config_read)
    app.router.add_post("/api/config/custom_words", api_config_custom_words)
    app.router.add_post("/api/config/{key:.+}", api_config_write)
    app.router.add_get("/api/audio_sources", api_audio_sources)
    app.router.add_get("/api/shortcuts", api_shortcuts)
    app.router.add_post("/api/shortcuts/{trigger}/combo", api_shortcut_combo_update)
    app.router.add_post("/api/shortcuts/{trigger}", api_shortcut_update)
    app.router.add_delete("/api/shortcuts/{trigger}", api_shortcut_delete)
    return app


async def start_web_server(daemon, host: str, port: int, webui_dir: Path):
    app = build_app(daemon, webui_dir)
    runner = web.AppRunner(app, handle_signals=False, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("web ui listening http://%s:%s", host, port)
    return runner
