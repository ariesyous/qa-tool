"""Native keyboard registration and a pass-through mouse-button hook."""

import ctypes
import ntpath
import os
import re
import sys
import threading
from ctypes import wintypes

MOUSE_BUTTONS = {"MIDDLE MOUSE": 0x207, "MOUSE BUTTON 4": 1, "MOUSE BUTTON 5": 2}
MAX_ADDITIONAL_SHORTCUTS = 5
_hotkey_ids = set()
_mouse_worker = None
OEM_KEYS = {0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xDB, 0xDC, 0xDD, 0xDE, 0xDF, 0xE2}
NATIVE_KEY = re.compile(r" \[VK:0x([0-9a-f]{2})\]$", re.IGNORECASE)


def shortcut_label(text):
    return NATIVE_KEY.sub("", text)


if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
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
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT,
    ]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL


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


class _MouseHookThread:
    """One native hook and message loop, independent of Qt and disk operations."""

    def __init__(self):
        self.handle = None
        self.bindings = {}
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._run, name="mouse-shortcuts", daemon=True)
        self.thread.start()
        self.ready.wait()
        if self.error:
            self.thread.join()
            raise self.error

    def _run(self):
        @MouseProc
        def procedure(code, message, data):
            if code >= 0 and message in (0x207, 0x20B):
                event = ctypes.cast(data, ctypes.POINTER(MouseEvent)).contents
                mask = 0
                for flag, keys in ((2, (0x11,)), (1, (0x12,)), (4, (0x10,)), (8, (0x5B, 0x5C))):
                    if any(user32.GetAsyncKeyState(key) & 0x8000 for key in keys):
                        mask |= flag
                with self.lock:
                    bindings = tuple(self.bindings.values())
                for modifiers, button, notify in bindings:
                    if mask == modifiers and mouse_message_matches(button, message, event.mouseData):
                        notify()  # Only queues a Qt signal; never capture or write files here.
            return user32.CallNextHookEx(self.handle, code, message, data)

        self.procedure = procedure  # Keep the ctypes callback alive until unhooked.
        try:
            self.thread_id = kernel32.GetCurrentThreadId()
            msg = wintypes.MSG()
            # Create the message queue before the owner can post WM_QUIT.
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
            self.handle = user32.SetWindowsHookExW(14, procedure, kernel32.GetModuleHandleW(None), 0)
            if not self.handle:
                raise OSError(
                    f"Cannot register mouse shortcut (Windows error {ctypes.get_last_error()})"
                )
            self.ready.set()
            while True:
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                if result == 0:
                    break
        except Exception as exc:
            self.error = exc
        finally:
            if self.handle:
                user32.UnhookWindowsHookEx(self.handle)
                self.handle = None
            self.ready.set()

    def close(self):
        if self.thread.is_alive():
            if not user32.PostThreadMessageW(self.thread_id, 0x12, 0, 0):  # WM_QUIT
                raise ctypes.WinError(ctypes.get_last_error())
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise OSError("Mouse shortcut thread did not stop")


class MouseHook:
    """A subscription to the shared mouse hook; accessed by the Qt owner thread."""

    def __init__(self, modifiers, button, notify):
        global _mouse_worker
        if _mouse_worker is None:
            _mouse_worker = _MouseHookThread()
        self.worker = _mouse_worker
        with self.worker.lock:
            self.worker.bindings[self] = (modifiers, button, notify)

    @property
    def procedure(self):
        return self.worker.procedure

    def close(self):
        global _mouse_worker
        with self.worker.lock:
            self.worker.bindings.pop(self, None)
            empty = not self.worker.bindings
        if empty and _mouse_worker is self.worker:
            self.worker.close()
            _mouse_worker = None


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


def window_context(hwnd):
    """Read optional screenshot context; unavailable fields must not prevent capture."""
    context = {}
    title = ctypes.create_unicode_buffer(32768)
    try:
        if user32.GetWindowTextW(hwnd, title, len(title)):
            context["title"] = title.value
    except OSError:
        pass  # Protected or closing windows can omit either field independently.
    try:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            process = kernel32.OpenProcess(0x1000, False, pid.value)  # Limited query access only.
            if process:
                try:
                    path = ctypes.create_unicode_buffer(32768)
                    size = wintypes.DWORD(len(path))
                    if kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
                        context["app"] = ntpath.basename(path.value)
                finally:
                    kernel32.CloseHandle(process)
    except OSError:
        pass
    return context


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
    native = NATIVE_KEY.search(text)
    parts = [part.strip().upper() for part in shortcut_label(text).split("+")]
    keys = {
        **{f"F{i}": 0x6F + i for i in range(1, 12)},
        **{c: ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
        "`": 0xC0,  # VK_OEM_3: backtick on the US keyboard layout.
        "~": 0xC0,
        "SCROLL LOCK": 0x91,  # VK_SCROLL
    }
    modifiers = {"CTRL": 2, "ALT": 1, "SHIFT": 4, "WIN": 8}
    key = int(native.group(1), 16) if native else keys.get(parts[-1])
    allowed_keys = set(keys.values()) | OEM_KEYS
    if key not in allowed_keys or len(set(parts)) != len(parts):
        raise ValueError(
            "Use Ctrl, Alt, or Win plus F1–F11, A–Z, or 0–9; "
            "or backtick (`) / Scroll Lock with optional modifiers. F12 is reserved."
        )
    mask = 0x4000  # MOD_NOREPEAT
    for part in parts[:-1]:
        if part not in modifiers:
            raise ValueError(f"Unknown shortcut modifier: {part}")
        mask |= modifiers[part]
    if key not in OEM_KEYS | {0x91} and parts[-1] not in ("`", "~") and not (mask & (1 | 2 | 8)):
        raise ValueError("Include Ctrl, Alt, or Win, or use backtick (`) / Scroll Lock on its own")
    return mask, key


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
                    _hotkey_ids.discard(self.key_id)
                    self.registered = False
                self.mouse_hook = new_hook
                return
            modifiers, key = parse_hotkey(text)
            # Every live binding needs its own id, including replacements awaiting commit.
            candidate = next(i for i in range(0x5141, 0xC000) if i not in _hotkey_ids)
            if not user32.RegisterHotKey(None, candidate, modifiers, key):
                code = ctypes.get_last_error()
                reason = (
                    "Windows denied access to global hotkeys"
                    if code == 5
                    else "another application may use it"
                )
                raise OSError(f"Cannot register {shortcut_label(text)}; {reason} (Windows error {code}).")
            _hotkey_ids.add(candidate)
            if self.registered:
                user32.UnregisterHotKey(None, self.key_id)
                _hotkey_ids.discard(self.key_id)
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
                _hotkey_ids.discard(self.key_id)
                self.registered = False
            app.removeNativeEventFilter(self)

    hotkey = Hotkey()
    try:
        hotkey.configure(shortcut)
    except Exception:
        hotkey.close()
        raise
    return hotkey


def validate_shortcuts(shortcuts):
    if not 1 <= len(shortcuts) <= MAX_ADDITIONAL_SHORTCUTS + 1:
        raise ValueError(f"Configure one screenshot shortcut and up to {MAX_ADDITIONAL_SHORTCUTS} more.")
    bindings = []
    for text in shortcuts:
        mouse = parse_mouse_shortcut(text)
        binding = ("mouse", *mouse) if mouse else ("keyboard", *parse_hotkey(text))
        if binding in bindings:
            raise ValueError(f"{shortcut_label(text)} is already configured as a screenshot shortcut.")
        bindings.append(binding)
    return bindings


class ScreenshotShortcuts:
    """Own all screenshot bindings and keep the working set on registration failure."""

    def __init__(self, app, callback, shortcuts):
        self.app, self.callback = app, callback
        self.bindings = {}
        self.configure(shortcuts)

    def configure(self, shortcuts):
        keys = validate_shortcuts(shortcuts)
        added = {}
        try:
            for key, text in zip(keys, shortcuts):
                if key not in self.bindings:
                    added[key] = install_hotkey(self.app, self.callback, text)
        except Exception:
            for binding in added.values():
                binding.close()
            raise
        for key, binding in self.bindings.items():
            if key not in keys:
                binding.close()
        self.bindings = {key: self.bindings.get(key) or added[key] for key in keys}

    def close(self):
        for binding in self.bindings.values():
            binding.close()
        self.bindings.clear()


def capture_target(mode, monitor_index, include_window_context=False):
    hwnd, pid = foreground()
    if pid == os.getpid():
        raise ValueError("Switch to the application being reviewed before capturing a screenshot")
    return {
        "hwnd": hwnd, "mode": mode, "monitor": monitor_index,
        "include_window_context": include_window_context,
    }
