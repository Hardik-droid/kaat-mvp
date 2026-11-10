"""Protocol integration checks against a real local stdio server process."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from engine import _binary, duration


ROOT = Path(__file__).resolve().parents[1]


def _sample(path):
    try:
        ffmpeg = _binary("ffmpeg")
        _binary("ffprobe")
    except RuntimeError as error:
        pytest.skip(str(error))
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
               "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=25:d=4.5",
               "-f", "lavfi", "-i",
               r"aevalsrc=if(lt(t\,1)\,0.1*sin(2*PI*440*t)\,if(gt(t\,3.5)\,0.1*sin(2*PI*440*t)\,0)):d=4.5:s=16000",
               "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)]
    subprocess.run(command, check=True, capture_output=True, timeout=30)


def test_stdio_real_video_workflow(tmp_path):
    pytest.importorskip("mcp")
    source, output = tmp_path / "source.mp4", tmp_path / "edited.mp4"
    _sample(source)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    async def workflow():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        environment = dict(os.environ, KAAT_DATA_DIR=str(tmp_path / "memory"))
        params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server.py")],
                                       cwd=str(ROOT), env=environment)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                available = {tool.name for tool in (await session.list_tools()).tools}
                assert {"video.inspect", "video.detect_pauses", "video.approve_cut", "video.undo",
                        "video.export", "memory.save_preference", "camera.start_recording"} <= available

                async def call(name, **args):
                    response = await session.call_tool(name, args)
                    assert not response.isError, response
                    data = response.structuredContent
                    if data is None:
                        data = json.loads(response.content[0].text)
                    return data

                failure = await call("video.detect_pauses")
                assert failure["ok"] is False
                assert "Select a video" in failure["error"]["message"]
                assert (await call("video.inspect", source=str(source)))["ok"]
                rejected = await call("memory.save_preference", key="pause_threshold", value=2.0)
                assert rejected["ok"] is False
                accepted = await call("memory.save_preference", key="pause_threshold", value=2.0, approved=True)
                assert accepted["ok"] is True
                assert (await call("memory.get_preferences"))["data"]["pause_threshold"] == 2.0

                pauses = await call("video.detect_pauses")
                assert pauses["ok"] and pauses["data"]["cuts"]
                cuts = pauses["data"]["cuts"]
                assert all(c["status"] == "suggested" for c in cuts)
                state = (await call("session.state"))["data"]
                assert state["edited_duration"] == pytest.approx(state["original_duration"], abs=.01)

                cut_id = cuts[0]["id"]
                assert (await call("video.approve_cut", cut_id=cut_id))["ok"]
                state = (await call("session.state"))["data"]
                assert state["edited_duration"] < state["original_duration"] - 1.5
                assert (await call("video.undo"))["ok"]
                assert (await call("session.state"))["data"]["cuts"][0]["status"] == "suggested"
                assert (await call("video.approve_cut", cut_id=cut_id))["ok"]
                exported = await call("video.export", output=str(output))
                assert exported["ok"], exported
                assert output.is_file()
                assert (await call("video.export", output=str(source)))["ok"] is False
                assert (await call("system.open_application", application="powershell -Command whoami"))["ok"] is False
                assert (await call("camera.start_recording"))["ok"] is False
                assert (await call("memory.delete_preference", key="pause_threshold"))["ok"]
                assert "pause_threshold" not in (await call("memory.get_preferences"))["data"]

    asyncio.run(asyncio.wait_for(workflow(), timeout=60))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    assert duration(output) < duration(source) - 1.5
    plan = json.loads(output.with_suffix(".kaat-edl.json").read_text(encoding="utf-8"))
    assert plan["source_untouched"] is True


def test_system_allowlist_and_active_window():
    import system_tools
    supported = system_tools.list_supported_apps()
    assert supported["arbitrary_shell"] is False
    assert supported["recording_supported"] is (os.name == 'nt')
    assert supported['recording_backend'] == 'Windows Camera UI Automation'
    with pytest.raises((ValueError, RuntimeError)):
        system_tools.open_application("cmd.exe /c anything")
    if os.name == "nt":
        window = system_tools.get_active_window()
        assert isinstance(window["title"], str)
        assert "process_id" in window
