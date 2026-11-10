"""Parser-only camera phrasing checks; no microphone or Camera operations."""
import pytest

from commands import parse_command


@pytest.mark.parametrize('text,intent', [
    ('Start recording from the camera app.', 'record_start'),
    ('Kaat, can you just start recording in the Camera app?', 'record_start'),
    ('Please begin recording using Windows Camera.', 'record_start'),
    ('Start recording a video with the camera app.', 'record_start'),
    ('Stop the recording in the camera app.', 'record_stop'),
    ('Finish recording from my camera.', 'record_stop'),
    ('Pause recording using the camera app please.', 'record_pause'),
    ('Resume recording in Windows Camera.', 'record_resume'),
    ('Using the camera app continue recording.', 'record_resume'),
    ('Camera app se recording start kar do.', 'record_start'),
    ('Kaat, camera mein recording shuru kar.', 'record_start'),
    ('Recording camera app se band kar do.', 'record_stop'),
    ('Camera app mein recording pause kar do.', 'record_pause'),
    ('Camera app par recording resume karo.', 'record_resume'),
    ('कैमरा ऐप में रिकॉर्डिंग शुरू कर दो', 'record_start'),
    ('कैमरा ऐप में रिकॉर्डिंग बंद कर दो', 'record_stop'),
    ('कैमरा ऐप में रिकॉर्डिंग रोको', 'record_pause'),
    ('कैमरा ऐप में रिकॉर्डिंग जारी करो', 'record_resume'),
    ('Camera open kar aur recording start kar.', 'record_start'),
])
def test_explicit_recording_verbs_accept_camera_qualifiers(text, intent):
    assert parse_command(text) == (intent, {})


@pytest.mark.parametrize('text', [
    'But recording from the camera app.',
    'Recording from the camera app.',
    'Kaat, recording using Windows Camera.',
    'Camera app se recording.',
])
def test_fragment_without_control_verb_asks_before_starting(text):
    intent, arguments = parse_command(text)
    assert intent == 'clarify_recording'
    assert arguments['suggested_command'] == 'Start recording from the camera app.'
    assert 'No recording action was taken' in arguments['reason']


@pytest.mark.parametrize('text', [
    'Do not start recording from the camera app.',
    "Kaat, don't stop recording in the camera app.",
    'Camera app se recording start mat karna.',
    'कैमरा ऐप में रिकॉर्डिंग शुरू मत करो',
    'How do I start recording from the camera app?',
    'I will start recording from the camera app.',
    'Start recording from the camera app tomorrow.',
    'We are recording from the camera app.',
    'But recording from the camera app failed yesterday.',
    'Start recording from the camera app and export this video.',
    'Start recording from the camera app and remove fillers.',
    'Stop recording from the camera app and open Notepad.',
    'Start recording in OBS.',
])
def test_negation_conversation_compounds_and_other_apps_stay_unsupported(text):
    assert parse_command(text)[0] == 'unknown'


def test_recording_qualifier_does_not_bypass_activation():
    assert parse_command('Start recording from the camera app.', activated=False)[0] == 'unknown'
    assert parse_command('Kaat, start recording from the camera app.', activated=False) == ('record_start', {})
