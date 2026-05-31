from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import time
from pathlib import Path
from typing import Any

from . import audio_sources
from . import paste as paste_mod
from .config import Config, language_for_mode, mode_config
from .control import ControlSocketServer
from .history import History, HistoryItem
from .input_events import InputSupervisor, KeyEvent
from .recorder import Recorder
from .retranslate import Retranslator
from .shortcuts import ShortcutManager, keycode_for_binding
from .state import IGNORED_BY_DESIGN, Event, State
from .streaming import StreamingSession
from .tones import Tones
from .transcriber import Transcriber
from .web import start_web_server
from .model_server import ModelServer

log = logging.getLogger(__name__)

GRAVE_KEYCODE = 41
TRIGGER_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class Daemon:
    def __init__(self, config: Config, webui_dir: Path) -> None:
        self.config = config
        self.webui_dir = webui_dir
        self.started_at = time.time()
        self.pid = os.getpid()

        self.runtime_dir = Path(config.get("runtime_dir"))
        self.runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.recordings_dir = self.runtime_dir / "recordings"

        self.state: State = State.IDLE
        self.state_changed_at = time.monotonic()
        self.last_stop_at: float = 0.0
        self.last_event_seq = 0

        self.history = History(limit=int(config.get("history_limit", 20)))
        self.tones = Tones(
            self.runtime_dir,
            enabled=bool(config.get("audio_cues.enabled", True)),
            volume=float(config.get("audio_cues.volume", 0.85)),
        )
        def _audio_target() -> str:
            t = (config.get("audio_input_device") or "").strip()
            return t or Recorder.DEFAULT_TARGET
        self.recorder = Recorder(self.recordings_dir, target_provider=_audio_target)
        self.shortcuts = ShortcutManager(webui_dir.parent)

        models = config.get("models") or {}
        self.primary_server = ModelServer(
            binary=config.get("whisper_server_binary"),
            host=config.get("whisper_host", "127.0.0.1"),
            port=int(config.get("whisper_port", 18178)),
            model_specs=models,
            gpu_python=config.get("gpu_asr_python") or "",
            startup_timeout=float(config.get("whisper_startup_timeout_seconds", 180.0)),
            idle_shutdown_seconds=float(config.get("whisper_idle_shutdown_seconds", 0.0)),
            name="primary",
        )
        self.transcriber = Transcriber(config)

        def alt_factory(model_name: str) -> ModelServer:
            return ModelServer(
                binary=config.get("whisper_server_binary"),
                host=config.get("whisper_host", "127.0.0.1"),
                port=int(config.get("alternate_whisper_port", 18179)),
                model_specs=models,
                gpu_python=config.get("gpu_asr_python") or "",
                startup_timeout=float(config.get("whisper_startup_timeout_seconds", 180.0)),
                idle_shutdown_seconds=0.0,
                name="alt",
            )

        self.retranslator = Retranslator(
            config=config,
            history=self.history,
            transcriber=self.transcriber,
            primary_server=self.primary_server,
            alt_server_factory=alt_factory,
        )

        self.control_server: ControlSocketServer | None = None
        self.web_runner = None
        self.input_supervisor: InputSupervisor | None = None
        self.event_queue: asyncio.Queue = asyncio.Queue()

        self._current_trigger: str = ""
        self._current_mode: str = ""
        self._current_mode_config: dict[str, Any] = {}
        self._current_language: str = ""
        self._current_model: str = ""
        self._combo_deadline_task: asyncio.Task | None = None
        self._grab_safety_task: asyncio.Task | None = None
        self._combo_active: bool = False
        self._max_duration_task: asyncio.Task | None = None
        self._warm_task: asyncio.Task | None = None
        self._startup_task: asyncio.Task | None = None
        self._physical_start_task: asyncio.Task | None = None
        self._combo_long_task: asyncio.Task | None = None
        self._start_queued: bool = False
        self._release_requested_while_starting: bool = False
        self._stream: StreamingSession | None = None
        self._last_preview_text: str = ""
        self._error_message: str = ""
        self._session_nostream: bool = False
        self._pressed_keycodes: set[int] = set()
        self._last_key_down_at: dict[int, float] = {}
        self._last_key_up_at: dict[int, float] = {}
        self._combo_key_down_at: dict[int, float] = {}

        self._fsm_check()

    # ------------------------------------------------------------------ FSM

    def _fsm_check(self) -> None:
        """Sanity-check the transition table at startup."""
        defined = set(TRANSITIONS.keys()) | IGNORED_BY_DESIGN
        for s in State:
            for e in Event:
                if (s, e) in defined:
                    continue
                log.debug("no transition defined for %s/%s (allowed to drop)", s, e)

    def post(self, event: Event, **payload) -> None:
        self.last_event_seq += 1
        self.event_queue.put_nowait((event, payload, self.last_event_seq))

    async def _drain_events(self) -> None:
        while True:
            event, payload, seq = await self.event_queue.get()
            await self._dispatch(event, payload, seq)

    async def _dispatch(self, event: Event, payload: dict, seq: int) -> None:
        handler = TRANSITIONS.get((self.state, event))
        if handler is None:
            if event == Event.START:
                self._start_queued = False
            if (self.state, event) not in IGNORED_BY_DESIGN:
                log.info("ignored event=%s state=%s payload=%s", event.value, self.state.value, payload)
            else:
                log.debug("ignored-by-design event=%s state=%s", event.value, self.state.value)
            return
        try:
            new_state = await handler(self, **payload)
        except Exception:
            log.exception("handler crashed for %s/%s", self.state.value, event.value)
            new_state = self.state
        if new_state is None:
            return
        age_ms = int((time.monotonic() - self.state_changed_at) * 1000)
        log.info("state %s -> %s on %s age_ms=%d seq=%d",
                 self.state.value, new_state.value, event.value, age_ms, seq)
        self.state = new_state
        self.state_changed_at = time.monotonic()

    # ------------------------------------------------------------ lifecycle

    async def setup(self) -> None:
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        socket_path = Path(self.config.get("socket_path"))
        self.control_server = ControlSocketServer(socket_path, self._control_request)
        await self.control_server.start()

        triggers_cfg = self.config.get("triggers") or {}
        grab_cfg = self.config.get("input_grab") or {}
        self.input_supervisor = InputSupervisor(
            self._on_key,
            include_patterns=grab_cfg.get("device_name_patterns") or [],
            exclude_patterns=grab_cfg.get("exclude_device_name_patterns") or [],
        )
        await self.input_supervisor.start()

        webcfg = self.config.get("web") or {}
        self.web_runner = await start_web_server(
            self, webcfg.get("host", "127.0.0.1"), int(webcfg.get("port", 16666)), self.webui_dir,
        )

        self.config.subscribe(self._config_changed)

        # Drain events as a background task.
        asyncio.create_task(self._drain_events())
        if bool(self.config.get("preload_default_model_on_startup", True)):
            self._schedule_warm(self.config.get("default_model"), reason="startup")

    async def shutdown(self) -> None:
        if self._stream is not None:
            await self._stream.stop()
        if self._warm_task is not None and not self._warm_task.done():
            self._warm_task.cancel()
            try:
                await self._warm_task
            except asyncio.CancelledError:
                pass
        if self.control_server is not None:
            await self.control_server.stop()
        if self.input_supervisor is not None:
            await self.input_supervisor.stop()
        if self.web_runner is not None:
            await self.web_runner.cleanup()
        await self.primary_server.stop()
        await self.transcriber.close()

    # ---------------------------------------------------------- handlers in

    def _config_changed(self, key: str, snapshot: dict) -> None:
        self.history.set_limit(int(snapshot.get("history_limit", 20)))
        models = snapshot.get("models") or {}
        self.primary_server.set_models(models)
        audio_cues = snapshot.get("audio_cues") or {}
        self.tones.configure(
            enabled=bool(audio_cues.get("enabled", True)),
            volume=float(audio_cues.get("volume", 0.85)),
        )
        self.primary_server.set_idle_shutdown_seconds(
            float(snapshot.get("whisper_idle_shutdown_seconds", 0.0))
        )

    def _schedule_warm(self, model: str | None, *, reason: str) -> bool:
        model = str(model or "").strip()
        if not model:
            log.info("model warm skipped reason=%s no default_model configured", reason)
            return False
        if self._warm_task is not None and not self._warm_task.done():
            log.info("model warm already running reason=%s model=%s", reason, model)
            return False
        self._warm_task = asyncio.create_task(self._warm_model_effect(model, reason=reason))
        return True

    async def _warm_model_effect(self, model: str, *, reason: str) -> None:
        log.info("model warm started reason=%s model=%s", reason, model)
        try:
            ok = await self.primary_server.ensure_ready(model)
        except asyncio.CancelledError:
            log.info("model warm cancelled reason=%s model=%s", reason, model)
            raise
        except Exception as e:
            log.exception("model warm crashed reason=%s model=%s", reason, model)
            self._error_message = f"model warm failed: {e}"
            return
        if ok:
            log.info("model warm ready reason=%s model=%s", reason, model)
            return
        self._error_message = self.primary_server.last_error
        log.error("model warm failed reason=%s model=%s error=%s", reason, model, self.primary_server.last_error)

    async def _control_request(self, req: dict) -> dict:
        cmd = req.get("cmd")
        if cmd == "start":
            trigger = req.get("trigger") or "grave"
            triggers = self.config.get("triggers") or {}
            if trigger not in triggers:
                return {"ok": False, "state": self.state.value, "reason": f"unknown trigger {trigger}"}
            now = time.monotonic()
            cooldown = float(self.config.get("start_cooldown_seconds", 0.2))
            if self.state != State.IDLE or self._start_queued:
                return {"ok": False, "state": self.state.value, "reason": "busy"}
            if self.last_stop_at and self._trigger_is_same_hold(trigger, self.last_stop_at):
                age_ms = int((now - self.last_stop_at) * 1000)
                log.info("ignored start same-hold trigger=%s age_ms=%d", trigger, age_ms)
                return {"ok": False, "state": self.state.value, "reason": "same-hold", "age_ms": age_ms}
            if self.last_stop_at and now - self.last_stop_at < cooldown:
                age_ms = int((now - self.last_stop_at) * 1000)
                log.info("ignored start cooldown trigger=%s age_ms=%d", trigger, age_ms)
                return {"ok": False, "state": self.state.value, "reason": "ignored-repeat", "age_ms": age_ms}
            if bool(self.config.get("require_physical_trigger_down", True)):
                is_down = await self._wait_trigger_down(trigger, timeout=0.12)
                if not is_down:
                    log.info("ignored start trigger=%s reason=not-held", trigger)
                    return {"ok": False, "state": self.state.value, "reason": "not-held"}
            self._start_queued = True
            self.post(Event.START, trigger=trigger)
            return {"ok": True, "state": "STARTING", "reason": "queued"}
        if cmd == "stop":
            self.post(Event.STOP)
            return {"ok": True, "state": self.state.value}
        if cmd == "status":
            return {"ok": True, "state": self.state.value, "status": self.status_snapshot()}
        if cmd == "warm":
            model = req.get("model") or self.config.get("default_model")
            ok = await self.warm_model(model)
            return {"ok": ok, "state": self.state.value, "model": model, "reason": self.primary_server.last_error}
        if cmd == "unload":
            await self.unload_model()
            return {"ok": True, "state": self.state.value}
        return {"ok": False, "reason": f"unknown cmd {cmd!r}"}

    def _on_key(self, ev: KeyEvent) -> None:
        lower_name = (ev.device_name or "").lower()
        if "ydotoold virtual device" not in lower_name:
            if ev.value == 1:
                self._pressed_keycodes.add(ev.code)
                self._last_key_down_at[ev.code] = time.monotonic()
                self._maybe_start_from_keydown(ev.code)
            elif ev.value == 0:
                self._pressed_keycodes.discard(ev.code)
                self._last_key_up_at[ev.code] = time.monotonic()

        # Release of grave during STARTING/RECORDING -> stop. STARTING matters
        # for short taps where the key-up can arrive before pw-record is ready.
        if ev.value == 0 and self.state in (State.STARTING, State.RECORDING):
            triggers = self.config.get("triggers") or {}
            trig_cfg = triggers.get(self._current_trigger) or {}
            stop_codes = set(int(c) for c in (trig_cfg.get("stop_on_release_codes") or [GRAVE_KEYCODE]))
            if ev.code in stop_codes:
                self.post(Event.RELEASE, trigger=self._current_trigger)
                return
        # Combo key press/release while combo grab is active. Press switches to
        # the key's short mode immediately. Holding past the threshold switches
        # to the key's long mode while the key is still down.
        if ev.value in (0, 1) and self._combo_active and self.state in (State.STARTING, State.RECORDING):
            triggers = self.config.get("triggers") or {}
            trig_cfg = triggers.get(self._current_trigger) or {}
            combo = trig_cfg.get("combo") or {}
            for k in combo.get("keys") or []:
                if int(k.get("code", -1)) == ev.code:
                    if ev.value == 1:
                        self._combo_key_down_at[ev.code] = time.monotonic()
                        if k.get("type") == "nostream":
                            self.post(Event.NOSTREAM)
                            return
                        mode = k.get("short_mode") or k.get("switch_language")
                        self.post(Event.COMBO, mode=mode, switch_language=k.get("switch_language"))
                        if self._combo_long_task and not self._combo_long_task.done():
                            self._combo_long_task.cancel()
                        long_mode = k.get("long_mode")
                        if long_mode:
                            self._combo_long_task = asyncio.create_task(
                                self._commit_long_combo_after_delay(
                                    long_mode,
                                    float(combo.get("long_press_seconds", 0.5)),
                                    code=ev.code,
                                )
                            )
                    else:
                        self._combo_key_down_at.pop(ev.code, None)
                        if self._combo_long_task and not self._combo_long_task.done():
                            self._combo_long_task.cancel()
                    return

    # ----------------------------------------------------------- coroutines

    def _maybe_start_from_keydown(self, code: int) -> None:
        if self.state != State.IDLE or self._start_queued:
            return
        triggers = self.config.get("triggers") or {}
        for trigger, trig_cfg in triggers.items():
            stop_codes = set(int(c) for c in (trig_cfg.get("stop_on_release_codes") or [GRAVE_KEYCODE]))
            if code not in stop_codes:
                continue
            if self._physical_start_task and not self._physical_start_task.done():
                self._physical_start_task.cancel()
            self._physical_start_task = asyncio.create_task(self._physical_start_fallback(trigger, code))
            return

    async def _physical_start_fallback(self, trigger: str, code: int) -> None:
        try:
            await asyncio.sleep(float(self.config.get("physical_start_fallback_delay_seconds", 0.08)))
        except asyncio.CancelledError:
            return
        if self.state != State.IDLE or self._start_queued or not self._trigger_is_down(trigger):
            return
        now = time.monotonic()
        cooldown = float(self.config.get("start_cooldown_seconds", 0.2))
        if self.last_stop_at and self._trigger_is_same_hold(trigger, self.last_stop_at):
            age_ms = int((now - self.last_stop_at) * 1000)
            log.info("ignored physical start same-hold trigger=%s age_ms=%d", trigger, age_ms)
            return
        if self.last_stop_at and now - self.last_stop_at < cooldown:
            age_ms = int((now - self.last_stop_at) * 1000)
            log.info("ignored physical start cooldown trigger=%s age_ms=%d", trigger, age_ms)
            return
        self._start_queued = True
        log.info("physical fallback start trigger=%s code=%s", trigger, code)
        self.post(Event.START, trigger=trigger)

    async def _commit_long_combo_after_delay(self, mode: str, delay: float, *, code: int | None = None) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if self.state not in (State.STARTING, State.RECORDING) or not self._combo_active:
            return
        if self._current_trigger and not self._trigger_is_down(self._current_trigger):
            return
        if code is not None and code not in self._pressed_keycodes:
            return
        self.post(Event.COMBO, mode=mode, switch_language=None)

    async def warm_model(self, model: str) -> bool:
        models = self.config.get("models") or {}
        if model not in models:
            self.primary_server.last_error = f"unknown model {model!r}"
            return False
        if self._warm_task is not None and not self._warm_task.done():
            self._warm_task.cancel()
            try:
                await self._warm_task
            except asyncio.CancelledError:
                pass
        self.config.set("default_model", model)
        return await self.primary_server.ensure_ready(model)

    async def unload_model(self) -> None:
        if self._warm_task is not None and not self._warm_task.done():
            self._warm_task.cancel()
            try:
                await self._warm_task
            except asyncio.CancelledError:
                pass
        await self.primary_server.stop()

    async def force_stop(self) -> bool:
        if self.state == State.RECORDING:
            self.post(Event.STOP)
            return True
        return False

    async def start_retranslate(self, *, model: str, limit: int, missing_only: bool) -> tuple[bool, str]:
        return await self.retranslator.start(model=model, limit=limit, missing_only=missing_only)

    async def shortcut_snapshot(self) -> dict:
        snap = await self.shortcuts.snapshot(self.config.get("triggers") or {})
        snap["modes"] = self.config.get("modes") or {}
        return snap

    async def update_shortcut(self, trigger: str, body: dict) -> tuple[bool, str, dict]:
        if not TRIGGER_NAME_RE.match(trigger):
            return False, "trigger name must use letters, numbers, dot, underscore, or dash", {}
        triggers = self.config.get("triggers") or {}
        if self.state != State.IDLE:
            return False, "cannot change shortcuts while recording", {}

        current = triggers.get(trigger) or {
            "binding": trigger,
            "default_mode": self.config.get("triggers.grave.default_mode", "en"),
            "language": self.config.get("triggers.grave.language", "en"),
            "stop_on_release_codes": [],
            "combo": {
                "enabled": True,
                "hold_grab_until_release": True,
                "deadline_seconds": 1.2,
                "long_press_seconds": 0.5,
                "long_press_commit_delay_seconds": 0.18,
                "keys": [],
            },
        }
        binding = str(body.get("binding") or current.get("binding") or trigger).strip()
        modes = self.config.get("modes") or {}
        modes_changed = False
        default_type = str(body.get("default_type") or "").strip()
        if default_type == "script":
            default_mode = f"default_{trigger}_script"
            modes[default_mode] = {
                "label": "Default script",
                "type": "script",
                "language": str(body.get("default_language") or "auto").strip() or "auto",
                "command": str(body.get("default_script_command") or "").strip(),
            }
            modes_changed = True
        elif "default_language" in body:
            default_mode = str(body.get("default_language") or "auto").strip()
        else:
            default_mode = str(
                body.get("default_mode")
                or body.get("language")
                or current.get("default_mode")
                or current.get("language")
                or "en"
            ).strip()
        keycode = body.get("keycode")
        if keycode in (None, ""):
            keycode = keycode_for_binding(binding)
        try:
            keycode = int(keycode)
        except Exception:
            return False, "keycode is required for this binding", {}
        if keycode <= 0:
            return False, "keycode must be positive", {}

        combo = current.get("combo") or {}
        combo_update_fields = {
            "combo_enabled",
            "combo_keycode",
            "combo_short_mode",
            "combo_language",
            "combo_long_mode",
            "combo_long_press_seconds",
        }
        updated_combo = combo
        cfg_snapshot = self.config.snapshot()
        cfg_snapshot["modes"] = modes
        if any(k in body for k in combo_update_fields):
            combo_enabled = bool(body.get("combo_enabled", combo.get("enabled", True)))
            combo_keycode = body.get("combo_keycode")
            combo_keys = combo.get("keys") or [{"code": 2, "short_mode": "uk"}]
            combo_short_mode = str(
                body.get("combo_short_mode")
                or body.get("combo_language")
                or combo_keys[0].get("short_mode")
                or combo_keys[0].get("switch_language")
                or "uk"
            ).strip()
            combo_long_mode = str(body.get("combo_long_mode") or combo_keys[0].get("long_mode") or "").strip()
            if combo_keycode in (None, ""):
                combo_keycode = combo_keys[0].get("code", 2)
            try:
                combo_keycode = int(combo_keycode)
            except Exception:
                return False, "combo keycode must be an integer", {}
            try:
                combo_long_press = float(body.get("combo_long_press_seconds", combo.get("long_press_seconds", 0.5)))
            except Exception:
                return False, "long-press seconds must be numeric", {}
            combo_key = {
                "code": combo_keycode,
                "short_mode": combo_short_mode,
                "switch_language": language_for_mode(cfg_snapshot, combo_short_mode),
            }
            if combo_long_mode:
                combo_key["long_mode"] = combo_long_mode
            updated_combo = {
                **combo,
                "enabled": combo_enabled,
                "deadline_seconds": float(combo.get("deadline_seconds", 1.2)),
                "long_press_seconds": combo_long_press,
                "keys": [combo_key],
            }

        ok, reason, path = await self.shortcuts.install_trigger(trigger=trigger, binding=binding)
        if not ok:
            return False, reason, {"path": path}

        updated = dict(current)
        updated["binding"] = binding
        updated["default_mode"] = default_mode
        updated["language"] = language_for_mode(cfg_snapshot, default_mode)
        updated["stop_on_release_codes"] = [keycode]
        updated["combo"] = updated_combo
        triggers[trigger] = updated
        if modes_changed:
            self.config.set("modes", modes)
        self.config.set("triggers", triggers)
        return True, reason, {"path": path, "trigger": updated}

    async def update_combo_shortcuts(self, trigger: str, body: dict) -> tuple[bool, str, dict]:
        if not TRIGGER_NAME_RE.match(trigger):
            return False, "trigger name must use letters, numbers, dot, underscore, or dash", {}
        if self.state != State.IDLE:
            return False, "cannot change shortcuts while recording", {}
        triggers = self.config.get("triggers") or {}
        if trigger not in triggers:
            return False, f"unknown trigger {trigger}", {}
        raw_keys = body.get("keys")
        if not isinstance(raw_keys, list):
            return False, "keys must be a list", {}

        modes = self.config.get("modes") or {}
        script_prefix = f"shortcut_{trigger}_"
        keep_script_modes: set[str] = set()
        seen_codes: set[int] = set()
        normalized_keys: list[dict[str, Any]] = []
        stop_codes = {int(c) for c in (triggers[trigger].get("stop_on_release_codes") or [])}

        for raw in raw_keys:
            if not isinstance(raw, dict):
                return False, "each shortcut must be an object", {}
            try:
                code = int(raw.get("code"))
            except Exception:
                return False, "shortcut keycode must be an integer", {}
            if code <= 0:
                return False, "shortcut keycode must be positive", {}
            if code in stop_codes:
                return False, "shortcut key cannot be the default trigger key", {}
            if code in seen_codes:
                return False, f"duplicate shortcut keycode {code}", {}
            seen_codes.add(code)

            label = str(raw.get("label") or f"code {code}").strip()
            binding = str(raw.get("binding") or "").strip()
            kind = str(raw.get("type") or raw.get("kind") or "language").strip()
            language = str(raw.get("language") or "auto").strip() or "auto"
            if kind == "script":
                mode_name = f"{script_prefix}{code}"
                command = str(raw.get("command") or "").strip()
                modes[mode_name] = {
                    "label": f"{label} script",
                    "type": "script",
                    "language": language,
                    "command": command,
                    "json_stdin": False,
                }
                keep_script_modes.add(mode_name)
                normalized_keys.append({
                    "code": code,
                    "binding": binding,
                    "label": label,
                    "type": "script",
                    "language": language,
                    "short_mode": mode_name,
                })
            elif kind == "nostream":
                normalized_keys.append({
                    "code": code,
                    "binding": binding,
                    "label": label,
                    "type": "nostream",
                })
            else:
                normalized_keys.append({
                    "code": code,
                    "binding": binding,
                    "label": label,
                    "type": "language",
                    "language": language,
                    "short_mode": language,
                    "switch_language": language,
                })

        for mode_name in list(modes):
            if mode_name.startswith(script_prefix) and mode_name not in keep_script_modes:
                modes.pop(mode_name, None)

        current = triggers[trigger]
        combo = current.get("combo") or {}
        current["combo"] = {
            **combo,
            "enabled": bool(normalized_keys),
            "hold_grab_until_release": True,
            "deadline_seconds": float(combo.get("deadline_seconds", 1.2)),
            "keys": normalized_keys,
        }
        triggers[trigger] = current
        self.config.set("modes", modes)
        self.config.set("triggers", triggers)
        return True, "updated", {"keys": normalized_keys}

    async def delete_shortcut(self, trigger: str) -> tuple[bool, str]:
        triggers = self.config.get("triggers") or {}
        if trigger not in triggers:
            return False, f"unknown trigger {trigger}"
        if len(triggers) <= 1:
            return False, "cannot delete the last shortcut"
        if self.state != State.IDLE:
            return False, "cannot delete shortcuts while recording"
        triggers.pop(trigger, None)
        self.config.set("triggers", triggers)
        ok, reason = await self.shortcuts.remove_trigger(trigger=trigger)
        return ok, reason

    def status_snapshot(self) -> dict:
        recent = self.history.list()
        last_text = recent[0].text if recent else ""
        return {
            "state": self.state.value,
            "pid": self.pid,
            "uptime_seconds": int(time.time() - self.started_at),
            "current_trigger": self._current_trigger,
            "current_mode": self._current_mode,
            "current_mode_label": (self._current_mode_config or {}).get("label", self._current_mode),
            "current_mode_type": (self._current_mode_config or {}).get("type", ""),
            "current_language": self._current_language,
            "current_model": self.primary_server.loaded_model or self.config.get("default_model"),
            "primary_server": self.primary_server.status(),
            "live_preview": self._last_preview_text if self.state == State.RECORDING else "",
            "last_transcript": last_text,
            "history_count": len(recent),
            "retranslate": self.retranslator.state,
            "error": self._error_message,
            "device_names": self.input_supervisor.device_names() if self.input_supervisor else [],
            "combo_active": self._combo_active,
            "topbar": self.config.get("topbar") or {},
            "audio_input_device": self.config.get("audio_input_device") or "",
            "session_nostream": self._session_nostream,
        }

    # ----------------------------------------------------- internal helpers

    def _trigger_stop_codes(self, trigger: str) -> set[int]:
        triggers = self.config.get("triggers") or {}
        trig_cfg = triggers.get(trigger) or {}
        return set(int(c) for c in (trig_cfg.get("stop_on_release_codes") or [GRAVE_KEYCODE]))

    def _trigger_is_down(self, trigger: str) -> bool:
        return bool(self._trigger_stop_codes(trigger) & self._pressed_keycodes)

    def _trigger_is_same_hold(self, trigger: str, since: float) -> bool:
        for code in self._trigger_stop_codes(trigger):
            if code not in self._pressed_keycodes:
                continue
            # Same physical hold means the key went down before `since` and
            # has not come up since then. A new key-down after `since` is a
            # legitimate new dictation attempt, even if the previous key-up
            # timestamp is older.
            if self._last_key_down_at.get(code, 0.0) <= since and self._last_key_up_at.get(code, 0.0) <= since:
                return True
        return False

    async def _wait_trigger_down(self, trigger: str, *, timeout: float) -> bool:
        if self._trigger_is_down(trigger):
            return True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(0.01)
            if self._trigger_is_down(trigger):
                return True
        return False

    def _start_max_duration_timer(self) -> None:
        max_dur = float(self.config.get("maximum_recording_seconds", 240))
        if max_dur <= 0:
            return
        if self._max_duration_task and not self._max_duration_task.done():
            self._max_duration_task.cancel()
        async def _fire():
            try:
                await asyncio.sleep(max_dur)
                self.post(Event.MAX_DURATION)
            except asyncio.CancelledError:
                return
        self._max_duration_task = asyncio.create_task(_fire())

    def _cancel_max_duration_timer(self) -> None:
        if self._max_duration_task and not self._max_duration_task.done():
            self._max_duration_task.cancel()
        self._max_duration_task = None

    def _activate_combo(self, trigger: str) -> None:
        triggers = self.config.get("triggers") or {}
        trig_cfg = triggers.get(trigger) or {}
        combo = trig_cfg.get("combo") or {}
        if not combo.get("enabled", False):
            self._combo_active = False
            return
        deadline = float(combo.get("deadline_seconds", 1.2))
        hold_until_release = bool(combo.get("hold_grab_until_release", True))
        if not self.input_supervisor:
            return
        grabbed = self.input_supervisor.grab_for_combo()
        if grabbed == 0:
            log.info("combo grab: no matching devices; combo disabled this session")
            self._combo_active = False
            return
        self._combo_active = True
        safety_seconds = float(self.config.get("input_grab.maximum_seconds", 5))
        if hold_until_release:
            safety_seconds = max(
                safety_seconds,
                float(self.config.get("maximum_recording_seconds", 240)) + 2.0,
            )
        async def _safety_task():
            try:
                await asyncio.sleep(safety_seconds)
                if self._combo_active:
                    log.warning("grab safety timeout fired seconds=%s", safety_seconds)
                    self._deactivate_combo("safety")
            except asyncio.CancelledError:
                return
        self._grab_safety_task = asyncio.create_task(_safety_task())
        if hold_until_release:
            log.info("grab held until release trigger=%s", trigger)
            return

        async def _deadline_task():
            try:
                await asyncio.sleep(deadline)
                self._deactivate_combo("deadline")
            except asyncio.CancelledError:
                return
        self._combo_deadline_task = asyncio.create_task(_deadline_task())

    def _deactivate_combo(self, reason: str) -> None:
        if not self._combo_active and self.input_supervisor and not self.input_supervisor._grabbed:
            return
        log.info("combo end reason=%s", reason)
        self._combo_active = False
        if self._combo_deadline_task and not self._combo_deadline_task.done():
            self._combo_deadline_task.cancel()
        if self._grab_safety_task and not self._grab_safety_task.done():
            self._grab_safety_task.cancel()
        if self._combo_long_task and not self._combo_long_task.done():
            self._combo_long_task.cancel()
        if self.input_supervisor:
            self.input_supervisor.ungrab_all()


# =================================================================== handlers


def _clear_current_recording(d: Daemon) -> None:
    d._current_trigger = ""
    d._current_mode = ""
    d._current_mode_config = {}
    d._current_language = ""
    d._combo_key_down_at.clear()
    if d._combo_long_task and not d._combo_long_task.done():
        d._combo_long_task.cancel()
    d._release_requested_while_starting = False


def _resolve_mode(d: Daemon, mode_name: str) -> dict[str, Any]:
    return mode_config(d.config.snapshot(), mode_name)


def _set_mode_fields(d: Daemon, mode_name: str) -> None:
    cfg = _resolve_mode(d, mode_name)
    d._current_mode = mode_name
    d._current_mode_config = cfg
    d._current_language = str(cfg.get("language") or "auto")


async def _apply_mode(d: Daemon, mode_name: str | None, *, source: str) -> None:
    if not mode_name:
        return
    old_mode = d._current_mode
    old_type = (d._current_mode_config or {}).get("type")
    old_language = d._current_language
    _set_mode_fields(d, str(mode_name))
    new_type = d._current_mode_config.get("type")
    log.info(
        "mode switch source=%s %s/%s -> %s/%s language=%s",
        source,
        old_mode,
        old_type,
        d._current_mode,
        new_type,
        d._current_language,
    )
    if d._stream is None:
        return
    if old_mode == d._current_mode and old_language == d._current_language and old_type == new_type:
        return
    ok = await d._stream.clear_committed_from_app()
    if not ok:
        log.warning("mode switched but existing streamed text could not be removed")
    d._last_preview_text = ""
    d._stream.language_switched()
    if new_type == "script":
        return


def _mode_allows_app_output(d: Daemon) -> bool:
    if d._session_nostream:
        return False
    return (d._current_mode_config or {}).get("type") != "script"


async def _handle_start_from_idle(d: Daemon, *, trigger: str) -> State:
    d._start_queued = False
    triggers = d.config.get("triggers") or {}
    trig_cfg = triggers.get(trigger) or {}
    mode_name = trig_cfg.get("default_mode") or trig_cfg.get("language") or "en"
    d._current_trigger = trigger
    _set_mode_fields(d, mode_name)
    d._last_preview_text = ""
    d._error_message = ""
    d._release_requested_while_starting = False
    d._session_nostream = False

    # Start cue FIRST.
    d.tones.play_start()
    d._activate_combo(trigger)

    # Background warm of the whisper model.
    if d._warm_task is None or d._warm_task.done():
        d._schedule_warm(d.config.get("default_model"), reason="recording-start")

    if d._startup_task is not None and not d._startup_task.done():
        d._startup_task.cancel()
    d._startup_task = asyncio.create_task(_start_recording_effect(d, trigger))
    return State.STARTING


async def _start_recording_effect(d: Daemon, trigger: str) -> None:
    """Spawn recorder after STARTING is visible; then publish ready/stopped."""

    def _on_unexpected_exit():
        d.post(Event.RECORDER_EXITED_ERROR)

    if d.tones.enabled:
        delay = float(d.config.get("audio_cues.start_recording_delay_seconds", 0.08))
        if delay > 0:
            await asyncio.sleep(delay)
    if d._release_requested_while_starting or d.state == State.STOPPING:
        d.post(Event.RECORDER_STOPPED)
        return

    ok = await d.recorder.start(on_unexpected_exit=_on_unexpected_exit)
    if not ok:
        d.post(Event.RECORDER_FAILED)
        return
    if d._release_requested_while_starting or d.state == State.STOPPING:
        await d.recorder.stop()
        d.post(Event.RECORDER_STOPPED)
        return
    d._start_max_duration_timer()
    # Streaming session (preview is on regardless; app-output gated by config).
    if d._stream is not None:
        await d._stream.stop()
    if (d.config.get("live_preview") or {}).get("enabled", True) or (
        d.config.get("streaming") or {}
    ).get("app_output_enabled", False):

        def wav_provider() -> bytes:
            return d.recorder.read_bytes()

        def language_provider() -> str:
            return d._current_language

        def on_preview(text: str) -> None:
            d._last_preview_text = text

        d._stream = StreamingSession(
            config=d.config,
            transcriber=d.transcriber,
            server=d.primary_server,
            language_provider=language_provider,
            wav_provider=wav_provider,
            on_preview=on_preview,
            loop=asyncio.get_event_loop(),
            app_output_allowed_provider=lambda: _mode_allows_app_output(d),
        )
        d._stream.start()
    d.post(Event.RECORDER_READY)


async def _handle_recorder_ready(d: Daemon) -> State:
    return State.RECORDING


async def _handle_combo_starting(d: Daemon, *, mode: str | None = None, switch_language: str | None = None) -> State:
    await _apply_mode(d, mode or switch_language, source="combo-starting")
    return State.STARTING


async def _handle_recorder_failed(d: Daemon) -> State:
    d.tones.play_error()
    d._deactivate_combo("recorder_failed")
    d._cancel_max_duration_timer()
    d._error_message = "recorder failed to start"
    d.last_stop_at = time.monotonic()
    _clear_current_recording(d)
    return State.IDLE


async def _handle_release_starting(d: Daemon, *, trigger: str | None = None) -> State:
    d.tones.play_stop()
    d._release_requested_while_starting = True
    d._deactivate_combo("release-starting")
    d._cancel_max_duration_timer()
    if d._stream is not None:
        await d._stream.stop()
    return State.STOPPING


async def _handle_release_recording(d: Daemon, *, trigger: str) -> State:
    d.tones.play_stop()
    d._deactivate_combo("release")
    d._cancel_max_duration_timer()
    if d._stream is not None:
        await d._stream.stop()
    await d.recorder.stop()
    d.post(Event.RECORDER_STOPPED)
    return State.STOPPING


async def _handle_combo_recording(d: Daemon, *, mode: str | None = None, switch_language: str | None = None) -> State:
    await _apply_mode(d, mode or switch_language, source="combo")
    triggers = d.config.get("triggers") or {}
    combo = (triggers.get(d._current_trigger) or {}).get("combo") or {}
    if not bool(combo.get("hold_grab_until_release", True)):
        d._deactivate_combo("combo")
    return State.RECORDING


async def _handle_nostream(d: Daemon) -> State:
    """Toggle the current session into non-streaming (buffered) mode and
    backspace over anything already streamed into the focused app."""
    if d._session_nostream:
        return d.state
    d._session_nostream = True
    log.info("session switched to non-streaming via modifier")
    if d._stream is not None:
        ok = await d._stream.clear_committed_from_app()
        if not ok:
            log.warning("nostream switch could not remove existing streamed text")
        d._last_preview_text = ""
    return d.state


async def _handle_max_duration(d: Daemon) -> State:
    log.warning("max duration hit")
    d.tones.play_stop()
    d._deactivate_combo("max_duration")
    d._cancel_max_duration_timer()
    if d._stream is not None:
        await d._stream.stop()
    await d.recorder.stop()
    d.post(Event.RECORDER_STOPPED)
    return State.STOPPING_NO_PASTE


async def _handle_recorder_exited_error(d: Daemon) -> State:
    log.error("recorder exited unexpectedly")
    d.tones.play_error()
    d._deactivate_combo("recorder_exit")
    d._cancel_max_duration_timer()
    if d._stream is not None:
        await d._stream.stop()
    d.post(Event.RECORDER_STOPPED)
    return State.STOPPING_NO_PASTE


async def _handle_stop_recording(d: Daemon) -> State:
    d.tones.play_stop()
    d._deactivate_combo("stop")
    d._cancel_max_duration_timer()
    if d._stream is not None:
        await d._stream.stop()
    await d.recorder.stop()
    d.post(Event.RECORDER_STOPPED)
    return State.STOPPING


async def _handle_recorder_stopped(d: Daemon) -> State:
    asyncio.create_task(_transcribe_and_paste(d, paste_allowed=True))
    return State.TRANSCRIBING


async def _handle_recorder_stopped_nopaste(d: Daemon) -> State:
    asyncio.create_task(_transcribe_and_paste(d, paste_allowed=False))
    return State.TRANSCRIBING_NO_PASTE


async def _handle_transcript_ready(
    d: Daemon,
    *,
    paste_allowed: bool,
    text: str,
    raw: str,
    model: str,
    language: str,
    duration: float,
    audio: bytes,
    generation_ms: int = 0,
    mode: str = "",
    script: dict[str, Any] | None = None,
) -> State:
    item = HistoryItem(
        mode=mode or d._current_mode,
        language=language,
        trigger=d._current_trigger or "grave",
        duration_seconds=duration,
        generation_ms=generation_ms,
        text=text,
        raw_text=raw,
        model=model,
        audio_bytes=audio,
        script=script or {},
    )
    if not paste_allowed:
        item.pasted = False
        if script:
            item.failed_reason = "" if script.get("ok") else "script_failed"
        else:
            item.failed_reason = "no_paste"
        d.history.add(item)
        if script and not script.get("ok"):
            d.tones.play_error()
        d.last_stop_at = time.monotonic()
        _clear_current_recording(d)
        return State.IDLE
    if not text:
        d.history.add(item)
        d.last_stop_at = time.monotonic()
        _clear_current_recording(d)
        return State.IDLE
    d.history.add(item)
    asyncio.create_task(_paste_and_finalize(d, item, text))
    return State.PASTING


async def _handle_transcript_failed(d: Daemon, *, reason: str, audio: bytes, language: str, duration: float) -> State:
    item = HistoryItem(
        mode=d._current_mode,
        language=language,
        trigger=d._current_trigger or "grave",
        duration_seconds=duration,
        text="",
        raw_text="",
        model=d.primary_server.loaded_model or "",
        audio_bytes=audio,
        failed_reason=reason,
    )
    d.history.add(item)
    d.tones.play_error()
    d.last_stop_at = time.monotonic()
    _clear_current_recording(d)
    return State.IDLE


async def _handle_no_text(d: Daemon) -> State:
    d.last_stop_at = time.monotonic()
    _clear_current_recording(d)
    return State.IDLE


async def _handle_paste_done(d: Daemon, *, item_id: str, ok: bool) -> State:
    d.history.update(item_id, pasted=ok, failed_reason=("" if ok else "paste_failed"))
    if not ok:
        d.tones.play_error()
    d.last_stop_at = time.monotonic()
    _clear_current_recording(d)
    return State.IDLE


# ---------------------------------------------------------- effect coroutines


async def _run_script_mode(
    d: Daemon,
    *,
    mode: str,
    mode_cfg: dict[str, Any],
    text: str,
    raw: str,
    language: str,
    model: str,
    duration: float,
    generation_ms: int,
) -> dict[str, Any]:
    command = str(mode_cfg.get("command") or "").strip()
    result = {
        "mode": mode,
        "command": command,
        "ok": False,
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }
    if not command:
        result["stderr"] = "script command is empty"
        return result
    try:
        args = shlex.split(command)
    except ValueError as e:
        result["stderr"] = str(e)
        return result
    if not args:
        result["stderr"] = "script command is empty"
        return result
    env = os.environ.copy()
    env.update({
        "MYWHISPR_MODE": mode,
        "MYWHISPR_LANGUAGE": language,
        "MYWHISPR_MODEL": model,
        "MYWHISPR_DURATION": f"{duration:.3f}",
        "MYWHISPR_GENERATION_MS": str(generation_ms),
        "MYWHISPR_RAW_TEXT": raw,
    })
    payload = text
    if bool(mode_cfg.get("json_stdin", False)):
        payload = json.dumps({
            "text": text,
            "raw_text": raw,
            "language": language,
            "model": model,
            "duration_seconds": duration,
            "generation_ms": generation_ms,
            "mode": mode,
        }, ensure_ascii=False)
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except Exception as e:
        result["stderr"] = str(e)
        return result
    try:
        timeout = float(mode_cfg.get("timeout_seconds") or d.config.get("script_timeout_seconds", 45))
        stdout, stderr = await asyncio.wait_for(proc.communicate(payload.encode("utf-8")), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        result["stderr"] = "script timed out"
        return result
    result["returncode"] = proc.returncode
    result["stdout"] = stdout.decode("utf-8", "replace")[:4000]
    result["stderr"] = stderr.decode("utf-8", "replace")[:4000]
    result["ok"] = proc.returncode == 0
    return result


async def _transcribe_and_paste(d: Daemon, *, paste_allowed: bool) -> None:
    wav_bytes = b""
    rec_path = d.recorder.path
    if rec_path is not None and rec_path.exists():
        wav_bytes = d.recorder.read_bytes()
    duration = d.recorder.duration_seconds()
    language = d._current_language
    mode = d._current_mode
    mode_cfg = dict(d._current_mode_config or {})
    min_dur = float(d.config.get("minimum_recording_seconds", 0.25))
    if not wav_bytes or len(wav_bytes) < 44 + int(16000 * 2 * min_dur):
        d.recorder.cleanup()
        d.post(Event.NO_TEXT)
        return
    try:
        res = await d.transcriber.transcribe(
            d.primary_server,
            wav_bytes,
            language=language,
        )
    except Exception as e:
        log.exception("transcription failed")
        reason = str(e) or type(e).__name__
        d.recorder.cleanup()
        d.post(
            Event.TRANSCRIPT_FAILED,
            reason=reason,
            audio=wav_bytes,
            language=language,
            duration=duration,
        )
        return
    d.recorder.cleanup()
    generation_ms = max(0, int(round(res.elapsed_seconds * 1000)))
    script_result = None
    if (mode_cfg.get("type") == "script") and res.text:
        paste_allowed = False
        script_result = await _run_script_mode(
            d,
            mode=mode,
            mode_cfg=mode_cfg,
            text=res.text,
            raw=res.raw_text,
            language=language,
            model=res.model,
            duration=duration,
            generation_ms=generation_ms,
        )
    d.post(
        Event.TRANSCRIPT_READY,
        paste_allowed=paste_allowed,
        text=res.text,
        raw=res.raw_text,
        model=res.model,
        language=language,
        duration=duration,
        generation_ms=generation_ms,
        audio=wav_bytes,
        mode=mode,
        script=script_result,
    )


async def _paste_and_finalize(d: Daemon, item, text: str) -> None:
    # If streaming committed text into the focused app, reconcile.
    streaming_committed = ""
    if d._stream is not None:
        streaming_committed = d._stream.committed_text
    type_kwargs = {
        "type_key_delay_ms": int(d.config.get("type_key_delay_ms", paste_mod.DEFAULT_TYPE_KEY_DELAY_MS)),
        "direct_type_max_chars": int(d.config.get("direct_type_max_chars", 240)),
        "direct_type_ascii_only": bool(d.config.get("direct_type_ascii_only", True)),
    }
    if streaming_committed:
        max_rewrite = int((d.config.get("streaming") or {}).get("max_rewrite_chars", 180))
        diverge = d._stream.divergence_from_final(text) if d._stream else 0
        if diverge > max_rewrite:
            # Refuse destructive rewrite; leave clipboard with full text, no paste.
            log.warning("final divergence %d > %d; refusing rewrite", diverge, max_rewrite)
            # Stash final on clipboard for manual paste.
            await paste_mod.copy_text(text)
            d.tones.play_error()
            d.post(Event.PASTE_DONE, item_id=item.id, ok=False)
            return
        # Reconcile via stream_replace (backspace divergence + paste remainder).
        ok = await paste_mod.stream_replace(
            previous=streaming_committed,
            new=text,
            settle_seconds=float(d.config.get("clipboard_settle_seconds", 0.03)),
            max_rewrite_chars=max_rewrite,
            consume_timeout=float(d.config.get("clipboard_paste_consume_timeout_seconds", 0.8)),
            key_delay_ms=int(d.config.get("paste_key_delay_ms", 18)),
            **type_kwargs,
        )
        d.post(Event.PASTE_DONE, item_id=item.id, ok=ok)
        return
    # Standard path: paste final text.
    ok = await paste_mod.paste_final(
        text,
        settle_seconds=float(d.config.get("clipboard_settle_seconds", 0.03)),
        consume_timeout=float(d.config.get("clipboard_paste_consume_timeout_seconds", 0.8)),
        key_delay_ms=int(d.config.get("paste_key_delay_ms", 18)),
        **type_kwargs,
    )
    d.post(Event.PASTE_DONE, item_id=item.id, ok=ok)


# ======================================================== dispatch table

TRANSITIONS: dict[tuple[State, Event], Any] = {
    (State.IDLE, Event.START): _handle_start_from_idle,
    (State.STARTING, Event.RECORDER_READY): _handle_recorder_ready,
    (State.STARTING, Event.RECORDER_FAILED): _handle_recorder_failed,
    (State.STARTING, Event.RECORDER_EXITED_ERROR): _handle_recorder_failed,
    (State.STARTING, Event.RELEASE): _handle_release_starting,
    (State.STARTING, Event.STOP): _handle_release_starting,
    (State.STARTING, Event.COMBO): _handle_combo_starting,
    (State.STARTING, Event.NOSTREAM): _handle_nostream,
    (State.RECORDING, Event.RELEASE): _handle_release_recording,
    (State.RECORDING, Event.COMBO): _handle_combo_recording,
    (State.RECORDING, Event.NOSTREAM): _handle_nostream,
    (State.RECORDING, Event.MAX_DURATION): _handle_max_duration,
    (State.RECORDING, Event.RECORDER_EXITED_ERROR): _handle_recorder_exited_error,
    (State.RECORDING, Event.STOP): _handle_stop_recording,
    (State.STOPPING, Event.RECORDER_STOPPED): _handle_recorder_stopped,
    (State.STOPPING, Event.RECORDER_FAILED): _handle_recorder_failed,
    (State.STOPPING, Event.RECORDER_EXITED_ERROR): _handle_recorder_failed,
    (State.STOPPING_NO_PASTE, Event.RECORDER_STOPPED): _handle_recorder_stopped_nopaste,
    (State.TRANSCRIBING, Event.TRANSCRIPT_READY): _handle_transcript_ready,
    (State.TRANSCRIBING, Event.TRANSCRIPT_FAILED): _handle_transcript_failed,
    (State.TRANSCRIBING, Event.NO_TEXT): _handle_no_text,
    (State.TRANSCRIBING_NO_PASTE, Event.TRANSCRIPT_READY): _handle_transcript_ready,
    (State.TRANSCRIBING_NO_PASTE, Event.TRANSCRIPT_FAILED): _handle_transcript_failed,
    (State.TRANSCRIBING_NO_PASTE, Event.NO_TEXT): _handle_no_text,
    (State.PASTING, Event.PASTE_DONE): _handle_paste_done,
}
