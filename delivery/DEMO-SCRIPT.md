# KAAT: 60–90 second demo script

Record the actual desktop and output playback. If commands are typed, keep **“Typed desktop walkthrough”** visible. A typed command must not be presented as a spoken command. Keep real errors visible; do not substitute a transcript or an execution result.

| Time | Show | Narration |
|---|---|---|
| 0–10s | Floating KAAT widget above the source video | “This is KAAT, my Hinglish-first Windows desktop assistant. I built it around a practical editing workflow: clean up a recording while keeping the original safe.” |
| 10–25s | Select the actual video; show its duration and transcript | “Gnani Prisma v3.0 handles speech recognition. KAAT uses the actual returned transcript, while the local editing tools inspect the video and measure its pauses. This walkthrough uses typed controls; it is not a live voice-command test.” |
| 25–40s | Enter `Kaat, is video ke pauses hata de`; show suggestions. If the optional model is installed, show **Fillers** and its actual result. | “Pause cuts are suggestions. Optional filler detection uses local Whisper estimates, not Gnani word alignment. This public sample returned zero fillers, so I’m not claiming successful filler removal. Nothing is automatically approved.” |
| 40–55s | Approve one reviewed cut; Undo; approve again | “I can review a cut, approve it, and undo it. The planned duration changes with my decision. I stay in control of what reaches the final video.” |
| 55–75s | Export a fresh MP4; play the edited copy with audio | “Export runs through FFmpeg and creates a separate playable MP4, plus a JSON edit list. The original stays unchanged. I verify the actual output and source fingerprint rather than treating a button click as success.” |
| 75–90s | Show saved preference, then source and edited files | “KAAT also remembers settings locally. The aim is a useful Hinglish workflow with real tool results, clear errors and reversible edits. The source and demo are included with the submission.” |

Let playback demonstrate the audible gap reduction. If a network call or export takes longer, either keep its real duration or visibly label the accelerated section. Do not imply instant transcription or rendering.

Filler-word status: optional local analysis is implemented; a real public human Hinglish run returned **zero suggestions**. Positive filler-removal accuracy still requires independent human review. Install `.\.venv\Scripts\python.exe -m pip install -r requirements-speech.txt` before showing **Fillers**; first use downloads the model. The user's filler-positive recording path has not been supplied. Do not invent one or substitute a generated transcript. Show a positive proposal only after real audio produces it, and verify the approved export. Whisper estimates and coarse Gnani chunks are different timing sources; neither supplies guaranteed word alignment.

The screen recording is delivered as [`KAAT-demo.mp4`](KAAT-demo.mp4). It is a typed desktop walkthrough, separate from a live voice-to-action test.

Separate from the displayed Hinglish sample, local Whisper `base` produced 11 review candidates on a real interview-filler fixture. That is evidence of candidate generation only; its exact cut boundaries and removal accuracy are not independently validated. Do not replace the demo's actual zero-result screen with those separate results.

For a separate live voice take, click the microphone, wait for **Listening**, and speak the command. Show **HEARD**, **INTERPRETED**, **TARGET** and **RESULT**, followed by the actual action. Keep that evidence distinct from this typed editing walkthrough.


A separate real filler-fixture controller check produced 11 proposals and exported a 12.00-second source to 5.42 seconds with full audio/video decode and the source hash unchanged. Approval was issued by test automation, not human review. This verifies the proposal-to-export path, not independent word-boundary accuracy or editorial safety. Evidence: `test_output/filler_real/actual_controller_export.json`. The primary Hinglish demo still returned zero filler proposals.
