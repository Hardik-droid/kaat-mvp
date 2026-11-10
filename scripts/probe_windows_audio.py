"""Bounded local-only Windows input probes. Never save or upload audio."""
from __future__ import annotations

from array import array
import argparse
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def capture_probe(connection, config):
    """All potentially blocking driver calls stay in a disposable child."""
    started = time.monotonic()
    connection.send({'stage': 'initializing', 'actual_pid': os.getpid()})
    try:
        import sounddevice as sd
        apis = sd.query_hostapis()
        api_index = next(i for i, api in enumerate(apis) if api['name'] == config['hostapi'])
        device_id = apis[api_index]['default_input_device']
        device = sd.query_devices(device_id)
        rate = config.get('samplerate') or round(device['default_samplerate'])
        kwargs = {'device': device_id, 'samplerate': rate, 'channels': config['channels'],
                  'dtype': config['dtype']}
        if config.get('auto_convert'):
            kwargs['extra_settings'] = sd.WasapiSettings(auto_convert=True)
        connection.send({'stage': 'opening', 'device': device_id, 'name': device['name'],
                         'rate': rate, 'channels': config['channels'], 'dtype': config['dtype']})
        stream = sd.RawInputStream(**kwargs)
        connection.send({'stage': 'opened', 'elapsed': round(time.monotonic() - started, 3)})
        stream.start()
        connection.send({'stage': 'started', 'elapsed': round(time.monotonic() - started, 3)})
        remaining, samples, energy, peak, overflows = round(rate * .5), 0, 0., 0., 0
        dtype = 'f' if config['dtype'] == 'float32' else 'h'
        divisor = 1. if dtype == 'f' else 32768.
        while remaining:
            frames = min(remaining, max(1, round(rate * .02)))
            data, overflow = stream.read(frames)
            values = array(dtype, bytes(data))
            samples += len(values)
            energy += sum((value / divisor) ** 2 for value in values)
            peak = max(peak, max((abs(value / divisor) for value in values), default=0))
            overflows += int(overflow)
            remaining -= frames
        result = {'stage': 'captured', 'frames': samples // config['channels'],
                  'rms_normalized': math.sqrt(energy / samples) if samples else 0.,
                  'peak_normalized': peak, 'overflows': overflows,
                  'elapsed': round(time.monotonic() - started, 3)}
        connection.send(result)
        stream.stop()
        stream.close()
        connection.send({'stage': 'completed', 'elapsed': round(time.monotonic() - started, 3)})
    except BaseException as error:
        connection.send({'stage': 'failed', 'type': type(error).__name__, 'error': str(error),
                         'elapsed': round(time.monotonic() - started, 3)})
    finally:
        connection.close()


def probe_one(config, timeout=5):
    context = mp.get_context('spawn')
    reader, writer = context.Pipe(duplex=False)
    child = context.Process(target=capture_probe, args=(writer, config))
    started = time.monotonic()
    child.start()
    writer.close()
    report = {'config': config, 'managed_pid': child.pid, 'events': []}
    deadline = started + timeout
    try:
        while time.monotonic() < deadline:
            if reader.poll(.1):
                try:
                    event = reader.recv()
                except EOFError:
                    break
                report['events'].append(event)
                if event['stage'] in ('failed', 'completed'):
                    break
            elif not child.is_alive():
                break
        if child.is_alive() and (not report['events'] or report['events'][-1]['stage'] not in ('completed', 'failed')):
            report['timed_out'] = True
            child.terminate()
        child.join(1)
        if child.is_alive():
            child.kill()
            child.join(2)
        report['child_exited'] = not child.is_alive()
        report['exitcode'] = child.exitcode
        report['seconds'] = round(time.monotonic() - started, 3)
        return report
    finally:
        reader.close()
        if child.is_alive():
            child.terminate()
            child.join(2)
        child.close()


def dshow_probe():
    from engine import _binary
    ffmpeg = _binary('ffmpeg')
    enumerate_run = subprocess.run([ffmpeg, '-hide_banner', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy'],
                                   capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
    text = enumerate_run.stderr.decode('utf-8', errors='replace')
    names = re.findall(r'\] "(.+?)" \(audio\)', text)
    chosen = next((name for name in names if 'microphone' in name.casefold() and 'array' in name.casefold()),
                  next((name for name in names if 'microphone' in name.casefold()), None))
    report = {'backend': 'ffmpeg-directshow', 'audio_devices': names, 'selected_input': chosen}
    if not chosen:
        return {**report, 'error': 'No actual microphone input was enumerated'}
    started = time.monotonic()
    command = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'info', '-f', 'dshow',
               '-i', 'audio=' + chosen, '-t', '0.5', '-ac', '1', '-ar', '16000', '-f', 's16le', 'pipe:1']
    try:
        run = subprocess.run(command, capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
        values = array('h', run.stdout)
        report.update(returncode=run.returncode, frames=len(values),
                      rms_normalized=math.sqrt(sum((value / 32768.) ** 2 for value in values) / len(values)) if values else 0.,
                      stderr=run.stderr.decode('utf-8', errors='replace')[-2500:])
    except subprocess.TimeoutExpired as error:
        report.update(timed_out=True, frames=len(error.stdout or b'') // 2,
                      stderr=(error.stderr or b'').decode('utf-8', errors='replace')[-1500:])
    report['seconds'] = round(time.monotonic() - started, 3)
    return report


def main():
    if os.name != 'nt':
        raise SystemExit('This probe requires Windows')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'test_output/current_audit/backend_probes.json')
    args = parser.parse_args()
    configurations = [
        {'hostapi': 'Windows WASAPI', 'samplerate': 48000, 'channels': 2, 'dtype': 'float32'},
        {'hostapi': 'Windows WASAPI', 'samplerate': 16000, 'channels': 1, 'dtype': 'int16', 'auto_convert': True},
        {'hostapi': 'Windows DirectSound', 'samplerate': 44100, 'channels': 1, 'dtype': 'int16'},
    ]
    report = {'provider_calls': 0, 'audio_saved': False, 'capture_seconds_per_successful_probe': .5,
              'portaudio': [probe_one(config) for config in configurations], 'directshow': dshow_probe()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    mp.freeze_support()
    main()
