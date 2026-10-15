import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QComboBox

from qa_narrator.ui import MainWindow


@pytest.mark.parametrize("default,saved,current,expected", [
    (0, "", "", 2),  # Prefer the matching endpoint rather than another WASAPI default.
    (1, "", "", 3),  # Sound Mapper alias uses the WASAPI default input.
    (2, "", "", 2),
    (0, "USB Mic (MME)", "", 0),
    (0, "USB Mic (MME)", "Other Mic (Windows WASAPI)", 3),
    (0, "Unplugged Mic (MME)", "", 2),
])
def test_microphone_defaults_to_wasapi_but_preserves_saved_and_current_choice(
    monkeypatch, tmp_path, default, saved, current, expected
):
    import sounddevice as sd

    app = QApplication.instance() or QApplication([])
    devices = [
        {"name": "USB Mic", "hostapi": 0, "max_input_channels": 1},
        {"name": "Microsoft Sound Mapper - Input", "hostapi": 0, "max_input_channels": 1},
        {"name": "USB Mic", "hostapi": 1, "max_input_channels": 1},
        {"name": "Other Mic", "hostapi": 1, "max_input_channels": 1},
        {"name": "Speakers", "hostapi": 1, "max_input_channels": 0},
    ]
    hosts = [{"name": "MME", "default_input_device": 1},
             {"name": "Windows WASAPI", "default_input_device": 3}]
    monkeypatch.setattr(sd, "query_devices", lambda: devices)
    monkeypatch.setattr(sd, "query_hostapis", lambda: hosts)
    monkeypatch.setattr(sd, "default", SimpleNamespace(device=(default, -1)))
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setValue("microphone", saved)
    mics = QComboBox()
    if current:
        mics.addItem(current)
    notices = []
    window = SimpleNamespace(mics=mics, settings=settings, _controls=lambda: None,
                             _notice=lambda *args: notices.append(args))
    MainWindow._devices(window)
    assert mics.currentData() == expected and mics.count() == 4 and not notices
    mics.close()
    assert app is not None


def test_microphone_keeps_default_when_wasapi_is_unavailable(monkeypatch, tmp_path):
    import sounddevice as sd

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(sd, "query_devices", lambda: [
        {"name": "First", "hostapi": 0, "max_input_channels": 1},
        {"name": "Default", "hostapi": 0, "max_input_channels": 1},
    ])
    monkeypatch.setattr(sd, "query_hostapis", lambda: [{"name": "MME"}])
    monkeypatch.setattr(sd, "default", SimpleNamespace(device=(1, -1)))
    mics = QComboBox()
    window = SimpleNamespace(mics=mics,
                             settings=QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat),
                             _controls=lambda: None, _notice=lambda *args: None)
    MainWindow._devices(window)
    assert mics.currentData() == 1
    mics.close()
    assert app is not None
