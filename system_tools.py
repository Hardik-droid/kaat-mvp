"""Small Windows-native adapters with an explicit application allowlist."""
from __future__ import annotations

import ctypes
import json
from ctypes import wintypes
import os
from pathlib import Path
import re
import subprocess

CAMERA_URI = 'microsoft.windows.camera:'
CAMERA_PACKAGE = 'Microsoft.WindowsCamera_8wekyb3d8bbwe'


def _package_family():
    size = ctypes.c_uint32()
    lookup = ctypes.windll.kernel32.GetCurrentPackageFamilyName
    if lookup(ctypes.byref(size), None) != 122:
        return None
    family = ctypes.create_unicode_buffer(size.value)
    return family.value if lookup(ctypes.byref(size), family) == 0 else None


def device_permission(capability, *, package=None):
    """Read local Windows settings without requesting access or changing consent.

    Settings cannot prove that a driver will open or that frames will arrive.
    """
    _windows()
    import winreg
    if capability not in ('webcam', 'microphone'):
        raise ValueError('Expected webcam or microphone')
    base = r'Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore'
    def read(hive, path, name='Value'):
        try:
            with winreg.OpenKey(hive, path) as key:
                return winreg.QueryValueEx(key, name)[0]
        except OSError:
            return None
    family = package or _package_family()
    path = base + '\\' + capability
    values = {'device': read(winreg.HKEY_LOCAL_MACHINE, path),
              'user': read(winreg.HKEY_CURRENT_USER, path),
              'application': read(winreg.HKEY_CURRENT_USER, path + '\\' + (family or 'NonPackaged'))}
    policy_name = 'LetAppsAccessCamera' if capability == 'webcam' else 'LetAppsAccessMicrophone'
    values['policy'] = read(winreg.HKEY_LOCAL_MACHINE,
        r'Software\Policies\Microsoft\Windows\AppPrivacy', policy_name)
    blocked = any(str(value).casefold() == 'deny' for value in values.values()) or values['policy'] == 2
    return {'status': 'blocked' if blocked else 'not_blocked_in_settings', 'settings': values,
            'package': family, 'capture_verified': False,
            'settings_uri': 'ms-settings:privacy-' + capability}


def _camera_registered():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, CAMERA_URI.rstrip(':')) as key:
            winreg.QueryValueEx(key, 'URL Protocol')
        return True
    except OSError:
        return False


def open_device_settings(capability):
    _windows()
    if capability not in ('webcam', 'microphone'):
        raise ValueError('Expected webcam or microphone')
    os.startfile('ms-settings:privacy-' + capability)


def device_status():
    """Passive client-only inventory; no camera/mic is opened and no server used."""
    _windows()
    status = {'camera': device_permission('webcam', package=CAMERA_PACKAGE),
              'microphone': device_permission('microphone'),
              'camera_app_available': _camera_registered(), 'devices': [],
              'capture_started': False, 'network_used': False}
    try:
        status['devices'] = list_camera_devices()['devices']
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        status['enumeration_error'] = str(exc)
    return status


def open_camera():
    _windows()
    if not _camera_registered():
        raise RuntimeError('Windows Camera is not installed or its launch handler is missing. Install or repair Camera in Windows Settings.')
    permission = device_permission('webcam', package=CAMERA_PACKAGE)
    if permission['status'] == 'blocked':
        raise PermissionError('Windows blocks camera access. Turn on Camera access and allow the Camera app in Windows camera privacy settings.')
    os.startfile(CAMERA_URI)
    return {'application': 'camera', 'launch_requested': True, 'preview_verified': False,
            'message': 'Camera app requested. Windows opens the preview locally; KAAT does not record it.'}


def _windows():
    if os.name != "nt":
        raise RuntimeError("This tool requires Windows.")


def list_supported_apps() -> dict:
    return {"platform": os.name, "applications": [
        {"id": "notepad", "name": "Notepad", "actions": ["open"]},
        {"id": "explorer", "name": "File Explorer", "actions": ["open"]},
        {"id": "camera", "name": "Windows Camera", "actions": ["open"]},
        {"id": "chrome", "name": "Google Chrome", "actions": ["open"]},
        {"id": "calculator", "name": "Calculator", "actions": ["open"]},
    ] if os.name == "nt" else [], "arbitrary_shell": False,
        "websites": {"google photos": "https://photos.google.com/", "youtube": "https://www.youtube.com/"},
        "folders": ["downloads", "desktop", "documents", "home"],
        "recording_supported": os.name == 'nt', "recording_backend": 'Windows Camera UI Automation'}


def open_application(application: str) -> dict:
    from tools.windows_apps import open_application as launch
    return launch(application)


def get_active_window() -> dict:
    from tools.windows_apps import get_active_window as active
    return active()


def list_camera_devices() -> dict:
    _windows()
    from engine import _binary
    ffmpeg = _binary("ffmpeg")
    result = subprocess.run([ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    # FFmpeg returns nonzero because 'dummy' is not a capture source.
    matches = re.findall(r'\] "(.+?)" \((video|audio)\)(?:\r?\n[^\r\n]*?Alternative name "([^"]+)")?', result.stderr)
    if not matches and not any(x in result.stderr.lower() for x in ("directshow", "could not enumerate")):
        raise RuntimeError("DirectShow enumeration failed: " + result.stderr[-600:])
    return {"devices": [{"name": name, "kind": kind, "device_id": device_id or None} for name, kind, device_id in matches],
            "backend": "ffmpeg-directshow", "recording_supported": True,
            "recording_backend": "Windows Camera UI Automation"}


def camera_control(action: str, approved=False) -> dict:
    _windows()
    if action not in {'status', 'start_recording', 'stop_recording', 'pause_recording', 'resume_recording'}:
        raise ValueError('Unknown camera action')
    if action != 'status' and approved is not True:
        raise ValueError('Camera recording requires an explicit local user instruction.')
    if action == 'start_recording':
        open_camera()  # Restore the Camera window before reading its live controls.
    script = Path(__file__).parent / 'scripts' / 'camera_control.ps1'
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-File', str(script), '-Action', action], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=18,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Windows Camera control failed: ' + result.stderr.split('\nAt ')[0].strip()[:600])
    data = json.loads(result.stdout)
    data['message'] = {'recording':'Windows Camera is recording.', 'paused':'Windows Camera recording is paused.',
                       'ready':'Windows Camera is ready; recording is off.'}.get(data['state'], 'Open Camera in video mode.')
    return data
