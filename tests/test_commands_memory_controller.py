"""Natural-language safety, durable preferences, and actual controller exports."""
import json
import subprocess

import pytest

from commands import parse_command
from controller import AgentController
from engine import _binary, duration, source_hash
from memory import Memory


@pytest.mark.parametrize("text,intent,args", [
    ("Kaat, is video mein jitne bhi unnecessary pauses hain wo remove kar de.", "analyse", {}),
    ("Kaat, is video ke pauses hata de.", "analyse", {}),
    ("Kaat, remove pauses longer than 3 seconds.", "analyse", {"seconds": 3.0}),
    ("Kaat, always remove pauses longer than two seconds.", "save_preference", {"seconds": 2.0}),
    ("Kaat, agli baar bhi same settings use karna.", "save_preference", {}),
    ("काट, इस वीडियो के विराम हटा दो", "analyse", {}),
    ("काट, pauses निकाल दो", "analyse", {}),
    ("Kaat, camera open kar aur recording start kar.", "record_start", {}),
    ("Kaat, recording stop kar.", "record_stop", {}),
    ("Kaat, recording pause kar.", "record_pause", {}),
    ("Kaat, recording resume kar.", "record_resume", {}),
    ("Kaat, pichla part hata de.", "cut_previous", {}),
    ("Kaat, ye wala rehne de.", "undo", {}),
    ("Kaat, original bhi save rakhna.", "preserve_original", {}),
    ("Kaat, keep the last take.", "retakes", {"keep_last": True}),
    ("Kaat, approve all cuts.", "approve", {}),
    ("Kaat, confirm.", "approve", {}),
])
def test_hinglish_hindi_and_english_instructions(text, intent, args):
    assert parse_command(text) == (intent, args)


@pytest.mark.parametrize("text", [
    "remove pauses", "undo", "start recording", "approve all cuts", "export video",
    "No Kaat, remove pauses", "Kaatastic remove pauses", "आज pauses remove करेंगे",
])
def test_ambient_content_without_leading_wake_word_never_executes(text):
    assert parse_command(text, activated=False)[0] == "unknown"


def test_leading_wake_word_or_explicit_push_to_talk_activates_commands():
    assert parse_command("Kaat, undo", activated=False) == ("undo", {})
    assert parse_command("undo", activated=True) == ("undo", {})
    assert parse_command("Kaat", activated=False)[0] == "unknown"


@pytest.mark.parametrize("text", [
    "Kaat, do not remove pauses", "Kaat, don't approve cuts", "Kaat, dont export",
    "Kaat, pauses hata mat dena", "Kaat, undo mat karna", "Kaat, pauses remove nahi karna",
    "Kaat, pauses remove nahin karna", "Kaat, never approve these cuts",
    "Kaat, pauses remove नहीं करना", "काट, pauses remove मत करना",
    "Kaat, I will approve these cuts later", "Kaat, how do I export this video?",
    "Kaat, I am talking about how to remove pauses",
    "Hello guys, aaj hum discuss karenge, umm, nahi yaar galat ho gaya",
])
def test_negation_deferred_actions_and_ordinary_conversation_are_not_tools(text):
    assert parse_command(text)[0] == "unknown"


def test_preferences_require_explicit_approval_and_survive_reopen(tmp_path):
    path = tmp_path / "kaat.sqlite3"
    memory = Memory(path)
    for approval in (False, None, 1, "yes"):
        with pytest.raises(ValueError, match="explicit"):
            memory.save("pause_threshold", 3.0, approved=approval)
    assert memory.preferences() == {}
    memory.save("pause_threshold", 3.0, approved=True)
    assert Memory(path).preferences() == {"pause_threshold": 3.0}
    memory.save("pause_threshold", 2.5, approved=True)
    assert Memory(path).preferences() == {"pause_threshold": 2.5}
    assert memory.delete("pause_threshold") == {}
    assert Memory(path).preferences() == {}


@pytest.mark.parametrize("key,value", [
    ("pause_threshold", True), ("pause_threshold", float("nan")),
    ("pause_threshold", float("inf")), ("pause_threshold", 0),
    ("pause_threshold", 21), ("pause_threshold", "2"),
    ("burn_subtitles", "true"), ("arbitrary_key", "arbitrary_value"),
])
def test_invalid_preferences_never_enter_storage(tmp_path, key, value):
    memory = Memory(tmp_path / "memory.sqlite3")
    with pytest.raises(ValueError):
        memory.save(key, value, approved=True)
    assert memory.preferences() == {}


def test_controller_memory_calls_are_structured_and_immediately_applied(tmp_path):
    path = tmp_path / "memory.sqlite3"
    agent = AgentController(path)
    denied = agent.call("memory.save_preference", key="pause_threshold", value=3.0)
    assert not denied["ok"] and denied["error"]["type"] == "ValueError"
    assert agent.state()["pause_threshold"] == 2.0
    accepted = agent.command("Kaat, always remove pauses longer than 3 seconds")
    assert accepted["ok"] and accepted["intent"] == "save_preference"
    assert AgentController(path).state()["pause_threshold"] == 3.0
    deleted = agent.command("Kaat, forget pause settings")
    assert deleted["ok"] and agent.state()["pause_threshold"] == 2.0
    assert AgentController(path).state()["preferences"] == {}
    history = agent.call("memory.get_history")
    assert history["ok"] and any(not item["ok"] for item in history["data"])


def test_voice_export_preserves_subtitle_request_while_choosing_path(tmp_path):
    agent = AgentController(tmp_path / 'memory.sqlite3')
    result = agent.command('Kaat, export with subtitles')
    assert result['ok'] and result['data']['choose_output']
    assert agent.state()['subtitles'] is True


def test_same_settings_request_remembers_subtitles_and_pause_threshold(tmp_path):
    agent = AgentController(tmp_path / 'memory.sqlite3')
    agent.subtitle_requested = True
    result = agent.command('Kaat, agli baar bhi same settings use karna')
    assert result['ok']
    reopened = AgentController(agent.memory.path)
    assert reopened.state()['subtitles'] is True
    assert reopened.state()['preferences'] == {'pause_threshold': 2.0, 'burn_subtitles': True}


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    try:
        ffmpeg = _binary("ffmpeg")
        _binary("ffprobe")
    except RuntimeError as exc:
        pytest.skip(str(exc))
    path = tmp_path_factory.mktemp("controller_media") / "source.mp4"
    subprocess.run([
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=navy:s=160x120:r=30:d=4.5",
        "-f", "lavfi", "-i", r"aevalsrc=if(between(t\,1\,3.5)\,0\,0.15*sin(2*PI*440*t)):s=48000:d=4.5",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    ], capture_output=True, check=True)
    return path


@pytest.fixture
def agent(source, tmp_path):
    controller = AgentController(tmp_path / "memory.sqlite3")
    assert controller.call("video.inspect", source=str(source))["ok"]
    return controller


def test_suggestions_approvals_overlap_restore_and_undo(agent):
    first = agent.call("video.propose_cut", start=.5, end=2.0)["data"]
    second = agent.call("video.propose_cut", start=1.5, end=3.0)["data"]
    assert agent.state()["edited_duration"] == 4.5
    assert agent.call("video.approve_cut", cut_id=first["id"])["ok"]
    assert agent.state()["edited_duration"] == 3.0
    assert agent.call("video.approve_cut", cut_id=second["id"])["ok"]
    assert agent.state()["edited_duration"] == 2.0  # Union: 0.5–3.0, not a double-counted overlap.
    assert agent.call("video.restore_cut", cut_id=second["id"])["ok"]
    assert agent.state()["edited_duration"] == 3.0
    assert agent.call("video.undo")["ok"]
    assert agent.state()["edited_duration"] == 2.0
    assert agent.call("video.clear_edits")["ok"]
    assert agent.state()["cuts"] == []
    assert agent.call("video.undo")["ok"]
    assert [cut["id"] for cut in agent.state()["cuts"]] == [first["id"], second["id"]]
    persisted = agent.memory.session()
    assert persisted["cuts"] == agent.state()["cuts"] and persisted["source"] == str(agent.source)


def test_filler_command_review_state_and_undo_unit_boundary(agent, monkeypatch):
    # Stubbed model boundary: this checks edit safety, not speech recognition.
    monkeypatch.setattr('speech_edits.detect_speech_edits', lambda source: {
        'cuts': [{'start': .5, 'end': .9, 'reason': 'filler_word',
                  'detail': 'unit boundary', 'status': 'suggested'}],
        'requires_review': True})
    result = agent.command('Kaat, filler words hata de')
    assert result['ok'] and result['intent'] == 'fillers'
    cut = agent.state()['cuts'][0]
    assert cut['status'] == 'suggested'
    assert agent.state()['edited_duration'] == agent.state()['original_duration']
    assert agent.command('Kaat, filler words hata de')['ok']
    assert agent.state()['cuts'][0]['id'] == cut['id']
    assert agent.call('video.approve_cut', cut_id=cut['id'])['ok']
    assert agent.command('Kaat, filler words hata de')['ok']
    assert agent.state()['cuts'][0]['status'] == 'approved'
    assert agent.call('video.undo')['ok']
    assert agent.state()['cuts'][0]['status'] == 'suggested'


@pytest.mark.parametrize('text', ['Kaat, do not remove fillers',
    'Kaat, remove fillers and export video', 'Kaat, approve all and remove fillers'])
def test_filler_requests_do_not_bypass_negation_or_approval(text):
    assert parse_command(text)[0] == 'unknown'


def test_combined_cleanup_requires_source_and_reports_real_failure(tmp_path):
    controller = AgentController(tmp_path / 'no_source.sqlite3')
    result = controller.command('Kaat, clean this video')
    assert not result['ok']
    assert len(result['operations']) == 1
    assert result['operations'][0]['tool'] == 'video.detect_pauses'


def test_failed_cut_and_transcript_import_leave_current_state_intact(agent):
    assert agent.call("video.propose_cut", start=1.0, end=2.0)["ok"]
    before = agent.state()["cuts"]
    for start, end in ((-1, 2), (2, 1), (float("nan"), 2), (1, float("inf")), (1, 99)):
        failure = agent.call("video.propose_cut", start=start, end=end)
        assert not failure["ok"] and agent.state()["cuts"] == before
    assert not agent.call("video.approve_cut", cut_id="missing")["ok"]
    assert agent.state()["cuts"] == before
    assert not agent.call("video.import_transcript", segments=[
        {"start": 0, "end": 1, "text": "untimed text", "timing": "invented"}])["ok"]
    assert agent.state()["transcript"] == []


def test_temporary_pause_setting_does_not_silently_persist(agent, tmp_path):
    result = agent.command("Kaat, remove pauses longer than 3 seconds")
    assert result["ok"] and result["intent"] == "analyse"
    assert agent.state()["pause_threshold"] == 3.0
    assert agent.memory.preferences() == {}
    reopened = AgentController(agent.memory.path)
    assert reopened.state()["pause_threshold"] == 2.0


def test_generated_video_controller_export_preserves_source_and_decision_states(agent, source, tmp_path):
    before = source_hash(source)
    result = agent.command("Kaat, is video ke pauses hata de")
    assert result["ok"] and result["intent"] == "analyse"
    cuts = agent.state()["cuts"]
    assert len(cuts) == 1 and cuts[0]["status"] == "suggested"
    assert agent.state()["edited_duration"] == agent.state()["original_duration"]
    assert agent.call("video.approve_cut", cut_id=cuts[0]["id"])["ok"]
    speech = agent.call("video.propose_cut", start=0, end=.5)["data"]
    output = tmp_path / "edited.mp4"
    exported = agent.call("video.export", output=str(output))
    assert exported["ok"], exported
    assert output.exists() and source_hash(source) == before
    assert abs(duration(output) - agent.state()["edited_duration"]) < .12
    assert duration(output) < duration(source) - 1.5
    plan = json.loads(output.with_suffix(".kaat-edl.json").read_text(encoding="utf-8"))
    assert plan["source_sha256"] == before and plan["source_untouched"]
    assert next(c for c in plan["operations"] if c["id"] == speech["id"])["status"] == "suggested"
    assert agent.memory.session()["output"] == str(output.resolve())


def test_controller_guards_original_existing_output_and_existing_sidecar(agent, source, tmp_path):
    before = source_hash(source)
    assert not agent.call("video.export", output=str(source))["ok"]
    assert not agent.call("video.export_edl", output=str(source))["ok"]
    existing = tmp_path / "existing.mp4"
    existing.write_bytes(b"unrelated user data")
    assert not agent.call("video.export", output=str(existing))["ok"]
    assert existing.read_bytes() == b"unrelated user data"
    target = tmp_path / "new.mp4"
    sidecar = target.with_suffix(".kaat-edl.json")
    sidecar.write_text("existing EDL", encoding="utf-8")
    assert not agent.call("video.export", output=str(target))["ok"]
    assert not target.exists() and sidecar.read_text(encoding="utf-8") == "existing EDL"
    assert source_hash(source) == before


def test_failed_export_does_not_leave_partial_artifacts(agent, tmp_path, monkeypatch):
    assert agent.call('video.import_transcript', segments=[
        {'start': 0, 'end': 4.5, 'text': 'Caller supplied caption', 'timing': 'segment'}])['ok']
    def fail(*args, **kwargs):
        raise RuntimeError('Encoder unavailable')
    monkeypatch.setattr('engine.render', fail)
    output = tmp_path / 'failed.mp4'
    result = agent.call('video.export', output=str(output), subtitles=True)
    assert not result['ok']
    assert not output.exists()
    assert not output.with_suffix('.srt').exists()
    assert not output.with_suffix('.kaat-edl.json').exists()


def test_subtitle_export_publishes_remapped_captions_and_video(agent, tmp_path):
    # Mapping is valid for whole retained cues. A cue spanning deleted words
    # requires edited-audio recognition, tested separately at that boundary.
    assert agent.call('video.import_transcript', segments=[
        {'start': 0, 'end': 1, 'text': 'First fully retained cue.', 'timing': 'segment'},
        {'start': 3, 'end': 4.5, 'text': 'Second fully retained cue.', 'timing': 'segment'}])['ok']
    assert agent.call('video.propose_cut', start=1, end=3)['ok']
    assert agent.call('video.approve_all')['ok']
    output = tmp_path / 'captioned.mp4'
    result = agent.command('Kaat, export with subtitles.', output=str(output))
    assert result['ok'], result
    assert output.exists() and output.with_suffix('.kaat-edl.json').exists()
    assert result['data']['caption_source'] == 'source_timestamps'
    srt = output.with_suffix('.srt').read_text(encoding='utf-8')
    assert '00:00:00,000 --> 00:00:01,000' in srt and 'First fully retained cue.' in srt
    assert '00:00:01,000 --> 00:00:02,500' in srt
    assert 'Second fully retained cue.' in srt
    assert abs(duration(output) - 2.5) < .12
