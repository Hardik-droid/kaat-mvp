"""Local, review-only filler proposals with real Whisper word-time estimates.

Gnani remains KAAT's primary command/transcription provider. This optional local
model supplies its own approximate word boundaries; these are never attributed
to Gnani or treated as proof that a suggested speech edit is safe.
"""
from __future__ import annotations

from array import array
from functools import lru_cache
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import wave

import engine


FILLERS = {'um', 'umm', 'ummm', 'uh', 'uhh', 'uhhh', 'erm', 'er', 'hmm', 'hmmm',
           'उम्', 'अम्', 'उह', 'अह', 'हम्म'}


@lru_cache(maxsize=2)
def _model(name):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError('Filler detection needs the optional local speech model. Run .venv\\Scripts\\python.exe -m pip install -r requirements-speech.txt.') from None
    if name not in {'tiny', 'base', 'small'}:
        raise ValueError('KAAT_SPEECH_MODEL must be tiny, base or small.')
    directory = Path(os.environ.get('KAAT_DATA_DIR', str(Path.home() / '.kaat'))) / 'models'
    directory.mkdir(parents=True, exist_ok=True)
    local = next((directory / (name + suffix) for suffix in ('-ranged', '-direct')
                  if all((directory / (name + suffix) / file).is_file()
                         for file in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'))), None)
    return WhisperModel(str(local) if local else name, device='cpu', compute_type='int8', cpu_threads=4,
                        download_root=str(directory))


def _filler_proposals(words, pcm, rate, total):
    """Conservative candidates only; meaningful discourse words are excluded."""
    cuts = []
    for index, word in enumerate(words):
        token = re.sub(r'[^\w\u0900-\u097f]', '', word['word'].casefold())
        if token not in FILLERS or word['probability'] < .65:
            continue
        # Keep a small margin inside the estimate and away from adjacent speech.
        start = max(0., word['start'] + .02, words[index-1]['end'] + .02 if index else 0.)
        end = min(total, word['end'] - .02, words[index+1]['start'] - .02 if index+1 < len(words) else total)
        if not .10 <= end-start <= 1.5:
            continue
        samples = pcm[round(start*rate):round(end*rate)]
        rms = math.sqrt(sum(value*value for value in samples)/len(samples)) if samples else 0.
        if rms < 30:
            continue  # A model token over decoded silence is not a speech cut.
        cuts.append({'start': round(start, 4), 'end': round(end, 4), 'reason': 'filler_word',
                     'detail': f"Possible filler {word['word'].strip()!r}; local Whisper word estimate, model probability {word['probability']:.2f}. Preview before approval.",
                     'status': 'suggested'})
    return cuts


def detect_speech_edits(video):
    """Decode real source audio and return approximate, unapproved filler cuts."""
    info = engine.inspect_video(video)
    if not info['has_audio']:
        raise ValueError('Filler detection requires an audio stream.')
    model_name = os.getenv('KAAT_SPEECH_MODEL', 'base').strip()
    model = _model(model_name)
    language = os.getenv('KAAT_SPEECH_LANGUAGE', '').strip() or None
    if language not in (None, 'hi', 'en'):
        raise ValueError('KAAT_SPEECH_LANGUAGE must be hi, en, or empty for detection.')
    with tempfile.TemporaryDirectory(prefix='kaat_speech_edits_') as temporary:
        audio = Path(temporary) / 'source.wav'
        conversion = subprocess.run([engine._binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-i', info['source'], '-map', '0:a:0', '-vn',
            '-af', f"aresample=async=1:first_pts=0,apad,atrim=end={info['duration_seconds']:.9f}",
            '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(audio)], capture_output=True, timeout=120)
        if conversion.returncode:
            raise RuntimeError('Could not decode source audio for filler detection.')
        with wave.open(str(audio), 'rb') as wav:
            pcm = array('h', wav.readframes(wav.getnframes()))
            rate = wav.getframerate()
        # FFmpeg already normalized PCM; pass it directly to avoid a second
        # decoder and PyAV-version-specific file-opening behavior.
        import numpy as np
        waveform = np.asarray(pcm, dtype=np.float32) / 32768.
        segments, detected = model.transcribe(waveform, language=language, task='transcribe',
            beam_size=5, temperature=0, word_timestamps=True, vad_filter=False,
            condition_on_previous_text=False)
        words = []
        transcript = []
        for segment in segments:
            transcript.append(segment.text)
            for word in segment.words or []:
                values = (float(word.start), float(word.end), float(word.probability))
                if not all(math.isfinite(value) for value in values):
                    continue
                start, end, probability = values
                if not 0 <= start < end <= info['duration_seconds'] + .02 or not 0 <= probability <= 1:
                    continue
                words.append({'word': word.word, 'start': start, 'end': min(end, info['duration_seconds']),
                              'probability': probability})
        cuts = _filler_proposals(words, pcm, rate, info['duration_seconds'])
    return {'cuts': cuts, 'words': words, 'text': ''.join(transcript).strip(),
            'provider': 'local-faster-whisper', 'model': model_name, 'language': detected.language,
            'timing': 'model_estimated_words', 'requires_review': True, 'analysis_completed': True,
            'message': f'{len(cuts)} possible filler word(s) suggested for review. '
                       'Local Whisper timings are approximate; inspect each cut before approval. '
                       'Zero suggestions does not prove the recording contains no fillers.'}
