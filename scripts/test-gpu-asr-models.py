#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mywhispr.config import load_config  # noqa: E402
from mywhispr.model_server import ModelServer  # noqa: E402
from mywhispr.model_specs import is_gpu_model, normalize_model_spec  # noqa: E402
from mywhispr.transcriber import Transcriber  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Warm and transcribe a WAV with configured GPU ASR models.")
    parser.add_argument("audio", type=Path, help="16 kHz mono 16-bit WAV test audio")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--language", default="en")
    parser.add_argument("--model", action="append", dest="models", help="Model key to test; repeatable")
    args = parser.parse_args()

    cfg = load_config(args.config)
    models = cfg.get("models") or {}
    targets = args.models or [
        name for name, raw in models.items() if is_gpu_model(normalize_model_spec(name, raw))
    ]
    wav = args.audio.read_bytes()
    server = ModelServer(
        binary=cfg.get("whisper_server_binary"),
        host=cfg.get("whisper_host", "127.0.0.1"),
        port=int(cfg.get("whisper_port", 18178)),
        model_specs=models,
        gpu_python=cfg.get("gpu_asr_python") or "",
        startup_timeout=float(cfg.get("whisper_startup_timeout_seconds", 180.0)),
        idle_shutdown_seconds=0.0,
        name="gpu-test",
    )
    transcriber = Transcriber(cfg)
    failures = 0
    try:
        for model in targets:
            print(f"==> {model}", flush=True)
            try:
                res = await transcriber.transcribe(
                    server,
                    wav,
                    language=args.language,
                    model=model,
                )
                preview = (res.raw_text or res.text).replace("\n", " ")[:180]
                print(f"PASS {model}: {preview!r} ({res.elapsed_seconds:.2f}s)", flush=True)
                report = server.status().get("gpu", {}).get("device_report") or server.status().get("device_report") or {}
                if report:
                    cuda_gib = float(report.get("cuda_bytes") or 0) / (1024**3)
                    alloc_gib = float(report.get("memory_allocated") or 0) / (1024**3)
                    print(
                        "GPU "
                        f"{report.get('gpu_name') or 'unknown'} "
                        f"cuda_tensors={report.get('cuda_tensor_count')} "
                        f"cuda_bytes={cuda_gib:.2f}GiB "
                        f"allocated={alloc_gib:.2f}GiB",
                        flush=True,
                    )
            except Exception as e:
                failures += 1
                print(f"FAIL {model}: {e}", flush=True)
            finally:
                await server.stop()
    finally:
        await transcriber.close()
        await server.stop()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
