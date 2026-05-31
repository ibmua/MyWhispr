from __future__ import annotations

import copy
import logging
import re
import socket
from pathlib import Path

from aiohttp import web
from aiohttp.web_request import FileField

from . import audio_sources
from .model_specs import BUILTIN_MODEL_OPTIONS, normalize_model_spec, public_model_card

log = logging.getLogger(__name__)

MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _redacted_config(config: dict) -> dict:
    out = copy.deepcopy(config)
    for raw in (out.get("models") or {}).values():
        if isinstance(raw, dict) and raw.get("api_key"):
            raw["api_key"] = "********"
    api_cfg = out.get("transcription_api") or {}
    if isinstance(api_cfg, dict) and api_cfg.get("api_key"):
        api_cfg["api_key"] = "********"
    return out


def _lan_ip_guess() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def transcription_api_client_spec(config: dict, *, include_key: bool = True) -> dict:
    api_cfg = config.get("transcription_api") or {}
    host = str(api_cfg.get("advertised_host") or "").strip() or _lan_ip_guess()
    scheme = str(api_cfg.get("advertised_scheme") or "http").strip() or "http"
    port = int(api_cfg.get("port") or 18180)
    key = str(api_cfg.get("api_key") or "")
    model_name = str(api_cfg.get("model_name") or "remote-large-q5").strip() or "remote-large-q5"
    server_model = str(config.get("default_model") or "").strip()
    server_card = {}
    models = config.get("models") or {}
    if server_model in models:
        try:
            server_card = public_model_card(server_model, models[server_model])
        except Exception:
            server_card = {}
    label = "Remote Whisper Large Q5" if model_name == "remote-large-q5" else f"MyWhispr {model_name}"
    spec = {
        "backend": "external_api",
        "provider": "MyWhispr LAN",
        "api_base_url": f"{scheme}://{host}:{port}",
        "endpoint": "/inference",
        "api_model": server_model or model_name,
        "api_key_required": True,
        "api_key_env": "",
        "send_model": False,
        "response_format": "verbose_json",
        "extra_fields": {"temperature": "0.0"},
        "label": label,
        "description": "MyWhispr LAN API",
        "subdescription": "Shared model",
        "languages": server_card.get("languages") or ["en", "uk"],
        "live_preview": True,
    }
    if include_key and key:
        spec["api_key"] = key
    return spec


def _external_api_spec_from_body(name: str, body: dict, existing: dict | None = None) -> dict:
    spec = {
        "backend": "external_api",
        "provider": str(body.get("provider") or (existing or {}).get("provider") or "External API").strip(),
        "label": str(body.get("label") or (existing or {}).get("label") or name).strip(),
        "description": str(body.get("description") or (existing or {}).get("description") or "External transcription API").strip(),
        "subdescription": str(body.get("subdescription") or (existing or {}).get("subdescription") or "API").strip(),
        "api_base_url": str(body.get("api_base_url") or (existing or {}).get("api_base_url") or "https://api.openai.com/v1").strip(),
        "endpoint": str(body.get("endpoint") or (existing or {}).get("endpoint") or "/audio/transcriptions").strip(),
        "api_model": str(body.get("api_model") or (existing or {}).get("api_model") or name).strip(),
        "api_key_env": str(body.get("api_key_env") or (existing or {}).get("api_key_env") or "OPENAI_API_KEY").strip(),
        "api_key_file": str(body.get("api_key_file") or (existing or {}).get("api_key_file") or "").strip(),
        "response_format": str(body.get("response_format") or (existing or {}).get("response_format") or "json").strip(),
        "live_preview": bool(body.get("live_preview", (existing or {}).get("live_preview", False))),
        "api_key_required": bool(body.get("api_key_required", (existing or {}).get("api_key_required", True))),
        "send_model": bool(body.get("send_model", (existing or {}).get("send_model", True))),
    }
    extra_fields = body.get("extra_fields", (existing or {}).get("extra_fields"))
    if isinstance(extra_fields, dict):
        spec["extra_fields"] = {str(k): str(v) for k, v in extra_fields.items() if v is not None}
    if "timeout_seconds" in body:
        spec["timeout_seconds"] = max(1.0, float(body.get("timeout_seconds") or 120.0))
    elif existing and "timeout_seconds" in existing:
        spec["timeout_seconds"] = existing["timeout_seconds"]
    else:
        spec["timeout_seconds"] = 120.0
    languages = body.get("languages")
    if isinstance(languages, str):
        languages = [s.strip() for s in languages.split(",") if s.strip()]
    if isinstance(languages, list):
        spec["languages"] = [str(s).strip() for s in languages if str(s).strip()]
    elif existing and isinstance(existing.get("languages"), list):
        spec["languages"] = existing["languages"]
    if body.get("clear_api_key"):
        pass
    elif isinstance(body.get("api_key"), str) and body.get("api_key").strip():
        spec["api_key"] = body["api_key"].strip()
    elif existing and existing.get("api_key"):
        spec["api_key"] = existing["api_key"]
    return spec


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
        return web.json_response(_redacted_config(daemon.config.snapshot()))

    async def api_transcription_share(_request):
        cfg = daemon.config.snapshot()
        api_cfg = cfg.get("transcription_api") or {}
        return web.json_response({
            "enabled": bool(api_cfg.get("enabled", False)),
            "running": daemon.transcription_api_runner is not None,
            "client_model_name": str(api_cfg.get("model_name") or "remote-large-q5"),
            "client_model": transcription_api_client_spec(cfg, include_key=True),
            "client_model_json": {
                str(api_cfg.get("model_name") or "remote-large-q5"): transcription_api_client_spec(cfg, include_key=True)
            },
        })

    async def api_model_external_save(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "reason": "invalid_json"}, status=400)
        name = str(body.get("name") or body.get("api_model") or "").strip()
        if not MODEL_NAME_RE.match(name):
            return web.json_response(
                {"ok": False, "reason": "model name must use letters, numbers, dot, underscore, or dash"},
                status=400,
            )
        models = daemon.config.get("models") or {}
        existing = models.get(name) if isinstance(models.get(name), dict) else None
        spec = _external_api_spec_from_body(name, body, existing)
        try:
            normalize_model_spec(name, spec)
            next_models = dict(models)
            next_models[name] = spec
            daemon.config.set("models", next_models)
        except Exception as e:
            return web.json_response({"ok": False, "reason": str(e)}, status=400)
        return web.json_response({"ok": True, "model": public_model_card(name, spec)})

    async def api_model_delete(request):
        name = request.match_info["name"]
        models = daemon.config.get("models") or {}
        if name not in models:
            return web.json_response({"ok": False, "reason": f"unknown model {name!r}"}, status=404)
        if name in BUILTIN_MODEL_OPTIONS:
            return web.json_response({"ok": False, "reason": "built-in models cannot be deleted"}, status=409)
        spec = normalize_model_spec(name, models[name])
        if spec.get("backend") == "whisper.cpp" and daemon.config.get("default_model") == name:
            return web.json_response({"ok": False, "reason": "cannot delete the active local default model"}, status=409)
        if daemon.primary_server.loaded_model == name:
            await daemon.unload_model()
        next_models = dict(models)
        next_models.pop(name, None)
        daemon.config.set("models", next_models)
        return web.json_response({"ok": True, "name": name})

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
    app.router.add_post("/api/models/external", api_model_external_save)
    app.router.add_delete("/api/models/{name}", api_model_delete)
    app.router.add_post("/api/model/unload", api_model_unload)
    app.router.add_post("/api/recording/stop", api_recording_stop)
    app.router.add_get("/api/config", api_config_read)
    app.router.add_get("/api/transcription_api/client_config", api_transcription_share)
    app.router.add_post("/api/config/custom_words", api_config_custom_words)
    app.router.add_post("/api/config/{key:.+}", api_config_write)
    app.router.add_get("/api/audio_sources", api_audio_sources)
    app.router.add_get("/api/shortcuts", api_shortcuts)
    app.router.add_post("/api/shortcuts/{trigger}/combo", api_shortcut_combo_update)
    app.router.add_post("/api/shortcuts/{trigger}", api_shortcut_update)
    app.router.add_delete("/api/shortcuts/{trigger}", api_shortcut_delete)
    return app


def _authorized(request: web.Request, api_key: str) -> bool:
    if not api_key:
        return False
    auth = request.headers.get("Authorization", "")
    if auth == f"Bearer {api_key}":
        return True
    if request.headers.get("X-API-Key", "") == api_key:
        return True
    return False


def build_transcription_api_app(daemon) -> web.Application:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app["daemon"] = daemon

    async def health(_request):
        return web.json_response({"ok": True, "service": "mywhispr-transcription-api"})

    async def transcribe(request):
        api_cfg = daemon.config.get("transcription_api") or {}
        api_key = str(api_cfg.get("api_key") or "")
        if not _authorized(request, api_key):
            raise web.HTTPUnauthorized(text="missing or invalid API key")
        post = await request.post()
        file_field = post.get("file")
        if not isinstance(file_field, FileField):
            return web.json_response({"error": "missing multipart file field 'file'"}, status=400)
        wav_bytes = file_field.file.read()
        if not wav_bytes:
            return web.json_response({"error": "empty audio file"}, status=400)
        language = str(post.get("language") or "auto")
        model = str(post.get("model") or daemon.config.get("default_model") or "")
        try:
            result = await daemon.transcriber.transcribe(
                daemon.primary_server,
                wav_bytes,
                language=language,
                model=model if model in (daemon.config.get("models") or {}) else None,
            )
        except Exception as e:
            log.exception("shared transcription API request failed")
            return web.json_response({"error": str(e) or type(e).__name__}, status=500)
        response_format = str(post.get("response_format") or "json")
        payload = {
            "text": result.raw_text or result.text,
            "segments": result.segments,
            "model": result.model,
            "language": language,
            "elapsed_seconds": result.elapsed_seconds,
        }
        if response_format == "text":
            return web.Response(text=payload["text"], content_type="text/plain")
        return web.json_response(payload)

    app.router.add_get("/health", health)
    app.router.add_post("/inference", transcribe)
    app.router.add_post("/audio/transcriptions", transcribe)
    app.router.add_post("/v1/audio/transcriptions", transcribe)
    return app


async def start_web_server(daemon, host: str, port: int, webui_dir: Path):
    app = build_app(daemon, webui_dir)
    runner = web.AppRunner(app, handle_signals=False, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("web ui listening http://%s:%s", host, port)
    return runner


async def start_transcription_api_server(daemon, host: str, port: int):
    app = build_transcription_api_app(daemon)
    runner = web.AppRunner(app, handle_signals=False, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("transcription API listening http://%s:%s", host, port)
    return runner
