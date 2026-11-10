"""Local stdio MCP adapter. Desktop and MCP execute the same controller tools."""
from __future__ import annotations

import atexit
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).with_name(".env"))
mcp = FastMCP("KAAT", instructions="Inspect a video, propose cuts, review and approve specific cut IDs, then export to a fresh filename. Source media is never overwritten. One editing session per server process.")
_controller = None


def _call(tool: str, **arguments) -> dict:
    global _controller
    if _controller is None:
        from controller import AgentController
        data_dir = os.environ.get("KAAT_DATA_DIR")
        memory_path = Path(data_dir).expanduser() / "kaat.sqlite3" if data_dir else None
        _controller = AgentController(memory_path=memory_path)
        atexit.register(_controller.close)
    return _controller.call(tool, **arguments)


@mcp.tool(name="video.inspect")
def inspect_video(source: str = "", path: str = "") -> dict:
    """Select an existing video and inspect actual media streams and duration."""
    return _call("video.inspect", source=source or path)


@mcp.tool(name="video.detect_pauses")
def detect_pauses() -> dict:
    """Suggest padded silence cuts on the selected video; never approve them."""
    return _call("video.detect_pauses")


@mcp.tool(name="video.detect_retakes")
def detect_retakes() -> dict:
    """Suggest repeated takes from the current verified transcript for review."""
    return _call("video.detect_retakes")


@mcp.tool(name="video.detect_fillers")
def detect_fillers() -> dict:
    """Propose filler cuts using a local secondary speech model's estimated word times. Review and approval required."""
    return _call('video.detect_fillers')


@mcp.tool(name="video.transcribe")
def transcribe_video() -> dict:
    """Send selected video's audio to Gnani Prisma; requires GNANI_API_KEY."""
    return _call("video.transcribe")


@mcp.tool(name="video.import_transcript")
def import_transcript(segments: list[dict]) -> dict:
    """Import caller-verified segments with start/end/text/timing; no automatic alignment."""
    return _call("video.import_transcript", segments=segments)


@mcp.tool(name="video.propose_cut")
def propose_cut(start: float, end: float, reason: str = "user_request") -> dict:
    """Propose a reversible interval on the original timeline, in seconds."""
    return _call("video.propose_cut", start=start, end=end, reason=reason)


@mcp.tool(name="video.approve_cut")
def approve_cut(cut_id: str) -> dict:
    """Approve a reviewed cut ID; only approved cuts affect export."""
    return _call("video.approve_cut", cut_id=cut_id)


@mcp.tool(name="video.restore_cut")
def restore_cut(cut_id: str) -> dict:
    """Restore the media covered by one proposed or approved cut."""
    return _call("video.restore_cut", cut_id=cut_id)


@mcp.tool(name="video.approve_all")
def approve_all() -> dict:
    """Approve all displayed suggestions only when the user explicitly requests this."""
    return _call("video.approve_all")


@mcp.tool(name="video.undo")
def undo() -> dict:
    """Restore the previous edit-decision state."""
    return _call("video.undo")


@mcp.tool(name="video.clear_edits")
def clear_edits() -> dict:
    """Clear all edit decisions without touching source media; undo is available."""
    return _call("video.clear_edits")


@mcp.tool(name="video.export")
def export_video(output: str, subtitles: bool = False) -> dict:
    """Render approved edits to a fresh MP4 plus EDL; optionally burn transcript captions."""
    return _call("video.export", output=output, subtitles=subtitles)


@mcp.tool(name="video.export_edl")
def export_edl(output: str) -> dict:
    """Save suggested and approved decisions as JSON without rendering video."""
    return _call("video.export_edl", output=output)


@mcp.tool(name="session.state")
def session_state() -> dict:
    """Inspect selected source, decisions, durations, preferences and recent tasks."""
    return _call("session.state")


@mcp.tool(name="memory.save_preference")
def save_preference(key: str, value: Any, approved: bool = False) -> dict:
    """Persist a preference only with the user's explicit approval."""
    return _call("memory.save_preference", key=key, value=value, approved=approved)


@mcp.tool(name="memory.get_preferences")
def get_preferences() -> dict:
    """Read locally stored preferences."""
    return _call("memory.get_preferences")


@mcp.tool(name="memory.update_preference")
def update_preference(key: str, value: Any, approved: bool = False) -> dict:
    """Update a saved preference only with the user's explicit approval."""
    return _call("memory.update_preference", key=key, value=value, approved=approved)


@mcp.tool(name="memory.delete_preference")
def delete_preference(key: str) -> dict:
    """Delete one local preference."""
    return _call("memory.delete_preference", key=key)


@mcp.tool(name="memory.get_history")
def get_history() -> dict:
    """Inspect recent local task outcomes without storing microphone audio."""
    return _call("memory.get_history")


@mcp.tool(name="system.list_supported_apps")
def list_supported_apps() -> dict:
    """List the exact allowlisted Windows application adapters."""
    return _call("system.list_supported_apps")


@mcp.tool(name="system.open_application")
def open_application(application: str = "", name: str = "") -> dict:
    """Launch a trusted Windows app by exact name/alias and verify its visible window."""
    return _call("system.open_application", application=application or name)


@mcp.tool(name="system.open_website")
def open_website(url: str) -> dict:
    """Open HTTP(S) in the default browser; verify the visible browser address when supported."""
    return _call("system.open_website", url=url)


@mcp.tool(name="system.open_folder")
def open_folder(path: str) -> dict:
    """Open an existing local folder or known folder alias and verify Explorer's path."""
    return _call("system.open_folder", path=path)


@mcp.tool(name="system.list_installed_apps")
def list_installed_apps() -> dict:
    """Read the actual Windows Start application registry."""
    return _call("system.list_installed_apps")


@mcp.tool(name="camera.open")
def open_camera() -> dict:
    """Launch the installed Windows Camera and verify its window; does not start recording."""
    return _call("camera.open")


@mcp.tool(name="system.get_active_window")
def get_active_window() -> dict:
    """Read the actual Windows foreground window title and process ID."""
    return _call("system.get_active_window")


@mcp.tool(name="system.close_recent")
def close_recent(approved: bool = False) -> dict:
    """Gracefully close only tracked KAAT-created windows on explicit user request; never force-close or dismiss save prompts."""
    return _call('system.close_recent', approved=approved)


@mcp.tool(name="camera.list_devices")
def list_camera_devices() -> dict:
    """Enumerate real DirectShow devices; this alone does not prove capture access."""
    return _call("camera.list_devices")


@mcp.tool(name="camera.start_recording")
def start_recording(approved: bool = False) -> dict:
    """Start local Windows Camera recording only on an explicit user instruction."""
    return _call("camera.start_recording", approved=approved)


@mcp.tool(name="camera.pause_recording")
def pause_recording(approved: bool = False) -> dict:
    """Pause recording and verify the actual local Camera UI state."""
    return _call("camera.pause_recording", approved=approved)


@mcp.tool(name="camera.resume_recording")
def resume_recording(approved: bool = False) -> dict:
    """Resume recording and verify the actual local Camera UI state."""
    return _call("camera.resume_recording", approved=approved)


@mcp.tool(name="camera.stop_recording")
def stop_recording(approved: bool = False) -> dict:
    """Stop local recording, verify Camera UI, and find our saved MP4 when possible."""
    return _call("camera.stop_recording", approved=approved)


@mcp.tool(name="system_open_application")
def system_open_application(name: str = "", application: str = "") -> dict:
    """Launch a trusted Windows app by exact name/alias and verify its visible window."""
    return _call("system.open_application", application=name or application)


@mcp.tool(name="system_open_website")
def system_open_website(url: str) -> dict:
    """Open HTTP(S) in the default browser; verify the visible browser window."""
    return _call("system.open_website", url=url)


@mcp.tool(name="system_open_folder")
def system_open_folder(path: str) -> dict:
    """Open an existing local folder or known folder alias and verify Explorer."""
    return _call("system.open_folder", path=path)


@mcp.tool(name="video_inspect")
def video_inspect(path: str = "", source: str = "") -> dict:
    """Select an existing video and inspect actual media streams and duration."""
    return _call("video.inspect", source=path or source)


@mcp.tool(name="video_detect_pauses")
def video_detect_pauses(path: str = "") -> dict:
    """Suggest padded silence cuts on the selected video."""
    if path:
        _call("video.inspect", source=path)
    return _call("video.detect_pauses")


@mcp.tool(name="video_propose_cuts")
def video_propose_cuts(path: str = "") -> dict:
    """Suggest padded silence cuts on the selected video."""
    if path:
        _call("video.inspect", source=path)
    return _call("video.detect_pauses")


@mcp.tool(name="video_export")
def video_export(output: str, path: str = "", subtitles: bool = False) -> dict:
    """Render approved edits to a fresh MP4 plus EDL."""
    if path:
        _call("video.inspect", source=path)
    return _call("video.export", output=output, subtitles=subtitles)


@mcp.tool(name="memory_save_preference")
def memory_save_preference(key: str, value: Any, approved: bool = True) -> dict:
    """Persist a preference in SQLite."""
    return _call("memory.save_preference", key=key, value=value, approved=approved)


@mcp.tool(name="memory_get_preferences")
def memory_get_preferences() -> dict:
    """Read locally stored preferences."""
    return _call("memory.get_preferences")


if __name__ == "__main__":
    mcp.run(transport="stdio")
