"""Exercise the real Windows overlay and capture its visible state.

Run after scripts/demo.py: python scripts/check_desktop.py
Uses generated media only; never activates the microphone or provider API.
"""
from pathlib import Path
import argparse
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT / 'demo_output/source_synthetic.mp4')
    parser.add_argument('--output', type=Path, default=ROOT / 'test_output/desktop')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    from app import Kaat
    from engine import source_hash
    from PIL import ImageGrab

    app = Kaat(memory_path=args.output / 'desktop.sqlite3')
    original = source_hash(args.source)
    def finish():
        deadline = time.monotonic() + 60
        while app.busy:
            app.update()
            if time.monotonic() > deadline:
                raise TimeoutError('Desktop task exceeded 60 seconds')
            time.sleep(.02)
        app.update()
        if app.status.get().startswith('Error:'):
            raise AssertionError(app.status.get())

    try:
        assert not app.expanded and not app.details.winfo_ismapped()
        app.toggle()
        app.update()
        app.submit('video.inspect', source=str(args.source.resolve()))
        finish()
        app.submit('video.detect_pauses')
        finish()
        assert app.cut_list.size() > 0
        assert app.cached['edited_duration'] == app.cached['original_duration']
        app.submit('video.approve_all')
        finish()
        assert app.cached['edited_duration'] < app.cached['original_duration']
        app.submit('video.undo')
        finish()
        assert app.cached['edited_duration'] == app.cached['original_duration']
        app.submit('video.approve_all')
        finish()
        app.submit('memory.save_preference', key='pause_threshold', value=3.0, approved=True)
        finish()
        app.toggle()
        app.update()
        assert not app.details.winfo_ismapped()
        app.toggle()
        app.update()
        bounds = (app.winfo_rootx(), app.winfo_rooty(), app.winfo_rootx()+app.winfo_width(), app.winfo_rooty()+app.winfo_height())
        ImageGrab.grab(bbox=bounds).save(args.output / 'overlay.png')
        # Check the export footer remains visible at the actual desktop resolution.
        assert app.details.winfo_y() + app.details.winfo_height() <= app.winfo_height()
        output = args.output / 'desktop_edit.mp4'
        app.submit('video.export', output=str(output.resolve()), subtitles=False)
        finish()
        assert output.is_file() and source_hash(args.source) == original
        report = {'overlay_launch': True, 'desktop_inspect_detect_approve_undo_export': True,
                  'collapse_expand': True, 'source_hash_unchanged': True,
                  'original_seconds': app.cached['original_duration'], 'edited_seconds': app.cached['edited_duration'],
                  'screenshot': str((args.output / 'overlay.png').resolve()), 'live_prisma_tested': False}
        (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
    finally:
        if app.busy:
            finish()
        app.close()


if __name__ == '__main__':
    main()
