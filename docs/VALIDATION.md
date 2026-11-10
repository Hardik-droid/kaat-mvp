# Current validation status

Latest follow-up: **238 tests passed in 41.68 seconds** with the real public-human-audio Gnani integration enabled. The user's actual microphone camera command and native video recording also passed separate practical checks. See [DELIVERY_CHECK.md](DELIVERY_CHECK.md); older pending/unsupported statements below describe earlier runs.

Updated **10 November 2026**. The user-reported microphone failure was reproduced after earlier automated/native checks. [ROOT_CAUSE_REVIEW.md](ROOT_CAUSE_REVIEW.md) records the blocked driver stack, denied runtime, environment correction, actual quiet-input result and editing regressions.

## Acceptance still missing

A human-spoken microphone command has **not** been successfully traced through capture → actual Prisma transcript → parsed intent → executed tool → durable result. The latest live attempt opened/completed under standalone Python but remained at 0.1% input; it returned **No microphone activity detected**, made no provider call and created no cuts. The user confirmed they were not speaking and would click Speak when ready. The next user-activated speaking check is pending, without an automatic retry. The quiet check is not a voice-success pass.

## Current evidence

| Workflow | What was actually established |
|---|---|
| Windows microphone runtime | Store Python was specifically denied while global/non-packaged access was allowed. MME hung in native opening; WASAPI failed. Standalone Python opened WASAPI and completed capture. No OS privacy setting was changed. |
| Quiet microphone input | A real six-second UI attempt completed with a low signal and an explicit no-activity error. No transcript/tool success is claimed. |
| Recorded human Hinglish | Actual public lecture clips reached Prisma, with disclosed recognition errors. This is file-based recognition, not a captured assistant command. |
| Existing-video edits/MCP | Actual selection, suggestions, approval/undo/restore and exports have evidence. Independently decoded media also reproduced/fixed accumulated cut-duration drift. |
| Captions after deletion | Actual retained-audio recognition produced a 13.55-second captioned export containing only the retained second utterance, with the source hash unchanged. Captions remain chunk-based. |
| UI/persistence | The earlier 17 cases used real input/dialogs, file transcription and process-restart checks. Speak was tested only with a missing key. |
| Browser playback | Actual files played to the end with visible captions and no media errors. This does not prove every caption word or microphone behavior. |
| Recording/streaming/arbitrary apps | Unsupported. Expected unsupported errors are guards, not successful capabilities. |
| Human retakes/word timing | Controlled matching tests exist; positive real-human retake deletion remains unverified and precise word alignment is unsupported. |

## Test coverage and the next run

The earlier 160-pass run included unit doubles, generated signals, recorded-human API calls and actual MCP tools. The 17-case native run did not exercise positive capture. Those historical numbers were real for their limited coverage; presenting them as complete voice acceptance was insufficient. [QA_REPORT.md](QA_REPORT.md) is now explicitly historical.

The revised standalone runtime/code completed **199 tests in 36.91 seconds, zero skipped**, with the actual public-WAV integration enabled. Raw output is `test_output/current_audit/final_standalone_tests.txt`. This confirms that configured regression suite, including contract unit checks; it does not complete the pending human microphone-command acceptance. Provider-boundary doubles never stand in for live capture or account responses.

## Remaining limits

Silence detection is amplitude-based and requires review. Prisma text does not provide guaranteed word timestamps. Partially removed caption cues cannot safely be split by reusing their whole text; the export recognizes retained audio instead. That requires actual provider access and may add requests at export. Fully retained/deleted source cues can be remapped without inventing words. Caller-supplied timing is not independently verified alignment.

PTT is bounded capture followed by REST, with actual phase feedback and native-driver process deadlines. It is not continuous streaming. API/network latency is additional. Long videos use temporary normalized audio. Safe publication requires local hard-link support. Exports select/re-encode supported A/V streams rather than preserving every track/metadata field. Approved preferences survive restart; selected-video state is local to each process.
