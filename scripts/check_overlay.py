"""Actual Windows overlay QA; never records audio or calls a provider.

Run: .venv\\Scripts\\python.exe scripts\\check_overlay.py --interactive
The interactive check moves the mouse and opens two disposable native windows.
It reads Win32 styles/z-order and uses real mouse input, not widget invoke().
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


def native():
    user = ctypes.WinDLL('user32', use_last_error=True)
    signatures = {
        'GetAncestor': ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
        'GetWindowLongPtrW': ([wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t),
        'GetWindowRect': ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
        'GetForegroundWindow': ([], wintypes.HWND),
        'SetForegroundWindow': ([wintypes.HWND], wintypes.BOOL),
        'WindowFromPoint': ([wintypes.POINT], wintypes.HWND),
        'MonitorFromWindow': ([wintypes.HWND, wintypes.DWORD], wintypes.HANDLE),
        'GetMonitorInfoW': ([wintypes.HANDLE, ctypes.c_void_p], wintypes.BOOL),
        'PostMessageW': ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        getattr(user, name).argtypes = arguments
        getattr(user, name).restype = result
    return user


def other_application(output):
    """A real separate-process application with no user documents involved."""
    import tkinter as tk
    user = native()
    app = tk.Tk()
    app.title('KAAT overlay check — another desktop application')
    app.configure(bg='#dce8f4')
    app.geometry(f'{app.winfo_screenwidth()}x{app.winfo_screenheight()}+0+0')
    tk.Label(app, text='Another desktop application', bg='#dce8f4', fg='#1a3452',
             font=('Segoe UI', 30, 'bold')).pack(pady=(100, 20))
    tk.Label(app, text='KAAT should remain above this foreground window.\n'
             'This check does not use the microphone.', bg='#dce8f4', fg='#365472',
             font=('Segoe UI', 17)).pack()
    app.update()
    output.write_text(json.dumps({'pid': os.getpid(), 'hwnd': user.GetAncestor(app.winfo_id(), 2)}), encoding='utf-8')
    app.mainloop()


def check(output):
    if os.name != 'nt':
        raise RuntimeError('Requires an interactive Windows desktop')
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    from app import Kaat
    from PIL import ImageGrab
    user = native()
    output.mkdir(parents=True, exist_ok=True)
    app = Kaat(memory_path=output / 'overlay.sqlite3')
    other = None
    other_hwnd = None
    cursor = wintypes.POINT()
    user.GetCursorPos(ctypes.byref(cursor))
    report = {'kind': 'actual Windows native input and OS checks', 'checks': [],
              'microphone_started': False, 'provider_called': False}

    def pump(seconds=.25):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.update()
            time.sleep(.015)

    def require(condition, label, **evidence):
        report['checks'].append({'check': label, 'passed': bool(condition), **evidence})
        if not condition:
            raise AssertionError(label)

    def rect(hwnd):
        value = wintypes.RECT()
        if not user.GetWindowRect(hwnd, ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        return [value.left, value.top, value.right, value.bottom]

    def work_area(hwnd):
        class Monitor(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                        ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
        value = Monitor(size=ctypes.sizeof(Monitor))
        if not user.GetMonitorInfoW(user.MonitorFromWindow(hwnd, 2), ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        return [value.work.left, value.work.top, value.work.right, value.work.bottom]

    def contained(bounds, area):
        return bounds[0] >= area[0] and bounds[1] >= area[1] and bounds[2] <= area[2] and bounds[3] <= area[3]

    def center(widget):
        return widget.winfo_rootx() + widget.winfo_width() // 2, widget.winfo_rooty() + widget.winfo_height() // 2

    def click(widget):
        require(bool(widget.winfo_ismapped()), 'input control is actually visible', control=widget.winfo_name())
        user.SetCursorPos(*center(widget))
        user.mouse_event(2, 0, 0, 0, 0)
        pump(.08)
        user.mouse_event(4, 0, 0, 0, 0)
        pump()

    def drag(target):
        user.SetCursorPos(*center(app.drag_handle))
        user.mouse_event(2, 0, 0, 0, 0)
        pump(.1)
        user.SetCursorPos(*target)
        pump(.2)
        user.mouse_event(4, 0, 0, 0, 0)
        pump()

    def screenshot(name, hwnd):
        bounds, area = rect(hwnd), work_area(hwnd)
        box = (max(area[0], bounds[0]-12), max(area[1], bounds[1]-12),
               min(area[2], bounds[2]+12), min(area[3], bounds[3]+12))
        path = output / name
        ImageGrab.grab(bbox=box).save(path)
        return str(path.resolve())

    try:
        pump(.7)
        hwnd = user.GetAncestor(app.winfo_id(), 2)
        initial = rect(hwnd)
        area = work_area(hwnd)
        scale = app.ui_scale
        style, extended = user.GetWindowLongPtrW(hwnd, -16), user.GetWindowLongPtrW(hwnd, -20)
        require(not app.expanded and not app.details.winfo_ismapped(), 'editing drawer is hidden at launch')
        require(initial[2]-initial[0] <= 370*scale and initial[3]-initial[1] <= 140*scale,
                'default footprint is compact', bounds=initial, scale=scale)
        require(bool(extended & 0x8), 'native WS_EX_TOPMOST is set', extended_style=hex(extended))
        require(not style & (0xC00000 | 0x40000), 'native caption and resize frame are absent', style=hex(style))
        require(bool(extended & 0x80) and not extended & 0x40000,
                'native tool window avoids a full app taskbar entry', extended_style=hex(extended))
        require(contained(initial, area), 'compact window stays inside actual monitor work area', bounds=initial, work_area=area)
        require(app.speak_button.winfo_ismapped() and app.peek_label.winfo_ismapped(),
                'microphone control and status are visible')

        probe = output / 'other.json'
        probe.unlink(missing_ok=True)
        other = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--other', '--output', str(probe)],
                                 cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 10
        while not probe.exists() and time.monotonic() < deadline and other.poll() is None:
            pump(.05)
        require(probe.exists(), 'separate desktop application starts')
        observation = json.loads(probe.read_text(encoding='utf-8'))
        other_hwnd = observation['hwnd']
        user.SetForegroundWindow(other_hwnd)
        pump(.5)
        if user.GetForegroundWindow() != other_hwnd:
            # Windows may enforce foreground lock; a real click on our own
            # disposable underlay is the normal user path to activate it.
            user.SetCursorPos(area[0]+40, area[1]+70)
            user.mouse_event(2, 0, 0, 0, 0)
            pump(.08)
            user.mouse_event(4, 0, 0, 0, 0)
            pump(.3)
        require(user.GetForegroundWindow() == other_hwnd, 'another process owns foreground focus',
                foreground_hwnd=user.GetForegroundWindow(), expected=other_hwnd, other_pid=observation['pid'])
        point = wintypes.POINT(*center(app.speak_button))
        upper = user.GetAncestor(user.WindowFromPoint(point), 2)
        require(upper == hwnd, 'KAAT remains above a different foreground application', hit_hwnd=upper, kaat_hwnd=hwnd)
        report['compact_screenshot'] = screenshot('compact_over_application.png', hwnd)

        # These are real pointer events sent through Windows into the drag binding.
        drag((area[0], area[1]))
        require(contained(rect(hwnd), area), 'real mouse drag clamps at top-left', bounds=rect(hwnd))
        require(rect(hwnd) != initial, 'real mouse drag changes position', before=initial, after=rect(hwnd))
        drag((area[2]-1, area[3]-1))
        collapsed = rect(hwnd)
        require(contained(collapsed, area), 'real mouse drag clamps at bottom-right', bounds=collapsed)
        click(app.toggle_button)
        expanded = rect(hwnd)
        require(app.expanded and app.details.winfo_ismapped(), 'real click opens editing drawer')
        require(expanded[2:] == collapsed[2:], 'expansion preserves bottom-right anchor', compact=collapsed, expanded=expanded)
        require(contained(expanded, area), 'expanded drawer fits actual work area', bounds=expanded)
        require(app.command_entry.winfo_ismapped() and app.cut_list.winfo_ismapped(),
                'existing command and editing controls remain available')
        report['expanded_screenshot'] = screenshot('expanded_over_application.png', hwnd)
        click(app.command_entry)
        require(user.GetForegroundWindow() == hwnd and app.focus_get() == app.command_entry,
                'expanded command field accepts native focus')
        user.keybd_event(0x20, 0, 0, 0)
        user.keybd_event(0x20, 0, 2, 0)
        pump()
        require(app.command_entry.get() == ' ', 'real keyboard input reaches expanded command field')
        user.keybd_event(0x08, 0, 0, 0)
        user.keybd_event(0x08, 0, 2, 0)
        pump()
        require(app.command_entry.get() == '', 'real backspace clears harmless focus-test character')
        click(app.toggle_button)
        require(not app.expanded and rect(hwnd) == collapsed, 'real click restores original compact bounds', bounds=rect(hwnd))
        require(not app.busy and app.voice_phase == 'idle' and app.last_result is None,
                'layout check never starts microphone or command work')
        report['passed'] = True
    except Exception as exc:
        report['passed'] = False
        report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if other_hwnd:
            user.PostMessageW(other_hwnd, 0x10, 0, 0)
        if other:
            try:
                other.wait(timeout=3)
            except subprocess.TimeoutExpired:
                other.terminate()
        app.close()
        user.SetCursorPos(cursor.x, cursor.y)
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interactive', action='store_true', help='Allow actual mouse drag/click checks')
    parser.add_argument('--other', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--output', type=Path, default=ROOT / 'test_output/overlay')
    arguments = parser.parse_args()
    if arguments.other:
        other_application(arguments.output)
    elif arguments.interactive:
        check(arguments.output)
    else:
        parser.error('--interactive is required because this check moves the real pointer')


if __name__ == '__main__':
    main()
