"""Human-in-the-loop microphone acceptance: user clicks Speak and speaks.

Fixture selection is setup. The microphone, provider and command execution are
never replaced. This script does not activate the microphone automatically.
It records observations only; a failed/absent command is never marked passed.
"""
from pathlib import Path
import argparse
import json
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'test_output/practical_speech/human_hinglish_with_pause.mp4')
    parser.add_argument('--output', type=Path, default=ROOT/'test_output/live_microphone')
    args = parser.parse_args()
    args.source = args.source.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=True)
    report_file = args.output/'report.json'
    if report_file.exists():
        parser.error('Choose a fresh output directory to preserve earlier observations')
    from dotenv import load_dotenv
    from app import Kaat
    from engine import source_hash
    load_dotenv(ROOT/'.env')
    app = Kaat(memory_path=args.output/'session.sqlite3')
    started = time.monotonic()
    report = {'status':'awaiting_user', 'source':str(args.source), 'source_sha256_before':source_hash(args.source),
              'source_selection':'fixture setup through the real inspect tool',
              'microphone_activated_automatically':False, 'provider_replaced':False,
              'phases':[], 'requested_command':'Kaat, is video ke pauses hata de',
              'capture_observed':False, 'user_confirmed_transcript':False, 'max_input_level_percent':0}
    last_phase = 'idle'
    last_result = None
    last_published = None
    def publish():
        nonlocal last_published
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if payload != last_published:
            report_file.write_text(payload, encoding='utf-8')
            last_published = payload
    def watch():
        nonlocal last_phase, last_result
        if app.closed:
            return
        phase = app.voice_phase
        if phase != last_phase:
            report['phases'].append({'phase':phase, 'seconds':round(time.monotonic()-started, 3), 'microphone_label':app.mic.get()})
            last_phase = phase
            if phase == 'preparing':
                report['status'] = 'opening_microphone'
                report['capture_observed'] = False
                report['max_input_level_percent'] = 0
                report.pop('actual_result', None)
            if phase == 'listening':
                report['capture_observed'] = True
                report['status'] = 'capturing'
            elif phase == 'transcribing':
                report['status'] = 'awaiting_actual_provider'
        report['current_ui_status'] = app.status.get()
        report['microphone_label'] = app.mic.get()
        level = re.search(r'input level ([0-9.]+)%', app.mic.get())
        if level:
            report['max_input_level_percent'] = max(report['max_input_level_percent'], float(level[1]))
        report['heard_label'] = app.heard.get()
        result = app.last_result
        if result and result is not last_result and not app.busy:
            last_result = result
            if 'heard' in result or report['capture_observed'] or any(event['phase']=='preparing' for event in report['phases']):
                report['actual_result'] = result
                report['source_sha256_after'] = source_hash(args.source)
                report['source_unchanged'] = report['source_sha256_after'] == report['source_sha256_before']
                report['actual_cut_decisions'] = app.cached['cuts']
                report['status'] = 'command_executed_pending_user_confirmation' if (
                    report['capture_observed'] and result.get('ok') and result.get('heard') and report['source_unchanged']) else 'failed'
        publish()
        app.after(100, watch)
    publish()
    app.after(100, lambda: app.submit('video.inspect', source=str(args.source)))
    app.after(200, watch)
    print('Live window ready. User must click Speak, wait for LISTENING, then speak. No automatic capture.', flush=True)
    app.mainloop()


if __name__ == '__main__':
    main()
