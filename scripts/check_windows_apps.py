"""Opt-in real Windows launch checks; opens actual apps/websites and writes evidence."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import json
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import windows_apps


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='test_output/emergency_apps/report.json')
    parser.add_argument('--controller',action='store_true',help='Route English/Hinglish commands through AgentController')
    args=parser.parse_args()
    commands=[('Open Notepad.','application','notepad'),('Chrome khol de.','application','chrome'),
        ('Open Calculator.','application','calculator'),('Open File Explorer.','application','explorer'),
        ('Open the Camera app.','application','camera'),('Mera Downloads folder khol.','folder','downloads'),
        ('Google Photos khol de.','website','https://photos.google.com/'),('Mujhe YouTube khol ke dikha.','website','https://www.youtube.com/'),
        ('Open Notepad.','application','notepad'),('Open KAAT nonexistent application 192859.','missing','KAAT nonexistent application 192859')]
    controller=None
    if args.controller:
        from controller import AgentController
        controller=AgentController()
    rows=[]
    for command,kind,target in commands:
        started=time.monotonic()
        try:
            if controller:result=controller.command(command)
            elif kind in ('application','missing'):result=windows_apps.open_application(target)
            elif kind=='website':result=windows_apps.open_website(target)
            else:result=windows_apps.open_folder(target)
            outcome=result.get('data',result)
            verified=outcome.get('verified',False)
            passed=(result.get('status')=='failed' and result.get('error',{}).get('type')=='FileNotFoundError') if kind=='missing' else verified
        except Exception as exc:
            result={'error':str(exc),'type':type(exc).__name__,'verified':False}
            passed=kind=='missing' and isinstance(exc,FileNotFoundError)
        row={'command':command,'kind':kind,'target':target,'passed':passed,
             'elapsed_seconds':round(time.monotonic()-started,3),'result':result}
        rows.append(row)
        print(json.dumps(row,ensure_ascii=True),flush=True)
    report={'time_utc':datetime.now(timezone.utc).isoformat(),'integration':'real Windows, no mocks',
        'route':'controller' if controller else 'Windows tools','passed':all(row['passed'] for row in rows),'checks':rows}
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,ensure_ascii=True),encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
