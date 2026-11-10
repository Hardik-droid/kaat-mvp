# Current root-cause review

Investigated on **10 November 2026** after the user reported that the microphone or commands did nothing. This review supersedes the earlier implication that passing test totals established the entire voice workflow.

## What actually failed

| Failure | Evidence and correction |
|---|---|
| Speak could wait indefinitely before recording | The live process was blocked in `Pa_OpenStream → waveInOpen → wdmaud.drv → WaitForSingleObject`. Device enumeration and format checks had succeeded; neither tests permission or proves capture. |
| Global microphone access looked allowed, but the running Python identity was denied | The Store Python 3.13 package's own microphone consent was **Deny**, while global and non-packaged access were Allow. WASAPI variants under that runtime returned `-9996 Invalid device`; DirectSound also failed. Independent non-packaged FFmpeg DirectShow capture returned real PCM frames. |
| The wrong local runtime remained in `.venv` | The environment was upgraded to installed standalone Python 3.13.7, preserving dependencies. No Windows privacy setting was changed. WASAPI subsequently opened in about 0.94 seconds in a bounded local probe. |
| The widget labelled capture before the driver opened, and did not distinguish waiting for the provider | Preparing, actual Listening with countdown/input level, Processing, Transcribing and actual Heard/error feedback are now separate. Known packaged-runtime denial is reported before driver entry. Capture runs in a spawned process with deadlines and cleanup. |
| Natural instructions could be rejected or misinterpreted | Direct literal inputs such as `Kaat, pauses hatao`, `video export kar do`, and `add subtitles` were rejected by rigid prefix/verb matching. The parser now handles the investigated imperative variants, modifiers and preference targets while retaining negation/ambiguity checks. Literal parser tests are not presented as recorded human-command evidence. |
| Repeated fractional cuts accumulated extra time | A 20-cut case planned 7.2 seconds but exported 7.61 seconds. Per-segment video rounding padded concatenated audio. Video now selects/remaps the original timeline while audio is trimmed independently; the reproduced export is 7.2 seconds. This was a real media bug, not a harmless single final-frame rounding difference. |
| Source-chunk captions could retain words from deleted speech | A real edit retained only the second public human utterance, yet reusing a whole source chunk could copy deleted first-utterance words into the SRT. If an approved edit partially removes any nonempty caption cue, export now recognizes the retained audio rather than splitting the cue's whole text. The actual provider-backed 13.55-second export contains only the retained utterance's caption and fully decodes, with the source hash unchanged. |

## Latest live microphone outcome

Under standalone Python, the actual six-second capture reached Listening, reported its input level, completed and returned:

> No microphone activity detected. Check the input device and speak again.

The highest displayed input level was **0.1%**. No recognized transcript, provider call or cut decision was recorded in that attempt. The source remained unchanged. The user subsequently confirmed they were not speaking during that check and would click Speak when ready. The observed no-activity result is therefore consistent with that input. It verifies that capture can now open and terminate; it does **not** establish a successful human microphone command. That user-activated speaking check remains pending, and is not automatically repeated.

The earlier 0.5-second non-packaged FFmpeg probe returned 7,984 mono 16 kHz PCM frames. That is local capture evidence, not speech recognition. All diagnostic audio was discarded rather than uploaded or bundled.

## What the old results did and did not prove

The historical **160 tests / 17 native scenarios** were real checks of the paths they exercised. They included provider-contract unit doubles, generated media, actual recorded-human API requests, typed commands, file dialogs and exports. The native Speak check intentionally used a missing key; it did not test positive microphone capture. Public human lecture transcription did not test a human assistant command. The totals were therefore insufficient as complete product acceptance evidence.

Actual public speech recognition and recorded-video editing still have supporting reports, including disclosed recognition errors. Camera recording, continuous streaming and precise word alignment remain unsupported. Positive natural human-retake removal remains unverified. A new complete voice acceptance result requires a real captured human instruction, the actual Prisma transcript, the parsed intent, the executed tool and durable read-back of its result.

## Local evidence

The following paths are ignored local evidence, not bundled recordings or credentials:

- `test_output/current_audit/blocked_mme_stack.txt`: blocked native driver stack.
- `test_output/current_audit/backend_probes.json` and `directshow_capture.json`: actual backend errors and independent PCM capture. An initial FFmpeg command-line typo is preserved as a harness error, not a product fault.
- `test_output/current_audit/standalone_audio_device.json`: standalone WASAPI open/capture followed by quiet-input rejection.
- `test_output/live_microphone_standalone/report.json`: actual six-second UI attempt, phase observations, quiet-input error and unchanged source hash.
- `test_output/current_audit/media/multicut_drift_before.json` and `multicut_drift_after.json`: independently measured accumulated-duration reproduction.
- `test_output/current_audit/edited_human_caption/report.json`: actual retained-audio transcription and captioned export.

The revised standalone runtime/code completed **199 tests in 36.91 seconds**, with zero skips. The existing integration test used an explicit public human WAV and the actual provider; its skip condition was not removed. Raw output is `test_output/current_audit/final_standalone_tests.txt`. That total includes contract unit checks as well as integration checks. It is regression evidence, not the still-pending user microphone-command acceptance. No quiet-input or pending speaking attempt is counted as successful recognition.
