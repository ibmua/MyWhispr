"""One-shot smoke test: drive mywhispr.gpu_asr_worker over stdin/stdout.

Usage: python scripts/test-gpu-worker-once.py <model-name> <wav-path>
Run with the daemon venv python; the worker subprocess uses gpu_asr_python
from config.json semantics (here: this same interpreter's sibling GPU venv).
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "parakeet-tdt-0.6b-v3"
    wav = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    sys.path.insert(0, str(ROOT))
    from mywhispr.model_specs import BUILTIN_MODEL_OPTIONS, normalize_model_spec

    spec = normalize_model_spec(model, BUILTIN_MODEL_OPTIONS[model])
    python = ROOT / ".venv-gpu-asr" / "Scripts" / "python.exe"
    proc = subprocess.Popen(
        [str(python), "-m", "mywhispr.gpu_asr_worker"],
        cwd=str(ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    def rpc(req):
        t0 = time.monotonic()
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        dt = time.monotonic() - t0
        return json.loads(line), dt

    reply, dt = rpc({"cmd": "warm", "model": model, "spec": spec})
    rep = reply.get("device_report") or {}
    print(f"warm ok={reply.get('ok')} backend={reply.get('backend')} {dt:.1f}s")
    print(
        f"  cuda_available={rep.get('cuda_available')} gpu={rep.get('gpu_name')}"
        f" cuda_tensors={rep.get('cuda_tensor_count')} vram_alloc={int(rep.get('memory_allocated') or 0)/1e6:.0f}MB"
    )
    if not reply.get("ok"):
        print("  error:", reply.get("error"))
        proc.kill()
        return 1
    if wav is not None:
        wav_b64 = base64.b64encode(wav.read_bytes()).decode()
        reply, dt = rpc({"cmd": "transcribe", "model": model, "spec": spec, "language": "en", "wav_b64": wav_b64})
        print(f"transcribe ok={reply.get('ok')} {dt:.2f}s text={reply.get('text')!r}")
        if not reply.get("ok"):
            print("  error:", reply.get("error"))
    rpc({"cmd": "stop"})
    proc.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
