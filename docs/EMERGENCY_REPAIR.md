# KAAT emergency repair — 10 November 2026

This report distinguishes executed checks from remaining acceptance work. The floating Windows app, direct controller calls, and actual local MCP protocol were tested separately. Production tools contain no fabricated execution results or transcripts. Mocked failure/edge cases remain explicitly labelled unit tests.

## Root causes and repairs

1. **Desktop launch commands had no route.** The original parser and controller concentrated on media and camera. `intent_parser.py` now handles the requested English/Hinglish application, URL, folder, help, recording and memory phrases. `tools/windows_apps.py` resolves trusted Windows executables/registered applications and known folders; `controller.py` routes every frontend to those same functions.
2. **A launch request was not evidence of completion.** App launches now inspect actual visible window process identity/AUMID, folders inspect Explorer's location, and websites inspect exposed browser addresses. Browser address comparison handles Chrome hiding `www.` while checking meaningful path/query components. Unobservable results are `unverified`, not successes. Unknown apps return an actual failure. Already-running apps are handled.
3. **Natural wording missed strict patterns.** Polite prefixes and Hinglish suffixes are normalized before common intent parsing. The screenshot's sentence “Hey, can you just start recording few seconds of reel? Main Hindi mein bolunga.” now resolves to recording. Negation, ordinary conversation and unsupported compound mutations do not execute tools.
4. **Windows Camera exposes stale/duplicate controls during mode changes.** The recording adapter now ignores disabled/offscreen controls, distinguishes the actual capture button by its current name, restores the app, and waits for a stable enabled video capture control before a single invocation. It verifies start/pause/resume/stop UI states and inspects the newly saved MP4. It does not infer recording from opening Camera.
5. **Voice capture could not be cancelled or configured from the widget.** The bounded native capture worker now accepts cancellation, cleans up its process/audio, and takes a validated 0.5–25 second maximum. The widget saves that limit locally and supports cancellation with its microphone button or Escape. Returned speech is checked for cancellation before tool dispatch. An already-sent REST request must finish within its timeout, but its cancelled result cannot execute a command.
6. **Feedback obscured which stage failed.** The widget shows actual listening/transcription/execution phases and HEARD, INTERPRETED, TARGET and RESULT. SQLite history records the observed outcome. Permission is a local Allow / Not now popup, with Allow remembered on this computer. Dragging the widget preserves a pending consent action.
7. **New controls crowded the existing drawer.** A real screenshot revealed a one-pixel export control despite the automation reaching it. The footer now reserves its space; the expanded drawer has enough room for feedback and tabs. The native harness rejects controls smaller than a usable click target, so a precisely automated one-pixel click cannot count as layout acceptance.
8. **The user's live request asked for cleanup, which had no implemented route.** The recorded transcript “Close all those stuff which you have opened recently.” exposed that gap after the initial repair checks. The new `close_recent` intent routes through the shared `system.close_recent` tool. A persistent SQLite journal records only newly created windows tagged by this version with a unique ownership marker; marker and process identity are rechecked before closing. Pre-existing/reused windows, untracked tabs and windows opened before this update remain untouched. Supported default browsers now open website requests in a dedicated new window so that window can be tracked individually.

## Implemented scope

- Chrome, Notepad, Calculator, File Explorer and installed Windows Camera launching; exact registered app names where resolvable.
- Google Photos/YouTube and validated HTTP(S) URLs in the default browser; actual local folders including Windows' Downloads known folder.
- Actual installed-app inventory and foreground-window query.
- Explicit cleanup of tracked KAAT-created windows through typed/voice commands and `system.close_recent(approved=true)`. Normal close requests preserve application confirmation prompts; pending windows remain unverified, active/paused Camera recording is protected, and ambiguous `close all` requests clarification locally.
- Shared typed/voice/MCP execution, with explicit status and verification fields. Legacy media intent names remain compatible; `interpreted` supplies the normalized display name.
- Official Gnani SDK 0.9.0, Prisma `prisma-v3.0`, actual PCM capture, local microphone selection/input levels and honest provider errors.
- Existing FFmpeg pause suggestions, approval, restore, undo, separate MP4/EDL export, retained audio and source protection.
- SQLite preference save/read/update/delete and task history. Local device permission is separate from the database and survives restart.
- An optional configurable reasoning endpoint returns validated **proposals only**. No automatic multi-step executor, file-date guessing, arbitrary shell or fabricated planner success was added.
- Environment diagnostics and `run_kaat.bat`, plus a source-only release packager.

## Cleanup repair verification

The screenshot's exact request now maps to `close_recent`. Verification for this addition:

- **359 tests passed in 36.31 seconds**, no skips, with actual public-speech provider integration enabled. `test_output/close_suite_final.txt`.
- **Real native UI:** typed Open Google Photos and an existing disposable folder; restarted the actual KAAT process; typed “Close all those stuff which you have opened recently.” The two tracked windows closed, the persisted tracking rows cleared, and both pre-existing browser windows remained open. `test_output/native_close_run1/report.json` and `native_close_result.png`.
- **Actual MCP:** a real new folder window remained open after an unapproved close request was rejected, then closed after `system.close_recent(approved=true)`. Same report, actual stdio protocol.
- **Native backend:** new Notepad, Explorer and dedicated default-browser windows closed from a separate process using persisted ownership records. All 25 pre-existing target windows remained open. Repeated closure classified the three records as already closed. `test_output/owned_windows_run1/report.json`.
- **Camera checks:** the real PowerShell selector test covers 13 conditions, including enabled photo preview being idle, hidden/stale photo controls being unsafe, and active recording remaining protected. No new camera capture was claimed by that selector test.

The cleanup's native test used typed input, not another live utterance. The original microphone transcript was real, but its failed result predates this fix. The updated user widget was restarted after verification. Windows opened before ownership tracking existed cannot safely be inferred from app names or titles and are not retroactively adopted.

## Executed evidence

The launch, media, regression and live-transcription results below were captured before the close-recent update. They remain historical evidence for those paths; they do not establish that the new cleanup path passed. Fresh cleanup results must be recorded separately.

| Check | Result and evidence |
|---|---|
| Direct Windows tools | 10/10 checks passed: apps, Photos/YouTube browser address, actual Downloads, already-running app and real missing-app failure. `test_output/emergency_apps/tools_report.json` |
| Shared command controller | 10/10 actual Windows checks passed. `test_output/emergency_apps/controller_report.json` |
| Native widget input | 17/17: all 16 requested English/Hinglish commands and missing-app failure. Real Windows mouse/SendInput keyboard; no callback shortcuts. `test_output/emergency_native_apps_run1/report.json` |
| Official MCP stdio desktop tools | 10/10 actual calls passed, including real launches and unsafe target failures. `test_output/emergency_mcp_apps_run1/report.json` |
| Actual provider | Doctor sent the explicitly selected public human Hindi-English WAV to Prisma. Actual request `req_190de0df40dd` returned 123 text characters. This proves authenticated file transcription, not a new live spoken Chrome command. `test_output/emergency_doctor/full.json` |
| Startup launcher | `run_kaat.bat --check` exited 0; invalid output-directory diagnostic correctly exited 1. `test_output/emergency_doctor/` |
| Windows Camera mode transition | Photo mode and minimized Camera -> recording -> pause -> resume -> stop produced a 6.085833-second real MP4 with decoded audio/video. `test_output/camera_mode_fix/photo_minimized_after2/report.json` |
| Native media workflow | First run passed 17 functional scenarios and exported a decoded 22.185-second captioned MP4 from public human speech, source hash unchanged, preferences restored after real app relaunch. Layout defect found separately and fixed; subsequent verification is recorded below. `test_output/emergency_native_media_run1/report.json` |
| Repaired native media/layout | Tightened rerun passed 17/17 functional scenarios, verified consent and preferences after an actual restart, and decoded the 22.185-second exported MP4. Separate Apps/Preferences inspection confirmed usable controls; Export edit list is 122 × 43 pixels. `test_output/emergency_native_media_run2/report.json`, `test_output/emergency_native_layout_run1/report.json` |
| Regression suite | **318 passed, no skips:** 310 non-overlay tests in 37.55 seconds, plus all 8 overlay tests in 1.02 seconds. GUI tests were separated to avoid opening another widget during the user's live check. Actual public-speech API integration was enabled through `KAAT_TEST_AUDIO`; unit mocks are not counted as native launch evidence. `test_output/emergency_suite_final.txt` |
| New live microphone capture, before cleanup implementation | Actual laptop capture -> Prisma completed (`req_563f60a03545`), peak observed input level 2.0%. Heard: “Close all those stuff which you have opened recently.” At that time KAAT returned unsupported/failed and executed no closing action. This was not the requested Chrome utterance and is **not** a spoken-launch or cleanup pass. Raw microphone audio was not retained. `test_output/emergency_live_chrome/report.json` |

Public fixture provenance: OpenSLR 104 human Hindi-English lecture speech (CC BY-SA 4.0), with a controlled silence gap and generated video test pattern. The speech is human; this is not a live microphone command. Reports and generated media remain local under `test_output/` and are excluded from the source ZIP.

## Remaining limits

- Newly added **human microphone -> Prisma -> Chrome** acceptance must be recorded separately. The first live request asked to close windows before that action was implemented. Typed launches, that real transcription, and public-file transcription do not prove a combined spoken Chrome launch.
- Cleanup covers only windows tagged and journaled by this update. It cannot safely reconstruct ownership of earlier windows or reused tabs. No tracked windows means nothing eligible to close, not proof that the desktop is clear. It uses normal [Windows WM_CLOSE](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-close), which allows an application to ask for confirmation; KAAT never force-kills it or answers save/discard prompts. Remaining windows or protected Camera recording prevent a verified all-closed claim.
- No continuous listening or streaming claim. This is bounded, explicitly activated push-to-talk REST recognition.
- Browser verification proves the observed address, not successful sign-in or page content. Browsers/locales that do not expose a supported address field can yield `unverified`.
- Recording control targets the tested English Windows Camera UI. Other camera applications and changed/localized control labels are not universal adapters.
- Captions use actual extraction-chunk timing, not invented word timing. Retakes are conservative suggestions requiring review. Recognition accuracy is not guaranteed.
- Optional reasoning-provider network integration is NOT TESTED. Date-relative media search and automatic compound editing/export are not implemented; the planner does not pretend they ran.
- Windows retains control of hardware privacy. KAAT remembers its own consent locally; it cannot bypass a Windows denial.
- Cancellation stops capture and prevents pending voice dispatch. It does not undo an already started application action/export.

## Changed files

Core: `app.py`, `commands.py`, `intent_parser.py`, `controller.py`, `tools/__init__.py`, `tools/windows_apps.py`, `system_tools.py`, `voice.py`, `memory.py`, `mcp_server.py`, `optional_planner.py`.

Windows adapters/checks: `scripts/windows_probe.ps1`, `scripts/camera_control.ps1`, `scripts/check_windows_apps.py`, `scripts/check_native_apps.py`, `scripts/check_native_workflow.py`, `scripts/check_spoken_camera.py`, `scripts/check_camera_recording.py`.

Delivery: `doctor.py`, `run_kaat.bat`, `.env.example`, `scripts/package_release.py`, `README.md`, `docs/DEMO.md`, `docs/SUBMISSION.md`, this report. Focused parser/Windows/voice/UI/planner/diagnostic tests were added or updated. No additional runtime dependency was needed for these repairs.

## Run and demonstrate

```powershell
cd C:\Users\Asus\Desktop\kaat-mvp\kaat-mvp
.\run_kaat.bat
# Diagnostics, without starting hardware capture:
.\.venv\Scripts\python.exe doctor.py
# Real operating-system launch checks:
.\.venv\Scripts\python.exe scripts\check_windows_apps.py --controller
```

1. Expand the widget, type **Open Calculator**, then **Chrome khol de**. Show actual windows and the verified result. Type a nonexistent app and show its failure.
2. Click the microphone, wait for green Listening, say **Kaat, Chrome khol de**. Show the actual transcript, target and result; record this as passed only when the real path succeeds.
3. Open a video, request **is video ke pauses hata de**, review/approve a cut, undo and approve again. Export a fresh MP4. Show playable audio/video, EDL, shorter duration and unchanged original hash.
4. Request **remember my pause threshold is two seconds**, quit/relaunch, then **show my preferences**. Show the persisted value.
5. Open a fresh website window through this updated KAAT, then request **Close all those stuff which you have opened recently.** Show which tracked windows closed and that pre-existing/untracked windows remain. Keep any app save prompt visible; do not treat a pending close as success.

Full demonstration instructions are in `docs/DEMO.md`; submission architecture and limitations are in `docs/SUBMISSION.md`. The source archive deliberately excludes credentials, local databases, microphone audio, camera recordings and generated test output.
