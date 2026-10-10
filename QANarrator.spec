# One-folder build: avoids re-extracting large inference libraries every launch.
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = [], [], []
for package in ('faster_whisper', 'ctranslate2', 'tokenizers', 'onnxruntime', 'av', '_sounddevice_data'):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
datas += collect_data_files('certifi')
a = Analysis(['scripts/launcher.py'], pathex=['src'], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
             excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml',
                       'PySide6.QtQuick', 'matplotlib', 'pytest'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='QANarrator', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          contents_directory='_internal')
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='QANarrator')

