# Current delivery check — 10 November 2026

This follow-up supersedes older microphone-pending and recording-unsupported statements in historical reports.

## Reproduced failures and corrections

- User input reached the physical device, but recognition returned empty text. Real speaker-playback and initial live attempts failed and remain recorded as failures. Capture now uses the microphone's native channels, selects a stronger channel without cancellation, applies bounded local gain, and uses WebRTC voice detection rather than treating loudness as speech. The later live native-format capture produced intelligible user commands. The exact cause of every earlier empty transcript is not retrospectively provable because those buffers were discarded.
- A real API check returned “Caught. Open camera.” for an explicitly labelled synthesized command. Wake-word punctuation and that observed spelling variant were rejected. Punctuation is now handled, and the phonetic variant is accepted only for explicitly activated input.
- The actual user said “Can you just open the camera quick? I want to take a read.” The strict parser rejected the polite wording and explanatory phrase. Anchored polite camera requests now work; negation, questions about actions and independent combined mutations remain rejected.
- Empty recognition never opens a camera or invents words. The notification offers retry and local microphone selection. Windows consent remains under Windows control, with local settings links when access is blocked. Successful camera notifications dismiss automatically.
- Recording previously returned an unsupported error. A fixed Windows Camera UI Automation adapter now invokes native video controls and waits for the actual recording/paused/ready state. Start can open Camera and switch to video mode. Stop finds a newly created MP4 and probes it; an empty session selects that file for editing. Existing selections/edits are preserved.

## Real evidence

The final configured suite passed **238 tests in 41.68 seconds**, with zero skips. It includes an explicitly selected public human WAV sent to the real Gnani service and local VAD validation. Unit doubles remain separate from the practical checks below. Raw output: `test_output/speech_command_fix/final_tests.txt`.

The live user command **“Please open the camera.”** passed through the physical laptop microphone, actual Gnani response, parser, camera adapter and visible native Camera window. It appeared at about 67.8 seconds in `test_output/speech_command_fix/live_final/report.json`, after the user waited about 61 seconds before activating capture. Capture began around 61.8 seconds and Camera returned around 67.8 seconds. This is an actual human check, separate from synthesized speech and unit doubles. The later request for recording failed in that older process, before the recording adapter was added; it was not relabelled a success.

The native recording test executed real start, pause, resume and stop actions. Its saved MP4 contained H.264 video and AAC audio and decoded successfully with FFmpeg. A later reproducible native check saved **5.574 seconds**, verified audio, preserved the original hash and selected the new recording for editing. The command microphone also opened/read/closed while Camera was recording. This proves simultaneous local device access; a human-spoken stop-recording command has not separately been observed.

Local evidence:

- `test_output/speech_command_fix/replay_result.json`: real retained-human-audio API replay and successful camera action.
- `test_output/speech_command_fix/live_final/report.json`: actual live phases and latest result; the user continued testing after camera success.
- `test_output/speech_command_fix/native_recording_final/report.json`: actual native recording states, microphone probe, saved file and decode checks.
- `test_output/speech_command_fix/physical_playback1` and `physical_playback2`: failed synthesized speaker-to-mic checks, not acceptance passes.

Diagnostic retention was explicitly enabled only for the channel investigation. Those short diagnostic WAVs were removed afterward. Normal capture does not archive microphone audio. Camera test clips stay privately in the local Camera Roll and are excluded from the source release.

## Reproduction

Install the pinned requirements, then run the project normally with `run.ps1`. For the native recording QA, which deliberately makes a real private camera clip:

```powershell
.\.venv\Scripts\python.exe scripts\check_camera_recording.py --interactive --output test_output\my_recording_check
```

For a user-activated camera/recording voice check without automatic capture:

```powershell
.\.venv\Scripts\python.exe scripts\check_spoken_camera.py --interactive --output test_output\my_voice_check
```

The recording adapter was verified against this machine's English Windows Camera UI. Other UI languages/builds can fail explicitly if the controls differ. Permissions and camera actions are local; speech recognition still sends the activated command to Gnani. This remains push-to-talk REST recognition, not continuous streaming. Current session recording status is the last verified native state, not continuous monitoring of other applications.
