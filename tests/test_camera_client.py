"""Command and failure-path units. Native camera launch is checked separately."""
import os

import pytest

from commands import parse_command
from controller import AgentController
import system_tools


@pytest.mark.parametrize('text', [
    'open camera', 'Kaat, open the camera', 'camera open kar', 'camera kholo',
    'please launch webcam', 'कैमरा खोलो', 'काट, कैमरा खोल दो',
    'Kaat. Open camera.', 'Caught. Open camera.',
    'Can you just open the camera quick? I want to take a read.',
    'Could you please open my camera quickly', 'just open camera for me',
    'open camera please I need to take a selfie', 'zara camera khol do na',
])
def test_camera_requests_have_a_route(text):
    assert parse_command(text) == ('open_camera', {})


@pytest.mark.parametrize('text', [
    'do not open camera', 'camera mat kholo', 'what happens if I open camera',
    'I will open camera later', 'open camera and export', 'open camera and delete files',
])
def test_camera_conversation_negation_and_multiple_actions_do_not_launch(text):
    assert parse_command(text)[0] == 'unknown'


def test_phonetic_wake_variant_never_activates_ambient_audio():
    assert parse_command('Caught. Open camera.', activated=False)[0] == 'unknown'


@pytest.mark.parametrize('text', ['start recording and export', 'start recording and delete files', 'stop recording and clear edits'])
def test_recording_never_executes_half_a_combined_request(text):
    assert parse_command(text)[0] == 'unknown'


@pytest.mark.skipif(os.name != 'nt', reason='Windows native adapter')
def test_camera_command_runs_without_video_key_or_approval_dialog(tmp_path, monkeypatch):
    launches = []
    monkeypatch.delenv('GNANI_API_KEY', raising=False)
    monkeypatch.setattr(system_tools, '_camera_registered', lambda: True)
    monkeypatch.setattr(system_tools, 'device_permission', lambda *a, **k: {'status': 'not_blocked_in_settings'})
    monkeypatch.setattr(os, 'startfile', launches.append)
    # Unit-only boundary: actual native-window verification is exercised by
    # scripts/check_windows_apps.py, not by this isolated dispatch check.
    monkeypatch.setattr('tools.windows_apps._matching_windows', lambda *a: [{'hwnd': 123, 'title': 'Camera'}])
    controller = AgentController(tmp_path / 'local.sqlite3')
    result = controller.command('open camera')
    assert result['ok'] and result['tool'] == 'camera.open'
    assert launches == [system_tools.CAMERA_URI]
    assert result['data']['launch_requested'] and result['data']['verified']
    assert controller.source is None


@pytest.mark.skipif(os.name != 'nt', reason='Windows native adapter')
def test_denied_camera_never_launches_or_claims_success(monkeypatch):
    monkeypatch.setattr(system_tools, '_camera_registered', lambda: True)
    monkeypatch.setattr(system_tools, 'device_permission', lambda *a, **k: {'status': 'blocked'})
    monkeypatch.setattr(os, 'startfile', lambda *a: pytest.fail('Denied camera must stay closed'))
    with pytest.raises(PermissionError, match='Windows blocks camera'):
        system_tools.open_camera()


@pytest.mark.skipif(os.name != 'nt', reason='Windows native adapter')
def test_missing_camera_app_is_an_error_instead_of_a_launch_claim(monkeypatch):
    monkeypatch.setattr(system_tools, '_camera_registered', lambda: False)
    monkeypatch.setattr(os, 'startfile', lambda *a: pytest.fail('Do not open an application chooser'))
    with pytest.raises(RuntimeError, match='not installed'):
        system_tools.open_camera()
