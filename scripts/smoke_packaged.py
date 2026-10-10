"""Exercise packaged offline processing and launch/close the real Windows GUI."""
import argparse
import base64
import ctypes
import json
import os
import re
import shutil
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from qa_narrator.storage import Session

parser = argparse.ArgumentParser()
parser.add_argument('--exe', default='dist/QANarrator/QANarrator.exe')
parser.add_argument('--embed-images', action='store_true')
args = parser.parse_args()
root = Path('.validation').resolve()
source = Session.load(json.loads((root / 'offline-result.json').read_text())['session'])
session = Session.create(root / 'packaged', source.data['sample_rate'], 'Packaged synthetic fixture')
shutil.copyfile(source.folder / 'audio.wav', session.folder / 'audio.wav')
session.update(status='stopped', duration=source.data['duration'])
for event in source.screenshots():
    shutil.copyfile(source.folder / event['path'], session.folder / event['path'])
    session.event(event)
exe = Path(args.exe).resolve()
environment = dict(os.environ, HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
command = [str(exe), '--process', str(session.folder)]
if args.embed_images:
    command.append('--embed-images')
result = subprocess.run(command, env=environment, timeout=120,
                        creationflags=subprocess.CREATE_NO_WINDOW)
assert result.returncode == 0, result.returncode
assert (session.folder / 'feedback.md').exists()
assert Session.load(session.folder).data['transcription_status'] == 'complete'
transcript = json.loads((session.folder / 'transcription.json').read_text(encoding='utf-8'))
assert 'button' in ''.join(s['text'] for s in transcript['segments']).lower()
if args.embed_images:
    report_text = (session.folder / 'feedback.md').read_text(encoding='utf-8')
    images = re.findall(r'!\[Screenshot \d+\]\(data:image/png;base64,([A-Za-z0-9+/=]+)\)', report_text)
    assert len(images) == len(session.screenshots())
    assert [base64.b64decode(payload, validate=True) for payload in images] == [
        (session.folder / event['path']).read_bytes() for event in session.screenshots()]
    assert '](screenshots/' not in report_text
    shutil.copyfile(session.folder / 'feedback.md', root / 'packaged-portable-feedback.md')

user32 = ctypes.WinDLL('user32', use_last_error=True)
callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
gui_log = (root / 'packaged-gui.log').open('wb')
process = subprocess.Popen([str(exe)], env=environment, creationflags=subprocess.CREATE_NO_WINDOW,
                           stdout=gui_log, stderr=gui_log)
found = []
observed = []

@callback_type
def visit(hwnd, _):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == process.pid:
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, len(title))
        observed.append(title.value)
        if title.value == 'Local QA Narrator':
            found.append(hwnd)
    return True

try:
    until = time.monotonic() + 20
    while time.monotonic() < until and not found:
        user32.EnumWindows(visit, 0)
        if process.poll() is not None:
            break
        time.sleep(0.1)
    assert found, f'Packaged GUI did not create its main window; exit={process.poll()}, windows={set(observed)}'
    user32.PostMessageW(found[0], 0x0010, 0, 0)  # WM_CLOSE: normal app cleanup, no recording
    assert process.wait(timeout=10) == 0
finally:
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)
    gui_log.close()
report = {'session': str(session.folder), 'offline_inference_and_export': 'passed',
          'gui_launch_and_normal_close': 'passed', 'embedded_png_roundtrip': args.embed_images}
(root / 'packaged-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))

