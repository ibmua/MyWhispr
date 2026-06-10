from __future__ import annotations

import asyncio
import logging
import re
import sys
from typing import Any

log = logging.getLogger(__name__)


def _windows_sources() -> list[dict[str, Any]]:
    """Active input endpoints with full names.

    WASAPI is the only Windows host API that lists exactly the currently
    enabled endpoints under their real names; MME truncates names to 31
    chars, DirectSound duplicates them, and WDM-KS exposes raw driver pins
    (including disconnected Bluetooth profiles). Other host APIs are only a
    fallback if WASAPI is unavailable.
    """
    import sounddevice as sd

    hostapis = sd.query_hostapis()
    wasapi = next(
        (i for i, api in enumerate(hostapis) if "wasapi" in str(api.get("name", "")).lower()),
        None,
    )

    def collect(only_hostapi: int | None) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for dev in sd.query_devices():
            if dev.get("max_input_channels", 0) <= 0:
                continue
            if only_hostapi is not None and dev.get("hostapi") != only_hostapi:
                continue
            name = str(dev.get("name", "")).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            sources.append({
                "name": name,
                "description": name,
                "nick": name,
                "monitor": "loopback" in name.lower(),
            })
        return sources

    return collect(wasapi) if wasapi is not None else collect(None)

_BLOCK_RE = re.compile(r"(?=\tid \d+,)")


def _parse_field(text: str, key: str) -> str:
    m = re.search(rf'{re.escape(key)} = "([^"]+)"', text)
    return m.group(1) if m else ""


async def list_sources() -> list[dict[str, Any]]:
    """Enumerate PipeWire Audio/Source nodes via `pw-cli ls Node`.

    Returns a list of dicts: {name, description, nick, monitor}.
    Empty list on any failure — the caller should fall back to the default
    source.
    """
    if sys.platform == "win32":
        try:
            return await asyncio.to_thread(_windows_sources)
        except Exception as e:
            log.warning("sounddevice enumeration failed: %s", e)
            return []
    try:
        proc = await asyncio.create_subprocess_exec(
            "pw-cli", "ls", "Node",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        log.warning("pw-cli not available; cannot enumerate audio sources")
        return []
    out, _err = await proc.communicate()
    if proc.returncode != 0:
        return []
    text = out.decode("utf-8", "replace")
    sources: list[dict[str, Any]] = []
    for block in _BLOCK_RE.split(text):
        if 'media.class = "Audio/Source"' not in block:
            continue
        name = _parse_field(block, "node.name")
        if not name:
            continue
        desc = _parse_field(block, "node.description") or name
        nick = _parse_field(block, "node.nick") or desc
        is_monitor = ".monitor" in name
        sources.append({
            "name": name,
            "description": desc,
            "nick": nick,
            "monitor": is_monitor,
        })
    return sources
