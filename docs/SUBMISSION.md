# Gnani.ai internship project: KAAT

**KAAT — Speak naturally. Get things done.**

KAAT is a Hinglish-first, voice-controlled Windows desktop companion. It sits above existing applications as a compact floating widget and converts explicitly activated speech into supported Windows actions and reversible video edits. Application launching, approved websites, local folders and video cleanup share one controller with the optional local MCP server.

## Problem and resulting workflow

Creators often leave long pauses and repeated attempts in a recording. KAAT lets a creator select that recording, say “Kaat, is video ke pauses hata de,” review suggested intervals, approve decisions and export an edited copy while preserving the original. The interface shows recognized instructions, tool results, reversible decisions and original/planned edited duration. Explicitly approved pause preferences survive restart.

## Gnani Prisma's role

Gnani is the primary speech-recognition engine. The official `gnani-vachana` client requests Prisma v3.0, `indic-auto`, and Hindi/Indian-English candidates. Bounded push-to-talk defaults to six seconds, is configurable up to 25 seconds, and requests Roman transliteration for deterministic command parsing; full-video transcription defaults to verbatim text in actual audio chunks of at most 25 seconds. Supported instructions reach the same controller used by the official Python MCP server. No training, fine-tuning or mandatory LLM is needed.

The application validates actual provider responses and reports authentication, network and service failures visibly. REST recognition runs after bounded capture; it is not presented as streaming. Transcript boundaries identify actual audio chunks because the API does not guarantee word timestamps. See [technical integration details](GNANI.md).

## Implemented engineering

- Extended the existing Python overlay and FFmpeg engine rather than replacing the desktop architecture.
- Added a shared Windows launcher using installed executable paths and registered application IDs, with observed window, browser-address and Explorer-path verification. Inconclusive launches remain unverified.
- Added common English/Hinglish desktop intents, application aliases and explicit target/result feedback while preserving supported editing commands.
- Added explicit suggested/approved/restored decisions, stable IDs, undo and overlapping-interval union.
- Used one FFmpeg trim/concat graph for actual A/V exports, with source-hash preservation and no-overwrite publication.
- Added transcript-similarity retake suggestions and optional SRT generation/burning using supplied timing.
- Added optional local filler-word proposals through `faster-whisper`, installed separately with `pip install -r requirements-speech.txt`. Gnani remains primary; Whisper's per-word times are approximate secondary-model estimates, not Gnani alignment. Candidates remain unapproved until reviewed.
- Added SQLite preference/session/task memory with explicit preference approval and bounded history.
- Exposed actual editing/memory/allowlisted Windows tools through the official local MCP SDK.
- Kept video/network work off the UI thread and provided runnable tests, a synthetic demo and Windows setup/source-release scripts.
- Added `doctor.py` and `run_kaat.bat`; device discovery, network reachability, authenticated transcription and live capture are reported as separate checks.
- Added an optional compatible reasoning endpoint for validated proposals only. It never executes tools, requires manual review and has no date-based recording search. Deterministic actions remain usable without a reasoning account.

## Evidence and candid scope

The optional `base` speech model produced 11 experimental filler proposals on a separate real interview-filler fixture. This is positive candidate-generation evidence, not independently validated word boundaries or removal accuracy. The primary public Hinglish sample still produced zero proposals. Fixture attribution and the distinction are recorded in [delivery verification](../delivery/VERIFICATION.md).

The [emergency repair report](EMERGENCY_REPAIR.md) is the current acceptance record and supersedes historical test totals below. It distinguishes actually observed Windows launches, real provider requests, native UI checks, isolated unit tests and remaining manual acceptance. `doctor.py --audio` made an actual Prisma v3.0 request using a public human speech clip during this repair; its nonempty response proves authenticated transcription, not a new live-microphone command or perfect recognition.

The [earlier camera delivery check](DELIVERY_CHECK.md) superseded the incomplete camera acceptance results at that stage. Windows runtime denial, empty recognition, native audio handling and strict polite-command parsing were investigated separately. The user's actual **“Please open the camera”** instruction passed through physical microphone capture, Gnani, the parser and a visible Windows Camera window. Local start/pause/resume/stop also produced a decoded MP4 with video and audio, with original files preserved. The new application-launch voice demonstration must be assessed from the latest report separately.

Existing-video capability has actual recorded-human API, MCP, native UI and browser evidence. Historical runs of 160 automated checks and 17 native cases covered recorded content, typed commands, file dialogs and preference restart rather than positive microphone capture. A subsequent standalone-runtime run passed 199 regression tests with actual public-WAV provider integration; live speech acceptance was still pending at that point. Those historical counts are not the current suite result. Later testing also reproduced and fixed accumulated multi-cut timing drift and captions retaining deleted source-chunk words. An actual retained-audio caption export contained only the kept second utterance and preserved the original hash.

Public Hinglish recognition is imperfect: strict sample-reference WERs were 31.58% and 22.22%, including script differences, and LibreOffice was misrecognized as Labour Office. Recording uses the tested English Windows Camera UI; streaming, precise word alignment and universal third-party application control remain unsupported. Positive natural-human retake deletion remains unverified. The optional filler detector completed a real public human Hinglish run with zero suggestions; that is not evidence of successful filler removal. A user recording and human-reviewed filler edit remain pending. The optional reasoning integration has boundary tests but no real reasoning-provider run yet; its proposals always remain unexecuted and unverified. KAAT combines established speech, media and tool patterns into a focused workflow; it does not claim these individual capabilities are novel.


A separate real filler-fixture controller check produced 11 proposals and exported a 12.00-second source to 5.42 seconds with full audio/video decode and the source hash unchanged. Approval was issued by test automation, not human review. This verifies the proposal-to-export path, not independent word-boundary accuracy or editorial safety. Evidence: `test_output/filler_real/actual_controller_export.json`. The primary Hinglish demo still returned zero filler proposals.
