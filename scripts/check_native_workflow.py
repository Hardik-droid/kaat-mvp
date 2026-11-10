"""Real Windows mouse/keyboard/file-dialog QA, with a read-only UI probe.

The host imports the actual app. No controller calls, widget invoke(), dialog
replacement, provider stubs, or synthetic success are used by the driver.
Microphone capture is never activated: speech tests use public recorded audio.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def host(output):
    from dotenv import load_dotenv
    from app import Kaat
    load_dotenv(ROOT / '.env')
    app = Kaat(memory_path=output / 'native.sqlite3')
    sequence = 0
    def bounds(widget):
        return [widget.winfo_rootx(), widget.winfo_rooty(), widget.winfo_width(), widget.winfo_height()]
    def observe():
        nonlocal sequence
        sequence += 1
        controls, tabs = {}, {}
        def walk(widget):
            if widget.winfo_ismapped():
                if widget.winfo_class() in ('Button', 'Checkbutton'):
                    controls[widget.cget('text')] = bounds(widget)
                if widget.winfo_class() == 'TNotebook':
                    groups = {}
                    for x in range(0, widget.winfo_width(), 4):
                        try:
                            index = widget.index(f'@{x},12')
                            groups.setdefault(index, []).append(x)
                        except Exception:
                            pass
                    for index, xs in groups.items():
                        tabs[widget.tab(index, 'text')] = [widget.winfo_rootx()+(min(xs)+max(xs))//2, widget.winfo_rooty()+12]
                for child in widget.winfo_children():
                    walk(child)
        walk(app)
        state = {'sequence':sequence, 'pid':os.getpid(), 'busy':app.busy, 'status':app.status.get(),
                 'expanded':app.expanded, 'bounds':bounds(app), 'controls':controls, 'tabs':tabs,
                 'state':app.cached, 'command':bounds(app.command_entry), 'cut_list':bounds(app.cut_list),
                 'start':bounds(app.start_entry), 'end':bounds(app.end_entry),
                 'pause_display':app.seconds.get(),'subtitle_display':app.burn.get(),
                 'device_consent':app.device_consent,'permission_prompt_open':app.permission_prompt_open,
                 'transcript_display':app.transcript.get('1.0','end')}
        temporary = output / 'probe.tmp'
        temporary.write_text(json.dumps(state), encoding='utf-8')
        try:
            temporary.replace(output / 'probe.json')
        except PermissionError:
            # Windows can briefly lock a snapshot while the external driver reads it.
            pass
        app.after(75, observe)
    app.after(150, observe)
    app.mainloop()


def drive(output, source):
    if os.name != 'nt':
        raise RuntimeError('This check requires a real interactive Windows desktop')
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    class Keyboard(ctypes.Structure):
        _fields_ = [('vk',wintypes.WORD),('scan',wintypes.WORD),('flags',wintypes.DWORD),('time',wintypes.DWORD),('extra',ctypes.c_size_t)]
    class Mouse(ctypes.Structure):
        _fields_ = [('x',wintypes.LONG),('y',wintypes.LONG),('data',wintypes.DWORD),('flags',wintypes.DWORD),('time',wintypes.DWORD),('extra',ctypes.c_size_t)]
    class Payload(ctypes.Union):
        _fields_ = [('keyboard',Keyboard),('mouse',Mouse)]
    class Input(ctypes.Structure):
        _fields_ = [('kind',wintypes.DWORD),('payload',Payload)]
    user32.SendInput.argtypes = [wintypes.UINT,ctypes.POINTER(Input),ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user32.PostMessageW.argtypes = [wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    from PIL import ImageGrab
    from engine import source_hash, duration
    environment = dict(os.environ, PYTHONIOENCODING='utf-8')
    log = (output / 'host.log').open('w', encoding='utf-8')
    process = subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--host','--output',str(output)],
                               cwd=ROOT,env=environment,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    steps = []
    def read():
        try:
            return json.loads((output / 'probe.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):
            return {}
    def wait(predicate, label, timeout=25):
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            if process.poll() is not None:
                raise RuntimeError(f'Application exited during {label}: see host.log')
            state = read()
            if state and predicate(state):
                return state
            time.sleep(.06)
        raise AssertionError(f'{label}: {read().get("status", "no probe")}')
    def send(vk=0, scan=0, flags=0):
        event = Input(kind=1,payload=Payload(keyboard=Keyboard(vk,scan,flags,0,0)))
        if user32.SendInput(1,ctypes.byref(event),ctypes.sizeof(event)) != 1:
            raise RuntimeError('Windows refused keyboard input')
    def key(vk, modifier=None):
        if modifier:
            send(modifier)
        send(vk); send(vk,flags=2)
        if modifier:
            send(modifier,flags=2)
    def type_text(value):
        raw = str(value).encode('utf-16-le')
        for index in range(0,len(raw),2):
            code = int.from_bytes(raw[index:index+2],'little')
            send(scan=code,flags=4); send(scan=code,flags=6)
    def point(x,y):
        user32.SetCursorPos(int(x),int(y))
        time.sleep(.08)
        user32.mouse_event(2,0,0,0,0)
        time.sleep(.04)
        user32.mouse_event(4,0,0,0,0)
        time.sleep(.15)
    def click(name):
        state = wait(lambda s:name in s['controls'] and not s['busy'], 'button '+name)
        x,y,w,h=state['controls'][name]
        if w<16 or h<16:
            raise AssertionError(f'Button is clipped and not practically clickable: {name} ({w}x{h})')
        point(x+w/2,y+h/2)
    def field(name,value):
        x,y,w,h=read()[name]
        point(x+w/2,y+h/2); key(0x41,0x11); type_text(value)
    def command(value, predicate):
        sequence=read()['sequence']
        field('command',value); key(0x0D)
        return wait(lambda s:s['sequence']>sequence+1 and not s['busy'] and predicate(s), 'command '+value)
    def windows():
        result=[]
        @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        def collect(hwnd,_):
            pid=wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if user32.IsWindowVisible(hwnd):
                text=ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd)+1)
                user32.GetWindowTextW(hwnd,text,len(text))
                # Windows' venv launcher can have a different PID from the GUI interpreter.
                if pid.value==read().get('pid',process.pid) or text.value in {'Choose source video','Export all decisions','Export a fresh edited copy'}:
                    result.append((hwnd,text.value))
            return True
        user32.EnumWindows(collect,0)
        return result
    def dialog(title,path=None,cancel=False):
        def filename_field():
            matches=[hwnd for hwnd,text in windows() if title==text]
            if not matches:
                return None
            children=[]
            @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
            def collect(child,_):
                if user32.IsWindowVisible(child) and user32.IsWindowEnabled(child):
                    text=ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(child)+1)
                    user32.GetWindowTextW(child,text,len(text))
                    kind=ctypes.create_unicode_buffer(128)
                    user32.GetClassNameW(child,kind,128)
                    rect=wintypes.RECT(); user32.GetWindowRect(child,ctypes.byref(rect))
                    children.append((kind.value,text.value,rect))
                return True
            user32.EnumChildWindows(matches[0],collect,0)
            (output/'dialog_controls.json').write_text(json.dumps([
                {'class':kind,'text':text,'rect':[rect.left,rect.top,rect.right,rect.bottom]}
                for kind,text,rect in children]),encoding='utf-8')
            labels=[rect for kind,text,rect in children if text.replace('&','').strip()=='File name:']
            if not labels:
                # Modern Save dialogs paint labels in DirectUI, exposing only
                # their one filename Edit control through Win32 enumeration.
                edits=[rect for kind,text,rect in children if kind=='Edit']
                return edits[0] if len(edits)==1 else None
            label=labels[0]
            edits=[rect for kind,text,rect in children if kind=='Edit' and abs(rect.top-label.top)<30 and rect.left>=label.right-15]
            if len(edits)!=1:
                return None
            return edits[0]
        wait(lambda _:filename_field() is not None,'painted native dialog '+title)
        ImageGrab.grab().save(output / ('dialog_'+str(len(steps))+'.png'))
        if cancel:
            key(0x1B)
        else:
            rect=filename_field()
            point((rect.left+rect.right)/2,(rect.top+rect.bottom)/2)
            key(0x41,0x11); type_text(str(path)); key(0x0D)
        wait(lambda _:not any(title==text for _,text in windows()),'native dialog closed '+title)
        # Wait for the modal shell's mouse capture/disabled owner state to unwind.
        time.sleep(.6)
    def tab(name):
        state=wait(lambda s:name in s['tabs'],'tab '+name)
        point(*state['tabs'][name]); time.sleep(.15)
    def note(name):
        steps.append({'scenario':name,'passed':True})
    original_hash=source_hash(source)
    try:
        wait(lambda s:s.get('controls'),'launch')
        click('Allow')
        wait(lambda s:'Allow' not in s['controls'],'local permission choice saved')
        assert json.loads((output/'desktop_permissions.json').read_text(encoding='utf-8'))=={'version':1,'devices':True}
        note('Actual Allow click persists device consent locally')
        click('\u2303')
        wait(lambda s:s['expanded'],'open controls')
        click('Export MP4')
        wait(lambda s:s['status']=='Select a video first.','missing source error')
        note('Export without source reports an actual visible error')
        click('Open video'); dialog('Choose source video',cancel=True)
        wait(lambda s:s['state']['source'] is None,'cancel open')
        note('Cancel native Open dialog preserves the empty session')
        invalid=output / 'corrupt.mp4'; invalid.write_bytes(b'not a video')
        click('Open video'); dialog('Choose source video',invalid)
        wait(lambda s:not s['busy'] and s['status'].startswith('Error:'),'corrupt input rejected')
        note('Corrupt MP4 fails visibly without changing selection')
        click('Open video'); dialog('Choose source video',source)
        wait(lambda s:not s['busy'] and s['state']['source']==str(source),'valid source opened')
        click('Find pauses')
        state=wait(lambda s:not s['busy'] and bool(s['state']['cuts']),'real pause detection')
        assert all(c['status']=='suggested' for c in state['state']['cuts'])
        assert state['state']['edited_duration']==state['state']['original_duration']
        note('Native file selection and actual FFmpeg detection create unapproved suggestions')
        x,y,w,h=state['cut_list']; point(x+50,y+10)
        click('Approve')
        wait(lambda s:not s['busy'] and any(c['status']=='approved' for c in s['state']['cuts']),'selected approval')
        command('Kaat, undo kar',lambda s:all(c['status']=='suggested' for c in s['state']['cuts']))
        note('Mouse selection, approval and typed Hinglish Undo restore actual decision state')
        click('Approve all')
        wait(lambda s:not s['busy'] and all(c['status']=='approved' for c in s['state']['cuts']),'approve all')
        before=read()['state']['cuts']
        command('Kaat, pauses remove nahi karna',lambda s:s['status'].startswith('Error:'))
        assert read()['state']['cuts']==before
        note('Negated Hinglish does not execute an editing action')
        command('Kaat, always remove pauses longer than 3 seconds',lambda s:s['state']['preferences'].get('pause_threshold')==3)
        tab('Preferences')
        note('Explicit preference persisted through the actual typed-command UI')
        tab('Cuts')
        field('start','bad'); field('end','.4'); click('Propose')
        wait(lambda s:s['status']=='Enter source start and end in seconds.','invalid manual cut')
        note('Invalid manual cut has a visible validation error')
        click('Transcribe')
        state=wait(lambda s:not s['busy'] and bool(s['state']['transcript']),'actual native Prisma transcription',90)
        assert any(segment['text'] for segment in state['state']['transcript'])
        assert any('\u0900'<=char<='\u097f' for char in state['transcript_display'])
        tab('Transcript')
        x,y,w,h=read()['bounds']
        ImageGrab.grab(bbox=(x,y,x+w,y+h)).save(output/'native_transcript.png')
        tab('Cuts')
        note('Actual Prisma button transcribes public human Hinglish and shows Devanagari in the native transcript tab')
        click('Add subtitles')
        command('Kaat, agli baar bhi same settings use karna',lambda s:s['state']['preferences'].get('burn_subtitles') is True)
        note('Subtitles checkbox is included in explicitly remembered current settings')
        click('Export edit list'); plan=output/'native decisions.json'
        dialog('Export all decisions',plan)
        wait(lambda s:not s['busy'] and plan.exists(),'native JSON save')
        assert json.loads(plan.read_text(encoding='utf-8'))['source_sha256']==original_hash
        note('Native EDL save dialog produces actual source-linked JSON')
        click('Export MP4'); edited=output/"native edited copy's.mp4"
        dialog('Export a fresh edited copy',edited)
        state=wait(lambda s:not s['busy'] and s['state']['output']==str(edited),'native MP4 export',60)
        assert edited.exists() and duration(edited)<duration(source)-1.5
        assert edited.with_suffix('.srt').exists()
        subprocess.run([__import__('engine')._binary('ffmpeg'),'-v','error','-i',str(edited),'-f','null','-'],check=True,capture_output=True)
        assert source_hash(source)==original_hash
        note('Native Save dialog exports a fully decodable captioned MP4 with an apostrophe/space path; source hash preserved')
        click('Clear edits')
        wait(lambda s:not s['busy'] and not s['state']['cuts'],'clear edits')
        click('↶ Undo')
        wait(lambda s:not s['busy'] and bool(s['state']['cuts']),'undo clear')
        note('Clear edits and Undo work through actual buttons')
        position=read()['bounds'][:2]
        click('\u2304'); wait(lambda s:not s['expanded'],'collapse')
        click('\u2303'); wait(lambda s:s['expanded'],'expand')
        assert read()['bounds'][:2]==position
        note('Collapse/expand preserves desktop position')
        state=read(); x,y,w,h=state['bounds']
        ImageGrab.grab(bbox=(x,y,x+w,y+h)).save(output/'native_final.png')
        for hwnd,title in windows():
            if title.startswith('KAAT'):
                user32.PostMessageW(hwnd,0x0010,0,0)
        process.wait(timeout=8)
        (output/'probe.json').unlink(missing_ok=True)
        # A genuinely new application process reads the same preference database.
        restart_environment=dict(environment,GNANI_API_KEY='')
        process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--host','--output',str(output)],
                                 cwd=ROOT,env=restart_environment,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        state=wait(lambda s:bool(s.get('controls')),'actual application relaunch')
        assert state['device_consent'] is True and state['permission_prompt_open'] is False
        assert float(state['pause_display'])==3 and state['subtitle_display'] is True
        assert state['state']['preferences']=={'pause_threshold':3.0,'burn_subtitles':True}
        note('Actual app close/relaunch restores local device consent plus displayed pause threshold and subtitle preference')
        click('\u2303'); wait(lambda s:s['expanded'],'reopen controls after relaunch')
        tab('Preferences'); click('Reset pause setting')
        wait(lambda s:not s['busy'] and 'pause_threshold' not in s['state']['preferences'],'forget preference')
        assert float(read()['pause_display'])==2
        note('Actual Preferences tab deletes a persisted preference and restores its default')
        # This media regression deliberately never activates the microphone
        # button. Live voice and the missing-key path have separate checks.
        report={'status':'passed','input_method':'real Windows mouse/keyboard, native Open/Save dialogs',
                'read_only_probe':True,'controller_or_widget_action_shortcuts':False,
                'steps':steps,'source':str(source),'export':str(edited),'source_unchanged':source_hash(source)==original_hash,
                'actual_export_seconds':duration(edited),'physical_microphone_tested':False,'browser_playback_tested':False}
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))
    except Exception as exc:
        ImageGrab.grab().save(output/'failure.png')
        (output/'report.json').write_text(json.dumps({'status':'failed','error':str(exc),'steps':steps,
            'source_unchanged':source_hash(source)==original_hash,'physical_microphone_tested':False},indent=2),encoding='utf-8')
        raise
    finally:
        for hwnd,title in windows():
            if title.startswith('KAAT'):
                user32.PostMessageW(hwnd,0x0010,0,0)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            host_pid=read().get('pid')
            if host_pid:
                try:
                    import signal
                    os.kill(host_pid,signal.SIGTERM)
                except ProcessLookupError:
                    pass
            process.terminate(); process.wait(timeout=5)
        log.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',action='store_true')
    parser.add_argument('--source',type=Path,default=ROOT/'test_output/practical_speech/human_hinglish_with_pause.mp4',
                        help='Human Hinglish video with a long pause; prepare via check_prisma_real.py --prepare-only')
    parser.add_argument('--output',type=Path,default=ROOT/'test_output/native_workflow')
    args=parser.parse_args()
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=True)
    if args.host:
        host(output)
    else:
        if not args.source.is_file():
            parser.error('Prepare the public speech fixture with scripts/check_prisma_real.py --prepare-only, or provide --source')
        if (output/'report.json').exists():
            raise ValueError('Choose a fresh output directory to preserve earlier evidence')
        drive(output,args.source.resolve(strict=True))


if __name__=='__main__':
    main()
