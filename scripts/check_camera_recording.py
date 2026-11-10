"""Explicit native recording QA; creates a private real camera clip in Camera Roll.

No provider responses, camera frames or state transitions are substituted.
Requires --interactive. The generated clip stays local and is never packaged.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(output, from_photo=False, minimized=False, brief=False, microphone_probe=True,
          start_command='start recording', stop_command='stop recording'):
    from controller import AgentController
    from engine import _binary, source_hash, inspect_video
    from voice import capture_command_audio
    from system_tools import camera_control
    output.mkdir(parents=True, exist_ok=False)
    initial = camera_control('status')
    if initial.get('idle_verified') is not True:
        raise RuntimeError('Camera is not verified idle; existing recording/state is left untouched.')
    if from_photo:
        # Reproduce the user's failure using the actual native mode switch.
        prepared = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-Command', ". ./scripts/camera_control.ps1 -Action status; $photo=@(Buttons) | Where-Object { $_.Current.Name -eq 'Switch to photo mode' } | Select-Object -First 1; if ($photo) { InvokeButton $photo }; Start-Sleep -Milliseconds 300; if ((State) -ne 'unavailable') { throw 'Photo-mode setup did not produce the expected precondition' }"],
            cwd=ROOT, capture_output=True, text=True, timeout=10)
        assert prepared.returncode == 0, prepared.stderr
    if minimized:
        import ctypes
        from ctypes import wintypes
        window = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-Command', '. ./scripts/camera_control.ps1 -Action status; (CameraRoot).Current.NativeWindowHandle'],
            cwd=ROOT, capture_output=True, text=True, timeout=10)
        assert window.returncode == 0, window.stderr
        handle = int(window.stdout.strip().splitlines()[-1])
        user = ctypes.WinDLL('user32')
        user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user.IsIconic.argtypes = [wintypes.HWND]
        user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user.GetAncestor.restype = wintypes.HWND
        # UWP can expose a child CoreWindow; minimize its actual desktop frame.
        handle = user.GetAncestor(handle, 2)
        user.ShowWindow(handle, 6)
        assert user.IsIconic(handle), 'Camera did not minimize'
    agent = AgentController(output/'recording.sqlite3')
    report = {'kind':'actual Windows Camera UI recording, save, and decoding', 'operations': [],
              'provider_called': False, 'microphone_probe': [], 'started_from_photo_mode': from_photo,
              'started_minimized': minimized, 'initial_state': initial,
              'microphone_probe_requested': microphone_probe and not brief, 'brief': brief}
    started_here = False
    try:
        commands = [('start', start_command), ('stop', stop_command)] if brief else [
            ('start', start_command), ('pause', 'pause recording'), ('resume', 'resume recording'), ('stop', stop_command)]
        for operation, command in commands:
            if operation == 'pause' and microphone_probe:
                try:
                    capture_command_audio(.5, on_phase=lambda phase,message: report['microphone_probe'].append({'phase':phase,'message':message}))
                except RuntimeError as exc:
                    report['microphone_probe_result'] = str(exc)
                assert any(event['phase']=='listening' for event in report['microphone_probe']), 'Command microphone could not open alongside recording'
            result = agent.command(command)
            report['operations'].append(result)
            assert result['ok'], result
            if operation == 'start':
                started_here = result['data'].get('action') == 'start_recording' and result['data'].get('previous_state') == 'ready'
                assert started_here, 'The test did not start this recording; leaving it untouched.'
            if operation in ('start', 'resume'):
                time.sleep(1)
        clip = Path(report['operations'][-1]['data']['output'])
        signature = source_hash(clip)
        info = inspect_video(clip)
        assert info['has_audio'] and info['duration_seconds'] > 0
        decoded = subprocess.run([_binary('ffmpeg'), '-nostdin', '-v', 'error', '-i', str(clip), '-f', 'null', '-'],
                                 capture_output=True, timeout=25)
        assert decoded.returncode == 0, decoded.stderr
        assert source_hash(clip) == signature
        assert agent.source == clip.resolve(), 'Fresh recording was not selected for editing'
        report.update(passed=True, output=str(clip), duration_seconds=info['duration_seconds'],
                      audio_present=True, decoded_successfully=True, original_unchanged=True)
    except Exception as exc:
        report.update(passed=False, error=str(exc))
        raise
    finally:
        if started_here and agent.recording_status in ('recording','paused'):
            report['cleanup_stop'] = agent.command('stop recording')
        (output/'report.json').write_text(json.dumps(report, indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'duration_seconds':report['duration_seconds'], 'report':str(output/'report.json')}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--from-photo', action='store_true', help='Exercise the real photo-to-video transition')
    parser.add_argument('--minimized', action='store_true', help='Start with the real Camera window minimized')
    parser.add_argument('--brief', action='store_true', help='Start/stop only; skips the extra command-microphone probe')
    parser.add_argument('--skip-microphone-probe', action='store_true', help='Do not capture command-microphone audio')
    parser.add_argument('--start-command', default='start recording')
    parser.add_argument('--stop-command', default='stop recording')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.interactive:
        parser.error('--interactive is required because this records a real camera clip')
    check(args.output, from_photo=args.from_photo, minimized=args.minimized, brief=args.brief,
          microphone_probe=not args.skip_microphone_probe,
          start_command=args.start_command, stop_command=args.stop_command)
