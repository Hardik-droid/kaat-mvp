# Gnani Prisma integration

The installed official SDK is `gnani-vachana==0.9.0`, licensed MIT. The hosted model/service has separate account terms. [SDK source/license](https://github.com/Gnani-AI-Mintlify/gnani-vachana), [REST contract](https://docs.gnani.ai/api/STT/speech-to-text). Current microphone findings are in [ROOT_CAUSE_REVIEW.md](ROOT_CAUSE_REVIEW.md); earlier file-based API success does not certify microphone commands.

## Actual pipeline

`voice.hear_command()` begins only after the user activates Speak. The UI distinguishes Preparing, actual Listening with countdown/input level, Processing, Transcribing and the actual Heard/error outcome. On Windows, the known packaged-runtime microphone denial is checked before driver opening. Audio setup/capture runs in a spawned process with deadlines because a native driver call cannot be cancelled safely by timing out a Python thread. Windows WASAPI uses the input's native rate; local conversion produces mono 16 kHz PCM for recognition.

The conservative RMS gate trims outside an activated instruction while preserving internal pauses. It can admit background noise and does not classify language. A quiet capture fails before contacting Prisma. Temporary WAVs are removed; diagnostic buffers are not silently retained.

`voice.transcribe_audio()` calls the official `GnaniSTTClient` with `model="prisma-v3.0"`, `language_code="indic-auto"` and Hindi/Indian-English candidates. The private `GNANI_API_KEY` comes from the environment; the SDK supplies authentication. Commands request `format="transliterate"` to obtain Roman Hinglish for parsing; video content defaults to verbatim, with codemix/transliterate available. This is provider output selection, not locally fabricated transliteration.

Actual success/text/model/truncation are validated. Empty text remains a no-speech result. Errors are reported without copying raw response bodies or credentials. Full-video content is never fed into the command parser.

## File transcription and caption exports

Video audio is decoded once to normalized PCM, retaining source clock/silence, then sliced by actual samples into requests of at most 25 seconds, below the documented 30-second REST limit. This avoids input fast-seeking that previously lost speech from negative-start MKV files.

Prisma REST does not guarantee word/sentence timestamps. Returned text is labelled `timing="chunk_only"`. When an approved edit partially removes a nonempty caption cue, that cue's words cannot be partitioned safely from timestamps alone. Export extracts the retained audio and obtains a fresh actual Prisma transcript for captions on the edited timeline; this can add API requests. Whole-kept/whole-deleted cues can be remapped without new recognition. There is no invented word alignment.

The actual public-human regression retained only the second utterance and exported 13.55 seconds. Fresh captions contained that retained speech rather than words from the deleted first utterance, and the original file hash was unchanged. These captions are still coarse chunk captions.

## What has and has not been verified

Public human Hindi/English lecture samples from [MUCS/OpenSLR104](https://www.openslr.org/104/) reached the actual provider in multiple output styles and through MCP/native file transcription. Strict reference WER was 31.58% and 22.22% for the individual samples and 21.74% for an earlier combined recording. Script differences count in those values; LibreOffice also genuinely became Labour Office. This is imperfect speech recognition, not a benchmark or a perfect-recognition pass. [Historical evidence/licensing](QA_REPORT.md).

The original microphone failure involved Store Python's individual Windows denial. The environment now uses standalone Python 3.13.7. Later empty-recognition and polite-parser failures were also reproduced. The current native-channel/local-VAD capture and parser passed the user's live **“Please open the camera”** instruction through actual Gnani and a visible Camera window. Native recording controls also passed real state/save/decode checks. [Current evidence and remaining limits](DELIVERY_CHECK.md) supersedes earlier pending-speech notes.

The SDK supports WebSocket streaming, but KAAT implements bounded PTT followed by REST; continuous listening/streaming is unsupported. [Streaming documentation](https://docs.gnani.ai/api/STT/stt-websocket).

## Re-run a recorded-audio provider check

```powershell
$env:KAAT_TEST_AUDIO = "C:\path\explicit-short-human-hinglish.wav"
# Keep GNANI_API_KEY private in .env.
.\.venv\Scripts\python.exe -m pytest tests/test_voice.py -q -rs
```

The explicit audio path and key are both required; otherwise that integration test skips. It makes a real request. Unit provider doubles check boundary contracts separately and are not live evidence. Credentials, recordings and local reports are excluded from the source archive. For a denied runtime or quiet input, follow the README's microphone troubleshooting rather than interpreting a test total as successful capture.
