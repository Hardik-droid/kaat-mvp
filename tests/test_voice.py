"""Provider boundary unit tests; only the opt-in final test makes a real call."""
from array import array
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import wave

import pytest

import voice
from engine import _binary


def ffmpeg_available():
    try:
        _binary("ffmpeg")
        _binary("ffprobe")
        return True
    except RuntimeError:
        return False


def write_wav(path, seconds=.2):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * int(16000 * seconds))
    return path


def test_provider_parameters_and_no_invented_timing(tmp_path, monkeypatch):
    calls = []

    def transcribe(*args, **kwargs):
        calls.append((args, kwargs))
        return {"success": True, "transcript": " Kaat, pauses hata de. ", "model": "prisma-v3.0"}

    monkeypatch.setattr(voice, "_client", lambda: SimpleNamespace(transcribe=transcribe))
    result = voice.transcribe_audio(write_wav(tmp_path / "command.wav"))
    assert result["text"] == "Kaat, pauses hata de."
    assert result["timing"] == "untimed" and "start" not in result and "words" not in result
    assert calls[0][1] == {"language_code": "indic-auto", "model": "prisma-v3.0", "format": "verbatim",
                           "language_candidates": ["hi-IN", "en-IN"]}


@pytest.mark.parametrize("response", [None, {}, {"success": False},
    {"success": True, "transcript": {}},
    {"success": True, "transcript": "text", "truncated": True},
    {"success": True, "transcript": "text", "model": "prisma-v2.5"}])
def test_invalid_provider_response_is_visible(tmp_path, monkeypatch, response):
    monkeypatch.setattr(voice, "_client", lambda: SimpleNamespace(transcribe=lambda *a, **kw: response))
    with pytest.raises(RuntimeError):
        voice.transcribe_audio(write_wav(tmp_path / "command.wav"))


def test_no_speech_is_a_valid_provider_response(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "_client", lambda: SimpleNamespace(
        transcribe=lambda *a, **kw: {"success": True, "transcript": ""}))
    assert voice.transcribe_audio(write_wav(tmp_path / "silence.wav"))["text"] == ""


def test_provider_error_does_not_leak_credentials(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private-key-should-not-appear")
    monkeypatch.setattr(voice, "_client", lambda: SimpleNamespace(transcribe=fail))
    with pytest.raises(RuntimeError) as error:
        voice.transcribe_audio(write_wav(tmp_path / "audio.wav"))
    assert "private-key" not in str(error.value)
    assert "Gnani Prisma request failed" in str(error.value)


def test_invalid_credentials_have_explicit_disconnected_status(tmp_path, monkeypatch):
    from gnani.stt.exceptions import APIError
    def fail(*args, **kwargs):
        raise APIError(401, 'private-key-must-never-appear')
    monkeypatch.setattr(voice, '_client', lambda: SimpleNamespace(transcribe=fail))
    with pytest.raises(RuntimeError) as error:
        voice.transcribe_audio(write_wav(tmp_path / 'audio.wav'))
    assert 'GNANI NOT CONNECTED' in str(error.value)
    assert '(401)' in str(error.value)
    assert 'private-key' not in str(error.value)


def test_missing_key_prevents_microphone_capture(monkeypatch):
    monkeypatch.delenv("GNANI_API_KEY", raising=False)
    monkeypatch.setattr(voice, "capture_command_audio", lambda *_: pytest.fail("microphone must stay closed"))
    with pytest.raises(RuntimeError, match="GNANI_API_KEY"):
        voice.hear_command()


def test_rms_gate_preserves_internal_silence_and_rejects_silence():
    quiet = b"\0\0" * 16000
    tone = array("h", [500] * 8000).tobytes()
    command = tone + quiet + tone
    trimmed = voice.trim_voice_activity(quiet + command + quiet)
    assert command in trimmed
    assert len(trimmed) < len(quiet + command + quiet)
    with pytest.raises(RuntimeError, match="No microphone activity"):
        voice.trim_voice_activity(quiet)


def test_rest_clip_limit_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "_client", lambda: pytest.fail("request must not run"))
    with pytest.raises(ValueError, match="30 seconds"):
        voice.transcribe_audio(write_wav(tmp_path / "long.wav", seconds=30.1))


@pytest.mark.skipif(not ffmpeg_available(), reason="FFmpeg unavailable")
def test_real_audio_chunk_boundaries_and_temporary_cleanup(tmp_path, monkeypatch):
    # Actual FFmpeg extraction; only the network transcription is replaced.
    audio_source = write_wav(tmp_path / "source.wav", seconds=26.2)
    source = tmp_path / "source.mp4"
    subprocess.run([_binary("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(audio_source),
                    "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=26.2", "-shortest",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)],
                   check=True, capture_output=True)
    captured_paths = []

    def transcribe(audio, **kwargs):
        captured_paths.append(Path(audio))
        with wave.open(str(audio), "rb") as wav:
            assert wav.getframerate() == 16000 and wav.getnchannels() == 1
            assert wav.getnframes() / wav.getframerate() <= 25.0
        return {"text": "actual audio, unit-test transcript", "timing": "untimed"}

    monkeypatch.setattr(voice, "_client", lambda: object())
    monkeypatch.setattr(voice, "transcribe_audio", transcribe)
    segments = voice.transcribe_video(source)
    assert [(seg["start"], seg["end"]) for seg in segments] == [(0.0, 25.0), (25.0, 26.2)]
    assert all(seg["timing"] == "chunk_only" for seg in segments)
    assert source.exists() and all(not path.exists() for path in captured_paths)


def test_real_gnani_hinglish_integration():
    """Requires explicit opt-in audio AND key; no fake response or mic capture."""
    from dotenv import load_dotenv
    load_dotenv()
    supplied_audio = os.getenv("KAAT_TEST_AUDIO")
    if not os.getenv("GNANI_API_KEY") or not supplied_audio:
        pytest.skip("Set GNANI_API_KEY and KAAT_TEST_AUDIO to a real <=30s Hinglish WAV for live validation.")
    audio = Path(supplied_audio).expanduser().resolve(strict=True)
    with wave.open(str(audio), 'rb') as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
        assert voice._command_speech(wav.readframes(wav.getnframes())), 'Real human speech must survive the local VAD.'
    result = voice.transcribe_audio(audio)
    assert result["text"], "Use an actual speech recording for the live integration test."
    assert result["model"] == "prisma-v3.0"
