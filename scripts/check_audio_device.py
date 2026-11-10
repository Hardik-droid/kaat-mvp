"""Explicit short real microphone diagnostic; never sends audio to an API."""
from pathlib import Path
import argparse
import json
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    from voice import capture_command_audio
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,default=.5)
    parser.add_argument('--output',type=Path,default=ROOT/'test_output/current_audit/audio_device.json')
    args=parser.parse_args()
    phases=[]
    started=time.monotonic()
    result={'provider_called':False,'audio_persisted':False,'requested_seconds':args.seconds}
    def progress(phase,message):
        phases.append({'phase':phase,'message':message,'seconds':round(time.monotonic()-started,3)})
    try:
        pcm=capture_command_audio(args.seconds,on_phase=progress)
        result.update(audio_returned=True,pcm_samples=len(pcm)//2)
    except Exception as exc:
        result.update(audio_returned=False,error=str(exc))
    result.update(phases=phases,elapsed_seconds=round(time.monotonic()-started,3))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
