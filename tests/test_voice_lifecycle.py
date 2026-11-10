"""Unit checks for phase ordering only; these do not claim a physical mic test."""
from array import array
import sys
from types import SimpleNamespace

import pytest
import voice


def test_listening_is_emitted_only_after_the_stream_is_open(monkeypatch):
    events = []
    class Stream:
        def __enter__(self):
            events.append('stream_open')
            return self
        def __exit__(self, *args):
            events.append('stream_closed')
        def read(self, count):
            return array('h', [500]*count).tobytes(), False
    audio = SimpleNamespace(RawInputStream=lambda **kwargs: Stream(), PortAudioError=RuntimeError)
    monkeypatch.setitem(sys.modules, 'sounddevice', audio)
    monkeypatch.setattr(voice, '_input_configuration', lambda _: (None, 16000, 1, 'unit stream'))
    monkeypatch.setattr(voice, '_command_speech', lambda pcm: pcm)  # This unit checks phase ordering only.
    pcm = voice._capture_in_process(.5, on_phase=lambda phase, message: events.append(phase))
    assert events.index('listening') > events.index('stream_open')
    assert events.index('processing') > events.index('stream_closed')
    assert len(pcm) == 16000


def test_missing_key_reports_preparation_but_never_claims_listening(monkeypatch):
    phases = []
    monkeypatch.delenv('GNANI_API_KEY', raising=False)
    with pytest.raises(RuntimeError, match='GNANI_API_KEY'):
        voice.hear_command(on_phase=lambda phase, message: phases.append(phase))
    assert phases == ['preparing']


def _hung_unit_worker(connection, seconds):
    import time
    time.sleep(30)


def test_a_native_open_hang_is_bounded_and_leaves_no_child():
    """Actual process termination test, not a successful-microphone assertion."""
    import multiprocessing
    import time
    before = {child.pid for child in multiprocessing.active_children()}
    started = time.monotonic()
    with pytest.raises(RuntimeError, match='opening timed out'):
        voice._bounded_capture(.5, worker=_hung_unit_worker, open_timeout=.4)
    assert time.monotonic()-started < 5
    assert {child.pid for child in multiprocessing.active_children()} <= before


def test_denied_runtime_fails_before_claiming_microphone_capture(monkeypatch):
    phases=[]
    monkeypatch.setattr(voice,'microphone_permission_error',lambda:'Windows denies this runtime microphone access')
    with pytest.raises(RuntimeError,match='denies this runtime'):
        voice._capture_in_process(.5,on_phase=lambda phase,message:phases.append(phase))
    assert 'listening' not in phases


@pytest.mark.parametrize('sections,expected_frames,raises', [
    ([(.6, 600), (5.4, 0)], 32000, False),
    ([(.6, 600), (.6, 0), (.6, 600), (4.2, 0)], 44800, False),
    ([(6., 0)], 96000, True),
    ([(.02, 600), (5.98, 0)], 96000, True),
])
def test_end_detection_saves_wait_but_keeps_internal_pauses_and_ignores_clicks(monkeypatch, sections, expected_frames, raises):
    """Deterministic PCM stream units; no physical microphone or provider claim."""
    samples = array('h')
    for seconds, level in sections:
        samples.extend([level] * round(seconds * 16000))
    position = 0
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, count):
            nonlocal position
            chunk = samples[position:position+count].tobytes()
            position += count
            return chunk, False
    audio = SimpleNamespace(RawInputStream=lambda **kwargs: Stream(), PortAudioError=RuntimeError)
    monkeypatch.setitem(sys.modules, 'sounddevice', audio)
    monkeypatch.setattr(voice, '_input_configuration', lambda _: (None, 16000, 1, 'unit PCM stream'))
    monkeypatch.setattr(voice, 'microphone_permission_error', lambda: None)
    # Isolate endpoint timing from classifier quality, which is checked with
    # actual noise below and public human audio in the live integration check.
    monkeypatch.setattr(voice, '_speech_frame', lambda detector, pcm, rate, channels: bool(array('h', pcm)[0]))
    monkeypatch.setattr(voice, '_command_speech', voice.trim_voice_activity)
    if raises:
        with pytest.raises(RuntimeError, match='No microphone activity'):
            voice._capture_in_process(6)
    else:
        voice._capture_in_process(6)
    assert position == expected_frames


def test_real_vad_rejects_steady_noise_before_a_provider_request():
    import random
    for level in (0, 30, 80, 300, 1000):
        rng = random.Random(51)
        pcm = array('h', (round(rng.gauss(0, level)) for _ in range(16000*4))).tobytes()
        with pytest.raises(RuntimeError, match='No speech detected'):
            voice._command_speech(pcm)


def test_local_gain_is_bounded_does_not_clip_and_keeps_silence():
    quiet = array('h', [0, 100, -200]).tobytes()
    assert list(array('h', voice._normalize_command(quiet))) == [0, 1200, -2400]
    loud = array('h', [0, 30000, -32768]).tobytes()
    assert voice._normalize_command(loud) == loud
    assert voice._normalize_command(b'\0\0'*100) == b'\0\0'*100


def test_microphone_channels_do_not_cancel_or_select_an_empty_reference():
    opposed = array('h', [1000, -1000, 2000, -2000]).tobytes()
    assert list(array('h', voice._microphone_mono(opposed, 2))) == [1000, 2000]
    reference = array('h', [0, 1500, 0, -1600]).tobytes()
    assert list(array('h', voice._microphone_mono(reference, 2))) == [1500, -1600]


def test_duration_uses_local_setting_and_rejects_invalid_values_before_capture(monkeypatch):
    monkeypatch.setenv('KAAT_CAPTURE_SECONDS', '12.5')
    assert voice.recording_duration() == 12.5
    assert voice.recording_duration(3) == 3
    monkeypatch.setattr(voice, '_bounded_capture', lambda *a, **kw: pytest.fail('Invalid duration must not open input'))
    for value in ('0', '26', 'nan', 'inf', 'abc', ''):
        monkeypatch.setenv('KAAT_CAPTURE_SECONDS', value)
        with pytest.raises(ValueError, match='between 0.5 and 25'):
            voice.capture_command_audio()


def test_cancelled_command_never_opens_microphone_or_provider(monkeypatch):
    from threading import Event
    cancelled = Event()
    cancelled.set()
    monkeypatch.setattr(voice, '_client', lambda: pytest.fail('Cancelled request must not create provider client'))
    with pytest.raises(voice.VoiceCancelled):
        voice.hear_command(cancel_event=cancelled)


def test_cancellation_terminates_actual_capture_worker_and_leaves_no_child():
    """Actual process cleanup under cancellation, not a physical-mic claim."""
    import multiprocessing
    from threading import Event, Timer
    import time
    cancelled = Event()
    before = {child.pid for child in multiprocessing.active_children()}
    timer = Timer(.25, cancelled.set)
    started = time.monotonic()
    timer.start()
    try:
        with pytest.raises(voice.VoiceCancelled):
            voice._bounded_capture(6, cancel_event=cancelled, worker=_hung_unit_worker)
    finally:
        timer.cancel()
    assert time.monotonic()-started < 3
    assert {child.pid for child in multiprocessing.active_children()} <= before


def test_cancel_during_provider_request_discards_result_and_temporary_audio(monkeypatch):
    """Unit-only provider response: cancellation must prevent command dispatch."""
    from pathlib import Path
    from threading import Event
    cancelled = Event()
    temporary_audio = []
    phases = []
    monkeypatch.setattr(voice, '_client', lambda: object())
    monkeypatch.setattr(voice, 'capture_command_audio', lambda *a, **kw: b'\0\0'*16000)
    def provider(path, **kwargs):
        temporary_audio.append(Path(path))
        cancelled.set()
        return {'text': 'Open Notepad'}
    monkeypatch.setattr(voice, 'transcribe_audio', provider)
    with pytest.raises(voice.VoiceCancelled):
        voice.hear_command(cancel_event=cancelled, on_phase=lambda phase, message: phases.append(phase))
    assert 'recognized' not in phases
    assert temporary_audio and all(not path.exists() for path in temporary_audio)
