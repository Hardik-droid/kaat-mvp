# KAAT submission pack

KAAT is a floating Windows assistant for supported English/Hinglish commands and reversible video edits. Gnani Prisma v3.0 supplies speech recognition; FFmpeg produces real edited copies. Video analysis, rendering, permissions and saved preferences are handled on this computer. Explicitly selected speech is sent to Gnani for transcription.

## Start the application

From the project folder in PowerShell:

```powershell
.\run_kaat.bat
```

On a fresh machine:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -DownloadFFmpeg
notepad .env
# Set GNANI_API_KEY privately for speech recognition.
.\.venv\Scripts\python.exe doctor.py
.\run_kaat.bat
```

Typed commands and local editing remain available without a speech key. Accept the local **Allow / Not now** prompt when using the microphone or camera, then wait for **Listening** before speaking. Windows controls its own hardware privacy settings.

For optional filler proposals, install the separate speech extra; `setup.ps1` does not install it:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-speech.txt
```

Select the real video and choose **Fillers**. First use downloads a local Whisper model. Gnani remains the primary speech provider; Whisper's approximate per-word estimates only support reviewable filler suggestions. Nothing is auto-approved.

## Files to submit

| Item | Location |
|---|---|
| Source archive | [`dist/KAAT-MVP-source.zip`](../dist/KAAT-MVP-source.zip) |
| Typed desktop walkthrough | [`delivery/KAAT-demo.mp4`](KAAT-demo.mp4) |
| Original public-speech sample | [`KAAT-original-sample.mp4`](KAAT-original-sample.mp4) |
| Fresh edited sample | [`KAAT-edited-sample.mp4`](KAAT-edited-sample.mp4) |
| Compact verification and attribution | [`VERIFICATION.md`](VERIFICATION.md) |
| Technical description | [`docs/SUBMISSION.md`](../docs/SUBMISSION.md) |
| Verification record and limits | [`docs/EMERGENCY_REPAIR.md`](../docs/EMERGENCY_REPAIR.md) |
| Short recording script | [`delivery/DEMO-SCRIPT.md`](DEMO-SCRIPT.md) |
| LinkedIn draft | [`delivery/LINKEDIN-POST.md`](LINKEDIN-POST.md) |

Rebuild the source archive after final code changes:

```powershell
.\.venv\Scripts\python.exe scripts\package_release.py
```

The archive excludes real credentials, the virtual environment, local databases, microphone recordings and generated test media. It needs the normal setup step after extraction.

## Verified demo outputs

`KAAT-demo.mp4` is a **78.933333-second silent screen recording** of actual Windows mouse input and typed commands, with real decoded media frames visible. The final run passed; metadata is recorded in `demo-evidence.json`. Play the separate original/edited sample files to hear the retained human speech; the screen recording contains no microphone capture or generated narration.

These files are available in the development workspace and are separate from the source ZIP:

- Source: `test_output\practical_speech\human_hinglish_with_pause.mp4`
- Delivery edited copy: `delivery\KAAT-edited-sample.mp4`
- Final recording metadata: `delivery\demo-evidence.json`; full run evidence: `test_output\demo_capture_run3\report.json`

The source measured 25.025 seconds; the fresh edited copy measured 22.185 seconds and passed full audio/video decode. Its original source fingerprint stayed unchanged. The source contains public OpenSLR 104 human Hindi-English speech with a controlled pause and generated video pattern; it is not a live microphone recording. Preserve the [attribution and CC BY-SA 4.0 terms](VERIFICATION.md) when sharing that fixture.

## What the demonstration proves

The typed desktop walkthrough demonstrates actual selection, pause proposals, approval, undo and export. A separate real provider response establishes recorded-speech transcription. Neither alone proves a newly recorded microphone-to-action command. Live voice acceptance requires visible capture, the actual transcript and the resulting action in the same run.

The optional filler detector completed a public human Hinglish analysis with **zero suggestions**. That does not establish successful filler removal or prove the source contains no fillers. A user recording and human-reviewed filler edit remain pending; the user's recording path has not been supplied. Do not describe Whisper estimates as Gnani word alignment, or coarse transcript chunks as word timestamps. Recognition can be wrong, and uncertain edits require review. Window cleanup covers only newly created windows tracked by this version; it does not close older or unrelated windows.

A separate real interview-filler fixture returned **11 experimental review proposals** with local Whisper `base`. Candidate generation is verified on that fixture; exact cut boundaries and removal accuracy are not independently validated. This does not change the Hinglish demo's zero-detection result. [Evidence and attribution](VERIFICATION.md).

No LinkedIn post has been published by preparing this pack. The draft needs the final repository and hosted demo links.


A separate real filler-fixture controller check produced 11 proposals and exported a 12.00-second source to 5.42 seconds with full audio/video decode and the source hash unchanged. Approval was issued by test automation, not human review. This verifies the proposal-to-export path, not independent word-boundary accuracy or editorial safety. Evidence: `test_output/filler_real/actual_controller_export.json`. The primary Hinglish demo still returned zero filler proposals.
