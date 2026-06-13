from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes as wintypes
import logging
import threading

from .key_event import KeyEvent

log = logging.getLogger(__name__)

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
LLKHF_EXTENDED = 0x01
LLKHF_INJECTED = 0x10
HC_ACTION = 0

DEVICE_NAME = "Windows low-level keyboard hook"

_VK_TO_EVDEV = {
    0x08: 14,   # backspace
    0x09: 15,   # tab
    0x0D: 28,   # enter
    0x10: 42,   # shift
    0x11: 29,   # ctrl
    0x12: 56,   # alt
    0x14: 58,   # caps lock
    0x1B: 1,    # escape
    0x20: 57,   # space
    0x30: 11,
    0x31: 2,
    0x32: 3,
    0x33: 4,
    0x34: 5,
    0x35: 6,
    0x36: 7,
    0x37: 8,
    0x38: 9,
    0x39: 10,
    0x41: 30,
    0x42: 48,
    0x43: 46,
    0x44: 32,
    0x45: 18,
    0x46: 33,
    0x47: 34,
    0x48: 35,
    0x49: 23,
    0x4A: 36,
    0x4B: 37,
    0x4C: 38,
    0x4D: 50,
    0x4E: 49,
    0x4F: 24,
    0x50: 25,
    0x51: 16,
    0x52: 19,
    0x53: 31,
    0x54: 20,
    0x55: 22,
    0x56: 47,
    0x57: 17,
    0x58: 45,
    0x59: 21,
    0x5A: 44,
    0x70: 59,
    0x71: 60,
    0x72: 61,
    0x73: 62,
    0x74: 63,
    0x75: 64,
    0x76: 65,
    0x77: 66,
    0x78: 67,
    0x79: 68,
    0x7A: 87,
    0x7B: 88,
    0xBA: 39,   # semicolon
    0xBB: 13,   # equal
    0xBC: 51,   # comma
    0xBD: 12,   # minus
    0xBE: 52,   # period
    0xBF: 53,   # slash
    0xC0: 41,   # grave/backquote
    0xDB: 26,   # left bracket
    0xDC: 43,   # backslash
    0xDD: 27,   # right bracket
    0xDE: 40,   # quote
}

# For the main key block, Windows set-1 scan codes equal Linux evdev keycodes
# (grave=41, 1..0=2..11, F8=66, ...), so configured trigger keycodes work
# unchanged. Extended (E0-prefixed) keys need an explicit map.
_EXTENDED_TO_EVDEV = {
    0x1C: 96,   # keypad enter
    0x1D: 97,   # right ctrl
    0x35: 98,   # keypad slash
    0x38: 100,  # right alt
    0x47: 102,  # home
    0x48: 103,  # up
    0x49: 104,  # page up
    0x4B: 105,  # left
    0x4D: 106,  # right
    0x4F: 107,  # end
    0x50: 108,  # down
    0x51: 109,  # page down
    0x52: 110,  # insert
    0x53: 111,  # delete
    0x5B: 125,  # left win
    0x5C: 126,  # right win
    0x5D: 127,  # menu
}


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


_LRESULT = ctypes.c_ssize_t
_HOOKPROC = ctypes.WINFUNCTYPE(_LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class WindowsInputSupervisor:
    """System-wide key events via a WH_KEYBOARD_LL hook in its own thread.

    Mirrors the Linux evdev InputSupervisor interface. "Grabbing" swallows
    every physical key event while active (combo selection); configured
    trigger keys are always swallowed so holding the dictation key does not
    type into the focused app — the GNOME shortcut binding does the same on
    Linux.
    """

    def __init__(
        self,
        on_key,
        *,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        trigger_codes_provider=None,
    ) -> None:
        self._on_key = on_key
        self._trigger_codes_provider = trigger_codes_provider or (lambda: set())
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._hook = None
        self._proc_ref = None  # keep callback alive for ctypes
        self._grab_active = False
        self._grabbed = False  # daemon pokes this attr on the Linux backend
        self._down_codes: set[int] = set()
        self._started = threading.Event()

    async def start(self) -> None:
        self._loop = asyncio.get_event_loop()
        self._thread = threading.Thread(target=self._run, name="mywhispr-kbd-hook", daemon=True)
        self._thread.start()
        await asyncio.to_thread(self._started.wait, 5.0)
        if self._hook:
            log.info("keyboard hook installed")
        else:
            log.error("keyboard hook failed to install")

    async def stop(self) -> None:
        if self._thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 3.0)
        self._thread = None
        self._thread_id = None

    def grab_for_combo(self) -> int:
        self._grab_active = True
        self._grabbed = True
        log.info("grab acquired (hook swallow mode)")
        return 1

    def ungrab_all(self) -> None:
        if not self._grab_active:
            return
        self._grab_active = False
        self._grabbed = False
        log.info("grab released")

    def device_names(self) -> list[str]:
        return [DEVICE_NAME] if self._hook else []

    # ------------------------------------------------------------ hook thread

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # 64-bit handle/LRESULT safety: ctypes defaults truncate to c_int.
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        user32.CallNextHookEx.restype = _LRESULT
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        self._thread_id = kernel32.GetCurrentThreadId()

        @_HOOKPROC
        def proc(n_code, w_param, l_param):
            try:
                if n_code == HC_ACTION:
                    kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    if not (kb.flags & LLKHF_INJECTED):
                        swallow = self._handle(kb, int(w_param))
                        if swallow:
                            return 1
            except Exception:
                log.exception("keyboard hook handler crashed")
            return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

        self._proc_ref = proc
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, None, 0)
        self._started.set()
        if not self._hook:
            log.error("SetWindowsHookExW failed: %s", ctypes.get_last_error())
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None

    def _handle(self, kb: KBDLLHOOKSTRUCT, w_param: int) -> bool:
        """Translate, report to the asyncio loop, decide whether to swallow."""
        scan = int(kb.scanCode) & 0xFF
        if kb.flags & LLKHF_EXTENDED:
            code = _EXTENDED_TO_EVDEV.get(scan, 0)
        else:
            code = scan
        if not code:
            code = _VK_TO_EVDEV.get(int(kb.vkCode), 0)
        if not code:
            return False
        is_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
        if is_down:
            value = 2 if code in self._down_codes else 1
            self._down_codes.add(code)
        else:
            value = 0
            self._down_codes.discard(code)
        if self._loop is not None and value in (0, 1):
            ev = KeyEvent("winhook", DEVICE_NAME, code, value)
            self._loop.call_soon_threadsafe(self._emit, ev)
        if self._grab_active:
            return True
        try:
            return code in self._trigger_codes_provider()
        except Exception:
            return False

    def _emit(self, ev: KeyEvent) -> None:
        try:
            self._on_key(ev)
        except Exception:
            log.exception("on_key handler crashed")
