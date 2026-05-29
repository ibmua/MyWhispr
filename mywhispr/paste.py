from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger(__name__)

# Ctrl+Shift+V keycodes for ydotool: 29=LCTRL, 42=LSHIFT, 47=V
PASTE_CHORD = ["29:1", "42:1", "47:1", "47:0", "42:0", "29:0"]
# Backspace single press/release: 14=BACKSPACE
BACKSPACE_CHORD = ["14:1", "14:0"]


async def _wl_copy(text: str, *, paste_once: bool) -> bool:
    proc = await _start_wl_copy(text, paste_once=paste_once)
    if proc is None:
        return False
    return True


async def _start_wl_copy(text: str, *, paste_once: bool) -> asyncio.subprocess.Process | None:
    args = ["wl-copy"]
    if paste_once:
        args.append("--paste-once")
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        log.error("wl-copy not found")
        return None
    try:
        assert proc.stdin is not None
        proc.stdin.write(text.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        try:
            await proc.stdin.wait_closed()
        except Exception:
            pass
    except asyncio.TimeoutError:
        log.error("wl-copy stdin timed out")
        proc.kill()
        await proc.wait()
        return None
    return proc


async def _wait_wl_copy(proc: asyncio.subprocess.Process, *, timeout: float) -> bool:
    try:
        rc = await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        log.error("wl-copy timed out")
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return False
    if rc != 0:
        try:
            err = await proc.stderr.read(400) if proc.stderr else b""
        except Exception:
            err = b""
        log.error("wl-copy rc=%s err=%r", rc, err)
        return False
    return True


async def _ydotool_keys(keycodes: list[str], *, delay_ms: int | None = None) -> bool:
    args = ["ydotool", "key"]
    if delay_ms is not None:
        args.extend(["-d", str(max(0, int(delay_ms)))])
    args.extend(keycodes)
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        log.error("ydotool not found")
        return False
    try:
        rc = await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False
    if rc != 0:
        try:
            err = await proc.stderr.read(400) if proc.stderr else b""
        except Exception:
            err = b""
        log.error("ydotool rc=%s err=%r", rc, err)
        return False
    return True


async def paste_final(text: str, *, settle_seconds: float, consume_timeout: float) -> bool:
    if not text:
        return True
    if not await _wl_copy(text, paste_once=False):
        return False
    await asyncio.sleep(max(settle_seconds, 0.12))
    keys_ok = await _ydotool_keys(PASTE_CHORD)
    if not keys_ok:
        await _wl_copy(text, paste_once=False)
        return False
    return True


async def stream_replace(
    *,
    previous: str,
    new: str,
    settle_seconds: float,
    max_rewrite_chars: int,
    consume_timeout: float = 1.5,
) -> bool:
    """Backspace common-suffix divergence and paste replacement. Returns False if
    the rewrite would exceed `max_rewrite_chars`.
    """
    # Compute common prefix length.
    i = 0
    n = min(len(previous), len(new))
    while i < n and previous[i] == new[i]:
        i += 1
    backspaces = len(previous) - i
    addition = new[i:]
    if backspaces == 0 and not addition:
        return True
    if backspaces > max_rewrite_chars:
        log.warning("stream rewrite cap hit: %d > %d", backspaces, max_rewrite_chars)
        return False
    if backspaces > 0:
        chord = BACKSPACE_CHORD * backspaces
        ok = await _ydotool_keys(chord, delay_ms=0)
        if not ok:
            return False
    if addition:
        if not await _wl_copy(addition, paste_once=False):
            return False
        await asyncio.sleep(max(settle_seconds, 0.12))
        ok = await _ydotool_keys(PASTE_CHORD)
        if not ok:
            await _wl_copy(addition, paste_once=False)
            return False
    return True
