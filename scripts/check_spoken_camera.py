"""Observe the real microphone -> Gnani -> parser -> Windows Camera path.

--playback WAV activates the real mic with a native click and plays that file
through Windows speakers after Listening. Label synthesized samples honestly.
--interactive waits for the user to click and speak; no automatic capture.
No microphone audio is saved and no provider/controller function is replaced.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--playback', type=Path)
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--retain-audio', action='store_true', help='Keep this diagnostic capture locally for waveform/channel inspection')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--application', default='camera', choices=['camera', 'chrome', 'notepad'],
                        help='Expected actual target for this live acceptance check')
    args = parser.parse_args()
    if not args.playback and not args.interactive:
        parser.error('Choose --playback or --interactive')
    args.output.mkdir(parents=True, exist_ok=False)
    if args.retain_audio:
        os.environ['KAAT_DIAGNOSTIC_AUDIO_DIR'] = str(args.output.resolve())
    from dotenv import load_dotenv
    from app import Kaat
    from scripts.check_overlay import native
    load_dotenv(ROOT / '.env')
    app = Kaat(memory_path=args.output/'session.sqlite3') if args.playback else Kaat()
    user = native()
    report = {'kind': 'actual speaker playback through physical mic' if args.playback else 'user-activated live microphone',
              'expected_application':args.application,
              'playback_file': str(args.playback) if args.playback else None,
              'speech_origin': 'synthesized Windows voice' if args.playback and 'synthetic' in args.playback.name else 'user voice',
              'provider_replaced': False, 'capture_replaced': False, 'audio_saved': args.retain_audio,
              'status': 'waiting', 'phases': [], 'attempts': [], 'max_level_percent': 0}
    started = time.monotonic()
    played = False
    last_phase = None
    last_result = None
    def publish():
        (args.output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    def click_microphone():
        if app.device_consent is not True:
            # --playback explicitly authorizes capture in this isolated QA client.
            # Click the real consent button; interactive mode leaves it to the user.
            widget = app.notice_action
            user.SetCursorPos(widget.winfo_rootx()+widget.winfo_width()//2, widget.winfo_rooty()+widget.winfo_height()//2)
            user.mouse_event(2, 0, 0, 0, 0)
            app.after(60, lambda: user.mouse_event(4, 0, 0, 0, 0))
            app.after(200, click_microphone)
            return
        widget = app.speak_button
        user.SetCursorPos(widget.winfo_rootx()+widget.winfo_width()//2, widget.winfo_rooty()+widget.winfo_height()//2)
        user.mouse_event(2, 0, 0, 0, 0)
        app.after(60, lambda: user.mouse_event(4, 0, 0, 0, 0))
    def camera_visible():
        found = []
        user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        @callback
        def visit(hwnd, _):
            title = ctypes.create_unicode_buffer(256)
            user.GetWindowTextW(hwnd, title, 256)
            if title.value == 'Camera' and user.IsWindowVisible(hwnd):
                found.append(int(hwnd))
            return True
        user.EnumWindows(visit, 0)
        return found
    def watch():
        nonlocal played, last_phase, last_result
        if app.closed:
            return
        if app.voice_phase != last_phase:
            last_phase = app.voice_phase
            report['phases'].append({'phase': last_phase, 'seconds': round(time.monotonic()-started, 3), 'message': app.status.get()})
        level = re.search(r'input level ([0-9.]+)%', app.mic.get())
        if level:
            report['max_level_percent'] = max(report['max_level_percent'], float(level[1]))
        if args.playback and app.voice_phase == 'listening' and not played:
            import winsound
            played = True
            winsound.PlaySound(str(args.playback.resolve(strict=True)), winsound.SND_FILENAME | winsound.SND_ASYNC)
        result = app.last_result
        if result is not None and result is not last_result and not app.busy:
            last_result = result
            report['actual_result'] = result
            from tools.windows_apps import _matching_windows
            report['target_windows'] = _matching_windows(args.application)
            expected_tool = 'camera.open' if args.application == 'camera' else 'system.open_application'
            report['passed'] = bool(result.get('ok') and result.get('verified') and result.get('heard')
                and result.get('tool') == expected_tool and result.get('target') == args.application and report['target_windows'])
            report['status'] = 'passed' if report['passed'] else 'failed'
            report['elapsed_seconds'] = round(time.monotonic()-started, 3)
            report['attempts'].append({'seconds': report['elapsed_seconds'], 'result': result,
                                        'passed': report['passed'], 'target_windows': report['target_windows']})
            publish()
            if args.playback:
                app.after(200, app.close)
                return
        report['current_status'] = app.status.get()
        publish()
        app.after(60, watch)
    publish()
    if args.playback:
        app.after(600, click_microphone)
    app.after(100, watch)
    app.mainloop()
    print(json.dumps({'status': report['status'], 'report': str(args.output/'report.json')}))
    if args.playback and report.get('passed') is not True:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
