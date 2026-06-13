from __future__ import annotations

import base64
import gc
import io
import json
import logging
import os
import sys
import tempfile
import traceback
import wave
from pathlib import Path
from typing import Any

from .model_specs import LANGUAGE_NAMES, model_source, normalize_model_spec


log = logging.getLogger(__name__)
_JSON_STDOUT: Any | None = None


def _setup_stdio_protocol() -> None:
    """Keep worker RPC bytes UTF-8 even on Windows ANSI-codepage systems."""
    global _JSON_STDOUT
    if _JSON_STDOUT is not None:
        return
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    try:
        _JSON_STDOUT = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
        try:
            os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        except OSError:
            pass
    except Exception:
        _JSON_STDOUT = getattr(sys.stdout, "buffer", sys.stdout)
    sys.stdout = sys.stderr


def _stdin_json_lines():
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        for raw in buffer:
            yield raw.decode("utf-8")
        return
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    yield from sys.stdin

SEAMLESS_LANGUAGE_CODES = {
    "ar": "arb",
    "bg": "bul",
    "cs": "ces",
    "da": "dan",
    "de": "deu",
    "el": "ell",
    "en": "eng",
    "es": "spa",
    "et": "est",
    "fa": "pes",
    "fi": "fin",
    "fr": "fra",
    "hi": "hin",
    "hr": "hrv",
    "hu": "hun",
    "id": "ind",
    "it": "ita",
    "ja": "jpn",
    "ko": "kor",
    "lt": "lit",
    "lv": "lvs",
    "mt": "mlt",
    "nl": "nld",
    "pl": "pol",
    "pt": "por",
    "ro": "ron",
    "ru": "rus",
    "sk": "slk",
    "sl": "slv",
    "sv": "swe",
    "tr": "tur",
    "uk": "ukr",
    "vi": "vie",
    "yue": "yue",
    "zh": "cmn",
}


def _reply(payload: dict[str, Any]) -> None:
    global _JSON_STDOUT
    if _JSON_STDOUT is None:
        _setup_stdio_protocol()
    data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    assert _JSON_STDOUT is not None
    try:
        _JSON_STDOUT.write(data)
    except TypeError:
        _JSON_STDOUT.write(data.decode("utf-8"))
    _JSON_STDOUT.flush()


def _torch_dtype(torch, value: Any):
    if value in (None, "", "auto"):
        return "auto"
    if value is torch.float16 or value is torch.bfloat16 or value is torch.float32:
        return value
    name = str(value).replace("torch.", "")
    return getattr(torch, name, value)


def _from_pretrained(cls, source: str, **kwargs):
    try:
        return cls.from_pretrained(source, **kwargs)
    except TypeError:
        kwargs.pop("local_files_only", None)
        kwargs.pop("trust_remote_code", None)
        return cls.from_pretrained(source, **kwargs)


def _decode_wav(wav_bytes: bytes):
    import numpy as np

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    if sample_width != 2:
        raise RuntimeError(f"expected 16-bit PCM WAV, got sample_width={sample_width}")
    audio = np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio, sample_rate


def _language(spec: dict[str, Any], code: str | None, *, default: str | None = None):
    code = (code or "").strip() or default
    if not code:
        return None
    supported = spec.get("languages") or []
    if supported and code not in supported:
        code = spec.get("fallback_language")
    if not code:
        return None
    if spec.get("language_format") == "name":
        return LANGUAGE_NAMES.get(code, code)
    return code


def _is_auto_language(code: str | None) -> bool:
    return str(code or "").strip().lower() == "auto"


def _first_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)) and value:
        return _first_text(value[0])
    text = getattr(value, "text", None)
    if text is not None:
        return str(text).strip()
    return str(value).strip()


class Worker:
    def __init__(self) -> None:
        self.name = ""
        self.spec: dict[str, Any] = {}
        self.backend = ""
        self.model = None
        self.processor = None
        self.tokenizer = None

    def unload(self) -> None:
        self.model = None
        self.processor = None
        self.tokenizer = None
        self.name = ""
        self.spec = {}
        self.backend = ""
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def load(self, name: str, raw_spec: dict[str, Any]) -> None:
        spec = normalize_model_spec(name, raw_spec)
        if self.name == name and self.model is not None:
            return
        self.unload()
        if spec.get("local_files_only", True):
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        backend = spec.get("backend")
        if backend == "qwen_asr":
            self._load_qwen_asr(spec)
        elif backend == "transformers_tdt":
            self._load_transformers_tdt(spec)
        elif backend == "transformers_speech_seq2seq":
            self._load_transformers_speech_seq2seq(spec)
        elif backend == "seamless_m4t_v2":
            self._load_seamless_m4t_v2(spec)
        elif backend == "cohere_asr":
            self._load_cohere_asr(spec)
        elif backend == "nemo_asr":
            self._load_nemo_asr(spec)
        elif backend == "nemo_salm":
            self._load_nemo_salm(spec)
        else:
            raise RuntimeError(f"unsupported GPU ASR backend: {backend}")
        self._verify_cuda_if_requested(spec)
        self.name = name
        self.spec = spec
        self.backend = str(backend)

    def transcribe(self, wav_bytes: bytes, *, language: str) -> dict[str, Any]:
        if self.model is None:
            raise RuntimeError("model is not loaded")
        audio, sample_rate = _decode_wav(wav_bytes)
        if self.backend == "qwen_asr":
            text = self._transcribe_qwen_asr(audio, sample_rate, language)
        elif self.backend == "transformers_tdt":
            text = self._transcribe_transformers_tdt(audio, sample_rate)
        elif self.backend == "transformers_speech_seq2seq":
            text = self._transcribe_transformers_speech_seq2seq(audio, sample_rate, language)
        elif self.backend == "seamless_m4t_v2":
            text = self._transcribe_seamless_m4t_v2(audio, sample_rate, language)
        elif self.backend == "cohere_asr":
            text = self._transcribe_cohere_asr(audio, sample_rate, language)
        elif self.backend == "nemo_asr":
            text = self._transcribe_nemo_file(wav_bytes, language)
        elif self.backend == "nemo_salm":
            text = self._transcribe_nemo_salm(wav_bytes)
        else:
            raise RuntimeError(f"unsupported loaded backend: {self.backend}")
        return {"text": text, "segments": []}

    def _source(self, spec: dict[str, Any]) -> str:
        source = model_source(spec)
        if not source:
            raise RuntimeError("model spec requires repo_id or local_path")
        return source

    def _cuda_requested(self, spec: dict[str, Any]) -> bool:
        return str(spec.get("device", "")).startswith("cuda")

    def _device_report(self) -> dict[str, Any]:
        try:
            import torch
        except Exception as e:
            return {"torch_import": False, "error": str(e)}

        report: dict[str, Any] = {
            "torch_import": True,
            "cuda_available": bool(torch.cuda.is_available()),
            "model_device": str(getattr(self.model, "device", "")),
            "cuda_tensor_count": 0,
            "cpu_tensor_count": 0,
            "other_tensor_count": 0,
            "cuda_bytes": 0,
            "cpu_bytes": 0,
            "memory_allocated": 0,
            "memory_reserved": 0,
            "max_memory_allocated": 0,
            "gpu_name": "",
        }
        if torch.cuda.is_available():
            current = torch.cuda.current_device()
            report["gpu_name"] = torch.cuda.get_device_name(current)
            report["memory_allocated"] = int(torch.cuda.memory_allocated(current))
            report["memory_reserved"] = int(torch.cuda.memory_reserved(current))
            report["max_memory_allocated"] = int(torch.cuda.max_memory_allocated(current))

        seen: set[int] = set()

        def visit(obj: Any) -> None:
            if obj is None or id(obj) in seen:
                return
            seen.add(id(obj))
            params = getattr(obj, "parameters", None)
            buffers = getattr(obj, "buffers", None)
            tensors = []
            if callable(params):
                try:
                    tensors.extend(list(params()))
                except Exception:
                    pass
            if callable(buffers):
                try:
                    tensors.extend(list(buffers()))
                except Exception:
                    pass
            for tensor in tensors:
                try:
                    size = int(tensor.numel() * tensor.element_size())
                    if tensor.device.type == "cuda":
                        report["cuda_tensor_count"] += 1
                        report["cuda_bytes"] += size
                    elif tensor.device.type == "cpu":
                        report["cpu_tensor_count"] += 1
                        report["cpu_bytes"] += size
                    else:
                        report["other_tensor_count"] += 1
                except Exception:
                    pass
            for attr in ("model", "module", "asr_model", "hf_model", "llm"):
                try:
                    visit(getattr(obj, attr, None))
                except Exception:
                    pass

        visit(self.model)
        return report

    def _verify_cuda_if_requested(self, spec: dict[str, Any]) -> None:
        if not self._cuda_requested(spec):
            return
        report = self._device_report()
        if not report.get("cuda_available"):
            raise RuntimeError("model requested CUDA but torch.cuda.is_available() is false")
        tensor_count = (
            int(report.get("cuda_tensor_count") or 0)
            + int(report.get("cpu_tensor_count") or 0)
            + int(report.get("other_tensor_count") or 0)
        )
        if int(report.get("cuda_tensor_count") or 0) == 0 and int(report.get("memory_allocated") or 0) == 0:
            raise RuntimeError(f"model requested CUDA but no CUDA tensors/allocation were found: {report}")
        if tensor_count and int(report.get("cuda_tensor_count") or 0) == 0:
            raise RuntimeError(f"model requested CUDA but model tensors are not on CUDA: {report}")

    def _local_hf_source(self, spec: dict[str, Any]) -> str:
        repo_id = str(spec.get("repo_id") or "")
        if not repo_id or not bool(spec.get("local_files_only", True)):
            return self._source(spec)
        try:
            from huggingface_hub import snapshot_download

            return snapshot_download(repo_id=repo_id, local_files_only=True)
        except Exception as e:
            name = spec.get("name") or repo_id
            raise RuntimeError(
                f"{repo_id} is not cached locally; run scripts/download-gpu-asr-model.sh {name}"
            ) from e

    def _local_nemo_file(self, spec: dict[str, Any]) -> str:
        source = self._source(spec)
        if source.endswith(".nemo") and Path(source).is_file():
            return source
        root = Path(self._local_hf_source(spec))
        if root.is_file() and root.suffix == ".nemo":
            return str(root)
        if root.is_dir():
            nemo_files = sorted(root.glob("*.nemo"))
            if nemo_files:
                return str(nemo_files[0])
        return ""

    def _load_qwen_asr(self, spec: dict[str, Any]) -> None:
        import torch
        from qwen_asr import Qwen3ASRModel

        dtype = _torch_dtype(torch, spec.get("dtype", "bfloat16"))
        kwargs = {
            "dtype": dtype,
            "device_map": spec.get("device", "cuda:0"),
            "max_inference_batch_size": int(spec.get("max_inference_batch_size", 8)),
            "max_new_tokens": int(spec.get("max_new_tokens", 256)),
            "local_files_only": bool(spec.get("local_files_only", True)),
        }
        self.model = _from_pretrained(Qwen3ASRModel, self._source(spec), **kwargs)

    def _transcribe_qwen_asr(self, audio, sample_rate: int, language: str) -> str:
        lang = _language(self.spec, language)
        results = self.model.transcribe(audio=(audio, sample_rate), language=lang)
        return _first_text(results)

    def _load_transformers_tdt(self, spec: dict[str, Any]) -> None:
        import torch
        from transformers import AutoModel, AutoProcessor

        source = self._source(spec)
        common = {
            "local_files_only": bool(spec.get("local_files_only", True)),
            "trust_remote_code": bool(spec.get("trust_remote_code", False)),
        }
        self.processor = _from_pretrained(AutoProcessor, source, **common)
        kwargs = dict(common)
        dtype = _torch_dtype(torch, spec.get("dtype", "auto"))
        if dtype != "auto":
            kwargs["torch_dtype"] = dtype
        else:
            kwargs["dtype"] = "auto"
        kwargs["device_map"] = spec.get("device", "cuda:0")
        self.model = _from_pretrained(AutoModel, source, **kwargs)
        self.model.eval()

    def _transcribe_transformers_tdt(self, audio, sample_rate: int) -> str:
        import torch

        target_sr = getattr(getattr(self.processor, "feature_extractor", None), "sampling_rate", sample_rate)
        if int(target_sr) != int(sample_rate):
            raise RuntimeError(f"audio sample rate {sample_rate} does not match model sample rate {target_sr}")
        inputs = self.processor([audio], sampling_rate=sample_rate)
        dtype = self.model.dtype if getattr(self.model, "dtype", None) is not None else torch.float32
        inputs.to(self.model.device, dtype=dtype)
        with torch.inference_mode():
            output = self.model.generate(**inputs, return_dict_in_generate=True)
        decoded = self.processor.decode(output.sequences, skip_special_tokens=True)
        return _first_text(decoded)

    def _load_transformers_speech_seq2seq(self, spec: dict[str, Any]) -> None:
        import torch
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

        source = self._source(spec)
        common = {
            "local_files_only": bool(spec.get("local_files_only", True)),
            "trust_remote_code": bool(spec.get("trust_remote_code", False)),
        }
        self.processor = _from_pretrained(AutoProcessor, source, **common)
        self.tokenizer = getattr(self.processor, "tokenizer", None)
        kwargs = dict(common)
        dtype = _torch_dtype(torch, spec.get("dtype", "bfloat16"))
        if dtype != "auto":
            kwargs["torch_dtype"] = dtype
        kwargs["device_map"] = spec.get("device", "cuda:0")
        self.model = _from_pretrained(AutoModelForSpeechSeq2Seq, source, **kwargs)
        self.model.eval()

    def _transcribe_transformers_speech_seq2seq(self, audio, sample_rate: int, language: str) -> str:
        import torch

        if sample_rate != 16000:
            raise RuntimeError(f"expected 16000 Hz audio, got {sample_rate}")
        prompt = str(self.spec.get("prompt") or "<|audio|>transcribe the speech.")
        lang_name = LANGUAGE_NAMES.get(str(_language(self.spec, language, default="en") or "en"), "English")
        prompt = prompt.format(language=lang_name)
        tokenizer = self.tokenizer or self.processor.tokenizer
        if hasattr(tokenizer, "apply_chat_template"):
            prompt = tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                tokenize=False,
                add_generation_prompt=True,
            )
        wav = torch.from_numpy(audio).unsqueeze(0)
        device = getattr(self.model, "device", self.spec.get("device", "cuda:0"))
        model_inputs = self.processor(prompt, wav, device=device, return_tensors="pt").to(device)
        with torch.inference_mode():
            model_outputs = self.model.generate(
                **model_inputs,
                max_new_tokens=int(self.spec.get("max_new_tokens", 200)),
                do_sample=False,
                num_beams=1,
        )
        num_input_tokens = model_inputs["input_ids"].shape[-1]
        new_tokens = model_outputs[0, num_input_tokens:].unsqueeze(0)
        decoded = tokenizer.batch_decode(
            new_tokens, add_special_tokens=False, skip_special_tokens=True
        )
        return _first_text(decoded)

    def _load_cohere_asr(self, spec: dict[str, Any]) -> None:
        from transformers import AutoProcessor, CohereAsrForConditionalGeneration

        source = self._source(spec)
        common = {
            "local_files_only": bool(spec.get("local_files_only", True)),
            "trust_remote_code": bool(spec.get("trust_remote_code", False)),
        }
        self.processor = _from_pretrained(AutoProcessor, source, **common)
        kwargs = dict(common)
        kwargs["device_map"] = spec.get("device", "cuda:0")
        self.model = _from_pretrained(CohereAsrForConditionalGeneration, source, **kwargs)
        self.model.eval()

    def _load_seamless_m4t_v2(self, spec: dict[str, Any]) -> None:
        import torch
        from transformers import AutoProcessor, SeamlessM4Tv2ForSpeechToText

        source = self._source(spec)
        common = {
            "local_files_only": bool(spec.get("local_files_only", True)),
            "trust_remote_code": bool(spec.get("trust_remote_code", False)),
        }
        self.processor = _from_pretrained(AutoProcessor, source, **common)
        kwargs = dict(common)
        dtype = _torch_dtype(torch, spec.get("dtype", "float16"))
        if dtype != "auto":
            kwargs["torch_dtype"] = dtype
        kwargs["device_map"] = spec.get("device", "cuda:0")
        self.model = _from_pretrained(SeamlessM4Tv2ForSpeechToText, source, **kwargs)
        self.model.eval()

    def _seamless_language(self, language: str) -> str:
        lang = str(_language(self.spec, language, default="en") or "en")
        return SEAMLESS_LANGUAGE_CODES.get(lang, lang)

    def _transcribe_seamless_m4t_v2(self, audio, sample_rate: int, language: str) -> str:
        import torch

        inputs = self.processor(
            audio=audio,
            sampling_rate=sample_rate,
            return_tensors="pt",
        )
        device = getattr(self.model, "device", self.spec.get("device", "cuda:0"))
        inputs = inputs.to(device)
        tgt_lang = self._seamless_language(language)
        with torch.inference_mode():
            outputs = self.model.generate(
                **inputs,
                tgt_lang=tgt_lang,
                max_new_tokens=int(self.spec.get("max_new_tokens", 256)),
                do_sample=False,
                num_beams=1,
            )
        tokens = outputs.sequences if hasattr(outputs, "sequences") else outputs
        decoded = self.processor.batch_decode(tokens, skip_special_tokens=True)
        return _first_text(decoded)

    def _transcribe_cohere_asr(self, audio, sample_rate: int, language: str) -> str:
        import torch

        lang = _language(self.spec, language, default="en") or "en"
        inputs = self.processor(
            audio,
            sampling_rate=sample_rate,
            return_tensors="pt",
            language=lang,
            punctuation=bool(self.spec.get("punctuation", True)),
        )
        audio_chunk_index = inputs.get("audio_chunk_index")
        inputs.to(self.model.device, dtype=getattr(self.model, "dtype", torch.float32))
        with torch.inference_mode():
            outputs = self.model.generate(**inputs, max_new_tokens=int(self.spec.get("max_new_tokens", 256)))
        decoded = self.processor.decode(
            outputs,
            skip_special_tokens=True,
            audio_chunk_index=audio_chunk_index,
            language=lang,
        )
        return _first_text(decoded)

    def _load_nemo_asr(self, spec: dict[str, Any]) -> None:
        import torch
        import nemo.collections.asr as nemo_asr

        local_nemo = self._local_nemo_file(spec)
        if spec.get("nemo_model_class") == "EncDecMultiTaskModel":
            from nemo.collections.asr.models import EncDecMultiTaskModel

            if local_nemo:
                self.model = EncDecMultiTaskModel.restore_from(local_nemo)
            else:
                self.model = EncDecMultiTaskModel.from_pretrained(model_name=self._source(spec))
        else:
            if local_nemo:
                self.model = nemo_asr.models.ASRModel.restore_from(local_nemo)
            else:
                self.model = nemo_asr.models.ASRModel.from_pretrained(model_name=self._source(spec))
        beam_size = spec.get("decode_beam_size")
        if beam_size is not None:
            try:
                decode_cfg = self.model.cfg.decoding
                decode_cfg.beam.beam_size = int(beam_size)
                self.model.change_decoding_strategy(decode_cfg)
            except Exception:
                log.warning("failed to set NeMo decode beam size", exc_info=True)
        if torch.cuda.is_available() and str(spec.get("device", "cuda")).startswith("cuda"):
            self.model = self.model.to(spec.get("device", "cuda:0"))
        self.model.eval()

    def _load_nemo_salm(self, spec: dict[str, Any]) -> None:
        import torch
        from nemo.collections.speechlm2.models import SALM

        self.model = SALM.from_pretrained(self._local_hf_source(spec))
        if torch.cuda.is_available() and str(spec.get("device", "cuda")).startswith("cuda"):
            self.model = self.model.to(spec.get("device", "cuda:0"))
        self.model.eval()

    def _transcribe_nemo_file(self, wav_bytes: bytes, language: str) -> str:
        path = self._temp_wav(wav_bytes)
        manifest_path: Path | None = None
        try:
            batch_size = int(self.spec.get("nemo_batch_size", 16))
            if self.spec.get("nemo_manifest_transcribe"):
                manifest = {
                    "audio_filepath": str(path),
                    "pnc": str(self.spec.get("nemo_pnc", "yes")),
                    "timestamp": str(self.spec.get("nemo_timestamps", "no")),
                }
                if not _is_auto_language(language):
                    lang = _language(self.spec, language, default="en") or "en"
                    manifest["source_lang"] = lang
                    manifest["target_lang"] = lang
                manifest_path = path.with_suffix(".jsonl")
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False)
                    + "\n"
                )
                output = self.model.transcribe(str(manifest_path), batch_size=batch_size)
            elif self.spec.get("nemo_language_kwargs"):
                kwargs = {
                    "timestamps": bool(self.spec.get("nemo_timestamps", False)),
                    "batch_size": batch_size,
                }
                if not _is_auto_language(language):
                    lang = _language(self.spec, language, default="en") or "en"
                    kwargs["source_lang"] = lang
                    kwargs["target_lang"] = lang
                try:
                    output = self.model.transcribe([str(path)], **kwargs)
                except TypeError:
                    kwargs.pop("batch_size", None)
                    output = self.model.transcribe([str(path)], **kwargs)
            else:
                output = self.model.transcribe([str(path)], batch_size=batch_size)
            return _first_text(output)
        finally:
            if manifest_path is not None:
                manifest_path.unlink(missing_ok=True)
            path.unlink(missing_ok=True)

    def _transcribe_nemo_salm(self, wav_bytes: bytes) -> str:
        path = self._temp_wav(wav_bytes)
        try:
            prompt = str(self.spec.get("prompt") or "Transcribe the following:")
            locator = getattr(self.model, "audio_locator_tag", "<|audioplaceholder|>")
            answer_ids = self.model.generate(
                prompts=[
                    [
                        {
                            "role": "user",
                            "content": f"{prompt} {locator}",
                            "audio": [str(path)],
                        }
                    ]
                ],
                max_new_tokens=int(self.spec.get("max_new_tokens", 128)),
            )
            return self.model.tokenizer.ids_to_text(answer_ids[0].cpu()).strip()
        finally:
            path.unlink(missing_ok=True)

    def _temp_wav(self, wav_bytes: bytes) -> Path:
        tmp = tempfile.NamedTemporaryFile(prefix="mywhispr-gpu-", suffix=".wav", delete=False)
        try:
            tmp.write(wav_bytes)
            return Path(tmp.name)
        finally:
            tmp.close()


def main() -> int:
    _setup_stdio_protocol()
    logging.basicConfig(
        level=os.environ.get("MYWHISPR_GPU_WORKER_LOG", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = Worker()
    for line in _stdin_json_lines():
        try:
            req = json.loads(line)
            cmd = req.get("cmd")
            if cmd == "warm":
                worker.load(str(req.get("model") or ""), req.get("spec") or {})
                _reply(
                    {
                        "ok": True,
                        "model": worker.name,
                        "backend": worker.backend,
                        "device_report": worker._device_report(),
                    }
                )
            elif cmd == "transcribe":
                model = str(req.get("model") or "")
                spec = req.get("spec") or {}
                if model and worker.name != model:
                    worker.load(model, spec)
                wav_bytes = base64.b64decode(req.get("wav_b64") or "")
                result = worker.transcribe(wav_bytes, language=str(req.get("language") or "auto"))
                _reply({"ok": True, **result, "device_report": worker._device_report()})
            elif cmd == "unload":
                worker.unload()
                _reply({"ok": True})
            elif cmd == "stop":
                worker.unload()
                _reply({"ok": True})
                return 0
            else:
                _reply({"ok": False, "error": f"unknown command {cmd!r}"})
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            _reply({"ok": False, "error": str(e)})
    worker.unload()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
