# Historical practical QA report

These checks were performed on **10 November 2026** before the user-reported microphone failure was investigated. The [current root-cause review](ROOT_CAUSE_REVIEW.md) supersedes any complete-product impression from this report. Historical results below are retained for traceability, not used to certify a working human microphone command.

## Coverage of the earlier run

The earlier automated run reported **160 passed in 23.20 seconds**, with zero skips/xfails. It included provider-contract unit doubles, generated-media regressions, actual public-audio provider requests and MCP subprocess checks. The separate **17 native UI cases** used actual Windows input and file dialogs, file-based Prisma transcription, caption export and preference restart. Speak was tested only with a deliberately missing key. Positive microphone capture was not exercised by those cases.

Those checks were real within that coverage, but the coverage was insufficient for the primary voice interaction. A later actual microphone attempt hung inside a native driver call under a specifically denied Store Python runtime. Additional editing failures were then reproduced. See the current review for the corrections and the latest quiet-input outcome.

## Actual recorded human speech

Two human-recorded Hindi/English technical-lecture clips came from [MUCS/OpenSLR SLR104](https://www.openslr.org/104/), through the [MUCS-Hinglish mirror](https://huggingface.co/datasets/dianavdavidson/MUCS-Hinglish). The original CC BY-SA 4.0 terms were retained even though the mirror labels CC BY 4.0. Audio is not bundled in the source release.

Three actual Prisma requests exercised verbatim, codemix and transliterate. Individual wall times were 3.875, 9.803 and 4.452 seconds. Strict reference errors were 6/19=31.58% and 6/27=22.22% on the individual samples; the combined MCP recording measured 10/46=21.74%. Unicode/case/punctuation normalization retained script differences, so Latin/Devanagari loanword differences count as errors. LibreOffice was genuinely misrecognized as Labour Office. No invented Roman reference or perfect-recognition claim is made.

The samples are lectures, not human assistant commands. An earlier generated-English instruction completed a real provider request and triggered pause detection, but it remains synthesized-speech evidence.

## Actual editing and native UI

A generated test-pattern video contained the two human clips and an inserted 3.2-second gap. It was not a filmed-person demo. Actual MCP/native workflows detected a suggested cut at 8.455–11.295 seconds and exported the 25.025-second source to a 22.21-second H.264/AAC copy; its mathematical plan was 22.185 seconds and the source hash remained unchanged.

The native cases included corrupt/cancelled selection, approval, typed Hinglish undo/negation, explicit preference saving, native JSON/MP4 Save dialogs, actual file transcription, clear/undo, collapse/expand and process-restart preference restore. Their source report is `test_output/native_human_verified/report.json`. They did not establish microphone success.

The old caption screenshot showed actual readable glyphs, but reused source-chunk text. Later testing proved that such text could retain words from removed speech. The new retained-audio caption path, described in the current review, fixes that demonstrated content error. Visible subtitles alone were not sufficient evidence of correct editing-aware captions.

## Browser and system checks

Actual Chromium playback reached the end of the original, native export and MCP captioned export with no media errors. Concurrent playback reported 625/554/554 decoded frames and 4/3/0 dropped frames. A separate native-captioned seek/play-to-end check reached 22.21 seconds with zero dropped frames. Those observations establish decoding/playback and visible captions, not physical audio capture or every transcript word.

Notepad launch produced new visible windows; Explorer launch succeeded with an already-visible Explorer window, so a newly created Explorer window was not claimed. Foreground-window inspection succeeded, and DirectShow listed four devices. Device enumeration did not establish capture permission. Camera recording returned an explicit unsupported error, not a successful capability.

## Evidence scope

Raw evidence is in ignored `test_output/practical_speech/`, `mcp_human/`, `native_human_verified/`, `browser_review/` and `system_practical/`. The key, audio, raw reports and SQLite stores are absent from the source archive. Initial native test-driver issues with process IDs/dialog paint timing were fixed as harness issues, not counted as application defects.

The current implementation and its remaining acceptance gaps are described in [VALIDATION.md](VALIDATION.md) and [ROOT_CAUSE_REVIEW.md](ROOT_CAUSE_REVIEW.md). Historical counts are not substituted for a captured human instruction, actual recognition, correct intent and durable action result.
