"""Native keyboard registration and a pass-through mouse-button hook."""

import ctypes
import os
import sys
from ctypes import wintypes

MOUSE_BUTTONS = {"MIDDLE MOUSE": 0x207, "MOUSE BUTTON 4": 1, "MOUSE BUTTON 5": 2}

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    MouseProc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int,
        MouseProc,
        wintypes.HINSTANCE,
        wintypes.DWORD,
    ]
    user32.SetWindowsHookExW.restype = wintypes.HANDLE
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
    user32.CallNextHookEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class MouseEvent(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


def parse_mouse_shortcut(text):
    parts = [part.strip().upper() for part in text.split("+")]
    if parts[-1] not in MOUSE_BUTTONS:
        return None
    modifiers = {"CTRL": 2, "ALT": 1, "SHIFT": 4, "WIN": 8}
    if len(set(parts)) != len(parts) or any(p not in modifiers for p in parts[:-1]):
        raise ValueError("Use Ctrl, Alt, Shift, or Win with a middle or side mouse button")
    return sum(modifiers[p] for p in parts[:-1]), parts[-1]


def mouse_message_matches(button, message, mouse_data):
    if button == "MIDDLE MOUSE":
        return message == 0x207  # WM_MBUTTONDOWN; release must not trigger a second capture.
    return message == 0x20B and (mouse_data >> 16) == MOUSE_BUTTONS[button]


class MouseHook:
    def __init__(self, modifiers, button, notify):
        self.handle = None

        @MouseProc
        def procedure(code, message, data):
            if code >= 0 and message in (0x207, 0x20B):
                event = ctypes.cast(data, ctypes.POINTER(MouseEvent)).contents
                if mouse_message_matches(button, message, event.mouseData):
                    mask = 0
                    for flag, keys in ((2, (0x11,)), (1, (0x12,)), (4, (0x10,)), (8, (0x5B, 0x5C))):
                        if any(user32.GetAsyncKeyState(key) & 0x8000 for key in keys):
                            mask |= flag
                    if mask == modifiers:
                        notify()  # Only queues a Qt signal; never capture or write files here.
            return user32.CallNextHookEx(self.handle, code, message, data)

        self.procedure = procedure  # Keep the ctypes callback alive until unhooked.
        self.handle = user32.SetWindowsHookExW(14, procedure, kernel32.GetModuleHandleW(None), 0)
        if not self.handle:
            raise OSError(
                f"Cannot register mouse shortcut (Windows error {ctypes.get_last_error()})"
            )

    def close(self):
        if self.handle:
            user32.UnhookWindowsHookEx(self.handle)
            self.handle = None


def enable_dpi_awareness():
    if sys.platform == "win32":
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))


def foreground():
    hwnd = user32.GetForegroundWindow()
    process = wintypes.DWORD()
    if hwnd:
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
    return hwnd, process.value


def window_rect(hwnd):
    if not hwnd or not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        raise OSError("Active window is unavailable or minimized")
    rect = wintypes.RECT()
    result = dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
    if result != 0 and not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    if rect.right <= rect.left or rect.bottom <= rect.top:
        raise OSError("Active window has no visible area")
    return {
        "left": rect.left,
        "top": rect.top,
        "width": rect.right - rect.left,
        "height": rect.bottom - rect.top,
    }


def parse_hotkey(text):
    parts = [part.strip().upper() for part in text.split("+")]
    keys = {
        **{f"F{i}": 0x6F + i for i in range(1, 12)},
        **{c: ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
    }
    modifiers = {"CTRL": 2, "ALT": 1, "SHIFT": 4, "WIN": 8}
    if len(parts) < 2 or parts[-1] not in keys or len(set(parts)) != len(parts):
        raise ValueError(
            "Use modifiers plus F1–F11, A–Z, or 0–9, e.g. Ctrl+Alt+F9. F12 is reserved."
        )
    mask = 0x4000  # MOD_NOREPEAT
    for part in parts[:-1]:
        if part not in modifiers:
            raise ValueError(f"Unknown shortcut modifier: {part}")
        mask |= modifiers[part]
    if not (mask & (1 | 2 | 8)):
        raise ValueError("Include Ctrl, Alt, or Win in the shortcut")
    return mask, keys[parts[-1]]


def install_hotkey(app, callback, shortcut):
    from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, Signal

    class MouseDispatch(QObject):
        triggered = Signal()

    class Hotkey(QAbstractNativeEventFilter):
        def __init__(self):
            super().__init__()
            self.key_id = 0x5141
            self.registered = False
            self.mouse_hook = None
            self.dispatch = MouseDispatch()
            self.dispatch.triggered.connect(self._mouse_fired, Qt.QueuedConnection)
            app.installNativeEventFilter(self)

        def configure(self, text):
            mouse = parse_mouse_shortcut(text)
            if mouse:
                new_hook = MouseHook(*mouse, self.dispatch.triggered.emit)
                if self.mouse_hook:
                    self.mouse_hook.close()
                if self.registered:
                    user32.UnregisterHotKey(None, self.key_id)
                    self.registered = False
                self.mouse_hook = new_hook
                return
            modifiers, key = parse_hotkey(text)
            # Register a second id first; a conflict never destroys the working shortcut.
            candidate = 0x5142 if self.key_id == 0x5141 else 0x5141
            if not user32.RegisterHotKey(None, candidate, modifiers, key):
                code = ctypes.get_last_error()
                reason = (
                    "Windows denied access to global hotkeys"
                    if code == 5
                    else "another application may use it"
                )
                raise OSError(f"Cannot register {text}; {reason} (Windows error {code}).")
            if self.registered:
                user32.UnregisterHotKey(None, self.key_id)
            self.key_id, self.registered = candidate, True
            if self.mouse_hook:
                self.mouse_hook.close()
                self.mouse_hook = None

        def _mouse_fired(self):
            if self.mouse_hook:
                callback()

        def nativeEventFilter(self, event_type, message):
            msg = wintypes.MSG.from_address(int(message))
            if self.registered and msg.message == 0x0312 and msg.wParam == self.key_id:
                callback()
                return True, 0
            return False, 0

        def close(self):
            if self.mouse_hook:
                self.mouse_hook.close()
                self.mouse_hook = None
            if self.registered:
                user32.UnregisterHotKey(None, self.key_id)
                self.registered = False
            app.removeNativeEventFilter(self)

    hotkey = Hotkey()
    try:
        hotkey.configure(shortcut)
    except Exception:
        hotkey.close()
        raise
    return hotkey


def capture_target(mode, monitor_index):
    hwnd, pid = foreground()
    if pid == os.getpid():
        raise ValueError("Switch to the application being reviewed before capturing a screenshot")
    return {"hwnd": hwnd, "mode": mode, "monitor": monitor_index}
