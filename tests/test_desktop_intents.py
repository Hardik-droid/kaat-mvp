"""Parser/contract units; real Windows evidence is check_windows_apps.py."""
import pytest

from commands import parse_command
from controller import AgentController


@pytest.mark.parametrize('text,intent,key,target', [
    ('Kaat, open Chrome.', 'open_application', 'application', 'chrome'),
    ('Kaat, Chrome khol de.', 'open_application', 'application', 'chrome'),
    ('Open Notepad.', 'open_application', 'application', 'notepad'),
    ('Notepad chala de.', 'open_application', 'application', 'notepad'),
    ('Open Calculator.', 'open_application', 'application', 'calculator'),
    ('Calculator kholo.', 'open_application', 'application', 'calculator'),
    ('Open File Explorer.', 'open_application', 'application', 'explorer'),
    ('Open Google Photos.', 'open_website', 'url', 'https://photos.google.com/'),
    ('Google Photos khol de.', 'open_website', 'url', 'https://photos.google.com/'),
    ('Open YouTube.', 'open_website', 'url', 'https://www.youtube.com/'),
    ('Mujhe YouTube khol ke dikha.', 'open_website', 'url', 'https://www.youtube.com/'),
    ('Open my Downloads folder.', 'open_folder', 'path', 'downloads'),
    ('Mera Downloads folder khol.', 'open_folder', 'path', 'downloads'),
    ('Chrome open karna.', 'open_application', 'application', 'chrome'),
])
def test_requested_desktop_phrases(text, intent, key, target):
    assert parse_command(text) == (intent, {key:target})
    assert parse_command(text.removeprefix('Kaat, '), activated=False)[0] == 'unknown'


def test_recording_phrase_and_cancel():
    assert parse_command('Hey, can you just start recording few seconds of reel? Main Hindi mein bolunga.') == ('record_start', {})
    assert parse_command('never mind') == ('cancel', {})
    assert parse_command('Kaat, pichla cut undo kar.') == ('undo', {})


@pytest.mark.parametrize('text', ['do not open Chrome', 'Chrome mat kholo', 'I will open Chrome later',
                                'open Chrome and delete files', 'how to open Notepad'])
def test_ambiguous_desktop_requests_do_not_execute(text):
    assert parse_command(text)[0] == 'unknown'


def test_memory_and_pending_contract(tmp_path):
    agent = AgentController(tmp_path/'memory.sqlite3')
    result = agent.command('remember my pause threshold is two seconds')
    assert result['status'] == 'success' and result['verified']
    assert agent.command('remember to save my original videos')['verified']
    restarted = AgentController(tmp_path/'memory.sqlite3')
    assert restarted.memory.preferences() == {'pause_threshold':2., 'preserve_original':True}
    for text in ('select video', 'export video'):
        result = agent.command(text)
        assert result['status'] == 'needs_input' and not result['verified']


def test_unverified_launch_does_not_report_completed(tmp_path, monkeypatch):
    # This deliberately supplies an inconclusive adapter result; it is a unit,
    # not a Windows launch or live provider success claim.
    import system_tools
    monkeypatch.setattr(system_tools, 'open_application', lambda **args: {
        'status':'unverified', 'verified':False, 'message':'No matching window observed.'})
    agent = AgentController(tmp_path/'memory.sqlite3')
    result = agent.command('open Chrome')
    assert not result['ok'] and not result['verified'] and result['status'] == 'unverified'
    assert agent.memory.history()[0]['ok'] == 0
