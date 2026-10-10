"""Native hook registration/reconfiguration and callback dispatch. Does not record.

Calls the real hook callback with a test event, without injecting clicks into other apps.
"""
import ctypes

from PySide6.QtWidgets import QApplication

from qa_narrator.windows import MouseEvent, install_hotkey

app = QApplication([])
received = []
binding = install_hotkey(app, lambda: received.append(True), "Middle Mouse")
event = MouseEvent()
try:
    binding.mouse_hook.procedure(0, 0x207, ctypes.addressof(event))
    app.processEvents()
    assert len(received) == 1
    binding.mouse_hook.procedure(0, 0x208, ctypes.addressof(event))
    app.processEvents()
    assert len(received) == 1
    binding.configure("Mouse Button 5")
    event.mouseData = 2 << 16
    binding.mouse_hook.procedure(0, 0x20B, ctypes.addressof(event))
    app.processEvents()
    assert len(received) == 2
    binding.configure("Ctrl+Alt+Shift+F10")
    assert binding.registered and binding.mouse_hook is None
    binding.configure("Middle Mouse")
    assert binding.mouse_hook and not binding.registered
finally:
    binding.close()
assert binding.mouse_hook is None and not binding.registered
print("PASS: native mouse hook setup, button dispatch, keyboard/mouse switching, and cleanup.")
