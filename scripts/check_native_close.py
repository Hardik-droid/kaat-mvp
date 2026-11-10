"""Native typed open/restart/close and real local MCP checks, scoped to new windows."""
from pathlib import Path
import argparse
import asyncio
import ctypes
import json
import os
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_native_apps import NativeInput
from tools import windows_apps as apps
from memory import Memory


async def mcp_check(output):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    folder=output/'MCP disposable folder';folder.mkdir()
    params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'mcp_server.py')],
        cwd=str(ROOT),env=dict(os.environ,KAAT_DATA_DIR=str(output/'mcp_memory')))
    rows=[]
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            async def call(name,arguments):
                response=await session.call_tool(name,arguments)
                assert not response.isError,response
                result=response.structuredContent or json.loads(response.content[0].text)
                rows.append({'tool':name,'arguments':arguments,'result':result})
                return result
            opened=await call('system.open_folder',{'path':str(folder)})
            assert opened['verified'] and opened['data']['opened_windows'],opened
            windows=opened['data']['opened_windows']
            denied=await call('system.close_recent',{})
            assert denied['status']=='failed' and denied['verified'] is False,denied
            assert all(apps.owned_window_status(row)=='owned' for row in windows)
            closed=await call('system.close_recent',{'approved':True})
            assert closed['verified'] and len(closed['data']['closed'])==len(windows),closed
            assert all(apps.owned_window_status(row)=='gone' for row in windows)
    return {'passed':True,'steps':rows}


def run(output):
    from PIL import ImageGrab
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    native=NativeInput();user,_=apps._native()
    before=[w for w in apps.visible_windows() if w['class'] in {'Chrome_WidgetWin_1','MozillaWindowClass'}
        and any(p['image'] in {'chrome.exe','msedge.exe','firefox.exe'} for p in w['processes'])]
    report={'status':'running','input_method':'real Windows mouse and SendInput keyboard',
        'physical_microphone_tested':False,'read_only_app_probe':True,'prior_browser_windows':before,'steps':[]}
    folder=output/'Native disposable folder';folder.mkdir()
    log=(output/'host.log').open('w',encoding='utf-8');process=None
    def read():
        try:return json.loads((output/'probe.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):return {}
    def start():
        return subprocess.Popen([sys.executable,str(ROOT/'scripts/check_native_apps.py'),'--host','--output',str(output)],
            cwd=ROOT,env=dict(os.environ,PYTHONIOENCODING='utf-8'),stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    def wait(predicate,label,timeout=25):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            if process.poll() is not None:raise RuntimeError('Isolated host exited during '+label)
            state=read()
            if state and predicate(state):return state
            time.sleep(.06)
        raise AssertionError(label+': '+read().get('status','no probe'))
    def click(label):
        state=wait(lambda s:label in s['controls'] and s['controls'][label]['state']!='disabled','button '+label)
        native.click(state['controls'][label]['bounds'])
    def command(text):
        if 'Dismiss' in read().get('controls',{}):click('Dismiss')
        state=read();before_result=state['result_number']
        native.click(state['command']);native.key(0x41,0x11);native.text(text)
        wait(lambda s:s['command_text']==text,'typed command')
        native.key(0x0D)
        state=wait(lambda s:s['result_number']>before_result and not s['busy'],'command '+text)
        row={'typed':text,'result':state['last_result'],'visible_status':state['status'],'visible_execution':state['execution']}
        report['steps'].append(row);print(json.dumps(row),flush=True)
        return state
    def stop_host():
        if process.poll() is None:
            state=read()
            if '\u00d7' in state.get('controls',{}):native.click(state['controls']['\u00d7']['bounds'])
            process.wait(timeout=8)
    try:
        process=start();wait(lambda s:'Allow' in s['controls'],'local consent')
        click('Allow');wait(lambda s:s['device_consent'] is True,'saved consent')
        click('\u2303');wait(lambda s:s['expanded'],'drawer')
        for text in ('Open Google Photos.',f'Open "{folder}"'):
            state=command(text);result=state['last_result']
            assert result['verified'] and result['data']['opened_windows'],result
        journal=Memory(output/'native.sqlite3').opened_windows()
        assert len(journal)==2,journal
        report['persisted_records_before_restart']=journal
        old_pid=read()['pid'];stop_host();(output/'probe.json').unlink()
        process=start();state=wait(lambda s:bool(s.get('controls')),'new actual app process')
        assert state['pid']!=old_pid and state['device_consent'] is True,state
        assert Memory(output/'native.sqlite3').opened_windows()==journal
        click('\u2303');wait(lambda s:s['expanded'],'drawer after restart')
        state=command('Close all those stuff which you have opened recently.')
        result=state['last_result']
        assert result['tool']=='system.close_recent' and result['verified'] is True,result
        assert len(result['data']['closed'])==2 and not result['data']['pending'],result
        assert all(not user.IsWindow(row['hwnd']) for row in journal)
        assert Memory(output/'native.sqlite3').opened_windows()==[]
        report['prior_browser_windows_unchanged']=all(user.IsWindow(w['hwnd']) for w in before)
        assert report['prior_browser_windows_unchanged']
        x,y,w,h=state['bounds'];ImageGrab.grab(bbox=(x,y,x+w,y+h)).save(output/'native_close_result.png')
        stop_host()
        report['mcp']=asyncio.run(asyncio.wait_for(mcp_check(output),timeout=60))
        report['status']='passed'
    except Exception as exc:
        report.update(status='failed',error=str(exc))
        state=read()
        if state.get('bounds'):
            x,y,w,h=state['bounds'];ImageGrab.grab(bbox=(x,y,x+w,y+h)).save(output/'failure_widget.png')
    finally:
        if process and process.poll() is None:
            try:stop_host()
            except subprocess.TimeoutExpired:
                # Cleanup targets only this isolated test interpreter, never a
                # broad KAAT title/process query or the user's monitored widget.
                pid=read().get('pid')
                if pid:
                    try:os.kill(pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                process.terminate();process.wait(timeout=5)
        log.close()
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'error':report.get('error'),'report':str(output/'report.json')}))
    return 0 if report['status']=='passed' else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'test_output/native_close')
    args=parser.parse_args();output=args.output.resolve()
    if output.exists() and any(output.iterdir()):parser.error('Use a fresh evidence directory.')
    output.mkdir(parents=True)
    return run(output)


if __name__=='__main__':raise SystemExit(main())
