"""Lightweight Windows native voice feedback using SAPI.SpVoice."""
from __future__ import annotations
import os
import re
import threading

_voice = None

def _get_voice():
    global _voice
    if _voice is None:
        try:
            import win32com.client
            _voice = win32com.client.Dispatch("SAPI.SpVoice")
        except Exception:
            _voice = False
    return _voice

def speak(text: str, async_mode: bool = True):
    """Speak text using Windows native SAPI voice."""
    if not text or not isinstance(text, str):
        return
    if os.environ.get("WHISPER_MUTE_TTS", "").lower() in ("1", "true", "yes"):
        return
    # Clean up formatting, markdown, emojis
    cleaned = re.sub(r'[*_#`~✦•\n\r]+', ' ', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if not cleaned:
        return
    # Truncate if excessively long for speech
    if len(cleaned) > 280:
        cleaned = cleaned[:280] + "..."
    voice = _get_voice()
    if voice:
        try:
            flags = 1 if async_mode else 0
            voice.Speak(cleaned, flags)
            return
        except Exception:
            pass
    def _ps():
        import subprocess
        safe = cleaned.replace("'", "''")
        cmd = f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{safe}')"
        try:
            subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', cmd],
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=10)
        except Exception:
            pass
    threading.Thread(target=_ps, daemon=True).start()
