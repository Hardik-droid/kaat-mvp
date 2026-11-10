"""Gnani Prisma REST transcription and explicitly activated microphone capture.

Audio buffers and temporary WAV files are discarded after each request. This is
push-to-talk, not streaming; source-video transcripts carry real chunk bounds.
"""
from __future__ import annotations

from array import array
from collections import deque
import math
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except Exception:
    pass

MODEL = "prisma-v3.0"
SAMPLE_RATE = 16000
CHUNK_SECONDS = 25.0


class VoiceCancelled(RuntimeError):
    """The user cancelled an activated command; never dispatch its transcript."""


def _check_cancelled(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise VoiceCancelled('Voice command cancelled. No command executed.')


def recording_duration(seconds=None) -> float:
    """Read the local push-to-talk limit, including an explicit per-call override."""
    value = os.getenv('KAAT_CAPTURE_SECONDS', '6') if seconds is None else seconds
    try:
        duration = float(value)
    except (TypeError, ValueError):
        raise ValueError('KAAT_CAPTURE_SECONDS must be a number between 0.5 and 25 seconds.') from None
    if not math.isfinite(duration) or not .5 <= duration <= CHUNK_SECONDS:
        raise ValueError('Microphone capture must be between 0.5 and 25 seconds.')
    return duration


def microphone_permission_error():
    """Read local Windows consent before opening a driver; never change it."""
    if os.name != 'nt':
        return None
    from system_tools import device_permission
    if device_permission('microphone')['status'] == 'blocked':
        return ('Windows denies microphone access to this Python runtime. Enable access in Windows microphone privacy settings. '
                'For a denied Store Python app, allow that app or use standalone Python. No audio was captured.')


def _client():
    if not os.environ.get("GNANI_API_KEY", "").strip():
        raise RuntimeError("GNANI NOT CONNECTED — CHECK API KEY. Set GNANI_API_KEY in .env.")
    try:
        from gnani.stt import GnaniSTTClient
    except ImportError as exc:
        raise RuntimeError("Install the official SDK: pip install gnani-vachana==0.9.0") from exc
    return GnaniSTTClient(timeout=45)


def transcribe_audio(audio: str | Path, *, output_format: str = "verbatim") -> dict:
    """Transcribe one <=30-second audio clip through the official Gnani SDK.

    Only documented text and metadata are accepted. No speech/word timestamps
    are inferred from transcript text. Empty text is a valid no-speech response.
    """
    if output_format not in {"verbatim", "codemix", "transliterate"}:
        raise ValueError("Choose verbatim, codemix, or transliterate output.")
    audio = Path(audio).expanduser().resolve(strict=True)
    if not audio.is_file() or audio.stat().st_size == 0:
        raise ValueError("Choose a non-empty audio file.")
    if audio.suffix.lower() == ".wav":
        with wave.open(str(audio), "rb") as wav:
            if wav.getnframes() / wav.getframerate() > 30.0:
                raise ValueError("Prisma v3 REST accepts at most 30 seconds per request.")
    client = _client()
    try:
        result = client.transcribe(
            str(audio), language_code="indic-auto", model=MODEL,
            format=output_format, language_candidates=["hi-IN", "en-IN"],
        )
    except Exception as exc:
        # APIError may include a raw HTTP body; keep credentials and transcripts
        # out of logs/history while retaining the useful status and error class.
        status = getattr(exc, "status_code", None)
        guidance = {
            401: "Check GNANI_API_KEY.",
            402: "Check your Gnani account credit.",
            403: "Enable STT scope for your Gnani key.",
            429: "Wait and retry; your account is rate limited.",
            504: "The provider timed out; retry a shorter clip.",
        }.get(status, "Check network access and the Gnani service, then retry.")
        prefix = 'GNANI NOT CONNECTED — CHECK API KEY. ' if status in (401, 403) else ''
        raise RuntimeError(f"{prefix}Gnani Prisma request failed ({status or type(exc).__name__}). {guidance}") from None
    if not isinstance(result, dict) or result.get("success") is not True:
        raise RuntimeError("Gnani Prisma did not return a successful transcription response.")
    if not isinstance(result.get("transcript"), str):
        raise RuntimeError("Gnani Prisma returned an invalid transcript; expected text.")
    if result.get("model") not in (None, MODEL):
        raise RuntimeError("Gnani returned a different model than Prisma v3.0.")
    if result.get("truncated"):
        raise RuntimeError("Gnani truncated the transcript. Retry with a shorter audio clip.")
    return {
        "text": result["transcript"].strip(), "provider": "gnani-prisma-v3",
        "model": MODEL, "timing": "untimed", "format": output_format,
        "request_id": result.get("request_id"),
        "detected_language_code": result.get("detected_language_code"),
    }


def trim_voice_activity(pcm: bytes, *, threshold: float = 80.0) -> bytes:
    """Conservative RMS activity gate for mono 16-bit LE PCM at 16 kHz.

    This only trims outside an activated command; internal pauses stay intact.
    Amplitude gating cannot distinguish speech from background noise.
    """
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    frame = SAMPLE_RATE // 50  # 20 ms
    active = []
    for offset in range(0, len(samples), frame):
        window = samples[offset:offset + frame]
        if window and math.sqrt(sum(n * n for n in window) / len(window)) >= threshold:
            active.append(offset)
    if len(active) < 5:
        raise RuntimeError("No microphone activity detected. Check the input device and speak again.")
    start = max(0, active[0] - int(.24 * SAMPLE_RATE))
    end = min(len(samples), active[-1] + frame + int(.36 * SAMPLE_RATE))
    return pcm[start * 2:end * 2]


def _input_configuration(sd):
    """Prefer the Windows shared audio engine over legacy waveIn/MME."""
    device = None
    backend = 'default audio input'
    if os.name == 'nt':
        for host in sd.query_hostapis():
            if 'WASAPI' in host['name'] and host['default_input_device'] >= 0:
                device = host['default_input_device']
                backend = host['name']
                break
    requested = os.getenv('KAAT_MICROPHONE', '').strip()
    if requested:
        devices = sd.query_devices()
        host = sd.query_devices(device, kind='input')['hostapi'] if device is not None else None
        choices = [i for i, value in enumerate(devices) if value['max_input_channels'] > 0
                   and value['name'] == requested and (host is None or value['hostapi'] == host)]
        if not choices:
            raise RuntimeError('The selected microphone is unavailable. Choose another microphone in KAAT.')
        device = choices[0]
    info = sd.query_devices(device, kind='input')
    rate = round(info['default_samplerate'])
    channels = min(2, info['max_input_channels'])
    try:
        sd.check_input_settings(device=device, samplerate=rate, channels=channels, dtype='int16')
    except sd.PortAudioError:
        channels = 1
        sd.check_input_settings(device=device, samplerate=rate, channels=channels, dtype='int16')
    return device, rate, channels, f"{backend}: {info['name']}"


def list_microphones():
    import sounddevice as sd
    host = next((i for i, value in enumerate(sd.query_hostapis()) if 'WASAPI' in value['name']), None)
    return [value['name'] for value in sd.query_devices() if value['max_input_channels'] > 0
            and (host is None or value['hostapi'] == host)]


def _speech_frame(detector, data, rate, channels):
    """WebRTC consumes exact 20 ms mono PCM frames; keep capture format native."""
    if channels != 1:
        data = _microphone_mono(data, channels)
    size = rate//50*2
    return detector.is_speech(data.ljust(size, b'\0'), rate)


def _microphone_mono(pcm, channels):
    """Keep the stronger microphone channel; mixing can cancel opposite phases."""
    if channels == 1:
        return pcm
    samples = array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    mono = max((samples[index::channels] for index in range(channels)), key=lambda channel: sum(value*value for value in channel))
    if sys.byteorder != 'little':
        mono.byteswap()
    return mono.tobytes()


def _command_speech(pcm):
    """Reject non-speech locally and retain context around actual voice frames."""
    import webrtcvad
    detector = webrtcvad.Vad(2)
    frame = SAMPLE_RATE//50*2
    active = [offset for offset in range(0, len(pcm), frame)
              if _speech_frame(detector, pcm[offset:offset+frame], SAMPLE_RATE, 1)]
    if len(active) < 8 or not any(active[i+7]-active[i] < 20*frame for i in range(len(active)-7)):
        raise RuntimeError('No speech detected on the selected microphone. Try again or choose a microphone.')
    return pcm[max(0, active[0]-round(.3*SAMPLE_RATE)*2):min(len(pcm), active[-1]+frame+round(.4*SAMPLE_RATE)*2)]


def _normalize_command(pcm):
    """Bounded local gain for quiet microphone speech; never invent samples."""
    samples = array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    peak = max((abs(sample) for sample in samples), default=0)
    if not peak or peak >= 16384:
        return pcm
    gain = min(12., 16384/peak)
    adjusted = array('h', (round(sample*gain) for sample in samples))
    if sys.byteorder != 'little':
        adjusted.byteswap()
    return adjusted.tobytes()


def _capture_in_process(seconds: float = 6, *, on_phase=None) -> bytes:
    """Capture a bounded, user-activated command from the default microphone."""
    if not math.isfinite(seconds) or not .5 <= seconds <= CHUNK_SECONDS:
        raise ValueError("Microphone capture must be between 0.5 and 25 seconds.")
    denied = microphone_permission_error()
    if denied:
        raise RuntimeError(denied)
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("Install sounddevice to enable microphone input.") from exc
    chunks = []
    device, rate, channels, description = _input_configuration(sd)
    if on_phase:
        on_phase('preparing', 'Opening ' + description)
    remaining = round(seconds * rate)
    captured = 0
    import webrtcvad
    detector = webrtcvad.Vad(2) if rate in (8000, 16000, 32000, 48000) else None
    recent_voice = deque(maxlen=20)
    speech_started = False
    last_activity = None
    try:
        with sd.RawInputStream(device=device, samplerate=rate, channels=channels, dtype="int16") as stream:
            if on_phase:
                on_phase("listening", f"Speak now · {seconds:g} seconds")
            while remaining:
                count = min(rate//50, remaining)
                data, overflowed = stream.read(count)
                if overflowed:
                    raise RuntimeError("Microphone buffer overflow. Retry with other audio apps closed.")
                chunks.append(bytes(data))
                remaining -= count
                captured += count
                window = array('h')
                window.frombytes(bytes(data))
                if sys.byteorder != 'little':
                    window.byteswap()
                rms = math.sqrt(sum(sample*sample for sample in window)/len(window)) if window else 0
                voiced = _speech_frame(detector, bytes(data), rate, channels) if detector else False
                recent_voice.append(voiced)
                if sum(recent_voice) >= 8:
                    speech_started = True
                if voiced and speech_started:
                    last_activity = captured
                # Loudness is not speech. Require sustained VAD evidence before
                # starting the end timer, plus a minimum two-second user window.
                if speech_started and captured >= rate*2 and last_activity is not None and captured-last_activity >= rate:
                    break
                if on_phase and (captured % (rate // 4) < count or not remaining):
                    on_phase("listening", f"{remaining/rate:.1f}s left · input level {100*rms/32768:.1f}%")
    except sd.PortAudioError as exc:
        raise RuntimeError(f"Could not open {description}: {exc}. Check the Windows input device and whether another app has exclusive access.") from None
    if on_phase:
        on_phase('processing', 'Microphone is off. Preparing captured audio…')
    pcm = b''.join(chunks)
    diagnostic = os.getenv('KAAT_DIAGNOSTIC_AUDIO_DIR')
    if diagnostic:
        with wave.open(str(Path(diagnostic)/f'native_{os.getpid()}_{time.time_ns()}.wav'), 'wb') as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(pcm)
    pcm = _microphone_mono(pcm, channels)
    if rate != SAMPLE_RATE or channels != 1:
        from engine import _binary
        converted = subprocess.run([_binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-f', 's16le', '-ar', str(rate), '-ac', '1', '-i', 'pipe:0',
            '-ar', str(SAMPLE_RATE), '-ac', '1', '-f', 's16le', 'pipe:1'],
            input=pcm, capture_output=True, timeout=8)
        if converted.returncode:
            raise RuntimeError('Could not convert microphone audio to 16 kHz PCM')
        pcm = converted.stdout
    return _command_speech(_normalize_command(pcm))


def _microphone_worker(connection, seconds):
    try:
        pcm = _capture_in_process(seconds, on_phase=lambda phase, message: connection.send(('phase', phase, message)))
        connection.send(('audio', pcm))
    except Exception as exc:
        connection.send(('error', str(exc)))
    finally:
        connection.close()


def _bounded_capture(seconds, on_phase=None, *, cancel_event=None, worker=_microphone_worker, open_timeout=8):
    # A driver can hang inside Pa_OpenStream: a thread cannot cancel that native
    # call. A short-lived process lets us terminate it and release audio handles.
    _check_cancelled(cancel_event)
    context = multiprocessing.get_context('spawn')
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=worker, args=(send, seconds), daemon=True)
    process.start()
    send.close()
    started = time.monotonic()
    deadline = started + open_timeout
    listening = False
    try:
        while True:
            _check_cancelled(cancel_event)
            if receive.poll(.1):
                try:
                    event = receive.recv()
                except EOFError:
                    raise RuntimeError('The microphone worker exited before returning audio') from None
                if event[0] == 'audio':
                    _check_cancelled(cancel_event)
                    return event[1]
                if event[0] == 'error':
                    raise RuntimeError(event[1])
                if event[0] == 'phase':
                    _, phase, message = event
                    if phase == 'listening' and not listening:
                        listening = True
                        deadline = time.monotonic()+seconds+3
                    elif phase == 'processing':
                        deadline = time.monotonic()+10
                    if on_phase:
                        on_phase(phase, message)
            if time.monotonic() > min(deadline, started+open_timeout+seconds+13):
                stage = 'capture' if listening else 'opening'
                raise RuntimeError(f'Microphone {stage} timed out. The blocked audio worker was stopped; check the selected Windows input device and try again.')
            if not process.is_alive() and not receive.poll():
                raise RuntimeError('The microphone worker exited without audio')
    finally:
        receive.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=3)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)


def capture_command_audio(seconds: float | None = None, *, on_phase=None, cancel_event=None) -> bytes:
    """User-activated capture with bounded driver initialization and cleanup."""
    return _bounded_capture(recording_duration(seconds), on_phase, cancel_event=cancel_event)


def hear_command(seconds: float | None = None, *, on_phase=None, cancel_event=None) -> str:
    """Listen only after a push-to-talk action, then make one real REST call."""
    seconds = recording_duration(seconds)
    _check_cancelled(cancel_event)
    if on_phase:
        on_phase("preparing", "Preparing microphone; wait for Listening before speaking.")
    _client()  # Fail before opening the microphone if configuration is missing.
    capture_options = {}
    if on_phase is not None:
        capture_options['on_phase'] = on_phase
    if cancel_event is not None:
        capture_options['cancel_event'] = cancel_event
    pcm = capture_command_audio(seconds, **capture_options)
    _check_cancelled(cancel_event)
    if on_phase:
        on_phase("transcribing", "Microphone is off. Sending the captured command to Gnani Prisma…")
    with tempfile.TemporaryDirectory(prefix="kaat_voice_") as temp:
        audio = Path(temp) / "command.wav"
        with wave.open(str(audio), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(pcm)
        diagnostic = os.getenv('KAAT_DIAGNOSTIC_AUDIO_DIR')
        if diagnostic:
            import shutil
            shutil.copyfile(audio, Path(diagnostic)/f'sent_{os.getpid()}_{time.time_ns()}.wav')
        # Real Hinglish REST checks show verbatim can spell English commands in
        # Devanagari. Request Roman script for the deterministic command parser;
        # video-content transcription keeps its caller-selected output style.
        text = transcribe_audio(audio, output_format="transliterate")["text"]
    _check_cancelled(cancel_event)
    if not text:
        raise RuntimeError("No words were recognized from the captured speech. Try again or choose a microphone.")
    if on_phase:
        on_phase("recognized", text)
    return text


def transcribe_video(video: str | Path, *, output_format: str = "verbatim") -> list[dict]:
    """Extract real 25-second audio chunks; label their timing honestly.

    Chunk boundaries identify the audio sent to Prisma, not spoken sentence or
    word alignment. This method never writes a transcript beside the source.
    """
    from engine import _binary, duration

    _client()
    video = Path(video).expanduser().resolve(strict=True)
    total = duration(video)
    with tempfile.TemporaryDirectory(prefix="kaat_stt_") as temp:
        normalized = Path(temp) / "normalized.wav"
        # Decode once: input -ss can jump to a video keyframe and erase audio in
        # negative-start MKV files. Slice the actual normalized PCM samples instead.
        result = subprocess.run(
            [_binary("ffmpeg"), "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(video), "-t", str(total), "-vn", "-af", "aresample=async=1:first_pts=0,apad",
             "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(normalized)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode:
            raise RuntimeError("Audio extraction failed. Confirm the video has a decodable audio track. " + result.stderr[-500:])
        segments = transcribe_pcm_wav(normalized, output_format=output_format)
        for segment in segments:
            segment['end'] = min(total, segment['end'])
        return segments


def transcribe_pcm_wav(audio: str | Path, *, output_format: str = 'verbatim') -> list[dict]:
    """Transcribe actual mono16kPCM samples, including a rendered edit's audio.

    Timestamps describe chunks of THIS WAV. An edited WAV therefore produces
    captions for retained speech, without reusing words removed from the source.
    """
    audio = Path(audio).expanduser().resolve(strict=True)
    segments = []
    frames_per_chunk = round(CHUNK_SECONDS*SAMPLE_RATE)
    with wave.open(str(audio), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, SAMPLE_RATE):
            raise ValueError('Caption audio must be mono 16 kHz 16-bit PCM WAV')
        if not wav.getnframes():
            raise ValueError('Caption audio is empty')
        with tempfile.TemporaryDirectory(prefix='kaat_pcm_chunks_') as temp:
            for index in range(math.ceil(wav.getnframes()/frames_per_chunk)):
                start = wav.tell()/SAMPLE_RATE
                pcm = wav.readframes(frames_per_chunk)
                audio_duration = len(pcm)/(2*SAMPLE_RATE)
                if not pcm:
                    break
                chunk_path = Path(temp)/f'chunk_{index:04d}.wav'
                with wave.open(str(chunk_path), 'wb') as chunk:
                    chunk.setnchannels(1)
                    chunk.setsampwidth(2)
                    chunk.setframerate(SAMPLE_RATE)
                    chunk.writeframes(pcm)
                transcript = transcribe_audio(chunk_path, output_format=output_format)
                segments.append({**transcript, 'start':start, 'end':start+audio_duration, 'timing':'chunk_only'})
    return segments
