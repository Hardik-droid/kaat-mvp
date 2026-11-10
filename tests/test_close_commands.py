"""Close-command parser/routing UNIT checks; no GUI windows are closed here."""
import pytest

from commands import parse_command
from controller import AgentController
from memory import Memory


@pytest.mark.parametrize('text', [
    'Close all those stuff which you have opened recently.',
    'Kaat, close all those stuff which you have opened recently.',
    'Close everything you opened.',
    'Close the apps you just opened.',
    'Close the windows you opened recently.',
    'Kaat, close all apps you opened.',
    'Can you just close what you opened?',
    'Please close everything that you opened.',
    'Jo apps tumne abhi khole hain unko band kar do.',
    'Tumne jo apps khole the unko band kar do.',
    'Kaat, jo tumne khola hai woh sab band kar de.',
])
def test_only_explicit_kaat_opened_scope_routes_to_close_recent(text):
    assert parse_command(text) == ('close_recent', {})


@pytest.mark.parametrize('text', [
    'Kaat, do not close the apps you opened.',
    "Kaat, don't close everything you opened.",
    'Kaat, jo apps tumne khole unko band mat karna.',
    'Kaat, tumne jo apps khole unko band nahi karna.',
    'Kaat, close the apps you opened later.',
    'Kaat, how do I close the apps you opened?',
    'Kaat, I will close the apps you opened.',
    'Close everything I opened.',
    'Close the apps you opened and delete their files.',
    'Close the apps you opened except Notepad.',
])
def test_negation_deferral_unsafe_combination_and_different_scope_do_not_close(text):
    assert parse_command(text)[0] != 'close_recent'


def test_background_speech_without_wake_word_never_closes_windows():
    phrase = 'Close all those stuff which you have opened recently.'
    assert parse_command(phrase, activated=False)[0] == 'unknown'
    assert parse_command('Kaat, ' + phrase, activated=False) == ('close_recent', {})


@pytest.mark.parametrize('text', ['Close all.', 'Close everything.', 'Close all apps.'])
def test_ambiguous_close_requests_ask_for_scope_without_calling_tools(tmp_path, monkeypatch, text):
    assert parse_command(text)[0] != 'close_recent'
    agent = AgentController(tmp_path / 'close_scope.sqlite3')
    monkeypatch.setattr(agent, 'call', lambda *args, **kwargs: pytest.fail('No close tool before scope is clear'))
    monkeypatch.setattr('optional_planner.propose_plan', lambda *args, **kwargs: pytest.fail('Clarify close scope locally'))
    result = agent.command(text)
    assert result['status'] == 'needs_clarification'
    assert result['verified'] is False


def _record(hwnd, nonce):
    """Synthetic ownership record for SQLite/routing checks, never a real HWND."""
    import time
    return {'version': 1, 'hwnd': hwnd, 'nonce': nonce, 'pid': 4321,
            'image': r'C:\Windows\System32\notepad.exe', 'app_id': '', 'class': 'Notepad',
            'application': 'notepad', 'target': 'notepad', 'opened_at': time.time(),
            'application_identity': {'pid': 4321, 'image': r'C:\Windows\System32\notepad.exe', 'app_id': ''}}


def _identities(records):
    return {(record['hwnd'], record['nonce']) for record in records}


def test_journal_survives_restart_and_removes_exact_identity_only(tmp_path):
    """Real SQLite durability/identity test; no native window-control evidence."""
    path = tmp_path / 'journal.sqlite3'
    older = _record(101, 501)
    reused_handle = _record(101, 502)
    separate_client = _record(102, 503)
    first = Memory(path)
    first.save_opened_windows([older])
    second = Memory(path)
    second.save_opened_windows([reused_handle, separate_client])
    assert _identities(Memory(path).opened_windows()) == {(101, 501), (101, 502), (102, 503)}
    first.remove_opened_windows([older])
    assert _identities(Memory(path).opened_windows()) == {(101, 502), (102, 503)}


def test_typed_launch_persists_ownership_and_close_keeps_pending_and_concurrent_rows(tmp_path, monkeypatch):
    """UNIT fake Windows boundary, with real controller and SQLite persistence."""
    from tools import windows_apps
    path = tmp_path / 'route.sqlite3'
    records = [_record(200 + i, 700 + i) for i in range(4)]
    concurrent = _record(209, 709)
    def opened(name):
        assert name == 'notepad'
        return {'application': name, 'target': name, 'status': 'success', 'verified': True,
                'message': 'UNIT boundary: no actual app launch', 'opened_windows': records, 'windows': []}
    monkeypatch.setattr(windows_apps, 'open_application', opened)
    first = AgentController(path)
    assert first.command('Open Notepad.')['ok']
    first.close()
    assert _identities(Memory(path).opened_windows()) == _identities(records)
    calls = []
    def close_boundary(opened_records):
        calls.append(opened_records)
        Memory(path).save_opened_windows([concurrent])
        return {'closed': [records[0]], 'already_closed': [records[1]],
                'pending': [{**records[2], 'reason': 'UNIT simulated unsaved document prompt'}],
                'skipped': [{**records[3], 'reason': 'UNIT simulated stale ownership'}],
                'status': 'unverified', 'verified': False, 'message': 'UNIT: one window remains pending'}
    monkeypatch.setattr(windows_apps, 'close_opened_windows', close_boundary, raising=False)
    restarted = AgentController(path)
    result = restarted.command('Close all those stuff which you have opened recently.')
    assert len(calls) == 1 and _identities(calls[0]) == _identities(records)
    assert result['status'] == 'unverified' and result['verified'] is False
    assert _identities(Memory(path).opened_windows()) == _identities([records[2], concurrent])


def test_direct_close_tool_without_user_approval_never_reaches_backend(tmp_path, monkeypatch):
    agent = AgentController(tmp_path / 'approval.sqlite3')
    agent.memory.save_opened_windows([_record(301, 801)])
    monkeypatch.setattr('tools.windows_apps.close_opened_windows', lambda records: pytest.fail('Missing explicit close request'), raising=False)
    result = agent.call('system.close_recent')
    assert result['ok'] is False
    assert len(agent.memory.opened_windows()) == 1


def test_empty_journal_does_not_claim_that_existing_windows_closed(tmp_path, monkeypatch):
    agent = AgentController(tmp_path / 'empty.sqlite3')
    monkeypatch.setattr('tools.windows_apps.close_opened_windows', lambda records: pytest.fail('Never fall back to all desktop windows'), raising=False)
    result = agent.command('Close the apps you opened.')
    assert result['status'] == 'nothing_to_close' and result['verified'] is False
    assert result['data']['closed'] == []


def test_recording_camera_is_protected_and_kept_in_journal(tmp_path, monkeypatch):
    """UNIT simulated adapter state; no real camera is opened or queried."""
    agent = AgentController(tmp_path / 'recording.sqlite3')
    camera = {**_record(302, 802), 'application': 'camera', 'target': 'camera'}
    agent.memory.save_opened_windows([camera])
    monkeypatch.setattr('tools.windows_apps.owned_window_status', lambda record: 'owned', raising=False)
    monkeypatch.setattr('system_tools.camera_control', lambda action: {'state': 'recording'})
    def no_camera_close(records):
        assert records == [], 'Active recording must never reach close backend'
        return {'closed': [], 'already_closed': [], 'pending': [], 'skipped': [],
                'status': 'success', 'verified': True, 'message': 'UNIT empty backend input'}
    monkeypatch.setattr('tools.windows_apps.close_opened_windows', no_camera_close, raising=False)
    result = agent.command('Close the apps you opened.')
    assert result['status'] == 'needs_attention' and result['verified'] is False
    assert _identities(agent.memory.opened_windows()) == _identities([camera])
