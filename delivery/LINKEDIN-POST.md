# LinkedIn draft

I built KAAT for the Gnani.ai internship challenge: a small Windows assistant for Hinglish commands and video cleanup.

The workflow is straightforward. Open a recording, ask KAAT to find long pauses, review the suggested cuts, approve or undo them, and export a separate MP4. The original stays unchanged.

Gnani Prisma v3.0 provides speech recognition. Python and FFmpeg handle the local tools, SQLite remembers approved preferences, and the floating widget shows what KAAT heard and what actually happened.

I focused on reproducible results: playable exports, retained audio, unchanged source files and visible failures when an action cannot be verified.

Optional filler proposals use a separate local Whisper model and need review. The Hinglish sample returned zero; a separate human interview fixture produced 11 candidates. Their exact cut boundaries still need independent checking, so I’m not presenting filler removal as validated.

The walkthrough shows the real desktop editing flow using typed controls. Recorded human speech was also tested with Gnani; that is separate from a new live voice-to-action demonstration.

Code: [Repository URL]
Demo: [Demo URL]

#GnaniAI #Python #Hinglish

---

Publication status: **draft only; not posted**. Replace the two links before publishing; the local recording is `delivery/KAAT-demo.mp4`. This draft makes no successful filler-removal or new spoken-cleanup claim. Add either only after its actual verification is recorded.
