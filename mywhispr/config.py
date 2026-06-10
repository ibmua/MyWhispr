from __future__ import annotations

import copy
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .model_specs import BUILTIN_MODEL_OPTIONS, MODEL_BACKENDS, normalize_model_spec

log = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "runtime_dir": None,
    "socket_path": None,
    "default_model": "parakeet-tdt-0.6b-v3",
    "preload_default_model_on_startup": True,
    "models": copy.deepcopy(BUILTIN_MODEL_OPTIONS),
    "gpu_asr_python": "",
    "audio_input_device": "",
    "whisper_server_binary": "",
    "whisper_host": "127.0.0.1",
    "whisper_port": 18178,
    "whisper_idle_shutdown_seconds": 0,
    "whisper_startup_timeout_seconds": 180,
    "alternate_whisper_port": 18179,
    "web": {"host": "127.0.0.1", "port": 16666},
    "transcription_api": {
        "enabled": False,
        "host": "0.0.0.0",
        "port": 18180,
        "api_key": "",
        "advertised_host": "",
        "advertised_scheme": "http",
        "model_name": "parakeet-tdt-0.6b-v3",
    },
    "history_limit": 20,
    "maximum_recording_seconds": 240,
    "stop_timeout_seconds": 3.0,
    "start_cooldown_seconds": 0.2,
    "append_trailing_space": True,
    "require_physical_trigger_down": True,
    "physical_start_fallback_delay_seconds": 0.08,
    "snapshot_leading_silence_seconds": 0.25,
    "minimum_recording_seconds": 0.25,
    "clipboard_settle_seconds": 0.03,
    "clipboard_paste_consume_timeout_seconds": 0.8,
    "paste_key_delay_ms": 18,
    "type_key_delay_ms": 0,
    "direct_type_max_chars": 240,
    "direct_type_ascii_only": True,
    "prefer_clipboard_paste": True,
    "script_timeout_seconds": 45,
    "modes": {
        "uk": {"label": "Ukrainian", "type": "language", "language": "uk"},
        "en": {"label": "English", "type": "language", "language": "en"},
    },
    "live_preview": {
        "enabled": True,
        "paste_into_app": False,
        "cancel_on_release": True,
        "interval_seconds": 0.8,
        "initial_delay_seconds": 1.2,
    },
    "topbar": {
        "enabled": True,
        "max_words": 10,
        "show_when_idle": True,
        "poll_interval_ms": 600,
    },
    "streaming": {
        "app_output_enabled": True,
        "interval_seconds": 0.45,
        "initial_delay_seconds": 0.35,
        "stable_lag_seconds": 0.35,
        "max_rewrite_chars": 180,
        "rewrite_backspace_confirmations": 2,
        "initial_commit_confirmations": 1,
        "crystallization_enabled": True,
        "crystallization_lag_seconds": 24,
        "crystallization_required_updates": 2,
        "cancel_streaming_on_release": True,
        "pause_gate_enabled": True,
        "pause_gate_min_silence_seconds": 0.25,
        "pause_gate_max_rms": 90.0,
        "pause_gate_relative_rms_ratio": 0.45,
        "pause_gate_frame_seconds": 0.05,
        "new_audio_gate_min_rms": 50.0,
    },
    "hallucination_filter": {
        "enabled": True,
        "silence_rms_threshold": 90,
        "phrases": {
            "en": [
                "Thank you for watching.",
                "Thank you.",
                "Thanks for watching!",
                "Thanks.",
                "Transcription by CastingWords",
                "Transcription by ESO",
                "Translation by",
                "I hope you enjoyed this video.",
                "Bye.",
                "Subscribe.",
            ],
            "uk": [
                "Дякую за перегляд!",
                "Дякую.",
                "Підписуйтесь на канал.",
            ],
        },
        "always_strip_phrases": [
            "Transcription by CastingWords",
            "Transcription by ESO",
            "Translation by",
        ],
    },
    "triggers": {
        "grave": {
            "binding": "grave",
            "default_mode": "en",
            "language": "en",
            "stop_on_release_codes": [41],
            "combo": {
                "enabled": True,
                "hold_grab_until_release": True,
                "deadline_seconds": 1.2,
                "long_press_seconds": 0.5,
                "long_press_commit_delay_seconds": 0.18,
                "keys": [
                    {"code": 15, "binding": "Tab", "label": "Tab", "type": "nostream"},
                ],
            },
        }
    },
    "input_grab": {
        "maximum_seconds": 5,
        "device_name_patterns": [],
        "exclude_device_name_patterns": ["ydotoold virtual device"],
    },
    "audio_cues": {"enabled": True, "volume": 0.85, "start_recording_delay_seconds": 0.08},
    "custom_words": [],
    "language_prompts": {
        "uk": (
            "Транскрипція українською. Дотримуйся літературної української, "
            "уникай російських форм та русизмів."
        ),
        "en": "English transcription.",
    },
    "debug": {"log_transcripts": False, "retained_recordings": 0},
}


LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class ConfigError(Exception):
    pass


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _runtime_defaults() -> dict[str, Any]:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "MyWhispr"
        return {"runtime_dir": str(base / "runtime"), "socket_path": str(base / "control.sock")}
    uid = os.getuid()
    rd = f"/run/user/{uid}/mywhispr"
    sock = f"/run/user/{uid}/mywhispr.sock"
    return {"runtime_dir": rd, "socket_path": sock}


def load_config(path: Path) -> "Config":
    raw: dict[str, Any] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            raise ConfigError(f"failed to parse {path}: {e}") from e
    merged = _deep_merge(DEFAULT_CONFIG, _runtime_defaults())
    merged = _deep_merge(merged, raw)
    _normalize(merged)
    _validate(merged)
    return Config(path, merged)


def mode_config(cfg: dict, mode_name: str) -> dict[str, Any]:
    modes = cfg.get("modes") or {}
    raw = modes.get(mode_name)
    if isinstance(raw, dict):
        out = copy.deepcopy(raw)
    else:
        out = {"label": mode_name, "type": "language", "language": mode_name}
    out.setdefault("label", mode_name)
    out.setdefault("type", "language")
    if out.get("type") == "script":
        out.setdefault("language", "auto")
        out.setdefault("command", "")
    else:
        out["type"] = "language"
        out.setdefault("language", mode_name)
    return out


def language_for_mode(cfg: dict, mode_name: str) -> str:
    return str(mode_config(cfg, mode_name).get("language") or "auto")


def _normalize(cfg: dict) -> None:
    modes = cfg.setdefault("modes", {})
    for name, label in (("uk", "Ukrainian"), ("en", "English")):
        modes.setdefault(name, {"label": label, "type": "language", "language": name})
    triggers = cfg.get("triggers") or {}
    for trig_cfg in triggers.values():
        default_mode = str(trig_cfg.get("default_mode") or trig_cfg.get("language") or "en")
        trig_cfg["default_mode"] = default_mode
        trig_cfg["language"] = language_for_mode(cfg, default_mode)
        combo = trig_cfg.get("combo") or {}
        combo.setdefault("long_press_seconds", 0.5)
        keys = combo.get("keys") or []
        for key in keys:
            if key.get("type") in {"nostream", "lowercase_initial"}:
                continue
            if "short_mode" not in key:
                key["short_mode"] = key.get("switch_language") or default_mode
            key["switch_language"] = language_for_mode(cfg, str(key.get("short_mode") or default_mode))
        combo["keys"] = keys
        trig_cfg["combo"] = combo


def _validate(cfg: dict) -> None:
    binary = cfg.get("whisper_server_binary") or ""
    models = cfg.get("models", {}) or {}
    normalized_models = {name: normalize_model_spec(name, raw) for name, raw in models.items()}
    needs_whisper_binary = any(spec.get("backend") == "whisper.cpp" for spec in normalized_models.values())
    binary_usable = bool(binary) and Path(binary).is_file() and os.access(binary, os.X_OK)
    if needs_whisper_binary and not binary_usable:
        # whisper.cpp models stay listed but unselectable; GPU and external API
        # models must keep working without a whisper-server binary installed.
        log.warning("whisper_server_binary missing or not executable (%r); whisper.cpp models disabled", binary)
    default_model = cfg.get("default_model") or ""
    if default_model and default_model not in models:
        log.warning("default_model %r not in models; clearing", default_model)
        cfg["default_model"] = ""
    for name, spec in normalized_models.items():
        backend = spec.get("backend")
        if backend == "whisper.cpp":
            path = spec.get("path") or ""
            if path and not Path(path).is_file():
                log.warning("whisper.cpp model %r is not present: %s", name, path)
        elif backend == "external_api":
            url = str(spec.get("api_base_url") or "").strip()
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ConfigError(f"external API model {name!r} has invalid api_base_url {url!r}")
            if bool(spec.get("send_model", True)) and not str(spec.get("api_model") or "").strip():
                raise ConfigError(f"external API model {name!r} is missing api_model")
        elif backend not in MODEL_BACKENDS:
            raise ConfigError(f"model {name!r} has unsupported backend {backend!r}")
    for host_key in ("whisper_host",):
        host = cfg.get(host_key)
        if host not in LOOPBACK_HOSTS:
            raise ConfigError(f"{host_key} must be loopback, got {host!r}")
    web_host = cfg.get("web", {}).get("host")
    if web_host not in LOOPBACK_HOSTS:
        raise ConfigError(f"web.host must be loopback, got {web_host!r}")
    api_cfg = cfg.setdefault("transcription_api", {})
    api_enabled = bool(api_cfg.get("enabled", False))
    api_host = str(api_cfg.get("host") or "0.0.0.0")
    api_key = str(api_cfg.get("api_key") or "")
    if api_enabled and not api_key:
        raise ConfigError("transcription_api.api_key is required when transcription_api.enabled is true")
    if not api_host.strip():
        raise ConfigError("transcription_api.host is required")
    api_scheme = str(api_cfg.get("advertised_scheme") or "http")
    if api_scheme not in {"http", "https"}:
        raise ConfigError("transcription_api.advertised_scheme must be http or https")
    api_port = int(api_cfg.get("port", 18180))
    if not 1 <= api_port <= 65535:
        raise ConfigError(f"transcription_api.port must be in [1, 65535], got {api_port}")
    cd = cfg.get("start_cooldown_seconds", 0.2)
    if not 0.1 <= cd <= 0.4:
        log.warning("start_cooldown_seconds %s outside [0.1, 0.4]; clamping", cd)
        cfg["start_cooldown_seconds"] = max(0.1, min(0.4, cd))
    audio_cues = cfg.setdefault("audio_cues", {})
    volume = float(audio_cues.get("volume", 0.85))
    if not 0.0 <= volume <= 1.0:
        log.warning("audio_cues.volume %s outside [0.0, 1.0]; clamping", volume)
        audio_cues["volume"] = max(0.0, min(1.0, volume))
    start_delay = float(audio_cues.get("start_recording_delay_seconds", 0.08))
    if not 0.0 <= start_delay <= 0.25:
        log.warning(
            "audio_cues.start_recording_delay_seconds %s outside [0.0, 0.25]; clamping",
            start_delay,
        )
        audio_cues["start_recording_delay_seconds"] = max(0.0, min(0.25, start_delay))


def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class Config:
    """Mutable, thread-safe-ish config wrapper. Writes back atomically."""

    def __init__(self, path: Path, data: dict) -> None:
        self.path = path
        self._data = data
        self._lock = threading.RLock()
        self._listeners: list = []

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            cur: Any = self._data
            for part in key.split("."):
                if not isinstance(cur, dict) or part not in cur:
                    return default
                cur = cur[part]
            return copy.deepcopy(cur)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            next_data = copy.deepcopy(self._data)
            parts = key.split(".")
            cur: dict = next_data
            for p in parts[:-1]:
                if p not in cur or not isinstance(cur[p], dict):
                    cur[p] = {}
                cur = cur[p]
            cur[parts[-1]] = value
            _normalize(next_data)
            _validate(next_data)
            self._data = next_data
            atomic_write_json(self.path, self._data)
            data = copy.deepcopy(self._data)
        for cb in list(self._listeners):
            try:
                cb(key, data)
            except Exception:
                log.exception("config listener failed")

    def reload_from_disk(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            log.error("config reload failed: %s", e)
            return
        merged = _deep_merge(DEFAULT_CONFIG, _runtime_defaults())
        merged = _deep_merge(merged, raw)
        _normalize(merged)
        try:
            _validate(merged)
        except ConfigError as e:
            log.error("config reload rejected: %s", e)
            return
        with self._lock:
            self._data = merged
            data = copy.deepcopy(self._data)
        for cb in list(self._listeners):
            try:
                cb("__reload__", data)
            except Exception:
                log.exception("config listener failed")

    def subscribe(self, cb) -> None:
        self._listeners.append(cb)
