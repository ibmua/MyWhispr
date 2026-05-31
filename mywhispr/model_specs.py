from __future__ import annotations

import os
from pathlib import Path
from typing import Any


WHISPER_CPP_BACKENDS = {"whisper.cpp", "whisper_cpp", "whisper"}
GPU_BACKENDS = {
    "qwen_asr",
    "transformers_tdt",
    "transformers_speech_seq2seq",
    "seamless_m4t_v2",
    "cohere_asr",
    "nemo_asr",
    "nemo_salm",
}
EXTERNAL_API_BACKENDS = {"external_api"}
MODEL_BACKENDS = {"whisper.cpp"} | GPU_BACKENDS | EXTERNAL_API_BACKENDS


HF_GPU_MODEL_OPTIONS: dict[str, dict[str, Any]] = {
    "qwen3-asr-1.7b": {
        "backend": "qwen_asr",
        "repo_id": "Qwen/Qwen3-ASR-1.7B",
        "device": "cuda:0",
        "dtype": "bfloat16",
        "local_files_only": True,
        "max_inference_batch_size": 8,
        "max_new_tokens": 256,
        "label": "Qwen3 ASR 1.7B",
        "description": "High accuracy",
        "subdescription": "Qwen GPU",
        "languages": [
            "ar", "cs", "da", "de", "el", "en", "es", "fa", "fi", "fil",
            "fr", "hi", "hu", "id", "it", "ja", "ko", "mk", "ms", "nl",
            "pl", "pt", "ro", "ru", "sv", "th", "tr", "vi", "yue", "zh",
        ],
        "language_format": "name",
        "live_preview": True,
        "install_hint": "pip install -U qwen-asr torch",
    },
    "parakeet-tdt-0.6b-v3": {
        "backend": "transformers_tdt",
        "repo_id": "nvidia/parakeet-tdt-0.6b-v3",
        "device": "cuda:0",
        "dtype": "auto",
        "local_files_only": True,
        "label": "Parakeet TDT 0.6B v3",
        "description": "Fast multilingual",
        "subdescription": "NVIDIA TDT",
        "languages": [
            "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr",
            "hr", "hu", "it", "lt", "lv", "mt", "nl", "pl", "pt", "ro",
            "ru", "sk", "sl", "sv", "uk",
        ],
        "live_preview": True,
        "install_hint": "pip install -U torch transformers",
    },
    "granite-speech-4.1-2b": {
        "backend": "transformers_speech_seq2seq",
        "repo_id": "ibm-granite/granite-speech-4.1-2b",
        "device": "cuda:0",
        "dtype": "bfloat16",
        "local_files_only": True,
        "max_new_tokens": 200,
        "label": "Granite Speech 4.1 2B",
        "description": "Multilingual",
        "subdescription": "IBM Granite",
        "languages": ["en", "fr", "de", "es", "pt", "ja"],
        "fallback_language": "en",
        "prompt": "<|audio|>transcribe the speech in {language} with proper punctuation and capitalization.",
        "live_preview": True,
        "install_hint": "pip install -U torch transformers torchaudio soundfile",
    },
    "cohere-transcribe-03-2026": {
        "backend": "cohere_asr",
        "repo_id": "CohereLabs/cohere-transcribe-03-2026",
        "device": "cuda:0",
        "dtype": "auto",
        "local_files_only": True,
        "trust_remote_code": False,
        "max_new_tokens": 256,
        "label": "Cohere Transcribe 03-2026",
        "description": "Long-form ASR",
        "subdescription": "Cohere",
        "languages": ["en", "de", "es", "fr", "it", "ja", "ko", "nl", "pl", "pt", "ru", "tr", "zh"],
        "fallback_language": "en",
        "live_preview": True,
        "install_hint": "pip install -U 'transformers>=5.4.0' torch soundfile librosa sentencepiece protobuf",
    },
    "canary-qwen-2.5b": {
        "backend": "nemo_salm",
        "repo_id": "nvidia/canary-qwen-2.5b",
        "device": "cuda:0",
        "dtype": "bfloat16",
        "local_files_only": True,
        "max_new_tokens": 128,
        "label": "Canary Qwen 2.5B",
        "description": "English ASR",
        "subdescription": "NVIDIA NeMo",
        "languages": ["en"],
        "fallback_language": "en",
        "prompt": "Transcribe the following:",
        "live_preview": True,
        "install_hint": "pip install 'nemo_toolkit[asr,tts] @ git+https://github.com/NVIDIA/NeMo.git'",
    },
    "canary-1b-v2": {
        "backend": "nemo_asr",
        "repo_id": "nvidia/canary-1b-v2",
        "device": "cuda:0",
        "dtype": "bfloat16",
        "local_files_only": True,
        "label": "Canary 1B v2",
        "description": "25-language ASR",
        "subdescription": "NVIDIA NeMo",
        "languages": [
            "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de",
            "el", "hu", "it", "lv", "lt", "mt", "pl", "pt", "ro", "sk",
            "sl", "es", "sv", "ru", "uk",
        ],
        "fallback_language": "en",
        "nemo_language_kwargs": True,
        "nemo_batch_size": 16,
        "nemo_timestamps": False,
        "decode_beam_size": 1,
        "live_preview": True,
        "install_hint": "pip install 'nemo_toolkit[asr,tts] @ git+https://github.com/NVIDIA/NeMo.git'",
    },
    "seamless-m4t-v2-large": {
        "backend": "seamless_m4t_v2",
        "repo_id": "facebook/seamless-m4t-v2-large",
        "device": "cuda:0",
        "dtype": "float16",
        "local_files_only": True,
        "max_new_tokens": 256,
        "label": "Seamless M4T v2 Large",
        "description": "Massively multilingual",
        "subdescription": "Meta SeamlessM4T",
        "languages": [
            "ar", "bg", "cs", "da", "de", "el", "en", "es", "et", "fa",
            "fi", "fr", "hi", "hr", "hu", "id", "it", "ja", "ko", "lt",
            "lv", "mt", "nl", "pl", "pt", "ro", "ru", "sk", "sl", "sv",
            "tr", "uk", "vi", "yue", "zh",
        ],
        "fallback_language": "en",
        "live_preview": True,
        "install_hint": "pip install -U transformers sentencepiece torch torchaudio",
    },
    "qwen3-asr-0.6b": {
        "backend": "qwen_asr",
        "repo_id": "Qwen/Qwen3-ASR-0.6B",
        "device": "cuda:0",
        "dtype": "bfloat16",
        "local_files_only": True,
        "max_inference_batch_size": 16,
        "max_new_tokens": 256,
        "label": "Qwen3 ASR 0.6B",
        "description": "Fast compact",
        "subdescription": "Qwen GPU",
        "languages": [
            "ar", "cs", "da", "de", "el", "en", "es", "fa", "fi", "fil",
            "fr", "hi", "hu", "id", "it", "ja", "ko", "mk", "ms", "nl",
            "pl", "pt", "ro", "ru", "sv", "th", "tr", "vi", "yue", "zh",
        ],
        "language_format": "name",
        "live_preview": True,
        "install_hint": "pip install -U qwen-asr torch",
    },
}

EXTERNAL_API_MODEL_OPTIONS: dict[str, dict[str, Any]] = {
    "gpt-4o-transcribe": {
        "backend": "external_api",
        "provider": "OpenAI",
        "api_base_url": "https://api.openai.com/v1",
        "endpoint": "/audio/transcriptions",
        "api_model": "gpt-4o-transcribe",
        "api_key_env": "OPENAI_API_KEY",
        "label": "GPT-4o Transcribe",
        "description": "External API",
        "subdescription": "OpenAI",
        "languages": ["en", "uk"],
        "live_preview": False,
        "install_hint": "Set OPENAI_API_KEY before selecting this model.",
    },
    "gpt-4o-mini-transcribe": {
        "backend": "external_api",
        "provider": "OpenAI",
        "api_base_url": "https://api.openai.com/v1",
        "endpoint": "/audio/transcriptions",
        "api_model": "gpt-4o-mini-transcribe",
        "api_key_env": "OPENAI_API_KEY",
        "label": "GPT-4o mini Transcribe",
        "description": "External API",
        "subdescription": "OpenAI mini",
        "languages": ["en", "uk"],
        "live_preview": False,
        "install_hint": "Set OPENAI_API_KEY before selecting this model.",
    },
}

BUILTIN_MODEL_OPTIONS: dict[str, dict[str, Any]] = {
    **HF_GPU_MODEL_OPTIONS,
    **EXTERNAL_API_MODEL_OPTIONS,
}


LANGUAGE_NAMES = {
    "ar": "Arabic",
    "bg": "Bulgarian",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "fa": "Persian",
    "fi": "Finnish",
    "fil": "Filipino",
    "fr": "French",
    "hi": "Hindi",
    "hr": "Croatian",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mk": "Macedonian",
    "ms": "Malay",
    "mt": "Maltese",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "yue": "Cantonese",
    "zh": "Chinese",
}

WHISPER_LANGUAGE_CODES = [
    "en", "uk", "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo", "br", "bs",
    "ca", "cs", "cy", "da", "de", "el", "es", "et", "eu", "fa", "fi", "fo", "fr", "gl",
    "gu", "ha", "haw", "he", "hi", "hr", "ht", "hu", "hy", "id", "is", "it", "ja", "jw",
    "ka", "kk", "km", "kn", "ko", "la", "lb", "ln", "lo", "lt", "lv", "mg", "mi", "mk",
    "ml", "mn", "mr", "ms", "mt", "my", "ne", "nl", "nn", "no", "oc", "pa", "pl", "ps",
    "pt", "ro", "ru", "sa", "sd", "si", "sk", "sl", "sn", "so", "sq", "sr", "su", "sv",
    "sw", "ta", "te", "tg", "th", "tk", "tl", "tr", "tt", "ur", "uz", "vi", "yi", "yo",
    "yue", "zh",
]


def normalize_backend(value: Any) -> str:
    backend = str(value or "whisper.cpp").strip().lower().replace("-", "_")
    if backend in {"whisper.cpp", "whisper_cpp", "whisper"}:
        return "whisper.cpp"
    if backend in {"qwen", "qwen3_asr"}:
        return "qwen_asr"
    if backend in {"parakeet", "tdt"}:
        return "transformers_tdt"
    if backend in {"granite", "speech_seq2seq"}:
        return "transformers_speech_seq2seq"
    if backend in {"seamless", "seamless_m4t", "seamlessm4t", "seamless_m4t_v2"}:
        return "seamless_m4t_v2"
    if backend in {"cohere", "cohere_transcribe"}:
        return "cohere_asr"
    if backend in {"canary", "salm"}:
        return "nemo_salm"
    if backend in {
        "api",
        "external",
        "external_api",
        "openai",
        "openai_api",
        "openai_compatible",
        "openai_transcriptions",
    }:
        return "external_api"
    return backend


def normalize_model_spec(name: str, raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return {
            "name": name,
            "backend": "whisper.cpp",
            "path": raw,
            "label": name,
            "description": "",
            "subdescription": None,
            "live_preview": True,
        }
    if not isinstance(raw, dict):
        return {
            "name": name,
            "backend": "invalid",
            "label": name,
            "description": "Invalid config",
            "subdescription": None,
            "live_preview": False,
        }
    spec = dict(raw)
    spec["name"] = name
    spec["backend"] = normalize_backend(spec.get("backend"))
    spec.setdefault("label", name)
    spec.setdefault("description", "")
    spec.setdefault("subdescription", None)
    spec.setdefault("live_preview", spec.get("backend") != "external_api")
    if spec["backend"] == "whisper.cpp" and "path" not in spec:
        spec["path"] = spec.get("model_path") or spec.get("file") or ""
    if spec["backend"] == "external_api":
        spec.setdefault("provider", "External API")
        spec.setdefault("api_base_url", spec.get("base_url") or "https://api.openai.com/v1")
        spec.setdefault("endpoint", spec.get("api_path") or "/audio/transcriptions")
        spec.setdefault("api_model", spec.get("model_id") or spec.get("model") or name)
        spec.setdefault("api_key_env", "OPENAI_API_KEY")
        spec.setdefault("api_key_required", True)
        spec.setdefault("response_format", "json")
        spec.setdefault("timeout_seconds", 120.0)
        spec.setdefault("description", "External transcription API")
    elif spec["backend"] != "whisper.cpp":
        spec.setdefault("local_files_only", True)
    return spec


def model_backend(models: dict[str, Any], name: str | None) -> str:
    if not name:
        return "whisper.cpp"
    return normalize_model_spec(name, (models or {}).get(name)).get("backend", "whisper.cpp")


def is_gpu_model(spec: dict[str, Any]) -> bool:
    return spec.get("backend") in GPU_BACKENDS


def is_external_api_model(spec: dict[str, Any]) -> bool:
    return spec.get("backend") in EXTERNAL_API_BACKENDS


def model_source(spec: dict[str, Any]) -> str:
    if spec.get("backend") == "external_api":
        base = str(spec.get("api_base_url") or "").rstrip("/")
        endpoint = str(spec.get("endpoint") or "").lstrip("/")
        return f"{base}/{endpoint}" if base and endpoint else base or endpoint
    return str(spec.get("local_path") or spec.get("repo_id") or spec.get("path") or "")


def external_api_key_configured(spec: dict[str, Any]) -> bool:
    if not bool(spec.get("api_key_required", True)):
        return True
    if str(spec.get("api_key") or "").strip():
        return True
    env_name = str(spec.get("api_key_env") or "").strip()
    if env_name and os.environ.get(env_name):
        return True
    key_file = str(spec.get("api_key_file") or "").strip()
    if key_file and Path(key_file).is_file():
        try:
            return bool(Path(key_file).read_text().strip())
        except OSError:
            return False
    return False


def hf_cache_path(repo_id: str) -> Path:
    hub = os.environ.get("HF_HUB_CACHE")
    if hub:
        root = Path(hub)
    else:
        root = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    return root / ("models--" + repo_id.replace("/", "--"))


def hf_cache_state(spec: dict[str, Any]) -> bool | None:
    repo_id = spec.get("repo_id")
    if not repo_id:
        return None
    root = hf_cache_path(str(repo_id))
    snapshots = root / "snapshots"
    return snapshots.is_dir() and any(snapshots.iterdir())


def model_availability(spec: dict[str, Any]) -> dict[str, Any]:
    backend = spec.get("backend")
    if backend == "external_api":
        ok = bool(str(spec.get("api_base_url") or "").strip()) and bool(str(spec.get("api_model") or "").strip())
        return {
            "exists": ok,
            "selectable": ok and external_api_key_configured(spec),
            "cached": None,
            "size_bytes": 0,
            "api_key_configured": external_api_key_configured(spec),
            "api_key_required": bool(spec.get("api_key_required", True)),
        }
    if backend == "whisper.cpp":
        path = Path(str(spec.get("path") or ""))
        exists = path.is_file()
        size = path.stat().st_size if exists else 0
        return {"exists": exists, "selectable": exists, "cached": None, "size_bytes": size}
    local_path = spec.get("local_path")
    if local_path:
        path = Path(str(local_path))
        exists = path.exists()
        return {"exists": exists, "selectable": exists, "cached": exists, "size_bytes": 0}
    cached = hf_cache_state(spec)
    # Hugging Face options stay selectable even before the weights are cached:
    # selecting them should update default_model and surface the precise worker
    # error/dependency hint instead of making the UI look immutable.
    return {"exists": True, "selectable": True, "cached": cached, "size_bytes": 0}


def default_languages_for_spec(spec: dict[str, Any]) -> list[str]:
    if spec.get("backend") != "whisper.cpp":
        return []
    path = str(spec.get("path") or "").lower()
    name = str(spec.get("name") or "").lower()
    if ".en" in Path(path).name or name.endswith(".en") or ".en-" in name:
        return ["en"]
    return WHISPER_LANGUAGE_CODES


def public_model_card(name: str, raw: Any) -> dict[str, Any]:
    spec = normalize_model_spec(name, raw)
    available = model_availability(spec)
    languages = spec.get("languages") or default_languages_for_spec(spec)
    card = {
        "name": name,
        "label": spec.get("label") or name,
        "backend": spec.get("backend"),
        "path": model_source(spec),
        "repo_id": spec.get("repo_id") or "",
        "description": spec.get("description") or "",
        "subdescription": spec.get("subdescription"),
        "languages": languages,
        "install_hint": spec.get("install_hint") or "",
        "live_preview": bool(spec.get("live_preview", False)),
        "provider": spec.get("provider") or "",
        "api_base_url": spec.get("api_base_url") or "",
        "endpoint": spec.get("endpoint") or "",
        "api_model": spec.get("api_model") or "",
        "api_key_env": spec.get("api_key_env") or "",
        "response_format": spec.get("response_format") or "",
        "builtin": name in BUILTIN_MODEL_OPTIONS,
    }
    card.update(available)
    return card
