from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import os
import threading
import webbrowser
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_KILLFOCUS = 0x0008
WM_KEYDOWN = 0x0100
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
WM_MOUSEMOVE = 0x0200
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_TIMER = 0x0113

VK_ESCAPE = 0x1B

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
CS_DROPSHADOW = 0x00020000
SW_SHOW = 5

MONITOR_DEFAULTTONEAREST = 0x00000002

PS_SOLID = 0
TRANSPARENT = 1
CLEARTYPE_QUALITY = 5
DEFAULT_CHARSET = 1
FW_NORMAL = 400

DT_LEFT = 0x00000000
DT_RIGHT = 0x00000002
DT_VCENTER = 0x00000004
DT_SINGLELINE = 0x00000020
DT_NOPREFIX = 0x00000800
DT_END_ELLIPSIS = 0x00008000

NIM_ADD = 0x0
NIM_MODIFY = 0x1
NIM_DELETE = 0x2
NIM_SETVERSION = 0x4
NIF_MESSAGE = 0x1
NIF_ICON = 0x2
NIF_TIP = 0x4
NIF_INFO = 0x10
NOTIFYICON_VERSION_4 = 4
NIIF_INFO = 0x1
NIIF_NOSOUND = 0x10

MF_STRING = 0x0
MF_GRAYED = 0x1
MF_SEPARATOR = 0x800
TPM_RIGHTBUTTON = 0x2
TPM_RETURNCMD = 0x100

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x10
LR_DEFAULTSIZE = 0x40

IDM_OPEN = 1001
IDM_QUIT = 1002
TIMER_ID = 1

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

# daemon state -> icon file
_STATE_ICONS = {
    "RECORDING": "tray-recording.ico",
    "STARTING": "tray-recording.ico",
    "STOPPING": "tray-busy.ico",
    "STOPPING_NO_PASTE": "tray-busy.ico",
    "TRANSCRIBING": "tray-busy.ico",
    "TRANSCRIBING_NO_PASTE": "tray-busy.ico",
    "PASTING": "tray-busy.ico",
}
_IDLE_ICON = "tray-idle.ico"

_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM
)


def _rgb(r: int, g: int, b: int) -> int:
    return int(r) | (int(g) << 8) | (int(b) << 16)


def _scale(value: int, dpi: int) -> int:
    return max(1, int(round(value * dpi / 96)))


def _rect(left: int, top: int, right: int, bottom: int) -> wintypes.RECT:
    return wintypes.RECT(left, top, right, bottom)


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class TrayIcon:
    """System tray icon: tooltip shows daemon state and active model, the icon
    color tracks recording/busy state, left click opens the control panel,
    right click offers Open / Quit."""

    def __init__(self, *, url: str, state_provider, model_provider, on_quit) -> None:
        self.url = url
        self.state_provider = state_provider
        self.model_provider = model_provider
        self.on_quit = on_quit
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._active = False
        self._hwnd = None
        self._icons: dict[str, int] = {}
        self._current_icon = ""
        self._current_tip = ""
        self._wndproc_ref = None
        self._taskbar_created_msg = 0
        self._menu_hwnd = None
        self._menu_wndproc_ref = None
        self._menu_class_name = ""
        self._menu_hover_id = 0
        self._menu_font = None
        self._menu_font_dpi = 0

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return self._active
        self._ready.clear()
        self._active = False
        self._thread = threading.Thread(target=self._run, name="mywhispr-tray", daemon=True)
        self._thread.start()
        if not self._ready.wait(2.0):
            log.warning("tray icon did not become ready within startup timeout")
        return self._active

    def stop(self) -> None:
        if self._hwnd:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
            user32.PostMessageW.restype = wintypes.BOOL
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        if self._thread is not None:
            self._thread.join(3.0)
            self._thread = None
        self._active = False

    # ------------------------------------------------------------ tray thread

    def _load_icon(self, filename: str) -> int:
        if filename in self._icons:
            return self._icons[filename]
        path = ASSETS_DIR / filename
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.LoadImageW.restype = wintypes.HICON
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE, wintypes.LPCWSTR, ctypes.c_uint,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        ]
        user32.LoadIconW.restype = wintypes.HICON
        user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        h = user32.LoadImageW(None, str(path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if not h:
            log.warning("tray icon asset missing: %s", path)
            h = user32.LoadIconW(None, ctypes.c_void_p(32512))  # IDI_APPLICATION
        self._icons[filename] = h
        return h

    def _icon_for_state(self, state: str) -> str:
        return _STATE_ICONS.get(str(state or "").upper(), _IDLE_ICON)

    def _tooltip(self) -> str:
        state = str(self.state_provider() or "idle").lower().replace("_", " ")
        model = str(self.model_provider() or "")
        tip = f"MyWhispr - {state}"
        if model:
            tip += f" | {model}"
        return tip[:127]

    def _status_label(self) -> str:
        state = str(self.state_provider() or "idle").lower().replace("_", " ")
        model = str(self.model_provider() or "")
        if model:
            return f"State: {state} | Model: {model}"[:127]
        return f"State: {state}"[:127]

    def _nid(self, flags: int) -> _NOTIFYICONDATAW:
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAYICON
        return nid

    def _notify(self, action: int, nid: _NOTIFYICONDATAW) -> bool:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL
        shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(_NOTIFYICONDATAW)]
        ok = bool(shell32.Shell_NotifyIconW(action, ctypes.byref(nid)))
        if not ok:
            log.warning("Shell_NotifyIconW action=%s failed: %s", action, ctypes.get_last_error())
        return ok

    def _add_icon(self) -> bool:
        nid = self._nid(NIF_ICON | NIF_TIP | NIF_MESSAGE)
        self._current_icon = self._icon_for_state(self.state_provider())
        self._current_tip = self._tooltip()
        nid.hIcon = self._load_icon(self._current_icon)
        nid.szTip = self._current_tip
        if not self._notify(NIM_ADD, nid):
            return False

        version_nid = self._nid(0)
        version_nid.uVersion = NOTIFYICON_VERSION_4
        self._notify(NIM_SETVERSION, version_nid)
        return True

    def _show_startup_notice(self) -> None:
        nid = self._nid(NIF_INFO)
        nid.szInfoTitle = "MyWhispr"
        nid.szInfo = "MyWhispr is running. Click the tray icon to open the control panel."
        nid.dwInfoFlags = NIIF_INFO | NIIF_NOSOUND
        self._notify(NIM_MODIFY, nid)

    def _update(self) -> None:
        icon = self._icon_for_state(self.state_provider())
        tip = self._tooltip()
        if icon == self._current_icon and tip == self._current_tip:
            return
        nid = self._nid(NIF_ICON | NIF_TIP | NIF_MESSAGE)
        nid.hIcon = self._load_icon(icon)
        nid.szTip = tip
        if not self._notify(NIM_MODIFY, nid):
            return
        self._current_icon = icon
        self._current_tip = tip

    def _dpi_for_window(self, hwnd) -> int:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        try:
            user32.GetDpiForWindow.restype = ctypes.c_uint
            user32.GetDpiForWindow.argtypes = [wintypes.HWND]
            dpi = int(user32.GetDpiForWindow(hwnd))
            return dpi or 96
        except Exception:
            return 96

    def _menu_size(self, dpi: int) -> tuple[int, int]:
        return _scale(326, dpi), _scale(142, dpi)

    def _menu_layout(self, dpi: int, width: int) -> dict[str, Any]:
        pad = _scale(10, dpi)
        status_h = _scale(34, dpi)
        row_h = _scale(40, dpi)
        sep_gap = _scale(5, dpi)
        sep1 = pad + status_h + sep_gap
        open_top = sep1 + _scale(1, dpi) + sep_gap
        quit_top = open_top + row_h + _scale(1, dpi)
        return {
            "pad": pad,
            "radius": _scale(12, dpi),
            "row_radius": _scale(8, dpi),
            "status": _rect(pad + _scale(12, dpi), pad, width - pad - _scale(12, dpi), pad + status_h),
            "status_model": _rect(width // 2, pad, width - pad - _scale(12, dpi), pad + status_h),
            "sep1": sep1,
            "open": _rect(pad, open_top, width - pad, open_top + row_h),
            "sep2": open_top + row_h,
            "quit": _rect(pad, quit_top, width - pad, quit_top + row_h),
            "text_left": pad + _scale(18, dpi),
        }

    def _menu_command_at(self, x: int, y: int) -> int:
        dpi = self._dpi_for_window(self._menu_hwnd or self._hwnd)
        width, _height = self._menu_size(dpi)
        layout = self._menu_layout(dpi, width)
        for cmd, key in ((IDM_OPEN, "open"), (IDM_QUIT, "quit")):
            rc = layout[key]
            if rc.left <= x <= rc.right and rc.top <= y <= rc.bottom:
                return cmd
        return 0

    def _ensure_menu_font(self, dpi: int):
        if self._menu_font and self._menu_font_dpi == dpi:
            return self._menu_font
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        if self._menu_font:
            gdi32.DeleteObject(self._menu_font)
        gdi32.CreateFontW.restype = wintypes.HFONT
        gdi32.CreateFontW.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            wintypes.LPCWSTR,
        ]
        self._menu_font = gdi32.CreateFontW(
            -_scale(15, dpi), 0, 0, 0, FW_NORMAL, 0, 0, 0,
            DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, "Segoe UI",
        )
        self._menu_font_dpi = dpi
        return self._menu_font

    def _destroy_menu(self) -> None:
        if not self._menu_hwnd:
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.DestroyWindow(self._menu_hwnd)

    def _perform_menu_command(self, cmd: int) -> None:
        self._destroy_menu()
        if cmd == IDM_OPEN:
            webbrowser.open(self.url)
        elif cmd == IDM_QUIT:
            try:
                self.on_quit()
            except Exception:
                log.exception("tray quit callback failed")

    def _draw_menu_text(self, hdc, text: str, rc: wintypes.RECT, color: int, flags: int) -> None:
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
        gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
        user32.DrawTextW.argtypes = [
            wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), ctypes.c_uint,
        ]
        gdi32.SetTextColor(hdc, color)
        gdi32.SetBkMode(hdc, TRANSPARENT)
        local = _rect(rc.left, rc.top, rc.right, rc.bottom)
        user32.DrawTextW(hdc, text, -1, ctypes.byref(local), flags)

    def _paint_menu(self, hwnd) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        user32.BeginPaint.restype = wintypes.HDC
        user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(_PAINTSTRUCT)]
        user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(_PAINTSTRUCT)]
        user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
        gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
        gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
        gdi32.CreatePen.restype = wintypes.HPEN
        gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
        gdi32.SelectObject.argtypes = [wintypes.HDC, ctypes.c_void_p]
        gdi32.SelectObject.restype = ctypes.c_void_p
        gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        gdi32.RoundRect.argtypes = [
            wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ]
        gdi32.MoveToEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        gdi32.LineTo.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]

        ps = _PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        if not hdc:
            return
        try:
            dpi = self._dpi_for_window(hwnd)
            width, height = self._menu_size(dpi)
            layout = self._menu_layout(dpi, width)

            bg = gdi32.CreateSolidBrush(_rgb(31, 31, 31))
            user32.FillRect(hdc, ctypes.byref(_rect(0, 0, width, height)), bg)
            gdi32.DeleteObject(bg)

            if self._menu_hover_id:
                key = "open" if self._menu_hover_id == IDM_OPEN else "quit"
                rc = layout[key]
                brush = gdi32.CreateSolidBrush(_rgb(47, 47, 47))
                pen = gdi32.CreatePen(PS_SOLID, 1, _rgb(47, 47, 47))
                old_brush = gdi32.SelectObject(hdc, brush)
                old_pen = gdi32.SelectObject(hdc, pen)
                gdi32.RoundRect(
                    hdc, rc.left, rc.top, rc.right, rc.bottom,
                    layout["row_radius"], layout["row_radius"],
                )
                gdi32.SelectObject(hdc, old_pen)
                gdi32.SelectObject(hdc, old_brush)
                gdi32.DeleteObject(pen)
                gdi32.DeleteObject(brush)

            sep_pen = gdi32.CreatePen(PS_SOLID, 1, _rgb(70, 70, 70))
            old_pen = gdi32.SelectObject(hdc, sep_pen)
            for y in (layout["sep1"], layout["sep2"]):
                gdi32.MoveToEx(hdc, _scale(12, dpi), y, None)
                gdi32.LineTo(hdc, width - _scale(12, dpi), y)
            gdi32.SelectObject(hdc, old_pen)
            gdi32.DeleteObject(sep_pen)

            font = self._ensure_menu_font(dpi)
            old_font = gdi32.SelectObject(hdc, font)
            state = str(self.state_provider() or "idle").lower().replace("_", " ")
            model = str(self.model_provider() or "")
            self._draw_menu_text(
                hdc, state.capitalize(), layout["status"], _rgb(174, 198, 214),
                DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS | DT_NOPREFIX,
            )
            if model:
                self._draw_menu_text(
                    hdc, model, layout["status_model"], _rgb(174, 174, 174),
                    DT_RIGHT | DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS | DT_NOPREFIX,
                )
            for key, label in (("open", "Open MyWhispr"), ("quit", "Quit MyWhispr")):
                rc = layout[key]
                text_rc = _rect(layout["text_left"], rc.top, rc.right - _scale(12, dpi), rc.bottom)
                self._draw_menu_text(
                    hdc, label, text_rc, _rgb(245, 245, 245),
                    DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS | DT_NOPREFIX,
                )
            gdi32.SelectObject(hdc, old_font)
        finally:
            user32.EndPaint(hwnd, ctypes.byref(ps))

    def _ensure_menu_class(self) -> bool:
        if self._menu_class_name:
            return True
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        @_WNDPROC
        def menu_wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_PAINT:
                self._paint_menu(hwnd)
                return 0
            if msg == WM_ERASEBKGND:
                return 1
            if msg == WM_MOUSEMOVE:
                x = int(lparam) & 0xFFFF
                y = (int(lparam) >> 16) & 0xFFFF
                cmd = self._menu_command_at(x, y)
                if cmd != self._menu_hover_id:
                    self._menu_hover_id = cmd
                    user32.InvalidateRect(hwnd, None, True)
                return 0
            if msg == WM_LBUTTONUP:
                x = int(lparam) & 0xFFFF
                y = (int(lparam) >> 16) & 0xFFFF
                cmd = self._menu_command_at(x, y)
                if cmd:
                    self._perform_menu_command(cmd)
                else:
                    self._destroy_menu()
                return 0
            if msg == WM_RBUTTONUP or msg == WM_KILLFOCUS:
                self._destroy_menu()
                return 0
            if msg == WM_KEYDOWN and int(wparam) == VK_ESCAPE:
                self._destroy_menu()
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                if self._menu_hwnd == hwnd:
                    self._menu_hwnd = None
                self._menu_hover_id = 0
                if self._menu_font:
                    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
                    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
                    gdi32.DeleteObject(self._menu_font)
                    self._menu_font = None
                    self._menu_font_dpi = 0
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._menu_wndproc_ref = menu_wndproc

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", ctypes.c_uint),
                ("lpfnWndProc", _WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        hinst = kernel32.GetModuleHandleW(None)

        self._menu_class_name = f"MyWhisprTrayMenu-{os.getpid()}-{id(self)}"
        wc = WNDCLASSW()
        wc.style = CS_DROPSHADOW
        wc.lpfnWndProc = menu_wndproc
        wc.hInstance = hinst
        wc.lpszClassName = self._menu_class_name
        if not user32.RegisterClassW(ctypes.byref(wc)):
            log.error("tray menu class registration failed: %s", ctypes.get_last_error())
            self._menu_class_name = ""
            return False
        return True

    def _show_menu(self) -> None:
        if not self._ensure_menu_class():
            return
        self._destroy_menu()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
        ]
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
        user32.SetWindowRgn.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.UpdateWindow.argtypes = [wintypes.HWND]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
        gdi32.CreateRoundRectRgn.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ]

        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        dpi = self._dpi_for_window(self._hwnd)
        width, height = self._menu_size(dpi)

        monitor = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
        work = wintypes.RECT(0, 0, 0, 0)
        if monitor:
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work = info.rcWork
        if work.right <= work.left:
            work = _rect(0, 0, 1920, 1080)

        margin = _scale(8, dpi)
        x = min(max(pt.x, work.left + margin), work.right - width - margin)
        y = min(max(pt.y, work.top + margin), work.bottom - height - margin)
        hinst = kernel32.GetModuleHandleW(None)
        self._menu_hover_id = 0
        self._menu_hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
            self._menu_class_name,
            "MyWhispr",
            WS_POPUP | WS_VISIBLE,
            x,
            y,
            width,
            height,
            self._hwnd,
            None,
            hinst,
            None,
        )
        if not self._menu_hwnd:
            log.error("tray menu window creation failed: %s", ctypes.get_last_error())
            return
        radius = _scale(14, dpi)
        rgn = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, radius, radius)
        if rgn:
            user32.SetWindowRgn(self._menu_hwnd, rgn, True)
        user32.ShowWindow(self._menu_hwnd, SW_SHOW)
        user32.SetForegroundWindow(self._menu_hwnd)
        user32.SetFocus(self._menu_hwnd)
        user32.UpdateWindow(self._menu_hwnd)

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        @_WNDPROC
        def wndproc(hwnd, msg, wparam, lparam):
            if self._taskbar_created_msg and msg == self._taskbar_created_msg:
                self._add_icon()
                return 0
            if msg == WM_TRAYICON:
                event = int(lparam) & 0xFFFF
                if event == WM_LBUTTONUP:
                    webbrowser.open(self.url)
                elif event == WM_RBUTTONUP:
                    self._show_menu()
                return 0
            if msg == WM_TIMER and wparam == TIMER_ID:
                try:
                    self._update()
                except Exception:
                    log.exception("tray update failed")
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                nid = self._nid(0)
                self._notify(NIM_DELETE, nid)
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = wndproc

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", ctypes.c_uint),
                ("lpfnWndProc", _WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            ctypes.c_void_p,
        ]
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.SetTimer.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
        user32.SetTimer.restype = wintypes.UINT
        user32.GetMessageW.restype = ctypes.c_int
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint]
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.RegisterWindowMessageW.restype = ctypes.c_uint
        user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
        user32.DestroyIcon.argtypes = [wintypes.HICON]
        user32.DestroyIcon.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = wndproc
        wc.hInstance = hinst
        wc.lpszClassName = f"MyWhisprTray-{os.getpid()}-{id(self)}"
        if not user32.RegisterClassW(ctypes.byref(wc)):
            log.error("tray window class registration failed: %s", ctypes.get_last_error())
            self._ready.set()
            return
        self._hwnd = user32.CreateWindowExW(
            0, wc.lpszClassName, "MyWhispr", 0, 0, 0, 0, 0, None, None, hinst, None
        )
        if not self._hwnd:
            log.error("tray window creation failed")
            self._ready.set()
            return

        self._taskbar_created_msg = user32.RegisterWindowMessageW("TaskbarCreated")
        if not self._add_icon():
            user32.DestroyWindow(self._hwnd)
            self._hwnd = None
            self._ready.set()
            return
        self._active = True
        self._ready.set()
        user32.SetTimer(self._hwnd, TIMER_ID, 350, None)
        self._show_startup_notice()
        log.info("tray icon active")

        msg = wintypes.MSG()
        while True:
            rc = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if rc <= 0:
                if rc < 0:
                    log.error("tray message loop failed: %s", ctypes.get_last_error())
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        for hicon in self._icons.values():
            try:
                user32.DestroyIcon(hicon)
            except Exception:
                pass
        self._active = False
        self._hwnd = None
