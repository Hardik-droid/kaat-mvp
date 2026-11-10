"""Planner boundary UNIT tests. HTTP responses are replaced; no live LLM claim."""
import io
import json
from urllib.error import HTTPError

import pytest

import optional_planner as planner


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('KAAT_PLANNER_URL', 'http://127.0.0.1:1234/v1/chat/completions')
    monkeypatch.setenv('KAAT_PLANNER_MODEL', 'unit-test-model')
    monkeypatch.delenv('KAAT_PLANNER_KEY', raising=False)


def response(monkeypatch, value, observed=None):
    class Opener:
        def open(self, request, timeout):
            if observed is not None:
                observed.append((request, timeout))
            return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(value)}}]}).encode())
    monkeypatch.setattr(planner, 'build_opener', lambda *args: Opener())


def test_no_configuration_never_connects(monkeypatch):
    monkeypatch.delenv('KAAT_PLANNER_URL', raising=False)
    monkeypatch.delenv('KAAT_PLANNER_MODEL', raising=False)
    monkeypatch.setattr(planner, 'build_opener', lambda *args: pytest.fail('No network without opt-in'))
    result = planner.propose_plan('Do something complicated')
    assert result['status'] == 'unknown' and result['verified'] is False


def test_compatible_request_only_returns_inert_review_steps(configured, monkeypatch):
    observed = []
    response(monkeypatch, {'steps': [{'tool': 'system.open_application', 'arguments': {'application': 'Google Chrome'}}]}, observed)
    result = planner.propose_plan('Open Chrome then show my preferences', {'history': 'private-history', 'source': None})
    assert result['status'] == 'needs_review' and result['verified'] is False
    assert result['proposal'] == [{'tool': 'system.open_application', 'arguments': {'application': 'chrome'}, 'requires_review': True}]
    payload = json.loads(observed[0][0].data)
    assert payload['model'] == 'unit-test-model'
    assert 'private-history' not in observed[0][0].data.decode()
    assert observed[0][1] == 20


@pytest.mark.parametrize('tool,arguments', [
    ('shell.execute', {'command': 'whoami'}),
    ('video.approve_all', {}),
    ('system.open_application', {'application': 'notepad', 'shell': True}),
    ('system.open_application', {'application': 'notepad & calc'}),
    ('system.open_website', {'url': 'javascript:alert(1)'}),
    ('memory.save_preference', {'key': 'pause_threshold', 'value': True}),
    ('video.detect_pauses', {'min_pause_seconds': float('nan')}),
])
def test_unsafe_or_unsupported_steps_are_rejected(configured, monkeypatch, tool, arguments):
    response(monkeypatch, {'steps': [{'tool': tool, 'arguments': arguments}]})
    result = planner.propose_plan('Unit request')
    assert result['status'] == 'failed' and result['verified'] is False
    assert result['proposal'] == []


def test_paths_must_be_selected_or_explicit_and_output_must_be_new(configured, monkeypatch, tmp_path):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'UNIT PATH VALIDATION ONLY')
    output = tmp_path / 'edited.mp4'
    steps = {'steps': [{'tool': 'video.inspect', 'arguments': {'source': str(source)}},
                       {'tool': 'video.export', 'arguments': {'output': str(output)}}]}
    response(monkeypatch, steps)
    assert planner.propose_plan('Edit this video', {'source': str(source)})['status'] == 'failed'
    result = planner.propose_plan(f'Edit current video and export to "{output}"', {'source': str(source)})
    assert result['status'] == 'needs_review'
    output.write_bytes(b'EXISTING OUTPUT MUST NOT CHANGE')
    assert planner.propose_plan(f'Export to "{output}"', {'source': str(source)})['status'] == 'failed'
    assert output.read_bytes() == b'EXISTING OUTPUT MUST NOT CHANGE'


def test_relative_date_requires_clarification_without_network(configured, monkeypatch, tmp_path):
    monkeypatch.setattr(planner, 'build_opener', lambda *args: pytest.fail('Do not guess a recording'))
    result = planner.propose_plan('Kaat, kal wali video nikal aur export kar', {'source': str(tmp_path / 'selected.mp4')})
    assert result['status'] == 'needs_clarification'
    assert result['proposal'] == [] and result['verified'] is False


def test_provider_errors_never_expose_key_or_body(configured, monkeypatch):
    monkeypatch.setenv('KAAT_PLANNER_KEY', 'unit-private-key')
    class Opener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 401, 'unit-private-key', {}, io.BytesIO(b'unit-private-key'))
    monkeypatch.setattr(planner, 'build_opener', lambda *args: Opener())
    result = planner.propose_plan('Open Chrome and Notepad')
    assert result['status'] == 'failed' and '401' in result['message']
    assert 'unit-private-key' not in json.dumps(result)


def test_redirects_are_disabled_and_remote_plaintext_is_rejected(configured, monkeypatch):
    assert planner._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid') is None
    monkeypatch.setenv('KAAT_PLANNER_URL', 'http://remote.invalid/v1/chat/completions')
    monkeypatch.setattr(planner, 'build_opener', lambda *args: pytest.fail('Do not transmit remote plaintext'))
    assert planner.propose_plan('Open Chrome and Notepad')['status'] == 'failed'
