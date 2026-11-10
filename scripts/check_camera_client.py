"""Real Windows input check: local startup discovery, camera launch and popups.

Requires --interactive; moves the pointer and leaves Windows Camera open.
No microphone capture, speech recognition, permission changes or preview image
storage. Window visibility proves launching, not working camera frames.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(output):
    from app import Kaat
    from scripts.check_overlay import native
    os.environ.pop('GNANI_API_KEY', None)
    output.mkdir(parents=True, exist_ok=False)
    user = native()
    user.VkKeyScanW.argtypes = [wintypes.WCHAR]
    user.VkKeyScanW.restype = ctypes.c_short
    started = time.monotonic()
    app = Kaat(memory_path=output / 'check.sqlite3')
    report = {'kind': 'actual Windows input and camera app launch', 'checks': [],
              'provider_key_present': False, 'microphone_started': False,
              'preview_verified': False, 'permissions_changed': False}
    cursor = wintypes.POINT()
    user.GetCursorPos(ctypes.byref(cursor))

    def pump(seconds=.15):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            app.update()
            time.sleep(.01)

    def wait(predicate, label, timeout=15):
        end = time.monotonic()+timeout
        while not predicate():
            if time.monotonic() > end:
                raise AssertionError(label + ': ' + app.status.get())
            pump(.04)

    def require(condition, label, **details):
        report['checks'].append({'check': label, 'passed': bool(condition), **details})
        if not condition:
            raise AssertionError(label)

    def click(widget):
        require(widget.winfo_ismapped(), 'native click target is visible', control=widget.winfo_name())
        user.SetCursorPos(widget.winfo_rootx()+widget.winfo_width()//2,
                          widget.winfo_rooty()+widget.winfo_height()//2)
        user.mouse_event(2, 0, 0, 0, 0)
        pump(.04)
        user.mouse_event(4, 0, 0, 0, 0)
        pump()

    def key(code):
        user.keybd_event(code, 0, 0, 0)
        user.keybd_event(code, 0, 2, 0)

    def command(words):
        if not app.expanded:
            click(app.toggle_button)
        click(app.command_entry)
        for letter in words:
            code = user.VkKeyScanW(letter)
            if code < 0 or code >> 8:
                raise ValueError('QA command requires unmodified keys')
            key(code)
        pump(.05)
        require(app.command_entry.get() == words, 'real keyboard input reaches the command field', command=words)
        app.last_result = None  # Observation reset only; execution uses native Return.
        command_started = time.monotonic()
        key(0x0D)
        wait(lambda: app.last_result is not None and not app.busy, words)
        if words == 'open camera':
            report['camera_command_result_seconds'] = round(time.monotonic()-command_started, 3)
        return app.last_result

    try:
        pump()
        require(not app.expanded and not app.busy, 'startup stays compact and responsive')
        if app.device_consent is not True:
            wait(lambda: app.permission_prompt_open, 'client permission popup')
            click(app.notice_action)
            require(app.device_consent is True, 'native Allow click approves only this test client')
        wait(lambda: app.devices is not None, 'local device discovery')
        report['device_discovery_seconds'] = round(time.monotonic()-started, 3)
        report['device_status'] = app.devices
        require(not app.devices.get('enumeration_error'), 'real DirectShow device discovery completes')
        require(app.devices.get('network_used') is False and app.devices.get('capture_started') is False,
                'passive startup inventory does not capture or use a network')
        result = command('open camera')
        require(result['ok'] and result['tool'] == 'camera.open', 'actual command requests the local Camera app', result=result)
        pump(2)
        camera = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
            'Get-Process WindowsCamera -ErrorAction SilentlyContinue | Select-Object Id,MainWindowHandle,MainWindowTitle | ConvertTo-Json -Compress'],
            capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        records = json.loads(camera.stdout or 'null')
        records = records if isinstance(records, list) else [records] if records else []
        # UWP Camera's top-level frame belongs to ApplicationFrameHost. Prove
        # that its visible child belongs to the actual WindowsCamera process.
        camera_pids = {record['Id'] for record in records}
        visible = []
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        @callback
        def child(hwnd, parent):
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in camera_pids and user.IsWindowVisible(hwnd):
                visible.append({'parent': parent, 'camera_child': hwnd, 'camera_pid': pid.value})
            return True
        @callback
        def top(hwnd, _):
            if user.IsWindowVisible(hwnd):
                child(hwnd, hwnd)
                user.EnumChildWindows(hwnd, child, hwnd)
            return True
        user.EnumWindows(top, 0)
        require(bool(visible), 'Windows Camera has a real visible native window', processes=records, visible_windows=visible)
        require(app.notice is not None and app.notice.winfo_ismapped(), 'camera result appears automatically in a popup')
        click(app.toggle_button)
        require(not app.expanded and app.notice.winfo_ismapped(), 'result popup remains visible with drawer closed')
        result = command('camera mat kholo')
        require(not result['ok'] and result['intent'] == 'unknown', 'negated camera instruction is rejected')
        click(app.toggle_button)
        require(not app.expanded and app.notice.winfo_ismapped(), 'unknown-command error is visible without expansion')
        click(app.toggle_button)
        pause_button = next(button for button in app.buttons if button.cget('text') == 'Find pauses')
        app.last_result = None
        click(pause_button)
        wait(lambda: app.last_result is not None and not app.busy, 'missing video error')
        click(app.toggle_button)
        require('Select a video first' in app.notice_text.get() and not app.expanded,
                'actual missing-source error appears above compact widget')
        require(app.notice_action.winfo_ismapped() and app.notice_action.cget('text') == 'Open video',
                'popup provides the action needed to resolve the error')
        area = app._work_area(app.notice.winfo_rootx(), app.notice.winfo_rooty())
        left, top = app.notice.winfo_rootx(), app.notice.winfo_rooty()
        box = (left, top, left+app.notice.winfo_width(), top+app.notice.winfo_height())
        require(box[0] >= area[0] and box[1] >= area[1] and box[2] <= area[2] and box[3] <= area[3],
                'automatic popup fits the monitor work area', bounds=box)
        from PIL import ImageGrab
        ImageGrab.grab(bbox=box).save(output / 'error_popup.png')
        buttons = [widget for row in app.notice.winfo_children() for widget in row.winfo_children()
                   if widget.winfo_class() == 'Button' and widget.cget('text') == 'Dismiss']
        click(buttons[0])
        require(app.notice is None and not app.busy, 'native dismiss closes feedback without changing the task')
        require(not os.getenv('GNANI_API_KEY') and app.cached['source'] is None,
                'camera launching needs no provider credential or selected video')
        report['passed'] = True
    except Exception as exc:
        report['passed'] = False
        report['error'] = str(exc)
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        app.close()
        user.SetCursorPos(cursor.x, cursor.y)
    print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']),
                      'report': str(output / 'report.json')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'test_output/camera_client')
    args = parser.parse_args()
    if not args.interactive:
        parser.error('--interactive is required because this launches Camera and uses the real keyboard')
    check(args.output)
