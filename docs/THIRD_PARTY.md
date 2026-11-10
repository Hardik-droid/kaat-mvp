# Third-party attribution

No source was copied from the reviewed video-editor applications. KAAT uses their architectural ideas only where the same conventional approach is independently implemented; [REUSE.md](REUSE.md) records all seven requested upstream reviews and pinned source snapshots.

| Dependency | Tested version | License | Use and source |
|---|---|---|---|
| Python / Tkinter | Python 3.13.7, Tk 8.6 | PSF; Tcl/Tk BSD-style terms | Local runtime and existing overlay; [Python license](https://docs.python.org/3/license.html), [Tcl/Tk](https://www.tcl-lang.org/software/tcltk/license.html) |
| FFmpeg / FFprobe | Gyan 9.0.2 essentials | Build-specific GPL; FFmpeg base LGPL, GPL when configured with GPL components | External process for actual media operations; [FFmpeg legal](https://ffmpeg.org/legal.html), [Windows build](https://www.gyan.dev/ffmpeg/builds/) |
| gnani-vachana | 0.9.0 | MIT (SDK only) | Official Prisma REST client; [source and license](https://github.com/Gnani-AI-Mintlify/gnani-vachana) |
| mcp | 1.30.0 | MIT | Official local MCP stdio server/client; [source/license](https://github.com/modelcontextprotocol/python-sdk) |
| python-dotenv | 1.2.4 | BSD-3-Clause | Load private environment configuration; [source](https://github.com/theskumar/python-dotenv) |
| sounddevice | 0.5.6 | MIT | Default Windows microphone capture using PortAudio; [source](https://github.com/spatialaudio/python-sounddevice) |
| webrtcvad-wheels | 2.0.14.post1 | MIT wrapper; BSD-3-Clause WebRTC | Small native local speech detector; [source](https://github.com/daanzu/py-webrtcvad-wheels), bundled notices in installed wheel |
| PortAudio | Bundled by sounddevice wheel | MIT-style | Audio device access; [license](https://www.portaudio.com/license.html) |
| pytest | 9.2.0 | MIT | Development tests; [source](https://github.com/pytest-dev/pytest) |
| Pillow | 12.3.0 | MIT-CMU | Development-only desktop screenshot evidence; [license](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| faster-whisper (optional) | 1.2.1 | MIT | Local secondary filler proposals; [official license](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE) |
| CTranslate2 (optional) | 4.8.5 installed | MIT | Local model inference dependency; [official license](https://github.com/OpenNMT/CTranslate2/blob/master/LICENSE) |
| OpenAI Whisper model (optional) | `tiny` used in this check | MIT | Model-estimated word timing, separate from Gnani; [official license](https://github.com/openai/whisper/blob/main/LICENSE) |

Python's `difflib.SequenceMatcher`, SQLite, subprocess, wave and other standard-library modules cover lightweight retake similarity, memory, tool execution and audio handling. The core app does not require Whisper, NumPy, a full editor framework, RapidFuzz or a paid LLM. The optional `requirements-speech.txt` extra installs faster-whisper and its dependencies, including CTranslate2 and NumPy; first use downloads the model. Gnani remains the primary speech provider. Local Whisper estimates are review-only candidates, not guaranteed alignment or verified filler removal.

The source ZIP does not redistribute FFmpeg, Python, wheels or models. Installers download upstream packages, which retain their own notices and transitive dependencies. If producing a binary bundle later, audit the exact wheel/binary licenses and include all required notices and corresponding-source obligations. Gnani model/service rights are separate from the SDK's MIT license. The existing starter did not provide a project license; this work does not invent a license for source owned by the project author.
