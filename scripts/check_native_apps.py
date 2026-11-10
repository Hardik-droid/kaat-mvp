"""Real Windows mouse/keyboard -> KAAT typed commands -> observed OS targets.

The host adds only a read-only probe. The driver never calls a controller,
widget.invoke(), command callback, or fabricated success. No microphone capture.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

COMMANDS=[
    ('Kaat, open Chrome.','chrome'),('Open Notepad.','notepad'),
    ('Open Calculator.','calculator'),('Open File Explorer.','explorer'),
    ('Open the Camera app.','camera'),('Open Google Photos.','https://photos.google.com/'),
    ('Open YouTube.','https://www.youtube.com/'),('Open my Downloads folder.','downloads'),
    ('Kaat, Chrome khol de.','chrome'),('Calculator kholo.','calculator'),
    ('Camera open kar.','camera'),('Mera Downloads folder khol.','downloads'),
    ('Google Photos khol de.','https://photos.google.com/'),('Notepad chala de.','notepad'),
    ('Chrome open karna.','chrome'),('Mujhe YouTube khol ke dikha.','https://www.youtube.com/'),
    ('Open KAAT nonexistent application 192859.','missing'),
]


def host(output):
    from dotenv import load_dotenv
    from app import Kaat
    load_dotenv(ROOT/'.env')
    app=Kaat(memory_path=output/'native.sqlite3')
    sequence=0
    result_number=0
    previous_result=None

    def bounds(widget):
        return [widget.winfo_rootx(),widget.winfo_rooty(),widget.winfo_width(),widget.winfo_height()]

    def observe():
        nonlocal sequence,result_number,previous_result
        sequence+=1
        if app.last_result is not previous_result:
            result_number+=1
            previous_result=app.last_result
        controls={};tabs={}
        def walk(widget):
            if not widget.winfo_ismapped():return
            if widget.winfo_class()=='Button':
                controls[widget.cget('text')]={'bounds':bounds(widget),'state':widget.cget('state')}
            if widget.winfo_class()=='TNotebook':
                groups={}
                for x in range(0,widget.winfo_width(),4):
                    try:groups.setdefault(widget.index(f'@{x},12'),[]).append(x)
                    except Exception:pass
                for index,xs in groups.items():
                    tabs[widget.tab(index,'text')]=[widget.winfo_rootx()+min(xs),widget.winfo_rooty(),max(xs)-min(xs),24]
            for child in widget.winfo_children():walk(child)
        walk(app)
        state={'sequence':sequence,'pid':os.getpid(),'busy':app.busy,'status':app.status.get(),
            'expanded':app.expanded,'bounds':bounds(app),'controls':controls,'tabs':tabs,
            'command':bounds(app.command_entry),'command_text':app.command_entry.get(),
            'heard':app.heard.get(),'execution':app.execution.get(),'result_number':result_number,
            'last_result':app.last_result,'device_consent':app.device_consent,
            'permission_prompt_open':app.permission_prompt_open}
        temporary=output/'probe.tmp'
        temporary.write_text(json.dumps(state),encoding='utf-8')
        try:temporary.replace(output/'probe.json')
        except PermissionError:pass  # Reader can briefly hold the snapshot on Windows.
        app.after(60,observe)
    app.after(150,observe)
    app.mainloop()


class NativeInput:
    """Same SendInput/physical mouse path used by check_native_workflow.py."""
    def __init__(self):
        class Keyboard(ctypes.Structure):
            _fields_=[('vk',wintypes.WORD),('scan',wintypes.WORD),('flags',wintypes.DWORD),('time',wintypes.DWORD),('extra',ctypes.c_size_t)]
        class Mouse(ctypes.Structure):
            _fields_=[('x',wintypes.LONG),('y',wintypes.LONG),('data',wintypes.DWORD),('flags',wintypes.DWORD),('time',wintypes.DWORD),('extra',ctypes.c_size_t)]
        class Payload(ctypes.Union):
            _fields_=[('keyboard',Keyboard),('mouse',Mouse)]
        class Input(ctypes.Structure):
            _fields_=[('kind',wintypes.DWORD),('payload',Payload)]
        self.Keyboard,self.Payload,self.Input=Keyboard,Payload,Input
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.user.SendInput.argtypes=[wintypes.UINT,ctypes.POINTER(Input),ctypes.c_int]

    def send(self,vk=0,scan=0,flags=0):
        event=self.Input(kind=1,payload=self.Payload(keyboard=self.Keyboard(vk,scan,flags,0,0)))
        if self.user.SendInput(1,ctypes.byref(event),ctypes.sizeof(event))!=1:
            raise RuntimeError('Windows refused keyboard input')

    def key(self,vk,modifier=None):
        if modifier:self.send(modifier)
        self.send(vk);self.send(vk,flags=2)
        if modifier:self.send(modifier,flags=2)

    def text(self,value):
        raw=value.encode('utf-16-le')
        for index in range(0,len(raw),2):
            code=int.from_bytes(raw[index:index+2],'little')
            self.send(scan=code,flags=4);self.send(scan=code,flags=6)

    def click(self,bounds):
        x,y,w,h=bounds
        if w<16 or h<16:raise AssertionError(f'Control is clipped and not practically clickable: {w}x{h}')
        self.user.SetCursorPos(int(x+w/2),int(y+h/2))
        time.sleep(.07)
        self.user.mouse_event(2,0,0,0,0)
        time.sleep(.04)
        self.user.mouse_event(4,0,0,0,0)
        time.sleep(.12)


def drive(output,layout_only=False):
    if os.name!='nt':raise RuntimeError('Requires an interactive Windows desktop')
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    native=NativeInput()
    from PIL import ImageGrab
    report={'time_utc':datetime.now(timezone.utc).isoformat(),'status':'running',
        'input_method':'real Windows mouse and SendInput keyboard',
        'read_only_probe':True,'controller_or_widget_action_shortcuts':False,
        'physical_microphone_tested':False,'steps':[]}
    log=(output/'host.log').open('w',encoding='utf-8')
    process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--host','--output',str(output)],
        cwd=ROOT,env=dict(os.environ,PYTHONIOENCODING='utf-8'),stdout=log,stderr=log,
        creationflags=subprocess.CREATE_NO_WINDOW)

    def read():
        try:return json.loads((output/'probe.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):return {}

    def wait(predicate,label,timeout=25):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError('App exited during '+label+'; inspect host.log')
            state=read()
            if state and predicate(state):return state
            time.sleep(.06)
        raise AssertionError(label+': '+read().get('status','no probe'))

    def click(label):
        state=wait(lambda s:label in s['controls'] and s['controls'][label]['state']!='disabled','button '+label)
        native.click(state['controls'][label]['bounds'])

    def capture(name,state):
        x,y,w,h=state['bounds']
        ImageGrab.grab(bbox=(x,y,x+w,y+h)).save(output/name)

    try:
        state=wait(lambda s:s.get('permission_prompt_open') and 'Allow' in s['controls'],'real local permission popup')
        click('Allow')
        wait(lambda s:s['device_consent'] is True and not s['permission_prompt_open'],'Allow choice')
        persisted=json.loads((output/'desktop_permissions.json').read_text(encoding='utf-8'))
        assert persisted=={'version':1,'devices':True},persisted
        report['permission']={'actual_allow_click':True,'saved_locally':True}
        click('\u2303')
        wait(lambda s:s['expanded'],'expanded controls')
        for index,(command,target) in enumerate([] if layout_only else COMMANDS):
            state=read()
            if 'Dismiss' in state['controls']:click('Dismiss')
            state=read();before_result=state['result_number'];before_sequence=state['sequence']
            native.click(state['command'])
            native.key(0x41,0x11);native.text(command)
            wait(lambda s:s['command_text']==command,'real text entry '+command)
            started=time.monotonic();native.key(0x0D)
            state=wait(lambda s:s['result_number']>before_result and not s['busy'],'executed '+command)
            result=state['last_result']
            expected_failure=target=='missing'
            if expected_failure:
                passed=result.get('status')=='failed' and result.get('verified') is False and result.get('error',{}).get('type')=='FileNotFoundError'
            else:
                passed=(result.get('status')=='success' and result.get('verified') is True
                    and result.get('target')==target and 'VERIFIED' in state['execution'])
                evidence=result.get('data',{})
                if result.get('tool') in ('system.open_application','camera.open'):
                    passed=passed and bool(evidence.get('windows')) and all(item.get('hwnd') for item in evidence['windows'])
                else:passed=passed and bool(evidence.get('evidence'))
            row={'command':command,'expected_target':target,'passed':bool(passed),
                'elapsed_seconds':round(time.monotonic()-started,3),
                'ui_heartbeat_ticks':state['sequence']-before_sequence,'visible_heard':state['heard'],
                'visible_execution':state['execution'],'visible_status':state['status'],'result':result}
            report['steps'].append(row)
            print(json.dumps(row),flush=True)
            if not passed:raise AssertionError('Native command failed: '+command+' -> '+str(result))
            if index in (0,5,8,15,16):capture(f'command_{index:02}.png',state)
        if 'Dismiss' in read()['controls']:click('Dismiss')
        report['layout_checks']=[]
        for tab,visible in [('Apps','Chrome'),('Preferences','Save pause setting')]:
            state=wait(lambda s:tab in s['tabs'],'visible tab '+tab)
            native.click(state['tabs'][tab])
            state=wait(lambda s:visible in s['controls'],'selected tab '+tab)
            sizes={name:item['bounds'][2:] for name,item in state['controls'].items()}
            assert all(w>=16 and h>=16 for w,h in sizes.values()),sizes
            capture('layout_'+tab.lower()+'.png',state)
            report['layout_checks'].append({'tab':tab,'passed':True,'visible_button_sizes':sizes})
        report['status']='passed'
    except Exception as exc:
        report.update(status='failed',error=str(exc))
        state=read()
        if state.get('bounds'):capture('failure_widget.png',state)
    finally:
        report['last_ui_state']=read()
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        state=read()
        if process.poll() is None and '\u00d7' in state.get('controls',{}):
            native.click(state['controls']['\u00d7']['bounds'])
        try:process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            host_pid=read().get('pid')
            if host_pid:
                import signal
                try:os.kill(host_pid,signal.SIGTERM)
                except ProcessLookupError:pass
            process.terminate();process.wait(timeout=5)
        log.close()
    print(json.dumps({'status':report['status'],'checks':len(report['steps']),'report':str(output/'report.json')}))
    return 0 if report['status']=='passed' else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',action='store_true')
    parser.add_argument('--layout-only',action='store_true',help='Native tab clicks and button-size/screenshot checks; no application launches')
    parser.add_argument('--output',type=Path,default=ROOT/'test_output/emergency_native_apps')
    args=parser.parse_args();output=args.output.resolve()
    if not args.host and output.exists() and any(output.iterdir()):
        parser.error('Choose an empty output directory so evidence and local consent are fresh.')
    output.mkdir(parents=True,exist_ok=True)
    return host(output) if args.host else drive(output,args.layout_only)


if __name__=='__main__':raise SystemExit(main())
