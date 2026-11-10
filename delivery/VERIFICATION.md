# KAAT delivery verification — 10 November 2026

The final [screen recording](KAAT-demo.mp4) uses the actual Windows application, mouse and typed input, with real FFmpeg-decoded media frames visible. It is **78.933333 seconds**, **silent**, and contains no microphone recording or generated narration. Run 3 passed; the capture process exited 0. Delivery metadata is in [`demo-evidence.json`](demo-evidence.json).

| Check | Observed result |
|---|---|
| Real source selection | Public human Hindi-English speech; 25.025 seconds |
| Local filler analysis | Completed; **zero suggestions**, not proof of successful filler removal |
| Separate positive filler fixture | Local Whisper `base` returned 11 review proposals from a real interview-filler compilation (model probabilities 0.81–0.94). Exact boundaries were not independently annotated; removal accuracy is not validated. |
| Pause analysis | Actual FFmpeg silence proposal, followed by explicit approval |
| Undo | Approval reverted, then explicitly approved again |
| Fresh export | Separate 22.185-second MP4; audio/video fully decoded |
| Original preservation | Source SHA256 unchanged |
| Automated suite | 365 passed, 1 skipped; the skipped live Gnani case requires its opt-in audio fixture. |
| Separate actual Gnani request | `test_voice::test_real_gnani_hinglish_integration`: 1 passed in 5.81 seconds using the existing public human `103085_w5Jyq3XMbb3WwiKQ_0000.wav`. This is recorded-audio provider evidence, not live microphone capture. |

Final media/capture evidence: local `test_output/demo_capture_run3/report.json`. Run 2's capture was rejected for insufficient playback visibility and replaced. Delivery metadata: [`demo-evidence.json`](demo-evidence.json). Source SHA256: `b8181ca05b9a5d335a4fe9ee5000066fb6ec5c9649b10334ddb5d4ea047c0bcd`.

Play [`KAAT-original-sample.mp4`](KAAT-original-sample.mp4) and [`KAAT-edited-sample.mp4`](KAAT-edited-sample.mp4) to compare the retained audio. These media checks do not establish a new live microphone-to-action command. Filler-removal accuracy remains unvalidated. Gnani remains the primary speech provider; optional local Whisper supplies approximate word estimates that require review and approval.

## Public sample attribution

Human Hindi-English technical-lecture speech comes from **MUCS / OpenSLR 104**, distributed through the [OpenSLR 104 source page](https://www.openslr.org/104/), with the downloaded [MUCS-Hinglish mirror](https://huggingface.co/datasets/dianavdavidson/MUCS-Hinglish). The included excerpt identifiers are `103085_w5Jyq3XMbb3WwiKQ_0000` and `103085_w5Jyq3XMbb3WwiKQ_0001`.

The upstream **[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)** terms are retained for the public-speech samples and their edited derivatives. KAAT combined the excerpts, inserted a controlled silence gap and generated a test-pattern picture; the edited sample removes the approved pause. The speech is human, not synthesized. The mirror's broader license label does not replace the retained upstream attribution/share-alike terms. Local provenance: `test_output/practical_speech/report.json`.

Application and model attribution is in [`docs/THIRD_PARTY.md`](../docs/THIRD_PARTY.md). The source archive excludes credentials and generated media. The LinkedIn text remains a draft, not a published post.

The separate positive filler fixture uses **tim.kahn, “ummmmm.wav”**, [Freesound recording 184732](https://freesound.org/people/tim.kahn/sounds/184732/), under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The first 12 seconds were wrapped in a black video for testing. This real interview compilation is excluded from the release. Local provenance: `test_output/filler_real/tim_kahn_attribution.json`; actual analysis: `base_interview_ums.json`. The primary Hinglish demo still returned zero proposals. No user-supplied filler recording has been provided.


A separate real filler-fixture controller check produced 11 proposals and exported a 12.00-second source to 5.42 seconds with full audio/video decode and the source hash unchanged. Approval was issued by test automation, not human review. This verifies the proposal-to-export path, not independent word-boundary accuracy or editorial safety. Evidence: `test_output/filler_real/actual_controller_export.json`. The primary Hinglish demo still returned zero filler proposals.

Additional single-candidate check: exactly one test-approved cut (4.82-5.38s) exported 12.00s to 11.44s with full audio/video decoding and unchanged source SHA. Compare [filler original](KAAT-filler-original.mp4) and [filler edited](KAAT-filler-edited.mp4); [evidence](filler-evidence.json), [CC BY 4.0 attribution](filler-attribution.json). This was automated fixture approval, not human review or a general accuracy result.
