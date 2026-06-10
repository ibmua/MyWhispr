"""Download one file to disk with JSON-line progress.

Used for direct whisper.cpp GGML model files:

    python -m mywhispr.file_download URL DEST

Emits:
    {"event": "total", "total_bytes": N}
    {"event": "progress", "downloaded_bytes": N}
    {"event": "done", "downloaded_bytes": N}
    {"event": "error", "message": "..."}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

USER_AGENT = "MyWhispr model downloader"
CHUNK_SIZE = 1024 * 1024


def _emit(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def _content_length(url: str) -> int:
    req = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        try:
            return int(resp.headers.get("Content-Length") or 0)
        except ValueError:
            return 0


def _total_from_content_range(value: str) -> int:
    m = re.search(r"/(\d+)\s*$", value or "")
    return int(m.group(1)) if m else 0


def _open_download(url: str, start: int):
    headers = {"User-Agent": USER_AGENT}
    if start > 0:
        headers["Range"] = f"bytes={start}-"
    req = Request(url, headers=headers)
    return urlopen(req, timeout=60)


def _download(url: str, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    try:
        total = _content_length(url)
    except Exception:
        total = 0
    _emit("total", total_bytes=total)

    if dest.exists():
        size = dest.stat().st_size
        if total > 0 and size == total:
            _emit("done", downloaded_bytes=size)
            return 0
        if size > 0 and (total <= 0 or size < total):
            os.replace(dest, part)
        else:
            dest.unlink()

    downloaded = part.stat().st_size if part.exists() else 0
    if total > 0 and downloaded >= total:
        os.replace(part, dest)
        _emit("done", downloaded_bytes=dest.stat().st_size)
        return 0

    try:
        resp = _open_download(url, downloaded)
    except HTTPError as e:
        if downloaded > 0 and e.code == 416:
            final_size = part.stat().st_size
            if total <= 0 or final_size >= total:
                os.replace(part, dest)
                _emit("done", downloaded_bytes=dest.stat().st_size)
                return 0
        raise

    with resp:
        status = getattr(resp, "status", 200)
        if downloaded > 0 and status != 206:
            downloaded = 0
            mode = "wb"
        else:
            mode = "ab" if downloaded > 0 else "wb"
        content_range_total = _total_from_content_range(resp.headers.get("Content-Range", ""))
        if content_range_total > total:
            total = content_range_total
            _emit("total", total_bytes=total)
        with part.open(mode) as f:
            last_emit = 0.0
            while True:
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now - last_emit >= 0.5:
                    _emit("progress", downloaded_bytes=downloaded)
                    last_emit = now

    final_size = part.stat().st_size if part.exists() else 0
    if final_size <= 0:
        raise RuntimeError("download produced an empty file")
    if total > 0 and final_size < total:
        raise RuntimeError(f"incomplete download: {final_size} of {total} bytes")
    os.replace(part, dest)
    _emit("done", downloaded_bytes=final_size)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("dest")
    args = parser.parse_args()

    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass

    try:
        return _download(args.url, Path(args.dest))
    except (HTTPError, URLError, OSError, RuntimeError) as e:
        _emit("error", message=f"download failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
