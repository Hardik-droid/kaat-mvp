"""Verification for Whisper rebranding, presentation mode, and smart commands."""
import pytest
from commands import parse_command
from controller import AgentController


@pytest.mark.parametrize('phrase,expected_intent,expected_args', [
    ('Whisper, open Chrome.', 'open_application', {'application': 'chrome'}),
    ('Hey Whisper, open Notepad.', 'open_application', {'application': 'notepad'}),
    ('Whisper, open PowerPoint.', 'open_application', {'application': 'powerpoint'}),
    ('Open PowerPoint.', 'open_application', {'application': 'powerpoint'}),
    ('PowerPoint khol de.', 'open_application', {'application': 'powerpoint'}),
    ('Whisper, give the presentation.', 'presentation', {}),
    ('Start presentation.', 'presentation', {}),
    ('Whisper, introduce yourself.', 'presentation', {}),
    ('Whisper, who are you?', 'identity', {}),
    ('Whisper, what time is it?', 'system_time', {}),
    ('What is the time?', 'system_time', {}),
    ('Whisper, what is today s date?', 'system_date', {}),
    ('Whisper, tell me a joke.', 'joke', {}),
    ('Tell me a joke.', 'joke', {}),
    ('Whisper, volume up.', 'system_volume_up', {}),
    ('Whisper, volume down.', 'system_volume_down', {}),
    ('Whisper, mute.', 'system_mute', {}),
    ('Whisper, take a screenshot.', 'system_screenshot', {}),
    ('Whisper, close Chrome.', 'close_application', {'application': 'chrome'}),
    ('Whisper, close this window.', 'close_active_window', {}),
    ('Search for deep learning on Google.', 'web_search', {'query': 'deep learning'}),
    ('Play jazz music on YouTube.', 'youtube_play', {'query': 'jazz music'}),
])
def test_whisper_intents_parsed(phrase, expected_intent, expected_args):
    intent, args = parse_command(phrase, activated=True)
    assert intent == expected_intent
    assert args == expected_args


def test_whisper_controller_responses(tmp_path, monkeypatch):
    monkeypatch.setenv("WHISPER_MUTE_TTS", "1")
    agent = AgentController(tmp_path / 'whisper.sqlite3')

    # Test time
    res = agent.command('Whisper, what time is it?')
    assert res['ok'] is True
    assert 'The current time is' in res['data']['message']

    # Test date
    res = agent.command('Whisper, what is today s date?')
    assert res['ok'] is True
    assert 'Today is' in res['data']['message']

    # Test joke
    res = agent.command('Whisper, tell me a joke.')
    assert res['ok'] is True
    assert len(res['data']['message']) > 5

    # Test identity
    res = agent.command('Whisper, who are you?')
    assert res['ok'] is True
    assert 'Whisper' in res['data']['message']

    # Test presentation
    res = agent.command('Whisper, give the presentation.')
    assert res['ok'] is True
    assert 'Whisper' in res['data']['message']
    assert res['data'].get('presentation') is True
