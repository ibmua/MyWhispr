from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

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
