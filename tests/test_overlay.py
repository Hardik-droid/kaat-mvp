"""Tk callback/layout regressions; real pointer/foreground QA is check_overlay.py.

These tests create the actual Windows UI but never activate speech or call APIs.
"""
import os
import json
from types import SimpleNamespace

import pytest

from app import Kaat

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='KAAT targets the Windows desktop')


@pytest.fixture(scope='module')
def overlay(tmp_path_factory):
    # Production owns one Tcl interpreter per process. Reuse the real window;
    # launching/relaunching is separately covered by the native script process.
    directory = tmp_path_factory.mktemp('overlay')
    # Existing layout checks represent an already-consenting client. Consent
    # gating is exercised separately below without touching real user settings.
    (directory / 'desktop_permissions.json').write_text('{"version":1,"devices":true}', encoding='utf-8')
    app = Kaat(memory_path=directory / 'overlay.sqlite3')
    app.update()
    try:
        yield app
    finally:
        app.close()


def bounds(widget):
    left, top = widget.winfo_rootx(), widget.winfo_rooty()
    return left, top, left + widget.winfo_width(), top + widget.winfo_height()


def fits(inner, outer):
    return inner[0] >= outer[0] and inner[1] >= outer[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def test_launch_is_compact_with_visible_controls_and_hidden_editor(overlay):
    app = overlay
    assert not app.expanded
    assert not app.details.winfo_ismapped()
    assert app.compact.winfo_ismapped()
    assert app.winfo_width() <= round(370 * app.ui_scale)
    assert app.winfo_height() <= round(140 * app.ui_scale)
    assert app.overrideredirect()
    assert app.attributes('-topmost')
    for widget in (app.speak_button, app.toggle_button, app.close_button, app.peek_label):
        assert widget.winfo_ismapped()
        assert fits(bounds(widget), bounds(app))
    assert not app.busy and app.voice_phase == 'idle' and app.last_result is None


def test_drawer_preserves_anchor_and_core_control_positions(overlay):
    app = overlay
    collapsed = bounds(app)
    microphone = bounds(app.speak_button)
    app.toggle()
    app.update()
    assert app.expanded and app.details.winfo_ismapped()
    assert bounds(app)[2:] == collapsed[2:]
    assert bounds(app.speak_button) == microphone
    assert app.command_entry.winfo_ismapped()
    assert app.notebook.tab(app.notebook.select(), 'text') == 'Apps'
    app.notebook.select(1)  # Cuts are available when selected; Apps is the default.
    app.update()
    assert app.cut_list.winfo_ismapped()
    assert fits(bounds(app.details), bounds(app))
    assert any(button.cget('text') == 'Export MP4' and button.winfo_ismapped() for button in app.buttons)
    for button in app.buttons:
        if button.cget('text') in {'Export MP4', 'Export edit list', 'Clear edits'}:
            assert button.winfo_height() >= 25 and fits(bounds(button), bounds(app.details))
    app.toggle()
    app.update()
    assert not app.expanded and not app.details.winfo_ismapped()
    assert bounds(app) == collapsed
    assert bounds(app.speak_button) == microphone


def test_drag_callback_clamps_compact_and_expanded_to_monitor_work_area(overlay):
    app = overlay
    area = app._work_area(app.winfo_x(), app.winfo_y())
    for expanded in (False, True):
        if app.expanded != expanded:
            app.toggle()
            app.update()
        for target in ((area[0]-1000, area[1]-1000), (area[2]+1000, area[3]+1000)):
            origin = bounds(app.drag_handle)
            app._drag_start(SimpleNamespace(x_root=origin[0]+5, y_root=origin[1]+5))
            app._drag(SimpleNamespace(x_root=target[0], y_root=target[1]))
            app.update()
            assert fits(bounds(app), app._work_area(*target))
    assert not app.busy and app.last_result is None


def test_errors_show_a_visible_actionable_popup_while_editor_stays_hidden(overlay, monkeypatch):
    import system_tools
    app = overlay
    if app.expanded:
        app.toggle()
    app.status.set('Error: Select a video first')
    app.update()
    assert not app.expanded and not app.details.winfo_ismapped()
    assert app.notice.winfo_ismapped()
    assert 'Select a video first' in app.notice_text.get()
    assert app.notice_action.cget('text') == 'Open video'
    opened = []
    monkeypatch.setattr(system_tools, 'open_device_settings', opened.append)
    app.status.set('Error: Windows denies microphone access. Check Windows privacy settings.')
    app.update()
    assert app.notice_action.cget('text') == 'Open Windows settings'
    app.notice_action.invoke()
    assert opened == ['microphone']
    app._dismiss_notice()
    app.status.set('Ready')
    app.update()
    assert app.notice is None and not app.busy


def test_no_speech_has_retry_and_a_working_local_microphone_picker(overlay, monkeypatch):
    import voice
    app = overlay
    monkeypatch.setattr(voice, 'list_microphones', lambda: ['Test microphone'])
    monkeypatch.setenv('KAAT_MICROPHONE', '')
    app.status.set('Error: No words were recognized from the captured speech. Try again or choose a microphone.')
    app.update()
    assert app.notice_action.cget('text') == 'Try again'
    assert app.notice_secondary.winfo_ismapped()
    app.notice_secondary.invoke()
    app.update()
    picker = next(child for child in app.notice.winfo_children() if child.winfo_class() == 'TCombobox')
    assert picker.winfo_ismapped() and 'Test microphone' in picker.cget('values')
    picker.set('Test microphone')
    app.notice_action.invoke()
    app.update()
    assert app.controller.memory.preferences()['microphone'] == 'Test microphone'
    assert voice.os.environ['KAAT_MICROPHONE'] == 'Test microphone'
    assert not app.busy and app.voice_phase == 'idle'
    app._dismiss_notice()
    app.status.set('Ready')


def test_local_allow_is_required_and_resumes_only_the_requested_action(overlay, monkeypatch):
    app = overlay
    app.device_consent = None
    app.permission_file.unlink(missing_ok=True)
    work = []
    monkeypatch.setattr(app, 'work', lambda function, task: work.append(task))
    app.hear()
    app.update()
    assert app.permission_prompt_open and app.notice_action.cget('text') == 'Allow'
    assert app.notice_secondary.cget('text') == 'Not now'
    assert not work and not app.busy and app.voice_phase == 'idle'
    app.notice_secondary.invoke()
    assert not app.permission_file.exists() and not work
    app.submit('camera.open')
    app.update()
    assert not work and app.permission_prompt_open
    app.notice_action.invoke()
    assert app.device_consent is True
    assert json.loads(app.permission_file.read_text(encoding='utf-8')) == {'version': 1, 'devices': True}
    assert len(work) == 1 and app.notice is None
    app.submit('camera.open')
    assert len(work) == 2 and app.notice is None


def test_typed_camera_command_waits_for_client_consent(overlay, monkeypatch):
    app = overlay
    app.device_consent = None
    work = []
    monkeypatch.setattr(app, 'work', lambda function, task: work.append(task))
    app.command_entry.insert(0, 'open camera')
    app.run_command()
    assert not work and app.permission_prompt_open
    app.notice_action.invoke()
    assert work == ['Recognizing command…'] and app.command_entry.get() == ''
    assert app.heard.get() == 'Typed: open camera'


def test_background_os_status_does_not_replace_the_allow_popup(overlay):
    app = overlay
    app.device_consent = None
    app._request_permissions()
    while not app.events.empty():
        app.events.get_nowait()
    app.events.put(({'device_status': {'camera': {'status': 'blocked'}}}, None))
    app._poll()
    assert app.devices['camera']['status'] == 'blocked'
    assert app.permission_prompt_open and app.notice_action.cget('text') == 'Allow'
    app._drag_start(SimpleNamespace(x_root=app.winfo_x()+5, y_root=app.winfo_y()+5))
    app._drag(SimpleNamespace(x_root=app.winfo_x()+15, y_root=app.winfo_y()+15))
    app.update()
    assert app.permission_prompt_open and app.notice_action.cget('text') == 'Allow'
    app._decline_permissions()
    app.device_consent = True


def test_incomplete_camera_request_offers_local_action_without_starting_capture(overlay, monkeypatch):
    # Callback/consent unit check, not a claim of actual camera recording.
    app = overlay
    app.device_consent = None
    work = []
    monkeypatch.setattr(app, 'work', lambda function, task: work.append(task))
    result = app.controller.command('But recording from the camera app.')
    assert result['status'] == 'needs_clarification' and not result['verified']
    while not app.events.empty():
        app.events.get_nowait()
    app.events.put(({**result, 'heard': 'But recording from the camera app.'}, None))
    app._poll()
    app.update()
    assert app.notice.winfo_ismapped()
    assert app.notice_action.cget('text') == 'Start recording'
    assert app.notice_dismiss.cget('text') == 'Not now'
    assert not work and not getattr(app, '_notice_timer', None)
    app.notice_action.invoke()
    assert app.permission_prompt_open and not work
    assert app.notice_action.cget('text') == 'Allow'
    app.notice_action.invoke()
    assert app.device_consent is True and len(work) == 1
    # Remembered consent requires no second permission prompt.
    app.submit('camera.start_recording', approved=True)
    assert len(work) == 2 and not app.permission_prompt_open
    app._dismiss_notice()
    app.status.set('Ready')
