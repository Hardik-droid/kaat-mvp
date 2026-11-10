"""Real disposable-window ownership and graceful close check; preserves prior windows."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import windows_apps as apps


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'test_output/owned_windows')
    parser.add_argument('--close-records',type=Path)
    args=parser.parse_args();output=args.output.resolve()
    if args.close_records:
        rows=json.loads(args.close_records.read_text(encoding='utf-8'))
        result=apps.close_opened_windows(rows)
        (output/'separate_process_close.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        return 0 if result['verified'] else 1
    if output.exists() and any(output.iterdir()):parser.error('Use a fresh evidence directory.')
    output.mkdir(parents=True)
    folder=output/'disposable folder';folder.mkdir()
    before=[w for w in apps.visible_windows() if any(p['image'] in
        {'notepad.exe','chrome.exe','msedge.exe','firefox.exe','explorer.exe'} for p in w['processes'])
        and w['class'] in {'Notepad','Chrome_WidgetWin_1','MozillaWindowClass','CabinetWClass'}]
    report={'status':'running','prior_windows':before,'steps':[],'opened_windows':[]}
    try:
        operations=[('notepad',lambda:apps.open_application('notepad')),
            ('folder',lambda:apps.open_folder(folder)),
            ('website',lambda:apps.open_website('https://example.com/?kaat_close_check='+uuid.uuid4().hex))]
        for name,operation in operations:
            result=operation()
            report['steps'].append({'name':name,'result':result})
            report['opened_windows'].extend(result.get('opened_windows',[]))
            assert result['verified'],result
            assert result['opened_windows'],name+' did not create a trackable new window'
            assert all(apps.owned_window_status(row)=='owned' for row in result['opened_windows'])
        assert not ({w['hwnd'] for w in before}&{w['hwnd'] for w in report['opened_windows']})
        records=output/'records.json'
        records.write_text(json.dumps(report['opened_windows'],indent=2),encoding='utf-8')
        process=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--close-records',str(records),'--output',str(output)],
            cwd=ROOT,capture_output=True,text=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
        result=json.loads((output/'separate_process_close.json').read_text(encoding='utf-8'))
        report['close']=result
        assert process.returncode==0 and result['verified'],result
        assert len(result['closed'])==len(report['opened_windows'])
        user,_=apps._native()
        report['prior_windows_still_open']=all(user.IsWindow(w['hwnd']) for w in before)
        assert report['prior_windows_still_open'],'A prior target window disappeared during the check'
        report['stale_records']=apps.close_opened_windows(report['opened_windows'])
        assert len(report['stale_records']['already_closed'])==len(report['opened_windows'])
        report['status']='passed'
    except Exception as exc:
        report.update(status='failed',error=str(exc))
        # Only these newly tagged disposable windows are eligible for cleanup.
        # This remains normal WM_CLOSE and never dismisses an application prompt.
        if report['opened_windows']:report['cleanup']=apps.close_opened_windows(report['opened_windows'])
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'error':report.get('error'),
        'new_windows':len(report['opened_windows']),'prior_windows':len(before),'report':str(output/'report.json')}))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
