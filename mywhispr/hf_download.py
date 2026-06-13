"""Download a Hugging Face model repo into the local HF cache.

Runs under the GPU venv python (which has huggingface_hub):

    python -m mywhispr.hf_download REPO_ID [--exclude PATTERN ...]

Emits JSON lines on stdout for the daemon to track progress:
    {"event": "total", "total_bytes": N}
    {"event": "progress", "downloaded_bytes": N}
    {"event": "done", "downloaded_bytes": N}
    {"event": "error", "message": "..."}
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import threading
from pathlib import Path

from .model_specs import hf_cache_path

# This stays a UTF-8 JSON-lines protocol regardless of the Windows codepage.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _emit(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def _dir_bytes(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for p in root.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def _excluded(filename: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(filename, pat) for pat in patterns)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_id")
    parser.add_argument("--exclude", action="append", default=[], help="ignore pattern (repeatable)")
    args = parser.parse_args()

    import os

    # The worker env intentionally pins offline mode; downloading is the one
    # place that must reach the hub.
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)

    try:
        # Corporate TLS interception breaks certifi-based verification; prefer
        # the OS trust store when available.
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass

    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError as e:
        _emit("error", message=f"huggingface_hub is not installed in this python: {e}")
        return 1

    cache_root = hf_cache_path(args.repo_id)
    try:
        info = HfApi().model_info(args.repo_id, files_metadata=True)
        total = sum(
            int(s.size or 0)
            for s in (info.siblings or [])
            if not _excluded(s.rfilename, args.exclude)
        )
        _emit("total", total_bytes=total)
    except Exception as e:
        _emit("error", message=f"failed to query {args.repo_id}: {e}")
        return 1

    done = threading.Event()

    def watch() -> None:
        while not done.wait(1.0):
            _emit("progress", downloaded_bytes=_dir_bytes(cache_root))

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        snapshot_download(args.repo_id, ignore_patterns=args.exclude or None)
    except Exception as e:
        done.set()
        _emit("error", message=f"download failed: {e}")
        return 1
    done.set()
    watcher.join(2.0)
    _emit("done", downloaded_bytes=_dir_bytes(cache_root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
