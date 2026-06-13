from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass
import logging
import os
import re
import sys
from typing import Protocol

log = logging.getLogger(__name__)

# ydotool keycodes: 29=LCTRL, 42=LSHIFT, 47=V, 110=INSERT, 14=BACKSPACE
PASTE_CHORD = ["29:1", "42:1", "47:1", "47:0", "42:0", "29:0"]
SHIFT_INSERT_CHORD = ["42:1", "110:1", "110:0", "42:0"]
PASTE_CHORDS = [
    ("ctrl+shift+v", PASTE_CHORD),
    ("shift+insert", SHIFT_INSERT_CHORD),
]
BACKSPACE_CHORD = ["14:1", "14:0"]
SHIFT_DOWN = "42:1"
SHIFT_UP = "42:0"
DEFAULT_PASTE_KEY_DELAY_MS = 18
DEFAULT_TYPE_KEY_DELAY_MS = 0
DEFAULT_DIRECT_TYPE_MAX_CHARS = 240
DEFAULT_PREFER_CLIPBOARD_PASTE = True
_CLIPBOARD_SNAPSHOT_TIMEOUT_SECONDS = 1.0

_ASCII_KEYCODES = {
    "a": 30, "b": 48, "c": 46, "d": 32, "e": 18, "f": 33, "g": 34,
    "h": 35, "i": 23, "j": 36, "k": 37, "l": 38, "m": 50, "n": 49,
    "o": 24, "p": 25, "q": 16, "r": 19, "s": 31, "t": 20, "u": 22,
    "v": 47, "w": 17, "x": 45, "y": 21, "z": 44,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8,
    "8": 9, "9": 10, "0": 11,
    " ": 57, "-": 12, "=": 13, "[": 26, "]": 27, "\\": 43,
    ";": 39, "'": 40, "`": 41, ",": 51, ".": 52, "/": 53,
}

_ASCII_SHIFTED = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6",
    "&": "7", "*": "8", "(": "9", ")": "0", "_": "-", "+": "=",
    "{": "[", "}": "]", "|": "\\", ":": ";", '"': "'", "~": "`",
    "<": ",", ">": ".", "?": "/",
}
_FAST_TYPE_US_LAYOUTS = {"us"}
_SPECIAL_CLIPBOARD_MIME_TYPES = {
    "TIMESTAMP",
    "TARGETS",
    "MULTIPLE",
    "SAVE_TARGETS",
}


@dataclass(frozen=True)
class _WaylandClipboardSnapshot:
    mime_type: str | None
    data: bytes = b""


class OutputBackend(Protocol):
    name: str

    async def type_text(self, text: str, *, delay_ms: int) -> bool:
        ...

    async def paste_text(
        self,
        text: str,
        *,
        settle_seconds: float,
        consume_timeout: float,
        key_delay_ms: int,
    ) -> bool:
        ...

    async def copy_text(self, text: str) -> bool:
        ...

    async def backspace(self, count: int) -> bool:
        ...


class LinuxWaylandYdotoolBackend:
    name = "linux-wayland-ydotool"

    async def type_text(self, text: str, *, delay_ms: int) -> bool:
        if not await _linux_fast_type_safe_for_current_layout():
            log.info("direct type disabled; active Linux input source is not US keycode compatible")
            return False
        if delay_ms <= 0:
            ok = await _ydotool_type_ascii_fast(text)
            if ok:
                return True
        return await _ydotool_type(text, delay_ms=delay_ms)

    async def paste_text(
        self,
        text: str,
        *,
        settle_seconds: float,
        consume_timeout: float,
        key_delay_ms: int,
    ) -> bool:
        return await _wayland_clipboard_paste(
            text,
            settle_seconds=settle_seconds,
            consume_timeout=consume_timeout,
            key_delay_ms=key_delay_ms,
        )

    async def copy_text(self, text: str) -> bool:
        return await _wl_copy(text, paste_once=False)

    async def backspace(self, count: int) -> bool:
        if count <= 0:
            return True
        return await _ydotool_keys(BACKSPACE_CHORD * count, delay_ms=0)


class WindowsSendInputBackend:
    name = "windows-sendinput"

    async def type_text(self, text: str, *, delay_ms: int) -> bool:
        return await asyncio.to_thread(_windows_type_text, text, delay_ms)

    async def paste_text(
        self,
        text: str,
        *,
        settle_seconds: float,
        consume_timeout: float,
        key_delay_ms: int,
    ) -> bool:
        if not await self.copy_text(text):
            return False
        await asyncio.sleep(max(settle_seconds, 0.03))
        return await asyncio.to_thread(_windows_paste, key_delay_ms)

    async def copy_text(self, text: str) -> bool:
        return await asyncio.to_thread(_windows_copy_text, text)

    async def backspace(self, count: int) -> bool:
        if count <= 0:
            return True
        return await asyncio.to_thread(_windows_backspace, count)


_backend: OutputBackend | None = None


def output_backend() -> OutputBackend:
    global _backend
    if _backend is None:
        if sys.platform == "win32":
            _backend = WindowsSendInputBackend()
        else:
            _backend = LinuxWaylandYdotoolBackend()
    return _backend


async def copy_text(text: str, *, backend: OutputBackend | None = None) -> bool:
    return await (backend or output_backend()).copy_text(text)


async def _wl_copy(text: str, *, paste_once: bool) -> bool:
    proc = await _start_wl_copy(text, paste_once=paste_once)
    if proc is None:
        return False
    return True


async def _start_wl_copy(text: str, *, paste_once: bool) -> asyncio.subprocess.Process | None:
    return await _start_wl_copy_bytes(
        text.encode("utf-8"),
        paste_once=paste_once,
        mime_type="text/plain;charset=utf-8",
    )


async def _wl_copy_bytes(
    data: bytes,
    *,
    paste_once: bool,
    mime_type: str | None = None,
) -> bool:
    proc = await _start_wl_copy_bytes(data, paste_once=paste_once, mime_type=mime_type)
    if proc is None:
        return False
    return True


async def _start_wl_copy_bytes(
    data: bytes,
    *,
    paste_once: bool,
    mime_type: str | None = None,
) -> asyncio.subprocess.Process | None:
    args = ["wl-copy"]
    if paste_once:
        args.append("--paste-once")
    if mime_type:
        args.extend(["--type", mime_type])
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
        proc.stdin.write(data)
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


async def _wl_clear() -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "wl-copy",
            "--clear",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        log.error("wl-copy not found")
        return False
    try:
        rc = await asyncio.wait_for(proc.wait(), timeout=1.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False
    if rc != 0:
        try:
            err = await proc.stderr.read(400) if proc.stderr else b""
        except Exception:
            err = b""
        log.error("wl-copy --clear rc=%s err=%r", rc, err)
        return False
    return True


async def _wait_wl_copy(
    proc: asyncio.subprocess.Process,
    *,
    timeout: float,
    kill_on_timeout: bool = True,
) -> bool:
    try:
        rc = await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        if kill_on_timeout:
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


async def _stop_wl_copy(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=0.5)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()


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


async def _ydotool_type(text: str, *, delay_ms: int | None = None) -> bool:
    args = ["ydotool", "type"]
    if delay_ms is not None:
        args.extend(["-d", str(max(0, int(delay_ms)))])
    args.append(text)
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
        rc = await asyncio.wait_for(proc.wait(), timeout=max(5.0, len(text) * 0.04))
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False
    if rc != 0:
        try:
            err = await proc.stderr.read(400) if proc.stderr else b""
        except Exception:
            err = b""
        log.error("ydotool type rc=%s err=%r", rc, err)
        return False
    return True


async def _command_stdout(args: list[str], *, timeout: float = 0.5) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return ""
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await proc.wait()
        except Exception:
            pass
        return ""
    if proc.returncode != 0:
        return ""
    return out.decode("utf-8", "replace").strip()


async def _command_bytes(args: list[str], *, timeout: float = 0.5) -> tuple[int | None, bytes, bytes]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return None, b"", b"not found"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await proc.wait()
        except Exception:
            pass
        return None, b"", b"timeout"
    return proc.returncode, out, err


def _parse_gsettings_current(raw: str) -> int | None:
    matches = re.findall(r"\d+", raw or "")
    if not matches:
        return None
    try:
        return int(matches[-1])
    except ValueError:
        return None


def _parse_gsettings_sources(raw: str) -> list[tuple[str, str]]:
    text = (raw or "").strip()
    if not text:
        return []
    try:
        parsed = ast.literal_eval(text)
    except Exception:
        parsed = None
    if isinstance(parsed, list):
        out: list[tuple[str, str]] = []
        for item in parsed:
            if isinstance(item, tuple) and len(item) == 2:
                out.append((str(item[0]), str(item[1])))
        if out:
            return out
    return [(a, b) for a, b in re.findall(r"\('([^']+)',\s*'([^']+)'\)", text)]


def _source_id_uses_us_keycodes(source_type: str, source_id: str) -> bool:
    if source_type != "xkb":
        return False
    return source_id.lower() in _FAST_TYPE_US_LAYOUTS


def _parse_ibus_engine(raw: str) -> tuple[str, str] | None:
    text = (raw or "").strip()
    if not text or text.lower() in {"none", "no engine is set."}:
        return None
    parts = text.split(":")
    if len(parts) < 2:
        return None
    source_type = parts[0].strip()
    source_id = parts[1].strip()
    if not source_type or not source_id:
        return None
    return source_type, source_id


async def _linux_fast_type_safe_for_current_layout() -> bool:
    if sys.platform == "win32":
        return True
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if desktop and "gnome" not in desktop and "ubuntu" not in desktop:
        return False

    # GNOME's gsettings "current" value can lag behind the visible layout under
    # Wayland. IBus exposes the live engine on the Ubuntu/GNOME path we use.
    ibus_engine = _parse_ibus_engine(await _command_stdout(["ibus", "engine"]))
    if ibus_engine is not None:
        return _source_id_uses_us_keycodes(*ibus_engine)

    current_raw, sources_raw = await asyncio.gather(
        _command_stdout(["gsettings", "get", "org.gnome.desktop.input-sources", "current"]),
        _command_stdout(["gsettings", "get", "org.gnome.desktop.input-sources", "sources"]),
    )
    idx = _parse_gsettings_current(current_raw)
    sources = _parse_gsettings_sources(sources_raw)
    if idx is None or idx < 0 or idx >= len(sources):
        return False
    if len(sources) != 1:
        log.info("direct type disabled; multiple input sources configured but live layout is unavailable")
        return False
    source_type, source_id = sources[idx]
    return _source_id_uses_us_keycodes(source_type, source_id)


def _ascii_key_chord(ch: str) -> list[str] | None:
    shifted = False
    key = ch
    if "A" <= ch <= "Z":
        shifted = True
        key = ch.lower()
    elif ch in _ASCII_SHIFTED:
        shifted = True
        key = _ASCII_SHIFTED[ch]
    code = _ASCII_KEYCODES.get(key)
    if code is None:
        return None
    down = f"{code}:1"
    up = f"{code}:0"
    if shifted:
        return [SHIFT_DOWN, down, up, SHIFT_UP]
    return [down, up]


async def _ydotool_type_ascii_fast(text: str) -> bool:
    keycodes: list[str] = []
    for ch in text:
        chord = _ascii_key_chord(ch)
        if chord is None:
            return False
        keycodes.extend(chord)
    if not keycodes:
        return True
    return await _ydotool_keys(keycodes, delay_ms=0)


def _preferred_clipboard_mime_type(mime_types: list[str]) -> str | None:
    types = [
        mime_type.strip()
        for mime_type in mime_types
        if mime_type.strip() and mime_type.strip() not in _SPECIAL_CLIPBOARD_MIME_TYPES
    ]
    if not types:
        return None
    for preferred in ("text/plain;charset=utf-8", "text/plain"):
        if preferred in types:
            return preferred
    for mime_type in types:
        if mime_type.startswith("text/plain"):
            return mime_type
    return types[0]


async def _wayland_clipboard_snapshot() -> _WaylandClipboardSnapshot | None:
    rc, out, err = await _command_bytes(
        ["wl-paste", "--list-types"],
        timeout=_CLIPBOARD_SNAPSHOT_TIMEOUT_SECONDS,
    )
    if rc is None:
        log.error("clipboard snapshot failed: wl-paste --list-types %r", err[:200])
        return None
    if rc != 0:
        err_text = err.decode("utf-8", "replace").lower()
        if "nothing is copied" in err_text or "no selection" in err_text:
            return _WaylandClipboardSnapshot(mime_type=None)
        log.error("clipboard snapshot failed: wl-paste --list-types rc=%s err=%r", rc, err[:200])
        return None
    if not out.strip():
        return _WaylandClipboardSnapshot(mime_type=None)

    mime_types = out.decode("utf-8", "replace").splitlines()
    mime_type = _preferred_clipboard_mime_type(mime_types)
    if mime_type is None:
        return _WaylandClipboardSnapshot(mime_type=None)

    rc, data, err = await _command_bytes(
        ["wl-paste", "--no-newline", "--type", mime_type],
        timeout=_CLIPBOARD_SNAPSHOT_TIMEOUT_SECONDS,
    )
    if rc is None or rc != 0:
        log.error("clipboard snapshot failed: wl-paste --type %s rc=%s err=%r", mime_type, rc, err[:200])
        return None
    return _WaylandClipboardSnapshot(mime_type=mime_type, data=data)


async def _restore_wayland_clipboard(snapshot: _WaylandClipboardSnapshot) -> bool:
    if snapshot.mime_type is None:
        return await _wl_clear()
    return await _wl_copy_bytes(
        snapshot.data,
        paste_once=False,
        mime_type=snapshot.mime_type,
    )


async def _wayland_clipboard_paste(
    text: str,
    *,
    settle_seconds: float,
    consume_timeout: float,
    key_delay_ms: int,
) -> bool:
    snapshot = await _wayland_clipboard_snapshot()
    if snapshot is None:
        return False
    proc = await _start_wl_copy(text, paste_once=True)
    if proc is None:
        return False
    try:
        await asyncio.sleep(max(settle_seconds, 0.12))
        for name, chord in PASTE_CHORDS:
            keys_ok = await _ydotool_keys(chord, delay_ms=key_delay_ms)
            if not keys_ok:
                log.warning("paste chord failed chord=%s", name)
                continue
            consumed = await _wait_wl_copy(
                proc,
                timeout=max(0.05, consume_timeout),
                kill_on_timeout=False,
            )
            if consumed:
                log.info("output method=paste backend=wayland chord=%s chars=%d", name, len(text))
                return True
            if proc.returncode is not None:
                return False
            log.warning("paste chord did not consume clipboard chord=%s", name)
        return False
    finally:
        await _stop_wl_copy(proc)
        restored = await _restore_wayland_clipboard(snapshot)
        if not restored:
            log.warning("failed to restore clipboard after paste attempt")


_windows_types: tuple | None = None


def _windows_input_types():
    global _windows_types
    if _windows_types is not None:
        return _windows_types
    import ctypes

    ulong_ptr = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ulong_ptr),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ulong_ptr),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.c_ulong),
            ("wParamL", ctypes.c_ushort),
            ("wParamH", ctypes.c_ushort),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("u", INPUT_UNION)]

    _windows_types = (ctypes, KEYBDINPUT, INPUT_UNION, INPUT)
    return _windows_types


def _windows_key_input(vk: int, scan: int, flags: int):
    ctypes, keybdinput, input_union, input_type = _windows_input_types()
    return input_type(
        1,
        input_union(ki=keybdinput(vk, scan, flags, 0, 0)),
    )


def _windows_send(inputs) -> bool:
    ctypes, _keybdinput, _input_union, input_type = _windows_input_types()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(input_type), ctypes.c_int)
    user32.SendInput.restype = ctypes.c_uint
    sent = user32.SendInput(len(inputs), inputs, ctypes.sizeof(input_type))
    if sent != len(inputs):
        log.error("SendInput sent %d/%d events", sent, len(inputs))
        return False
    return True


def _windows_send_unicode_units(units: list[int]) -> bool:
    _ctypes, _keybdinput, _input_union, input_type = _windows_input_types()
    keyeventf_keyup = 0x0002
    keyeventf_unicode = 0x0004
    events = []
    for unit in units:
        events.append(_windows_key_input(0, unit, keyeventf_unicode))
        events.append(_windows_key_input(0, unit, keyeventf_unicode | keyeventf_keyup))
    inputs = (input_type * len(events))(*events)
    return _windows_send(inputs)


def _windows_type_text(text: str, delay_ms: int) -> bool:
    import time

    encoded = text.encode("utf-16-le")
    units = [int.from_bytes(encoded[i : i + 2], "little") for i in range(0, len(encoded), 2)]
    if not units:
        return True
    if delay_ms <= 0:
        chunk_size = 512
        for i in range(0, len(units), chunk_size):
            if not _windows_send_unicode_units(units[i : i + chunk_size]):
                return False
        return True
    for unit in units:
        if not _windows_send_unicode_units([unit]):
            return False
        time.sleep(delay_ms / 1000)
    return True


def _windows_key_chord(vks: list[int], delay_ms: int) -> bool:
    import time

    ctypes, _keybdinput, _input_union, input_type = _windows_input_types()
    keyeventf_keyup = 0x0002
    events = [_windows_key_input(vk, 0, 0) for vk in vks]
    events.extend(_windows_key_input(vk, 0, keyeventf_keyup) for vk in reversed(vks))
    inputs = (input_type * len(events))(*events)
    ok = _windows_send(inputs)
    if ok and delay_ms > 0:
        time.sleep(delay_ms / 1000)
    return ok


def _windows_paste(delay_ms: int) -> bool:
    return _windows_key_chord([0x11, 0x56], delay_ms)


def _windows_backspace(count: int) -> bool:
    for _ in range(count):
        if not _windows_key_chord([0x08], 0):
            return False
    return True


def _windows_copy_text(text: str) -> bool:
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    data = (text + "\0").encode("utf-16-le")
    gmem_moveable = 0x0002
    cf_unicode_text = 13

    kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalFree.argtypes = (ctypes.c_void_p,)
    user32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)
    user32.SetClipboardData.restype = ctypes.c_void_p

    handle = kernel32.GlobalAlloc(gmem_moveable, len(data))
    if not handle:
        return False
    locked = kernel32.GlobalLock(handle)
    if not locked:
        kernel32.GlobalFree(handle)
        return False
    ctypes.memmove(locked, data, len(data))
    kernel32.GlobalUnlock(handle)

    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(handle)
        return False
    try:
        if not user32.EmptyClipboard():
            return False
        if not user32.SetClipboardData(cf_unicode_text, handle):
            return False
        handle = None
        return True
    finally:
        user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)


def should_direct_type(
    text: str,
    *,
    max_chars: int = DEFAULT_DIRECT_TYPE_MAX_CHARS,
    ascii_only: bool = True,
) -> bool:
    if not text or len(text) > max_chars:
        return False
    if any(ch in "\r\n\t" for ch in text):
        return False
    if ascii_only:
        return all(0x20 <= ord(ch) <= 0x7E for ch in text)
    return all(ord(ch) >= 0x20 for ch in text)


async def _paste_text(
    text: str,
    *,
    settle_seconds: float,
    consume_timeout: float,
    key_delay_ms: int,
    type_key_delay_ms: int,
    direct_type_max_chars: int,
    direct_type_ascii_only: bool,
    prefer_clipboard_paste: bool,
    backend: OutputBackend | None = None,
) -> bool:
    if not text:
        return True
    out = backend or output_backend()
    direct_typable = should_direct_type(
        text,
        max_chars=direct_type_max_chars,
        ascii_only=direct_type_ascii_only,
    )
    if prefer_clipboard_paste:
        pasted = await out.paste_text(
            text,
            settle_seconds=settle_seconds,
            consume_timeout=consume_timeout,
            key_delay_ms=key_delay_ms,
        )
        if pasted:
            return True
        if direct_typable:
            log.warning("clipboard paste failed; falling back to direct type chars=%d", len(text))
            typed = await out.type_text(text, delay_ms=type_key_delay_ms)
            if typed:
                log.info("output method=type-fallback backend=%s chars=%d", out.name, len(text))
                return True
        return False
    if direct_typable:
        typed = await out.type_text(text, delay_ms=type_key_delay_ms)
        if typed:
            log.info("output method=type backend=%s chars=%d", out.name, len(text))
            return True
        log.warning("direct type failed; falling back to clipboard paste chars=%d", len(text))
    return await out.paste_text(
        text,
        settle_seconds=settle_seconds,
        consume_timeout=consume_timeout,
        key_delay_ms=key_delay_ms,
    )


async def paste_final(
    text: str,
    *,
    settle_seconds: float,
    consume_timeout: float,
    key_delay_ms: int = DEFAULT_PASTE_KEY_DELAY_MS,
    type_key_delay_ms: int = DEFAULT_TYPE_KEY_DELAY_MS,
    direct_type_max_chars: int = DEFAULT_DIRECT_TYPE_MAX_CHARS,
    direct_type_ascii_only: bool = True,
    prefer_clipboard_paste: bool = DEFAULT_PREFER_CLIPBOARD_PASTE,
    backend: OutputBackend | None = None,
) -> bool:
    return await _paste_text(
        text,
        settle_seconds=settle_seconds,
        consume_timeout=consume_timeout,
        key_delay_ms=key_delay_ms,
        type_key_delay_ms=type_key_delay_ms,
        direct_type_max_chars=direct_type_max_chars,
        direct_type_ascii_only=direct_type_ascii_only,
        prefer_clipboard_paste=prefer_clipboard_paste,
        backend=backend,
    )


async def stream_replace(
    *,
    previous: str,
    new: str,
    settle_seconds: float,
    max_rewrite_chars: int,
    consume_timeout: float = 1.5,
    key_delay_ms: int = DEFAULT_PASTE_KEY_DELAY_MS,
    type_key_delay_ms: int = DEFAULT_TYPE_KEY_DELAY_MS,
    direct_type_max_chars: int = DEFAULT_DIRECT_TYPE_MAX_CHARS,
    direct_type_ascii_only: bool = True,
    prefer_clipboard_paste: bool = DEFAULT_PREFER_CLIPBOARD_PASTE,
    backend: OutputBackend | None = None,
) -> bool:
    """Backspace common-prefix divergence and append replacement text."""
    out = backend or output_backend()
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
        ok = await out.backspace(backspaces)
        if not ok:
            return False
    if addition:
        ok = await _paste_text(
            addition,
            settle_seconds=settle_seconds,
            consume_timeout=consume_timeout,
            key_delay_ms=key_delay_ms,
            type_key_delay_ms=type_key_delay_ms,
            direct_type_max_chars=direct_type_max_chars,
            direct_type_ascii_only=direct_type_ascii_only,
            prefer_clipboard_paste=prefer_clipboard_paste,
            backend=out,
        )
        if not ok:
            return False
    return True
