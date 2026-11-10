"""Shared tool execution for the desktop overlay and local MCP server."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import math
import threading
import tempfile
import sqlite3
import time

import engine
from commands import parse_command
from memory import Memory


class AgentController:
    def __init__(self, memory_path=None):
        self.memory = Memory(memory_path)
        self.lock = threading.RLock()
        self.source = None
        self.info = {}
        self.cuts = []
        self.segments = []
        self.undo_stack = []
        self.pause_seconds = self.memory.preferences().get("pause_threshold", 2.0)
        self.subtitle_requested = self.memory.preferences().get("burn_subtitles", False)
        self.last_output = None
        self.source_signature = None
        self.recording_status = 'unknown'
        self.recording_before = None

    def close(self):
        pass  # Connections are scoped to each operation; nothing remains open.

    def state(self):
        with self.lock:
            return self._state()

    def _state(self):
        total = self.info.get("duration_seconds", 0)
        kept = engine.keep_ranges(total, self.cuts) if total else []
        memory_warning = None
        try:
            preferences, history = self.memory.preferences(), self.memory.history()
        except (sqlite3.Error, OSError):
            preferences, history = {}, []
            memory_warning = "Local memory is unavailable; preferences/history could not be read."
        return {"source": str(self.source) if self.source else None,
                "original_duration": total, "edited_duration": round(sum(b-a for a, b in kept), 3),
                "cuts": [asdict(c) for c in self.cuts], "transcript": deepcopy(self.segments),
                "pause_threshold": self.pause_seconds, "subtitles": self.subtitle_requested,
                "preferences": preferences, "history": history, "memory_warning": memory_warning,
                "undo_available": bool(self.undo_stack), "output": self.last_output,
                "recording_status": self.recording_status, "microphone_mode": "push_to_talk"}

    def _require_video(self):
        if not self.source:
            raise ValueError("Select a video first")
        if self._source_signature() != self.source_signature:
            raise ValueError("The selected source changed. Select the video again before editing.")

    def _source_signature(self):
        stat = self.source.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

    def _snapshot(self):
        self.undo_stack.append(deepcopy(self.cuts))
        self.undo_stack = self.undo_stack[-100:]

    def _cut(self, cut_id):
        return next((c for c in self.cuts if c.id == cut_id), None)

    def _persist(self):
        # Session metadata survives a crash; raw speech/text stays in RAM only.
        self.memory.save_session({"source": str(self.source) if self.source else None,
                                  "cuts": [asdict(c) for c in self.cuts], "output": self.last_output})

    def call(self, tool, **kwargs):
        with self.lock:
            if not isinstance(tool, str) or not tool:
                return {"ok": False, "tool": "invalid", "error": {"type": "ValueError", "message": "Tool name must be a nonempty string"}}
            try:
                data = self._execute(tool, **kwargs)
                verified = self._verified(tool, data, kwargs)
                status = 'success' if verified else 'unverified'
                if isinstance(data, dict) and data.get('status') in {'success', 'failed', 'unverified', 'needs_attention', 'nothing_to_close'}:
                    status = data['status']
                result = {"ok": status in {'success', 'nothing_to_close'}, "tool": tool, "data": data,
                          "status": status, "verified": verified}
                if not result['ok']:
                    result['error'] = {'type': 'VerificationInconclusive', 'message': data.get('message', 'The result could not be verified.')}
                if tool != "session.state" and not tool.startswith("memory.get"):
                    try:
                        self.memory.record(tool, result['ok'], data.get('message', status) if isinstance(data, dict) else status)
                        self._persist()
                    except (sqlite3.Error, OSError):
                        result["warnings"] = ["The action result is available, but local history/session metadata could not be saved."]
                return result
            except Exception as exc:
                message = str(exc)
                # SDKs can include credentials in errors; never display a configured key.
                import os
                key = os.getenv("GNANI_API_KEY")
                if key:
                    message = message.replace(key, "[redacted]")
                try:
                    self.memory.record(tool, False, message)
                except (sqlite3.Error, OSError):
                    pass  # Return the original tool failure even if its logger is unavailable.
                return {"ok": False, "tool": tool, "status": "failed", "verified": False,
                        "error": {"type": type(exc).__name__, "message": message}}

    def _verified(self, tool, data, args):
        """Verify against the observed tool output or independently read local state."""
        if isinstance(data, dict) and 'verified' in data:
            return data['verified'] is True
        if tool.startswith('memory.'):
            if tool in {'memory.save_preference', 'memory.update_preference'}:
                return self.memory.preferences().get(args['key']) == args['value']
            if tool == 'memory.delete_preference':
                return args['key'] not in self.memory.preferences()
            return True  # The read itself completed against SQLite.
        if tool in {'session.state', 'system.list_supported_apps', 'camera.list_devices'}:
            return True  # Inventory only; does not imply device capture works.
        if tool.startswith('camera.'):
            expected = {'camera.start_recording':'recording', 'camera.resume_recording':'recording',
                        'camera.pause_recording':'paused', 'camera.stop_recording':'ready'}.get(tool)
            return bool(expected and data.get('state') == expected)
        if tool == 'video.inspect':
            return bool(data.get('duration_seconds', 0) > 0 and data.get('streams'))
        if tool == 'video.export':
            actual = engine.inspect_video(data['output'])
            return abs(actual['duration_seconds'] - data['edited_duration']) < .15
        if tool == 'video.export_edl':
            import json
            return json.loads(Path(args['output']).read_text(encoding='utf-8')) == data
        if tool in {'video.detect_pauses', 'video.detect_retakes', 'video.detect_fillers', 'video.undo', 'video.clear_edits'}:
            current = {cut.id: asdict(cut) for cut in self.cuts}
            return all(current.get(cut['id']) == cut for cut in data['cuts'])
        if tool in {'video.propose_cut', 'video.approve_cut', 'video.restore_cut'}:
            cut = self._cut(data['id'])
            return cut is not None and all(data.get(k) == v for k, v in asdict(cut).items())
        if tool == 'video.approve_all':
            return not any(c.status == 'suggested' for c in self.cuts)
        if tool == 'video.transcribe':
            return data['segments'] == self.segments
        if tool == 'video.import_transcript':
            return self.segments == args['segments']
        return False

    def _execute(self, tool, **args):
        if tool == "session.state":
            return self.state()
        if tool == "memory.get_preferences":
            return self.memory.preferences()
        if tool == "memory.get_history":
            return self.memory.history()
        if tool in ("memory.save_preference", "memory.update_preference"):
            data = self.memory.save(args["key"], args["value"], args.get("approved", False))
            if args["key"] == "pause_threshold":
                self.pause_seconds = float(args["value"])
            elif args["key"] == "burn_subtitles":
                self.subtitle_requested = args["value"]
            return data
        if tool == "memory.delete_preference":
            result = self.memory.delete(args["key"])
            if args["key"] == "pause_threshold":
                self.pause_seconds = 2.0
            if args["key"] == "burn_subtitles":
                self.subtitle_requested = False
            return result
        if tool.startswith("system.") or tool.startswith("camera."):
            import system_tools
            from tools import windows_apps
            functions = {"system.list_supported_apps": system_tools.list_supported_apps,
                         "system.list_installed_apps": windows_apps.list_installed_apps,
                         "system.open_application": system_tools.open_application,
                         "system.open_website": windows_apps.open_website,
                         "system.open_folder": windows_apps.open_folder,
                         "system.get_active_window": system_tools.get_active_window,
                         "camera.open": lambda: windows_apps.open_application('camera'),
                         "camera.list_devices": system_tools.list_camera_devices,
                         "system.close_application": windows_apps.close_application,
                         "system.close_active_window": windows_apps.close_active_window,
                         "system.change_volume": windows_apps.change_volume,
                         "system.take_screenshot": windows_apps.take_screenshot,
                         "system.minimize_all": windows_apps.minimize_all,
                         "system.web_search": windows_apps.web_search,
                         "system.youtube_play": windows_apps.youtube_play}
            if tool in functions:
                result = functions[tool](**args)
                if result.get('opened_windows'):
                    try:
                        self.memory.save_opened_windows(result['opened_windows'])
                    except (sqlite3.Error, OSError):
                        result['warning'] = 'The window opened, but its close tracking could not be saved locally.'
                return result
            if tool == 'system.close_recent':
                if args.get('approved') is not True:
                    raise ValueError('Closing KAAT-opened windows requires an explicit user request.')
                records = self.memory.opened_windows()
                if not records:
                    return {'status':'nothing_to_close', 'verified':False, 'closed':[], 'already_closed':[],
                        'pending':[], 'skipped':[], 'message':'No KAAT-opened windows are tracked. Windows from before this update or opened elsewhere are left open.'}
                candidates, protected = [], []
                for record in records:
                    if record.get('application') == 'camera' and windows_apps.owned_window_status(record) == 'owned':
                        try:
                            camera_state = system_tools.camera_control('status')
                            state = camera_state['state']
                            idle_verified = camera_state.get('idle_verified') is True or state == 'ready'
                        except (RuntimeError, OSError):
                            state = 'unknown'
                            idle_verified = False
                        if not idle_verified:
                            protected.append({**record, 'reason':'Stop recording before closing Camera.' if state in {'recording','paused'} else 'Camera recording state could not be checked.'})
                            continue
                    candidates.append(record)
                result = windows_apps.close_opened_windows(candidates)
                result['pending'].extend(protected)
                if protected:
                    result.update(status='needs_attention', verified=False,
                        message=result['message']+' '+protected[0]['reason'])
                terminal = result['closed']+result['already_closed']+result['skipped']
                self.memory.remove_opened_windows([record for record in terminal if 'hwnd' in record and 'nonce' in record])
                return result
            if tool in {"camera.start_recording", "camera.pause_recording", "camera.resume_recording", "camera.stop_recording"}:
                if args.get('approved') is not True:
                    raise ValueError('Recording requires an explicit local user instruction.')
                action = tool.split('.')[1]
                if action == 'start_recording':
                    try:
                        status = system_tools.camera_control('status')
                    except RuntimeError:
                        system_tools.open_camera()
                        deadline = time.monotonic()+5
                        while True:
                            try:
                                status = system_tools.camera_control('status')
                                break
                            except RuntimeError:
                                if time.monotonic() >= deadline:
                                    raise
                                time.sleep(.2)
                    if status['state'] == 'recording':
                        self.recording_status = 'recording'
                        return status
                    directory = Path(status['camera_roll']) if status.get('camera_roll') else None
                    before = set(directory.glob('*.mp4')) if directory else set()
                result = system_tools.camera_control(action, approved=True)
                self.recording_status = result['state']
                if action == 'start_recording':
                    self.recording_before = before
                elif action == 'stop_recording' and self.recording_before is not None:
                    directory = Path(result['camera_roll']) if result.get('camera_roll') else None
                    deadline = time.monotonic()+8
                    while directory and time.monotonic() < deadline:
                        candidates = set(directory.glob('*.mp4'))-self.recording_before
                        if len(candidates) == 1:
                            recorded = candidates.pop()
                            try:
                                info = engine.inspect_video(recorded)
                            except (OSError, RuntimeError, ValueError):
                                time.sleep(.2)
                                continue
                            result.update(output=str(recorded), duration_seconds=info['duration_seconds'])
                            result['message'] = 'Recording saved: ' + str(recorded)
                            if self.source is None:
                                self._execute('video.inspect', source=str(recorded))
                                result['selected_for_editing'] = True
                            break
                        time.sleep(.2)
                    self.recording_before = None
                    if not result.get('output'):
                        result['warning'] = 'Recording stopped, but its saved file could not be verified. Check Camera Roll.'
                return result
            raise ValueError("Unknown system or camera tool")
        if tool == "video.inspect":
            source = Path(args["source"]).expanduser().resolve(strict=True)
            info = engine.inspect_video(source)
            self.source, self.info = source, info
            self.source_signature = self._source_signature()
            self.cuts, self.segments, self.undo_stack = [], [], []
            self.last_output = None
            return info
        if tool not in {"video.detect_pauses", "video.transcribe", "video.detect_retakes", "video.detect_fillers", "video.import_transcript",
                        "video.propose_cut", "video.approve_cut", "video.restore_cut", "video.approve_all",
                        "video.undo", "video.clear_edits", "video.export_edl", "video.export"}:
            raise ValueError(f"Unknown tool: {tool}")
        self._require_video()
        if tool == 'video.detect_fillers':
            from speech_edits import detect_speech_edits
            detected = detect_speech_edits(self.source)
            self._require_video()
            refreshed = [cut for cut in self.cuts if cut.reason != 'filler_word' or cut.status != 'suggested']
            actual = []
            for proposed in detected['cuts']:
                candidate = engine.Cut(**proposed)
                if not 0 <= candidate.start < candidate.end <= self.info['duration_seconds'] + .01:
                    raise ValueError('Speech detector returned a cut outside the source video.')
                candidate.end = min(candidate.end, self.info['duration_seconds'])
                existing = next((cut for cut in self.cuts if cut.reason == candidate.reason
                    and abs(cut.start-candidate.start) < .02 and abs(cut.end-candidate.end) < .02), candidate)
                if all(cut.id != existing.id for cut in refreshed):
                    refreshed.append(existing)
                actual.append(existing)
            if refreshed != self.cuts:
                self._snapshot()
                self.cuts = refreshed
            return {**detected, 'cuts':[asdict(cut) for cut in actual]}
        if tool == "video.detect_pauses":
            threshold = args.get("min_pause_seconds", self.pause_seconds)
            Memory.validate("pause_threshold", threshold)
            cuts = engine.find_pauses(self.source, threshold)
            # Refresh pause suggestions while retaining approved and user-made cuts.
            refreshed = [c for c in self.cuts if c.reason not in ("long_pause", "trailing_silence") or c.status != "suggested"]
            actual = []
            for cut in cuts:
                existing = next((c for c in refreshed if c.reason == cut.reason and abs(c.start-cut.start) < .02 and abs(c.end-cut.end) < .02), None)
                if existing is None:
                    # Retain IDs of unchanged suggestions so clients can keep their selections.
                    existing = next((c for c in self.cuts if c.reason == cut.reason and abs(c.start-cut.start) < .02 and abs(c.end-cut.end) < .02), cut)
                    refreshed.append(existing)
                actual.append(existing)
            if refreshed != self.cuts:
                self._snapshot()
                self.cuts = refreshed
            self.pause_seconds = float(threshold)
            return {"cuts": [asdict(c) for c in actual], "requires_review": True, "threshold_seconds": threshold}
        if tool == "video.transcribe":
            self.segments = engine.prisma_transcribe(self.source)
            return {"segments": deepcopy(self.segments), "timing": "chunk_only", "word_timestamps": False}
        if tool == "video.detect_retakes":
            if not self.segments:
                raise ValueError("Transcribe the video first or import a verified timed transcript")
            cuts = engine.retake_suggestions(self.segments)
            actual = []
            additions = []
            for cut in cuts:
                existing = next((c for c in self.cuts if c.reason == cut.reason and c.start == cut.start and c.end == cut.end), None)
                if existing is None:
                    additions.append(cut)
                actual.append(existing or cut)
            if additions:
                self._snapshot()
                self.cuts.extend(additions)
            return {"cuts": [asdict(c) for c in actual], "requires_review": True,
                    "note": "Similarity is a suggestion; later takes need manual review."}
        if tool == "video.import_transcript":
            segments = args["segments"]
            if not isinstance(segments, list):
                raise ValueError("Transcript segments must be a list")
            for seg in segments:
                if not isinstance(seg, dict) or isinstance(seg.get("start"), bool) or isinstance(seg.get("end"), bool):
                    raise ValueError("Transcript segments require numeric start/end boundaries")
                start, end = float(seg["start"]), float(seg["end"])
                if not all(math.isfinite(x) for x in (start, end)) or not 0 <= start < end <= self.info["duration_seconds"] + .01:
                    raise ValueError("Transcript boundaries must be finite and within this source")
                if not isinstance(seg.get("text"), str) or seg.get("timing") not in ("segment", "word", "chunk_only"):
                    raise ValueError("Transcript needs text and declared timing: segment, word or chunk_only")
            self.segments = deepcopy(segments)
            return {"segments": len(segments), "note": "Caller supplied timestamps; KAAT did not align or invent them."}
        if tool == "video.propose_cut":
            if isinstance(args["start"], bool) or isinstance(args["end"], bool):
                raise ValueError("Cut boundaries must be numeric seconds, not booleans")
            start, end = float(args["start"]), float(args["end"])
            if not all(math.isfinite(x) for x in (start, end)) or not 0 <= start < end <= self.info["duration_seconds"]:
                raise ValueError("Cut boundaries must be within the source")
            self._snapshot()
            cut = engine.Cut(start, end, str(args.get("reason", "user_request")))
            self.cuts.append(cut)
            return asdict(cut)
        if tool in ("video.approve_cut", "video.restore_cut"):
            cut = self._cut(args["cut_id"])
            if cut is None:
                raise ValueError("Unknown cut ID")
            status = "approved" if tool == "video.approve_cut" else "restored"
            if cut.status != status:
                self._snapshot()
                cut.status = status
            data = asdict(cut)
            if status == "restored" and any(c.id != cut.id and c.status == "approved" and c.start < cut.end and c.end > cut.start for c in self.cuts):
                data["warning"] = "Other approved cuts overlap this interval and still remove their covered media."
            return data
        if tool == "video.approve_all":
            if any(cut.status == "suggested" for cut in self.cuts):
                self._snapshot()
            for cut in self.cuts:
                if cut.status == "suggested":
                    cut.status = "approved"
            return {"approved": sum(c.status == "approved" for c in self.cuts)}
        if tool == "video.undo":
            if not self.undo_stack:
                raise ValueError("No edit history to undo")
            self.cuts = self.undo_stack.pop()
            return {"cuts": [asdict(c) for c in self.cuts]}
        if tool == "video.clear_edits":
            if self.cuts:
                self._snapshot()
                self.cuts = []
            return {"cuts": []}
        if tool == "video.export_edl":
            return engine.save_plan(self.source, self.cuts, args["output"])
        if tool == "video.export":
            output = Path(args["output"]).expanduser().resolve()
            edl = output.with_suffix(".kaat-edl.json")
            srt = output.with_suffix(".srt")
            subtitles = args.get("subtitles", self.subtitle_requested)
            if not isinstance(subtitles, bool):
                raise ValueError("subtitles must be true or false")
            for path in (output, edl, *([srt] if subtitles else [])):
                if path == self.source or path.exists():
                    raise ValueError(f"Choose a fresh output filename: {path.name} already exists or is the source")
            if subtitles and not self.segments:
                raise ValueError("Transcribe the video before exporting subtitles")
            output.parent.mkdir(parents=True, exist_ok=True)
            # Finish every artifact before publishing; roll back our links on failure.
            with tempfile.TemporaryDirectory(prefix=".kaat_export_", dir=output.parent) as temp:
                staged = Path(temp)
                staged_srt = staged / srt.name
                caption_source = None
                if subtitles:
                    caption_segments, caption_cuts = self.segments, self.cuts
                    caption_total = self.info["duration_seconds"]
                    caption_source = "source_timestamps"
                    kept_ranges = engine.keep_ranges(caption_total, self.cuts)
                    partial_caption = False
                    for segment in self.segments:
                        start, end = float(segment["start"]), float(segment["end"])
                        remaining = sum(max(0., min(end, b)-max(start, a)) for a, b in kept_ranges)
                        if str(segment.get("text", "")).strip() and 1e-7 < remaining < end-start-1e-7:
                            partial_caption = True
                            break
                    if partial_caption:
                        # No text cue can be split into words from just its outer bounds.
                        # Re-recognize retained audio when a cut removes only part of a cue.
                        edited_audio = staged / "edited_audio.wav"
                        engine.extract_edit_audio(self.source, self.cuts, edited_audio)
                        from voice import transcribe_pcm_wav
                        caption_segments = transcribe_pcm_wav(edited_audio)
                        caption_cuts = None
                        caption_total = sum(end-start for start, end in kept_ranges)
                        caption_source = "edited_audio"
                    engine.write_srt(caption_segments, staged_srt, cuts=caption_cuts, total=caption_total)
                self._require_video()
                staged_video = engine.render(self.source, self.cuts, staged / output.name,
                                             subtitles=staged_srt if subtitles else None)
                plan = engine.save_plan(self.source, self.cuts, staged / edl.name)
                artifacts = [(staged_video, output), (staged / edl.name, edl)]
                if subtitles:
                    artifacts.append((staged_srt, srt))
                published = []
                try:
                    for origin, target in artifacts:
                        engine._publish(origin, target)
                        published.append((origin, target))
                except Exception:
                    for origin, target in published:
                        if target.exists() and target.samefile(origin):
                            target.unlink()
                    raise
            self.last_output = str(output)
            return {"output": str(output), "edl": str(edl), "subtitles": str(srt) if subtitles else None,
                    "original_duration": plan["original_duration"], "edited_duration": plan["edited_duration"],
                    "source_untouched": True, "caption_source": caption_source}
        raise ValueError(f"Unknown tool: {tool}")

    def _handle_presentation(self):
        try:
            from pathlib import Path
            import os
            desktop = Path.home() / 'Desktop'
            cwd = Path.cwd()
            slides = list(desktop.glob('*.pptx')) or list(cwd.glob('*.pptx')) or list((desktop / 'New folder (3)').glob('*.pptx'))
            if slides:
                os.startfile(slides[0])
            else:
                from tools import windows_apps
                windows_apps.open_application('powerpoint')
        except Exception:
            pass
        msg = (
            "✦ Whisper Presentation:\n"
            "Hello everyone! Welcome to Whisper — the Next-Generation Voice & Desktop Companion.\n\n"
            "• Instant Windows & App Control (PowerPoint, Chrome, Code, Terminal, Explorer)\n"
            "• Web Automation & Media Playback (Google Search, YouTube, Spotify)\n"
            "• Smart Video & Audio Editing (Automated pause cuts, filler removal, subtitle burning)\n"
            "• System Commands (Volume control, screenshots, window cleanup)\n\n"
            "Everything you speak, Whisper executes instantly!"
        )
        try:
            import speaker
            speaker.speak("Hello everyone! I am Whisper, your AI desktop companion. I seamlessly control Windows applications, automate web workflows, and edit video content. Let's get started!")
        except Exception:
            pass
        return {'ok': True, 'tool': 'whisper.presentation', 'status': 'success', 'verified': True,
                'data': {'presentation': True, 'message': msg}}

    def command(self, text, activated=True, output=None):
        with self.lock:
            return self._command(text, activated, output)

    def _command(self, text, activated=True, output=None):
        intent, args = parse_command(text, activated=activated)
        direct = {"undo": "video.undo", "approve": "video.approve_all", "clear": "video.clear_edits",
                  "preferences": "memory.get_preferences", "delete_preference": "memory.delete_preference",
                  "open_camera": "camera.open", "open_application": "system.open_application",
                  "open_website": "system.open_website", "open_folder": "system.open_folder",
                  "list_applications": "system.list_installed_apps", "get_active_application": "system.get_active_window",
                  "close_application": "system.close_application", "close_active_window": "system.close_active_window",
                  "system_screenshot": "system.take_screenshot", "system_minimize": "system.minimize_all",
                  "web_search": "system.web_search", "youtube_play": "system.youtube_play"}
        if intent in direct:
            result = self.call(direct[intent], **args)
        elif intent in ('system_volume_up', 'system_volume_down', 'system_mute'):
            action = 'up' if intent == 'system_volume_up' else 'down' if intent == 'system_volume_down' else 'mute'
            result = self.call('system.change_volume', action=action)
        elif intent == 'presentation':
            result = self._handle_presentation()
        elif intent == 'identity':
            msg = "I am Whisper, your AI-powered desktop companion."
            result = {'ok': True, 'tool': 'whisper.identity', 'status': 'success', 'verified': True, 'data': {'message': msg}}
        elif intent == 'system_time':
            import datetime
            now_str = datetime.datetime.now().strftime("%I:%M %p")
            msg = f"The current time is {now_str}."
            result = {'ok': True, 'tool': 'whisper.time', 'status': 'success', 'verified': True, 'data': {'message': msg}}
        elif intent == 'system_date':
            import datetime
            date_str = datetime.datetime.now().strftime("%A, %B %d, %Y")
            msg = f"Today is {date_str}."
            result = {'ok': True, 'tool': 'whisper.date', 'status': 'success', 'verified': True, 'data': {'message': msg}}
        elif intent == 'joke':
            import random
            jokes = [
                "Why do programmers prefer dark mode? Because light attracts bugs!",
                "There are 10 types of people in the world: those who understand binary, and those who don't.",
                "Why was the computer cold? It left its Windows open!"
            ]
            msg = random.choice(jokes)
            result = {'ok': True, 'tool': 'whisper.joke', 'status': 'success', 'verified': True, 'data': {'message': msg}}
        elif intent == 'status_check':
            msg = "I'm running smoothly and ready for your next command!"
            result = {'ok': True, 'tool': 'whisper.status', 'status': 'success', 'verified': True, 'data': {'message': msg}}
        elif intent == 'close_recent':
            result = self.call('system.close_recent', approved=True)
        elif intent in {'fillers', 'speech_cleanup'}:
            operations = []
            if intent == 'speech_cleanup':
                operations.append(self.call('video.detect_pauses'))
            if not operations or operations[-1]['ok']:
                operations.append(self.call('video.detect_fillers'))
            result = {**operations[-1], 'operations':operations,
                      'follow_up':'Review the filler/pauses suggestions and preview their audio before approving. Original media is unchanged.'}
        elif intent == 'clarify_close':
            result = {'ok':False, 'tool':'command.clarify', 'status':'needs_clarification', 'verified':False,
                      'error':{'type':'AmbiguousTarget', 'message':args['reason']}}
        elif intent == 'clarify_recording':
            result = {'ok':False, 'tool':'command.clarify', 'status':'needs_clarification', 'verified':False,
                      'data':{'suggested_command':args['suggested_command']},
                      'error':{'type':'AmbiguousRecordingAction', 'message':args['reason']}}
        elif intent == 'select_video':
            result = self.call('video.inspect', **args) if args.get('source') else {
                'ok': True, 'tool':'video.inspect', 'status':'needs_input', 'verified':False,
                'data':{'choose_source':True, 'message':'Choose a video file.'}}
        elif intent == 'inspect_video':
            result = self.call('video.inspect', source=str(self.source)) if self.source else self.call('video.detect_pauses')
        elif intent == 'help':
            result = {'ok':True, 'tool':'command.help', 'status':'success', 'verified':True,
                'data':{'message':'Try: Chrome khol de; Open Notepad; Open Downloads; Google Photos khol de; '
                    'Select video; pauses hata de; filler words hata de; clean this video; approve cuts; undo; export video; remember my settings. '
                    'Close the apps you opened. Camera: open camera; start/pause/resume/stop recording. '
                    'Press the microphone again to cancel listening.'}}
        elif intent == 'cancel':
            result = {'ok':True, 'tool':'command.cancel', 'status':'cancelled', 'verified':False,
                      'data':{'message':'Command cancelled. No action taken.'}}
        elif intent == "analyse":
            result = self.call("video.detect_pauses", min_pause_seconds=args.get("seconds", self.pause_seconds))
            if result["ok"] and "subtitles" in args:
                self.subtitle_requested = args["subtitles"]
            if result["ok"] and (args.get("keep_last") or args.get("detect_retakes") or args.get("subtitles")):
                operations = [result]
                if not self.segments:
                    operations.append(self.call("video.transcribe"))
                if operations[-1]["ok"] and (args.get("keep_last") or args.get("detect_retakes")):
                    operations.append(self.call("video.detect_retakes"))
                if args.get("subtitles") and self.segments:
                    self.subtitle_requested = True
                result = {**operations[-1], "operations": operations,
                          "follow_up": "Pause/retake decisions require review. Captions use supplied segment/chunk timing."}
        elif intent == "save_preference":
            if "key" in args:
                result = self.call("memory.save_preference", key=args["key"], value=args["value"], approved=True)
            else:
                result = self.call("memory.save_preference", key="pause_threshold", value=args.get("seconds", self.pause_seconds), approved=True)
                if result['ok'] and (args.get('all_settings') or "subtitles" in args or 'same setting' in text.casefold()):
                    result = self.call("memory.save_preference", key="burn_subtitles", value=args.get("subtitles", self.subtitle_requested), approved=True)
        elif intent == "transcribe":
            result = self.call("video.transcribe")
            if result["ok"] and "subtitles" in args:
                self.subtitle_requested = args["subtitles"]
        elif intent == "set_subtitles":
            self.subtitle_requested = args["enabled"]
            result = {"ok": True, "tool": "video.subtitle_settings", "data": {"subtitles": self.subtitle_requested,
                      "message": "Subtitle burning is disabled for future exports. Existing videos are unchanged."}}
        elif intent == "retakes":
            result = self.call("video.detect_retakes")
        elif intent == "export":
            if "subtitles" in args:
                self.subtitle_requested = args["subtitles"]
            result = self.call("video.export", output=output, **args) if output else {
                "ok": True, "tool": "video.export", "status":"needs_input", "verified":False, "data": {"choose_output": True}}
        elif intent.startswith("record_"):
            result = self.call("camera." + {"record_start": "start", "record_stop": "stop", "record_pause": "pause", "record_resume": "resume"}[intent] + "_recording", approved=True)
        elif intent == "preserve_original":
            result = {"ok": True, "tool": "video.policy", "data": {"message": "The original is always preserved. Export creates a separate file."}}
        elif intent == "cut_previous":
            # ponytail: no playback/live recorder clock; ask for explicit boundaries.
            result = {"ok": False, "tool": "video.propose_cut", "error": {"type": "AmbiguousTarget", "message": "No live take boundary is available. Enter source start/end seconds to propose this cut."}}
        else:
            result = {"ok": False, "tool": "command", "error": {"type": "UnknownIntent", "message": args.get("reason", "No supported instruction recognized; no action taken.")}}
            from optional_planner import is_configured, propose_plan
            if is_configured() and activated:
                plan = propose_plan(text, {'source':str(self.source) if self.source else None,
                    'pause_threshold':self.pause_seconds, 'subtitles':self.subtitle_requested})
                result = {'ok':False, 'tool':'planner.propose', 'data':plan,
                    'status':plan['status'], 'verified':False,
                    'error':{'type':'PlanNotExecuted', 'message':plan['message']}}
        normalized = {'analyse':'remove_pauses', 'fillers':'detect_fillers', 'speech_cleanup':'clean_video', 'inspect_video':'analyse_video', 'undo':'undo_edit',
            'retakes':'detect_retakes', 'export':'export_video', 'preferences':'get_preferences',
            'open_camera':'open_application', 'record_start':'start_recording', 'record_pause':'pause_recording',
            'record_resume':'resume_recording', 'record_stop':'stop_recording'}.get(intent, intent)
        target = args.get('application') or args.get('url') or args.get('path') or args.get('source') or (
            'kaat_opened_windows' if intent == 'close_recent' else 'camera' if intent in {'open_camera', 'clarify_recording'} or intent.startswith('record_') else
            'current_video' if result.get('tool', '').startswith('video.') else 'local_preferences' if 'preference' in normalized else None)
        data = result.get('data', {})
        result.setdefault('status', 'success' if result['ok'] else 'failed')
        result.setdefault('verified', intent in {'set_subtitles', 'preserve_original'})
        message = data.get('message') if isinstance(data, dict) else None
        try:
            if result.get('ok') and intent in {'identity', 'system_time', 'system_date', 'joke', 'status_check'}:
                import speaker
                speaker.speak(message or '')
        except Exception:
            pass
        return {'intent':intent, 'interpreted':normalized, 'target':target, 'parameters':args,
                'message':message or result.get('error', {}).get('message') or result['status'], **result}
