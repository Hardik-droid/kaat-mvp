"""Capture actual Windows KAAT actions and actual source playback, without a mic.

The plain background and captions are a presentation stage, not simulated app
frames. All editing uses native mouse/keyboard. Read-only probes collect proof.
"""
from pathlib import Path
import argparse
import ctypes
from ctypes import wintypes
import json
import os
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_native_apps import NativeInput
from engine import _binary,source_hash,inspect_video

RECT=(40,30,1500,980)


def host(output):
    import tkinter as tk
    from dotenv import load_dotenv
    from app import Kaat
    load_dotenv(ROOT/'.env')
    app=Kaat(memory_path=output/'demo.sqlite3')
    stage=tk.Toplevel(app,bg='#080d15');stage.overrideredirect(True)
    stage.attributes('-topmost',True)
    x,y,w,h=RECT;stage.geometry(f'{w}x{h}+{x}+{y}')
    tk.Label(stage,text='KAAT  /  LIVE DESKTOP DEMO',bg='#080d15',fg='#9bc6ff',font=('Segoe UI',20,'bold')).place(x=35,y=28)
    headline=tk.StringVar(value='Real commands. Real files. Verified output.')
    detail=tk.StringVar(value='The right-hand window is the running KAAT app.\nThis capture uses typed commands; no microphone recording.')
    tk.Label(stage,textvariable=headline,bg='#080d15',fg='white',font=('Segoe UI',18,'bold'),wraplength=760,justify='left',anchor='nw').place(x=35,y=100,width=770,height=100)
    tk.Label(stage,textvariable=detail,bg='#080d15',fg='#bbcadc',font=('Segoe UI',14),wraplength=740,justify='left',anchor='nw').place(x=35,y=660,width=760,height=220)
    tk.Label(stage,text='PUBLIC HUMAN HINGLISH SPEECH  •  ORIGINAL FILE PRESERVED',bg='#080d15',fg='#7bd6b0',font=('Segoe UI',10)).place(x=35,y=930)
    playback=tk.Label(stage,bg='#080d15');playback.place(x=35,y=205,width=760,height=428)
    import queue,threading
    frames=queue.Queue(maxsize=2);play_token=None
    def decode(request):
        decoder=subprocess.Popen([_binary('ffmpeg'),'-v','error','-re','-i',request['path'],'-t',str(request['seconds']),
            '-vf','scale=760:428,fps=15','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        count=0
        while True:
            data=decoder.stdout.read(760*428*3)
            if len(data)!=760*428*3:break
            frames.put(data);count+=1
        error=decoder.stderr.read().decode('utf-8',errors='replace');code=decoder.wait()
        (output/'playback_status.json').write_text(json.dumps({'token':request['token'],'frames':count,'exit_code':code,'error':error}),encoding='utf-8')
    stage.lower(app)
    sequence=0;result_number=0;previous=None
    def bounds(widget):return [widget.winfo_rootx(),widget.winfo_rooty(),widget.winfo_width(),widget.winfo_height()]
    def observe():
        nonlocal sequence,result_number,previous,play_token
        sequence+=1
        if app.last_result is not previous:previous=app.last_result;result_number+=1
        controls={}
        def walk(widget):
            if not widget.winfo_ismapped():return
            if widget.winfo_class() in ('Button','Checkbutton'):
                controls[widget.cget('text')]={'bounds':bounds(widget),'state':widget.cget('state')}
            for child in widget.winfo_children():walk(child)
        walk(app)
        state={'sequence':sequence,'pid':os.getpid(),'hwnd':app._native_window(),
            'busy':app.busy,'bounds':bounds(app),'controls':controls,'expanded':app.expanded,
            'command':bounds(app.command_entry),'command_text':app.command_entry.get(),
            'result_number':result_number,'last_result':app.last_result,'state':app.cached,
            'status':app.status.get(),'cut_list':bounds(app.cut_list),'device_consent':app.device_consent}
        temp=output/'probe.tmp';temp.write_text(json.dumps(state),encoding='utf-8')
        try:temp.replace(output/'probe.json')
        except PermissionError:pass
        try:
            caption=json.loads((output/'caption.json').read_text(encoding='utf-8'))
            headline.set(caption['title']);detail.set(caption['detail'])
        except (OSError,ValueError,KeyError):pass
        try:
            request=json.loads((output/'playback_request.json').read_text(encoding='utf-8'))
            if request['token']!=play_token:
                play_token=request['token'];threading.Thread(target=decode,args=(request,),daemon=True).start()
        except (OSError,ValueError,KeyError):pass
        try:
            from PIL import Image,ImageTk
            picture=ImageTk.PhotoImage(Image.frombytes('RGB',(760,428),frames.get_nowait()))
            playback.configure(image=picture);playback.image=picture
        except queue.Empty:pass
        app.after(65,observe)
    app.after(150,observe)
    app.mainloop()


def drive(output,source,video):
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    native=NativeInput();user=ctypes.WinDLL('user32',use_last_error=True)
    user.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
    log=(output/'host.log').open('w',encoding='utf-8')
    process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--host','--output',str(output)],cwd=ROOT,
        env=dict(os.environ,PYTHONIOENCODING='utf-8',GNANI_API_KEY=''),stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    recorder=None;player=None;record_log=None;record_start=None
    source_before=source_hash(source)
    report={'status':'running','source':str(source),'source_sha256_before':source_before,
        'input_method':'real Windows mouse/keyboard; read-only application probe',
        'capture':'FFmpeg gdigrab of isolated stage, actual KAAT window, and real FFmpeg-decoded source frames',
        'microphone_recorded':False,'narration_generated':False,'steps':[]}
    def read():
        try:return json.loads((output/'probe.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):return {}
    def wait(predicate,label,timeout=90):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            if process.poll() is not None:raise RuntimeError('Demo app exited during '+label)
            state=read()
            if state and predicate(state):return state
            time.sleep(.08)
        raise AssertionError(label+': '+read().get('status','no probe'))
    def click(text):
        state=wait(lambda s:text in s['controls'] and s['controls'][text]['state']!='disabled','button '+text)
        native.click(state['controls'][text]['bounds'])
    def caption(title,detail):
        (output/'caption.json').write_text(json.dumps({'title':title,'detail':detail}),encoding='utf-8')
        report['steps'].append({'at_seconds':round(time.monotonic()-record_start,2) if record_start else 0,
            'title':title,'detail':detail})
    def dismiss():
        if 'Dismiss' in read().get('controls',{}):click('Dismiss')
    def command(text):
        dismiss();state=read();previous=state['result_number']
        native.click(state['command']);native.key(0x41,0x11);native.text(text)
        wait(lambda s:s['command_text']==text,'typed input',10)
        native.key(0x0D)
        state=wait(lambda s:s['result_number']>previous and not s['busy'],'command '+text,150)
        result=state['last_result'];report['steps'].append({'command':text,'result':result})
        assert result['ok'],result
        return state
    def action(text):
        dismiss();number=read()['result_number'];click(text)
        state=wait(lambda s:s['result_number']>number and not s['busy'],'action '+text,150)
        assert state['last_result']['ok'],state['last_result']
        report['steps'].append({'button':text,'result':state['last_result']})
        return state
    def play(path,seconds=9):
        token=str(time.monotonic())
        (output/'playback_request.json').write_text(json.dumps({'token':token,'path':str(path),'seconds':seconds}),encoding='utf-8')
        until=time.monotonic()+seconds+15
        while time.monotonic()<until:
            try:
                result=json.loads((output/'playback_status.json').read_text(encoding='utf-8'))
                if result['token']==token:
                    assert result['exit_code']==0 and result['frames']>=seconds*10,result
                    report['steps'].append({'actual_playback':str(path),'decoded_frames':result['frames']});return
            except (OSError,ValueError):pass
            time.sleep(.1)
        raise AssertionError('Actual media playback did not complete')
    def save_dialog(path):
        from tools.windows_apps import visible_windows
        wait(lambda _:any(w['title']=='Export a fresh edited copy' for w in visible_windows()),'native Save dialog',20)
        native.key(0x4e,0x12);native.key(0x41,0x11);native.text(str(path));native.key(0x0d)
    try:
        wait(lambda s:'Allow' in s['controls'],'permission popup',20);click('Allow')
        wait(lambda s:s['device_consent'] is True,'local consent',10)
        click('\u2303');state=wait(lambda s:s['expanded'],'expanded app',10)
        x,y,w,h=state['bounds']
        user.SetWindowPos(state['hwnd'],None,960,75,w,h,0x0014)
        time.sleep(.5)
        video.parent.mkdir(parents=True,exist_ok=True)
        record_log=(output/'capture.log').open('w',encoding='utf-8')
        x,y,w,h=RECT
        recorder=subprocess.Popen([_binary('ffmpeg'),'-hide_banner','-loglevel','warning','-f','gdigrab',
            '-framerate','15','-draw_mouse','1','-offset_x',str(x),'-offset_y',str(y),'-video_size',f'{w}x{h}',
            '-i','desktop','-c:v','libx264','-preset','ultrafast','-crf','23','-pix_fmt','yuv420p',
            '-movflags','+faststart',str(video)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=record_log,
            creationflags=subprocess.CREATE_NO_WINDOW)
        record_start=time.monotonic();time.sleep(2)
        caption('1. Select the real source','A public human Hindi-English recording on a test-pattern picture.\nAll commands below are typed into the actual KAAT app.')
        state=command('select video '+str(source))
        original=state['state']['original_duration'];time.sleep(3)
        caption('Original source playback',f'Actual source duration: {original:.3f} seconds.\nPreview is muted in this screen recording; no room audio or microphone is captured.')
        play(source,8)
        caption('2. Find filler-word suggestions','Running the actual local word-timing model.\nSuggestions are approximate and require review; no filler result is invented.')
        state=command('Kaat, filler words hata de')
        fillers=[c for c in state['state']['cuts'] if c['reason']=='filler_word']
        report['filler_suggestions']=fillers
        if fillers:
            caption('Review a real filler suggestion',f'{len(fillers)} possible filler(s) detected.\nThe selected interval is only a proposal until approval.')
            index=next(i for i,c in enumerate(state['state']['cuts']) if c['id']==fillers[0]['id'])
            native.click(state['cut_list']);native.key(0x24)
            for _ in range(index):native.key(0x28)
            time.sleep(3);action('Approve');time.sleep(3)
            caption('Undo is real and reversible','Undo restores the selected decision.\nThe original source file is never rewritten.')
            action('\u21b6 Undo');time.sleep(3)
        else:
            caption('No confident filler detected in this sample','The actual model returned zero filler suggestions.\nKAAT leaves the speech untouched. This is not a claim that the sample contains no fillers.')
            time.sleep(6)
        caption('3. Find actual long pauses','FFmpeg analyses the source audio.\nSuggested cuts do not change the edited duration until approval.')
        state=action('Find pauses');time.sleep(4)
        assert state['state']['cuts'],'No actual suggestions available for this editing demonstration'
        caption('Review, approve, then undo',f"{len(state['state']['cuts'])} actual suggestion(s) are visible.\nApprove all is an explicit action; undo returns to the previous decision state.")
        action('Approve all');time.sleep(3);action('\u21b6 Undo');time.sleep(3);state=action('Approve all');time.sleep(3)
        expected=state['state']['edited_duration']
        caption('4. Export a fresh edited MP4',f'Planned duration: {original:.3f}s → {expected:.3f}s.\nRendering the approved edits into a separate file.')
        edited=output/'KAAT-real-edited-copy.mp4';number=read()['result_number'];click('Export MP4');save_dialog(edited)
        state=wait(lambda s:s['result_number']>number and not s['busy'] and s['state']['output']==str(edited),'actual FFmpeg export',90)
        assert state['last_result']['ok'],state['last_result']
        actual=inspect_video(edited)
        subprocess.run([_binary('ffmpeg'),'-v','error','-i',str(edited),'-f','null','-'],check=True,capture_output=True,timeout=30)
        assert source_hash(source)==source_before
        caption('Verified exported-file playback',f"Export duration: {actual['duration_seconds']:.3f}s.\nAudio and video fully decoded. Original source SHA-256 is unchanged.\nFiller suggestions in this sample: {len(fillers)}.")
        play(edited,9)
        caption('Real editing. Honest results.',f"Original: {original:.3f}s   Edited: {actual['duration_seconds']:.3f}s\nSeparate playable MP4 + edit-decision JSON.\nNo microphone or synthetic speech was used in this capture.")
        remaining=90-(time.monotonic()-record_start)
        time.sleep(max(5,min(remaining,15)))
        report.update(status='passed',export=str(edited),source_unchanged=True,export_duration=actual['duration_seconds'],original_duration=original)
    except Exception as exc:report.update(status='failed',error=str(exc));print('DEMO ERROR',str(exc),flush=True)
    finally:
        if recorder:
            if recorder.poll() is None:
                recorder.communicate(input=b'q\n',timeout=15)
            report['capture_exit_code']=recorder.returncode
            if recorder.returncode!=0:report['status']='failed'
        if record_log:record_log.close()
        if player and player.poll() is None:player.terminate();player.wait(timeout=3)
        state=read()
        if process.poll() is None and not state.get('busy') and '\u00d7' in state.get('controls',{}):native.click(state['controls']['\u00d7']['bounds'])
        try:process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            pid=read().get('pid')
            if pid:
                try:os.kill(pid,signal.SIGTERM)
                except ProcessLookupError:pass
            process.terminate();process.wait(timeout=3)
        log.close()
        if video.exists():report['demo_duration']=inspect_video(video)['duration_seconds']
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'video':str(video),'duration':report.get('demo_duration'),'error':report.get('error')}))
    return 0 if report['status']=='passed' else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'test_output/demo_capture')
    parser.add_argument('--source',type=Path,default=ROOT/'test_output/practical_speech/human_hinglish_with_pause.mp4')
    parser.add_argument('--video',type=Path,default=ROOT/'delivery/KAAT-demo.mp4')
    args=parser.parse_args();output=args.output.resolve()
    if not args.host and output.exists() and any(output.iterdir()):parser.error('Choose a fresh output directory.')
    output.mkdir(parents=True,exist_ok=True)
    return host(output) if args.host else drive(output,args.source.resolve(strict=True),args.video.resolve())


if __name__=='__main__':raise SystemExit(main())
