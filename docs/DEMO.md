# KAAT demonstration

## Delivery demonstration: real Windows actions first

Run `.\run_kaat.bat`. On first use, accept KAAT's local **Allow / Not now** prompt if you want microphone and camera access. Its choice is saved on this computer. Windows still owns device privacy settings.

1. Expand KAAT and type `Open Calculator.` Confirm an actual Calculator window and inspect the returned status. Then type `Kaat, Chrome khol de.` Confirm the Chrome window. An **unverified** outcome is inconclusive and must not be described as a pass.
2. Type `Google Photos khol de.` Inspect the browser address. A Google sign-in page may appear; KAAT does not sign into an account. Type `Mera Downloads folder khol.` Confirm the path in Explorer matches the Windows Downloads folder.
3. Click KAAT's microphone, wait for **Listening**, and say **“Kaat, Chrome khol de.”** Show the actual **HEARD**, **INTERPRETED**, **TARGET** and **RESULT** feedback. Confirm Chrome opened. This is the voice acceptance test; typed commands and a recorded-audio API test are not substitutes.
4. Select a real video using **+**. Activate the microphone and say **“Kaat, is video ke pauses remove kar.”** Review suggestions, approve a correct cut, undo and approve it again. Export a fresh MP4; play it and compare the original SHA256 before/after.
5. Activate the microphone and say **“Kaat, remember my pause threshold is two seconds.”** Inspect the saved preference, quit and reopen KAAT, then use `Show my preferences`. The value must still be present. `Remember my settings` explicitly saves the current pause threshold and subtitle setting; the listening limit has its own **Save** control.
6. Type `Open KaatDefinitelyMissingApp.` The result must be a genuine application-not-found failure, with no success claim.
7. With this updated KAAT version running, open a fresh supported browser window through `Open Google Photos`. Then type or speak **“Close all those stuff which you have opened recently.”** Confirm that the tracked new window closes and any pre-existing browser window stays open. If a save/close prompt remains, leave it for the user and report the pending window accurately. Reused windows and windows opened before this update are intentionally outside this cleanup; do not present them as a cleanup failure or silently close them by another method.

Record these results individually. If speech is wrong, show the real transcript and repeat the short command; do not replace it with a typed transcript while claiming the voice test passed. If the provider is unavailable, continue the typed/video demonstration and mark speech **NOT TESTED** or **FAILED**, as appropriate. The [emergency report](EMERGENCY_REPAIR.md) records the evidence actually obtained during repair; the steps above describe a new live run.

Before recording the demonstration:

```powershell
.\.venv\Scripts\python.exe doctor.py
.\run_kaat.bat --check
```

The doctor does not open the microphone or camera. To validate the real provider separately, use `doctor.py --audio C:\path\short-human-speech.wav`. Keep that file under 30 seconds and explicitly select audio you intend to send to Gnani. Default push-to-talk is bounded to six seconds and can be configured with `KAAT_CAPTURE_SECONDS` (0.5–25 seconds). **Preferences → Listen up to (seconds) → Save** overrides that environment default. Press the microphone again or **Escape** to cancel before action dispatch.

The optional reasoning provider is separate from this acceptance demonstration. It is disabled by default and returns proposed steps for review; it never executes a compound workflow. Do not demonstrate “find yesterday's video, edit and save” as implemented. The user must select an exact source and run supported reviewed actions. Configuration and data sent to that optional provider are described in the README.

Cleanup uses a persistent local journal plus a unique marker on each newly created window, and verifies that ownership before issuing a normal close request. The journal survives a KAAT restart; it does not reconstruct older untracked windows or tabs. Active/paused Camera recording is protected. An ambiguous `close all` must ask what should be closed without sending that ambiguity to an LLM. For MCP, demonstrate the same operation with `system.close_recent({"approved":true})` only after an explicit user instruction. Normal [Windows WM_CLOSE](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-close) lets the target app show its own confirmation; KAAT never accepts a discard prompt or force-kills it.

## Reproducible local editing proof

From the project folder in PowerShell, after setup:

```powershell
.\.venv\Scripts\python.exe scripts\demo.py --output demo_output
```

The output directory must be empty or new. Existing files are never replaced. To repeat, choose a different directory, for example `--output demo_output\run2`.

The script generates a real 4.5-second MP4 with a moving test pattern, one second of tone, 2.5 seconds of silence and another second of tone. **It contains no Hinglish speech and does not call Gnani.** It executes the shared controller to inspect the media, detect a pause, approve cuts, undo the last approval, approve again and render through FFmpeg. It verifies the actual output duration, original SHA256 and EDL fingerprint, then writes:

- `source_synthetic.mp4`: preserved generated source.
- `cleaned_synthetic.mp4`: separately rendered approved edit.
- `cleaned_synthetic.kaat-edl.json`: source fingerprint and edit decisions.
- `report.json`: exact measured durations, cuts, execution steps and verification limits.
- `demo.sqlite3`: isolated task history; the demo does not change your normal preferences.

Minor differences between planned and encoded durations come from video frame boundaries and audio/container timing. The script checks the actual exported media rather than treating a requested render as success. `demo_output/` is ignored by Git.

This demo calls the controller directly. The real stdio MCP equivalent is exercised separately by `tests/test_mcp.py`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_mcp.py
```

## Live Hinglish demonstration for the challenge

This part requires your own recording, an available microphone, network access and a valid `GNANI_API_KEY` in the local `.env`. It is a manual verification procedure, not evidence that your account or microphone has already passed.

Prepare a short Hinglish talking-head recording with a clear pause longer than two seconds. Include a repeated sentence if demonstrating retake suggestions. Keep the original in a separate folder and record its fingerprint:

```powershell
Get-FileHash -Algorithm SHA256 .\your_hinglish_video.mp4
.\.venv\Scripts\python.exe app.py
```

1. Open the recording in your usual media player. Select the same file using KAAT's **+** button; keep the floating overlay visible above the player. Expand the controls to review cuts and export.
2. Press KAAT's **microphone** button, wait for **Listening**, and say: **“Kaat, is video ke pauses hata de.”** The button explicitly activates one command capture. Wait for the real Prisma response; expand the controls to show the recognized words and tool result. If the API fails, show the error and fix the configuration before claiming a voice demonstration.
3. Show the proposed pause interval and the original/edited durations. A suggestion alone must not shorten the approved duration. Review the proposed cut, then approve it.
4. Undo that approval and show the restored duration. Approve the reviewed cut again. This demonstrates reversible decisions without changing the original file.
5. Export to a fresh MP4 filename. Open the edited copy and compare its duration with the original. Show the JSON operations and their approval statuses.
6. Run `Get-FileHash` again on the original and compare the SHA256 values.
7. Activate push-to-talk and say: **“Kaat, agli baar bhi 3 seconds se bade pauses hata dena, yaad rakhna.”** Check that the recognized text explicitly requests remembering the setting, and inspect the saved preference. Close and reopen KAAT and show that the changed three-second preference remains. A one-off “remove pauses over two seconds” command must not silently persist a preference.
8. If demonstrating subtitles, click **Transcribe** and inspect the returned text first. Enable **Add subtitles** and use a new output name. File transcription currently uses real extraction-chunk boundaries; captions are coarse segment captions, not word-aligned or karaoke subtitles.
9. If demonstrating retakes, run detection after transcription, inspect the repeated segments and approve only a clearly correct cut. Similarity results remain suggestions; coarse chunks can contain unrelated speech.

For the credential-gated file transcription check, point the test at audio you intend to send to Gnani:

```powershell
$env:KAAT_TEST_AUDIO = 'C:\path\to\short_hinglish.wav'
.\.venv\Scripts\python.exe -m pytest -q tests\test_voice.py
```

See [GNANI.md](GNANI.md) for the exact integration-test activation requirements and speech timing limitations.

## Suggested narration

“KAAT stays beside the applications I already use. I activate its microphone and speak a Hinglish instruction. Gnani Prisma transcribes the audio, the deterministic parser chooses a supported tool, and FFmpeg proposes silence cuts. I approve the cuts before export, and I can undo them. The original stays intact. Explicitly approved preferences survive a restart.”

Do not describe the synthetic demo as real speech recognition or bounded push-to-talk REST requests as streaming. This release supports recording through the tested English Windows Camera UI: demonstrate `start recording`, `pause recording`, `resume recording`, then `stop recording` and inspect the actual saved MP4. Other camera/editor applications remain unsupported. [Earlier camera evidence](DELIVERY_CHECK.md); [latest repair acceptance](EMERGENCY_REPAIR.md).
