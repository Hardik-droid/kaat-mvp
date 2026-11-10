"""KAAT's floating desktop overlay; heavy work never runs on the Tk thread."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from dotenv import load_dotenv
from controller import AgentController

BG, PANEL, INK, MUTED = '#11151d', '#1a2230', '#e6edf7', '#91a1b8'
ACCENT, GREEN = '#95b9ff', '#7be0b2'


class Kaat(tk.Tk):
    def __init__(self, memory_path=None):
        if os.name == 'nt':
            import ctypes
            # Keep Tk coordinates and Windows screenshots aligned on scaled displays.
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        super().__init__()
        self.ui_scale = max(1., self.winfo_fpixels('1i') / 96.)
        self.controller = AgentController(memory_path)
        self.permission_file = self.controller.memory.path.parent / 'desktop_permissions.json'
        try:
            saved = json.loads(self.permission_file.read_text(encoding='utf-8'))
            self.device_consent = saved.get('devices') if saved.get('version') == 1 and type(saved.get('devices')) is bool else None
        except (OSError, ValueError, AttributeError):
            self.device_consent = None
        self.permission_prompt_open = False
        self.permissions_prompted = False
        self.pending_device_action = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='kaat')
        self.events = queue.Queue()
        self.busy = False
        self.expanded = False
        self.closed = False
        self.voice_phase = 'idle'
        self.voice_cancel = None
        self.voice_dispatch_lock = threading.Lock()
        self.last_result = None
        self.devices = None
        self.notice = None
        self.cached = self.controller.state()
        if 'microphone' in self.cached['preferences']:
            os.environ['KAAT_MICROPHONE'] = self.cached['preferences']['microphone']
        self.title('KAAT — AI Desktop Companion')
        self.configure(bg=BG)
        self.overrideredirect(True)
        if os.name == 'nt':
            self.attributes('-toolwindow', True)
        self.resizable(False, False)
        self.attributes('-topmost', True)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.status = tk.StringVar(value='Speak or type a request, such as “Chrome khol de”.')
        self.video_name = tk.StringVar(value='No video selected')
        self.stats = tk.StringVar(value='0 cuts  ·  0.0s → 0.0s')
        self.mic = tk.StringVar(value='Microphone off')
        self.peek = tk.StringVar(value='Ready when you are')
        self.heard = tk.StringVar(value='Press Speak and wait for Listening before speaking.')
        self.execution = tk.StringVar(value='INTERPRETED: —   TARGET: —   RESULT: IDLE')
        self.capture_seconds = tk.StringVar(value=str(self.cached['preferences'].get('capture_seconds', os.getenv('KAAT_CAPTURE_SECONDS', '6'))))
        self.seconds = tk.StringVar(value=str(self.cached['pause_threshold']))
        self.burn = tk.BooleanVar(value=self.cached['subtitles'])
        self.buttons = []
        self._build()
        for entry in reversed(self.cached['history'][:8]):
            self._log(f"{entry['at']} · {entry['tool']}: {entry['detail']}")
        self._size()
        self.status.trace_add('write', lambda *_: self._sync_compact())
        self.bind('<Configure>', lambda event: self.after_idle(self._round_window) if event.widget is self else None)
        self.after(80, self._poll)
        self.after(200, self._round_window)
        self.after(100, self._check_devices)
        self.after(300, lambda: self._request_permissions() if self.device_consent is None and not self.permissions_prompted else None)

    def _request_permissions(self, action=None):
        if self.device_consent is True:
            if action:
                action()
            return
        self._show_notice('Allow microphone and Camera controls?\n\nVoice commands go to Gnani for recognition. Camera runs locally when you ask. Windows privacy settings still apply.')
        self.permissions_prompted = True
        self.permission_prompt_open = True
        self.pending_device_action = action
        self.notice_action.config(text='Allow', command=self._allow_permissions)
        self.notice_action.pack(side='left')
        self.notice_secondary.config(text='Not now', command=self._decline_permissions)
        self.notice_secondary.pack(side='right')
        self.notice_dismiss.pack_forget()
        self.peek.set('Allow device access')

    def _allow_permissions(self):
        temporary = self.permission_file.with_name(f'.desktop_permissions_{os.getpid()}.tmp')
        try:
            temporary.write_text(json.dumps({'version': 1, 'devices': True}), encoding='utf-8')
            temporary.replace(self.permission_file)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            self._show_notice('Could not save device permission on this computer: ' + str(exc))
            return
        action = self.pending_device_action
        self.device_consent = True
        self._dismiss_notice()
        self.peek.set('Ready when you are')
        if action:
            action()
        elif self.devices:
            for key in ('camera', 'microphone'):
                if self.devices.get(key, {}).get('status') == 'blocked':
                    self.status.set(f'Error: Windows blocks {key} access. Enable it in Windows privacy settings.')
                    break

    def _decline_permissions(self):
        self._dismiss_notice()
        self.peek.set('Device access not allowed')

    def _check_devices(self):
        def inspect():
            try:
                from system_tools import device_status
                result = device_status()
            except Exception as exc:
                result = {'enumeration_error': str(exc)}
            self.events.put(({'device_status': result}, None))
        # Device discovery must not delay commands or block the Tk event loop.
        threading.Thread(target=inspect, name='kaat-devices', daemon=True).start()

    def _dismiss_notice(self):
        self.permission_prompt_open = False
        self.pending_device_action = None
        if getattr(self, '_notice_timer', None):
            self.after_cancel(self._notice_timer)
            self._notice_timer = None
        if self.notice is not None:
            self.notice.destroy()
            self.notice = None

    def _show_notice(self, message, *, transient=False):
        """Visible, modeless feedback above the widget; never an approval gate."""
        self.permission_prompt_open = False
        self.pending_device_action = None
        if getattr(self, '_notice_timer', None):
            self.after_cancel(self._notice_timer)
            self._notice_timer = None
        if self.notice is None:
            self.notice = tk.Toplevel(self, name='notice', bg=PANEL, bd=1, relief='solid')
            self.notice.overrideredirect(True)
            self.notice.attributes('-topmost', True)
            if os.name == 'nt':
                self.notice.attributes('-toolwindow', True)
            self.notice.protocol('WM_DELETE_WINDOW', self._dismiss_notice)
            self.notice_text = tk.StringVar()
            tk.Label(self.notice, text='✦ KAAT', bg=PANEL, fg=INK, font=('Segoe UI', 10, 'bold'),
                     anchor='w').pack(fill='x', padx=14, pady=(12, 4))
            self.notice_label = tk.Label(self.notice, textvariable=self.notice_text, bg=PANEL, fg=INK,
                justify='left', anchor='w', font=('Segoe UI', 9), wraplength=round(310*self.ui_scale))
            self.notice_label.pack(fill='x', padx=14, pady=(0, 10))
            row = tk.Frame(self.notice, bg=PANEL)
            row.pack(fill='x', padx=10, pady=(0, 10))
            self.notice_action = tk.Button(row, bg='#334e78', fg=INK, relief='flat', padx=10, pady=6)
            self.notice_secondary = tk.Button(row, bg=BG, fg=INK, relief='flat', padx=10, pady=6)
            self.notice_dismiss = tk.Button(row, text='Dismiss', command=self._dismiss_notice, bg=BG, fg=INK,
                      relief='flat', padx=10, pady=6)
        self.notice_dismiss.config(text='Dismiss')
        self.notice_dismiss.pack(side='right')
        no_speech = any(text in message.casefold() for text in ('no speech', 'no microphone activity', 'no words were recognized', 'selected microphone is unavailable'))
        self.notice_text.set('Couldn’t hear a command. Try again or choose a microphone.' if no_speech else message.removeprefix('Error: '))
        self.notice_action.pack_forget()
        self.notice_secondary.pack_forget()
        lower = message.casefold()
        if no_speech:
            self.notice_action.config(text='Try again', command=self.hear)
            self.notice_action.pack(side='left')
            self.notice_secondary.config(text='Microphone…', command=self.choose_microphone)
            self.notice_secondary.pack(side='left', padx=4)
        elif any(word in lower for word in ('denies', 'blocks', 'denied', 'permission', 'privacy settings')):
            capability = 'webcam' if 'camera' in lower else 'microphone' if 'microphone' in lower else None
            if capability:
                from system_tools import open_device_settings
                def settings():
                    try:
                        open_device_settings(capability)
                    except OSError as exc:
                        self._show_notice('Could not open Windows settings: ' + str(exc))
                self.notice_action.config(text='Open Windows settings', command=settings)
                self.notice_action.pack(side='left')
        elif 'select a video' in lower:
            self.notice_action.config(text='Open video', command=self.select)
            self.notice_action.pack(side='left')
        self.notice.update_idletasks()
        self._position_notice()
        if transient:
            self._notice_timer = self.after(5000, self._dismiss_notice)

    def _position_notice(self):
        area = self._work_area(self.winfo_rootx(), self.winfo_rooty())
        width = min(round(340*self.ui_scale), area[2]-area[0])
        height = self.notice.winfo_reqheight()
        x = max(area[0], min(self.compact.winfo_rootx()+self.compact.winfo_width()-width, area[2]-width))
        y = max(area[1], min(self.compact.winfo_rooty()-height-round(8*self.ui_scale), area[3]-height))
        self._place(x, y, width, height, widget=self.notice)

    def choose_microphone(self):
        if self.busy:
            self._show_notice('Wait for the current command before changing microphones.')
            return
        from voice import list_microphones
        try:
            microphones = list_microphones()
        except Exception as exc:
            self._show_notice('Could not list microphones: ' + str(exc))
            return
        self._dismiss_notice()
        self._show_notice('Choose the microphone you speak into:')
        chosen = tk.StringVar(value=os.getenv('KAAT_MICROPHONE', '') or 'Windows default')
        picker = ttk.Combobox(self.notice, values=['Windows default', *microphones], textvariable=chosen, state='readonly')
        picker.pack(fill='x', padx=14, pady=(0, 12), before=self.notice_action.master)
        def save():
            value = '' if chosen.get() == 'Windows default' else chosen.get()
            result = self.controller.call('memory.save_preference', key='microphone', value=value, approved=True)
            if result['ok']:
                os.environ['KAAT_MICROPHONE'] = value
                self._dismiss_notice()
                self._show_notice('Microphone selected. Press the mic and wait for Listening.', transient=True)
            else:
                self.status.set('Error: ' + result['error']['message'])
        self.notice_action.config(text='Use microphone', command=save)
        self.notice_action.pack(side='left')
        self.notice.update_idletasks()
        self._place(self.notice.winfo_x(), self.notice.winfo_y(), self.notice.winfo_width(), self.notice.winfo_reqheight(), widget=self.notice)

    def show_devices(self):
        if self.devices is None:
            self._show_notice('Checking local camera and microphone information…')
            return
        cameras = [d['name'] for d in self.devices.get('devices', []) if d['kind'] == 'video']
        lines = ['Camera: ' + (', '.join(cameras) if cameras else
                 'Discovery unavailable' if self.devices.get('enumeration_error') else 'No camera found')]
        lines.append('Camera app: ' + ('Installed' if self.devices.get('camera_app_available') else 'Unavailable'))
        for key in ('camera', 'microphone'):
            permission = self.devices.get(key, {})
            state = ('Blocked in Windows settings' if permission.get('status') == 'blocked' else
                     'No denial found in settings; capture not verified' if permission else 'Not checked')
            lines.append(key.capitalize() + ': ' + state)
        if self.devices.get('enumeration_error'):
            lines.append('Device discovery: ' + self.devices['enumeration_error'])
        lines.append('Checked on this computer. No recording or upload.')
        self._show_notice('\n\n'.join(lines))

    def _round_window(self):
        if os.name == 'nt':
            try:
                import ctypes
                from ctypes import wintypes
                geometry = (self._native_window(), self.winfo_width(), self.winfo_height(), self.speak_button.winfo_width(), self.speak_button.winfo_height())
                if geometry == getattr(self, '_rounded_geometry', None):
                    return
                self._rounded_geometry = geometry
                user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
                gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
                user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
                gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
                for hwnd, width, height, radius in (
                    (self._native_window(), self.winfo_width(), self.winfo_height(), round(20*self.ui_scale)),
                    (self.speak_button.winfo_id(), self.speak_button.winfo_width(), self.speak_button.winfo_height(), round(52*self.ui_scale))):
                    region = gdi32.CreateRoundRectRgn(0, 0, width+1, height+1, radius, radius)
                    if region and not user32.SetWindowRgn(hwnd, region, True):
                        gdi32.DeleteObject(region)
            except (AttributeError, OSError):
                pass

    def _native_window(self, widget=None):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        return user32.GetAncestor((widget or self).winfo_id(), 2)

    def _work_area(self, x=0, y=0):
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            class MonitorInfo(ctypes.Structure):
                _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT), ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
            user32 = ctypes.windll.user32
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            user32.MonitorFromPoint.restype = wintypes.HANDLE
            user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
            info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
            monitor = user32.MonitorFromPoint(wintypes.POINT(round(x), round(y)), 2)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return info.work.left, info.work.top, info.work.right, info.work.bottom
        return 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()

    def _place(self, x, y, width=None, height=None, *, widget=None):
        widget = widget or self
        width, height = width or widget.winfo_width(), height or widget.winfo_height()
        left, top, right, bottom = self._work_area(x+width/2, y+height/2)
        x, y = round(max(left, min(x, right-width))), round(max(top, min(y, bottom-height)))
        widget.geometry(f'{width}x{height}+{max(0,x)}+{max(0,y)}')
        widget.update_idletasks()
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos(self._native_window(widget), None, x, y, width, height, 0x0010 | 0x0004)

    def _size(self):
        positioned = getattr(self, '_positioned', False)
        anchor_x, anchor_y = (self.winfo_x()+self.winfo_width(), self.winfo_y()+self.winfo_height()) if positioned else (0, 0)
        area = self._work_area(anchor_x-1, anchor_y-1) if positioned else self._work_area()
        margin = round(16*self.ui_scale)
        width = min(round((450 if self.expanded else 330)*self.ui_scale), area[2]-area[0]-2*margin)
        height = min(round((700 if self.expanded else 76)*self.ui_scale), area[3]-area[1]-2*margin)
        if not positioned:
            anchor_x, anchor_y = area[2]-margin, area[3]-margin
        self._place(anchor_x-width, anchor_y-height, width, height)
        self.toggle_button.configure(text='⌄' if self.expanded else '⌃')
        self._positioned = True

    def _menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _sync_compact(self):
        status = self.status.get()
        error = status.startswith('Error:') or status.startswith('Warning:') or status.startswith('Set GNANI_API_KEY')
        phases = {'preparing':'Getting microphone ready…', 'listening':'Listening…', 'processing':'Preparing your audio…',
                  'transcribing':'Understanding your words…', 'recognized':'Acting on your request…'}
        if error:
            lower = status.casefold()
            text = ('Select a video' if 'select a video' in lower else
                    'No mic activity' if 'no microphone activity' in lower else
                    'Microphone blocked' if 'microphone' in lower and ('denies' in lower or 'blocks' in lower) else
                    'Camera blocked' if 'camera' in lower and ('denies' in lower or 'blocks' in lower) else
                    'Voice needs setup' if 'gnani_api_key' in lower else 'Check the message')
            self._show_notice(status)
        elif self.busy:
            text = phases.get(self.voice_phase, 'Working on your request…')
            if self.voice_phase == 'listening' and 's left' in self.mic.get():
                text = 'Listening · '+self.mic.get().split('·')[1].strip()
        else:
            suggested = sum(c['status']=='suggested' for c in self.cached['cuts'])
            approved = sum(c['status']=='approved' for c in self.cached['cuts'])
            recording = self.cached.get('recording_status')
            text = ('Camera recording…' if recording == 'recording' else 'Camera paused' if recording == 'paused' else
                    f'{suggested} cut(s) to review' if suggested else 'Ready to export' if approved else 'Ready when you are')
            if self.last_result and self.last_result.get('verified') and self.last_result.get('target'):
                if self.last_result.get('tool') == 'system.close_recent':
                    text = f"Closed {len(self.last_result['data']['closed'])} window(s)"
                else:
                    text = str(self.last_result['target']).split('/')[-1][:18] + ' · verified'
        self.peek.set(text)
        self.peek_label.configure(fg='#ffb4a9' if error else GREEN if self.voice_phase=='listening' else MUTED)
        self.speak_button.configure(bg=GREEN if self.voice_phase=='listening' else '#4266db')

    def label(self, parent, text=None, variable=None, color=INK, size=10, bold=False):
        return tk.Label(parent, text=text, textvariable=variable, bg=BG, fg=color,
                        font=('Segoe UI', size, 'bold' if bold else 'normal'), anchor='w')

    def button(self, parent, text, command, primary=False, width=None):
        b = tk.Button(parent, text=text, command=command, bg='#334e78' if primary else PANEL,
                      fg=INK, activebackground='#405776', activeforeground='white',
                      relief='flat', bd=0, padx=10, pady=7, cursor='hand2', font=('Segoe UI', 9), width=width)
        self.buttons.append(b)
        return b

    def _build(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=PANEL, foreground=MUTED, padding=(10, 6))
        style.map('TNotebook.Tab', background=[('selected', '#30415c')], foreground=[('selected', INK)])
        scale = self.ui_scale
        self.compact = tk.Frame(self, bg=BG, width=round(330*scale), height=round(76*scale))
        self.compact.pack(side='bottom', anchor='e')
        self.compact.pack_propagate(False)
        self.speak_button = tk.Button(self.compact, text='\ue720', command=self.hear,
            font=('Segoe MDL2 Assets', 22), bg='#4266db', fg='white', activebackground='#5578ed',
            activeforeground='white', disabledforeground='#dce5fa', relief='flat', bd=0,
            cursor='hand2', takefocus=True)
        self.speak_button.place(x=round(12*scale), y=round(12*scale), width=round(52*scale), height=round(52*scale))
        self.buttons.append(self.speak_button)
        self.drag_handle = tk.Frame(self.compact, bg=BG, cursor='fleur')
        self.drag_handle.place(x=round(77*scale), y=round(14*scale), width=round(163*scale), height=round(49*scale))
        brand = self.label(self.drag_handle, '✦ KAAT', color=INK, size=11, bold=True)
        brand.pack(anchor='w')
        self.peek_label = self.label(self.drag_handle, variable=self.peek, color=MUTED, size=9)
        self.peek_label.pack(anchor='w', pady=(2, 0))
        for widget in (self.compact, self.drag_handle, brand, self.peek_label):
            widget.bind('<Button-1>', self._drag_start)
            widget.bind('<B1-Motion>', self._drag)
            widget.bind('<Button-3>', self._menu)
        def small(text, command, x, name):
            button = tk.Button(self.compact, name=name, text=text, command=command, bg=BG, fg=MUTED,
                activebackground=PANEL, activeforeground=INK, relief='flat', bd=0,
                font=('Segoe UI', 14), cursor='hand2', takefocus=True)
            button.place(x=round(x*scale), y=round(20*scale), width=round(25*scale), height=round(34*scale))
            return button
        self.open_button = small('+', self.select, 243, 'open_video')
        self.buttons.append(self.open_button)
        self.toggle_button = small('\u2303', self.toggle, 270, 'details')
        self.close_button = small('\u00d7', self.close, 298, 'close')
        self.context_menu = tk.Menu(self, tearoff=False, bg=PANEL, fg=INK, activebackground='#30415c')
        self.context_menu.add_command(label='Open video…', command=self.select)
        self.context_menu.add_command(label='Open camera', command=lambda: self.submit('camera.open'))
        self.context_menu.add_command(label='Camera & microphone', command=self.show_devices)
        self.context_menu.add_command(label='Choose microphone…', command=self.choose_microphone)
        self.context_menu.add_command(label='Show controls', command=self.toggle)
        self.context_menu.add_separator()
        self.context_menu.add_command(label='Quit KAAT', command=self.close)
        self.bind('<Escape>', lambda _: self.cancel_listening() if self.voice_cancel is not None else self.toggle() if self.expanded else None)
        self.bind('<Control-o>', lambda _: self.select())
        self.bind('<Control-space>', lambda _: self.hear())
        self.bind('<Alt-F4>', lambda _: self.close())
        self.details = tk.Frame(self, bg=BG)
        # The drawer opens above the widget, preserving the microphone's position.
        header = tk.Frame(self.details, bg=BG)
        header.pack(fill='x', padx=16, pady=(14, 4))
        self.label(header, 'Your workspace', size=12, bold=True).pack(side='left')
        self.button(header, 'Open video', self.select).pack(side='right')
        self.label(self.details, variable=self.video_name, color=MUTED, size=9).pack(fill='x', padx=18, pady=(0, 8))
        row = tk.Frame(self.details, bg=BG)
        row.pack(fill='x', padx=16)
        self.button(row, 'Find pauses', lambda: self.submit('video.detect_pauses', min_pause_seconds=self._seconds()), True).pack(side='left', fill='x', expand=True, padx=(0, 4))
        self.button(row, 'Fillers', lambda: self.submit('video.detect_fillers')).pack(side='left', padx=(0, 4))
        self.button(row, 'Transcribe', lambda: self.submit('video.transcribe')).pack(side='left', fill='x', expand=True, padx=(0, 4))
        self.button(row, 'Retakes', lambda: self.submit('video.detect_retakes')).pack(side='left')
        self.command_entry = tk.Entry(self.details, bg=PANEL, fg=INK, insertbackground=INK, font=('Segoe UI', 10), relief='flat')
        self.command_entry.pack(fill='x', padx=16, pady=(9, 3), ipady=7)
        self.command_entry.bind('<Return>', lambda _: self.run_command())
        self.label(self.details, 'Or type a request and press Enter', color=MUTED, size=8).pack(fill='x', padx=18)
        self.label(self.details, variable=self.heard, color=ACCENT, size=9).pack(fill='x', padx=18, pady=(5, 2))
        tk.Label(self.details, textvariable=self.execution, bg=BG, fg=MUTED, font=('Segoe UI', 8),
                 wraplength=round(410*scale), justify='left', anchor='w').pack(fill='x', padx=18)
        self.label(self.details, variable=self.stats, color=GREEN, size=10, bold=True).pack(fill='x', padx=18, pady=(2, 4))
        self.status_label = tk.Label(self.details, textvariable=self.status, bg=BG, fg=INK, font=('Segoe UI', 9),
                                    wraplength=round(410*scale), justify='left', anchor='nw', height=2)
        self.status_label.pack(fill='x', padx=18, pady=(0, 4))
        notebook = ttk.Notebook(self.details)
        self.notebook = notebook
        notebook.pack(fill='both', expand=True, padx=16, pady=(4, 7))
        cut_tab, activity_tab, transcript_tab, pref_tab, apps_tab = [tk.Frame(notebook, bg=BG) for _ in range(5)]
        for frame, text in ((apps_tab, 'Apps'), (cut_tab, 'Cuts'), (transcript_tab, 'Transcript'), (pref_tab, 'Preferences'), (activity_tab, 'Activity')):
            notebook.add(frame, text=text)
        self.label(apps_tab, 'Open an app or type its installed name above.', color=MUTED, size=9).pack(fill='x', pady=8)
        for targets in (('Chrome', 'Notepad', 'Calculator'), ('File Explorer', 'Google Photos', 'YouTube')):
            row = tk.Frame(apps_tab, bg=BG)
            row.pack(fill='x', pady=3)
            for name in targets:
                self.button(row, name, lambda value=name: self._run_typed_command('Open '+value)).pack(side='left', padx=3)
        row = tk.Frame(apps_tab, bg=BG)
        row.pack(fill='x', pady=3)
        self.button(row, 'Downloads', lambda: self._run_typed_command('Open Downloads')).pack(side='left', padx=3)
        self.button(row, 'Camera', lambda: self.submit('camera.open')).pack(side='left', padx=3)
        self.button(row, 'List apps', lambda: self._run_typed_command('List applications')).pack(side='left', padx=3)
        row = tk.Frame(apps_tab, bg=BG)
        row.pack(fill='x', pady=3)
        self.button(row, '🎤 Presentation', lambda: self._run_typed_command('Give the presentation')).pack(side='left', padx=3)
        self.button(row, 'PowerPoint', lambda: self._run_typed_command('Open PowerPoint')).pack(side='left', padx=3)
        self.button(row, 'Close Apps', lambda: self._run_typed_command('Close the apps you opened')).pack(side='left', padx=3)
        self.cut_list = tk.Listbox(cut_tab, bg=PANEL, fg=INK, relief='flat', selectbackground='#3d587d',
                                  font=('Consolas', 9), height=4, exportselection=False)
        self.cut_list.pack(fill='both', expand=True, pady=(6, 4))
        self.cut_list.bind('<Double-Button-1>', lambda _: self.selected('video.approve_cut'))
        row = tk.Frame(cut_tab, bg=BG)
        row.pack(fill='x')
        self.button(row, 'Preview', self.preview_cut).pack(side='left', padx=(0, 4))
        self.button(row, 'Approve', lambda: self.selected('video.approve_cut')).pack(side='left', padx=(0, 4))
        self.button(row, 'Restore', lambda: self.selected('video.restore_cut')).pack(side='left', padx=(0, 4))
        self.button(row, 'Approve all', lambda: self.submit('video.approve_all')).pack(side='right')
        manual = tk.Frame(cut_tab, bg=BG)
        manual.pack(fill='x', pady=4)
        self.label(manual, 'Cut seconds: ', size=8).pack(side='left')
        self.start_entry = tk.Entry(manual, width=7, bg=PANEL, fg=INK, insertbackground=INK, relief='flat')
        self.end_entry = tk.Entry(manual, width=7, bg=PANEL, fg=INK, insertbackground=INK, relief='flat')
        self.start_entry.pack(side='left', ipady=4)
        self.label(manual, ' → ', size=8).pack(side='left')
        self.end_entry.pack(side='left', ipady=4)
        self.button(manual, 'Propose', self.propose).pack(side='right')
        self.activity = self._text(activity_tab)
        self.transcript = self._text(transcript_tab)
        self.label(pref_tab, 'Save a preference only when you want to reuse it.', color=MUTED, size=8).pack(fill='x', pady=8)
        row = tk.Frame(pref_tab, bg=BG)
        row.pack(fill='x')
        self.label(row, 'Pause length (seconds): ', size=9).pack(side='left')
        tk.Spinbox(row, from_=.2, to=20, increment=.5, textvariable=self.seconds, width=6,
                   bg=PANEL, fg=INK, buttonbackground=PANEL, relief='flat').pack(side='left')
        row = tk.Frame(pref_tab, bg=BG)
        row.pack(fill='x', pady=8)
        self.button(row, 'Save pause setting', self.remember).pack(side='left', padx=(0, 5))
        self.button(row, 'Reset pause setting', lambda: self.submit('memory.delete_preference', key='pause_threshold')).pack(side='left')
        self.pref_text = self.label(pref_tab, '', color=GREEN, size=9)
        self.pref_text.pack(fill='x', pady=4)
        row = tk.Frame(pref_tab, bg=BG)
        row.pack(fill='x', pady=4)
        self.label(row, 'Listen up to (seconds): ', size=9).pack(side='left')
        tk.Spinbox(row, from_=.5, to=25, increment=.5, textvariable=self.capture_seconds, width=5,
                   bg=PANEL, fg=INK, buttonbackground=PANEL, relief='flat').pack(side='left')
        self.button(row, 'Save', self.save_capture_duration).pack(side='left', padx=4)
        footer = tk.Frame(self.details, bg=BG)
        footer.pack(side='bottom', fill='x', before=notebook)
        row = tk.Frame(footer, bg=BG)
        row.pack(fill='x', padx=16, pady=(0, 5))
        self.button(row, '↶ Undo', lambda: self.submit('video.undo')).pack(side='left', padx=(0, 5))
        self.button(row, 'Clear edits', lambda: self.submit('video.clear_edits')).pack(side='left')
        self.button(row, 'Export MP4', self.export, True).pack(side='right')
        row = tk.Frame(footer, bg=BG)
        row.pack(fill='x', padx=16, pady=(0, 5))
        tk.Checkbutton(row, text='Add subtitles', variable=self.burn, bg=BG, fg=MUTED,
                       selectcolor=PANEL, activebackground=BG, activeforeground=INK, font=('Segoe UI', 8)).pack(side='left')
        self.button(row, 'Export edit list', self.export_edl).pack(side='right')
        self._refresh(self.cached)

    def _text(self, frame):
        text = tk.Text(frame, bg=PANEL, fg=INK, wrap='word', font=('Segoe UI', 9), relief='flat', height=5, state='disabled')
        text.pack(fill='both', expand=True, pady=6)
        return text

    def _drag_start(self, event):
        self.drag_offset = (event.x_root-self.winfo_x(), event.y_root-self.winfo_y())

    def _drag(self, event):
        self._place(event.x_root-self.drag_offset[0], event.y_root-self.drag_offset[1])
        if self.notice is not None:
            self._position_notice()

    def toggle(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.details.pack(side='top', fill='both', expand=True)
        else:
            self.details.pack_forget()
        self._size()

    def _seconds(self):
        try:
            return float(self.seconds.get())
        except ValueError:
            return float('nan')  # Controller produces a visible validation error.

    def _log(self, value):
        self.activity.configure(state='normal')
        self.activity.insert('end', value + '\n\n')
        self.activity.see('end')
        self.activity.configure(state='disabled')

    def _refresh(self, state):
        if state['source'] and state['source'] != self.cached.get('source'):
            self.notebook.select(1)  # Opening media brings its review controls into view.
        self.burn.set(state['subtitles'])
        self.cached = state
        self.video_name.set(Path(state['source']).name if state['source'] else 'No video selected')
        approved = sum(c['status'] == 'approved' for c in state['cuts'])
        suggested = sum(c['status'] == 'suggested' for c in state['cuts'])
        self.stats.set(f'{suggested} suggested · {approved} approved   {state["original_duration"]:.1f}s → {state["edited_duration"]:.1f}s')
        self.cut_list.delete(0, 'end')
        for c in state['cuts']:
            detail = (' · '+c.get('detail','')[:30]) if c['reason'] == 'filler_word' else ''
            self.cut_list.insert('end', f'{c["status"][:4].upper():4} {c["start"]:6.2f}–{c["end"]:6.2f}s  {c["reason"]}{detail}')
        saved = []
        if 'pause_threshold' in state['preferences']:
            saved.append(f"Pauses over {state['preferences']['pause_threshold']:g}s")
        if 'burn_subtitles' in state['preferences']:
            saved.append('Subtitles '+('on' if state['preferences']['burn_subtitles'] else 'off'))
        self.pref_text.config(text=' · '.join(saved) if saved else 'No saved preferences yet')
        self.seconds.set(str(state['pause_threshold']))
        self.transcript.config(state='normal')
        self.transcript.delete('1.0', 'end')
        for s in state['transcript']:
            self.transcript.insert('end', f'[{s["start"]:.1f}–{s["end"]:.1f}s · {s.get("timing", "segment")}]\n{s["text"]}\n\n')
        self.transcript.config(state='disabled')

    def work(self, function, task):
        if self.busy:
            self.status.set('A task is running. Wait for its result.')
            return
        self.busy = True
        self.status_label.configure(fg=INK)
        self.status.set(task)
        if self.notice is not None:
            self._show_notice(task)
        for b in self.buttons:
            b.config(state='disabled')
        subtitle_setting = self.burn.get()
        def worker():
            try:
                # The checkbox is a session setting, including for "remember same settings".
                self.controller.subtitle_requested = subtitle_setting
                result = function()
                self.events.put((result, self.controller.state()))
            except Exception as exc:
                self.events.put(({'ok': False, 'tool': 'desktop', 'error': {'type':type(exc).__name__, 'message': str(exc)}}, None))
        self.executor.submit(worker)

    def submit(self, tool, **arguments):
        if tool in {'camera.open', 'camera.start_recording', 'camera.resume_recording'} and self.device_consent is not True:
            self._request_permissions(lambda: self.submit(tool, **arguments))
            return
        tasks = {'video.inspect':'Opening your video…', 'video.detect_pauses':'Finding long pauses…',
                 'video.detect_fillers':'Finding filler words locally… First use downloads the speech model.',
                 'video.transcribe':'Transcribing your video…', 'video.detect_retakes':'Looking for repeated takes…',
                 'video.export':'Exporting your edited copy…', 'video.export_edl':'Saving your edit list…'}
        self.work(lambda: self.controller.call(tool, **arguments), tasks.get(tool, 'Updating your request…'))

    def _poll(self):
        if self.closed:
            return
        try:
            result, state = self.events.get_nowait()
        except queue.Empty:
            self.after(80, self._poll)
            return
        if 'device_status' in result:
            self.devices = result['device_status']
            self._log('Local devices: ' + json.dumps(self.devices, ensure_ascii=False))
            if not self.busy and self.device_consent is True and not self.permission_prompt_open:
                for key, capability in (('camera', 'camera'), ('microphone', 'microphone')):
                    if self.devices.get(key, {}).get('status') == 'blocked':
                        self.status.set(f'Error: Windows blocks {capability} access. Open Windows privacy settings to allow it.')
                        break
            self.after(80, self._poll)
            return
        if 'phase' in result:
            phase, message = result['phase'], result['message']
            if phase != self.voice_phase:
                self._log(f'Voice · {phase}: {message}')
            self.voice_phase = phase
            if 'interpreted' in result:
                self.execution.set(f"INTERPRETED: {result['interpreted']}\nTARGET: {result.get('target') or '—'}   RESULT: EXECUTING")
            if phase == 'listening':
                self.mic.set('● LISTENING · ' + message)
                self.status.set('Speak your command now. The input level shows whether audio is reaching KAAT.')
            elif phase == 'recognized':
                self.heard.set('Heard: ' + message[:110])
                self.mic.set('MIC OFF · INTERPRETING COMMAND')
                self.status.set('Recognized speech. Resolving the command…')
            else:
                self.mic.set('MIC OFF · ' + phase.upper())
                self.status.set(message)
            if self.notice is not None:
                self._show_notice('Heard: ' + message if phase == 'recognized' else
                    'Speak now. KAAT sends your command after a one-second pause.\n\n' + message if phase == 'listening' else message)
            self.after(80, self._poll)
            return
        self.busy = False
        self.last_result = dict(result)
        self.voice_phase = 'idle'
        self.voice_cancel = None
        self.speak_button.config(text='\ue720', command=self.hear)
        for b in self.buttons:
            b.config(state='normal')
        self.mic.set('Microphone off')
        if state:
            self._refresh(state)
        heard = result.get('heard')
        if 'heard' in result:
            self.heard.set('Heard: ' + result['heard'][:110])
            self._log('Prisma heard: ' + result.pop('heard'))
        self._log(json.dumps(result, ensure_ascii=False, indent=2))
        self.execution.set(f"INTERPRETED: {result.get('interpreted', result.get('tool', 'unknown'))}\n"
            f"TARGET: {result.get('target') or '—'}   RESULT: {result.get('status', 'success' if result['ok'] else 'failed').upper()}"
            + (' · VERIFIED' if result.get('verified') else ''))
        if result['ok']:
            if result.get('data', {}).get('choose_source'):
                self.select()
            elif result.get('data', {}).get('choose_output'):
                self.export()
            elif result.get('tool') == 'video.export':
                self.status.set('Saved: ' + result['data']['output'])
            elif result.get('tool') == 'video.transcribe':
                self.status.set('Transcript ready. Captions use broad audio segments; check them before export.')
            elif result.get('tool') == 'video.detect_pauses':
                cuts = result['data'].get('cuts', [])
                self.status.set(f'Found {len(cuts)} pause cut(s). Review and approve them before export.' if cuts else
                                'No pauses matched this threshold. No edits were made; try a shorter threshold or inspect the recording.')
            else:
                messages = {'video.inspect':'Video ready. Speak a request or choose a tool.',
                            'video.approve_cut':'Cut approved.', 'video.approve_all':'Suggested cuts approved.',
                            'video.restore_cut':'Cut restored.', 'video.undo':'Last edit undone.',
                            'video.clear_edits':'Edits cleared. Your original is unchanged.',
                            'memory.save_preference':'Preference saved.', 'memory.delete_preference':'Preference reset.'}
                self.status.set(result.get('follow_up') or result.get('data', {}).get('message') or
                                messages.get(result.get('tool'), 'Done. Your original is unchanged.'))
        else:
            self.status_label.configure(fg='#ffb4a9')
            prefix = 'Warning: ' if result.get('status') in {'needs_attention', 'needs_clarification'} else 'Error: '
            self.status.set(prefix + result.get('error', {}).get('message', 'Task failed'))
        warnings = list(result.get('warnings', []))
        if isinstance(result.get('data'), dict) and result['data'].get('warning'):
            warnings.append(result['data']['warning'])
        if state and state.get('memory_warning'):
            warnings.append(state['memory_warning'])
        if result['ok'] and warnings:
            message = '; '.join(dict.fromkeys(warnings))
            self.status.set('Warning: ' + message)
            self._log('Warning: ' + message)
        if heard or result.get('tool', '').startswith(('camera.', 'system.')):
            self._show_notice(('HEARD: ' + heard + '\n\n' if heard else '') + self.execution.get() + '\n\n' + self.status.get(),
                              transient=result['ok'] and result.get('status') == 'success')
        if result.get('intent') == 'clarify_recording' and result.get('status') == 'needs_clarification':
            self._show_notice(('Heard: ' + heard + '\n\n' if heard else '') + result['error']['message'])
            self.notice_action.config(text='Start recording', command=lambda: self.submit('camera.start_recording', approved=True))
            self.notice_action.pack(side='left')
            self.notice_dismiss.config(text='Not now')
            self.notice.update_idletasks()
            self._position_notice()
        self.after(80, self._poll)

    def select(self):
        if self.busy:
            return
        source = filedialog.askopenfilename(parent=self, title='Choose source video', filetypes=[('Video', '*.mp4 *.mov *.mkv *.webm *.avi')])
        if source:
            self.submit('video.inspect', source=source)

    def run_command(self):
        words = self.command_entry.get().strip()
        if words and not self.busy:
            from commands import parse_command
            if self.device_consent is not True and parse_command(words)[0] in {'open_camera', 'record_start', 'record_resume'}:
                self._request_permissions(lambda: self._run_typed_command(words))
                return
            self._run_typed_command(words)

    def _run_typed_command(self, words):
        if not self.busy:
            self.heard.set('Typed: ' + words[:110])
            self.command_entry.delete(0, 'end')
            self.work(lambda: self._execute_command(words), 'Recognizing command…')

    def _execute_command(self, words):
        from commands import parse_command
        intent, args = parse_command(words)
        self.events.put(({'phase':'executing', 'message':'Executing the requested action…',
            'interpreted':intent, 'target':next(iter(args.values()), 'KAAT-opened windows' if intent == 'close_recent' else 'camera' if intent == 'open_camera' else 'current video')}, None))
        return self.controller.command(words, activated=True)

    def save_capture_duration(self):
        from voice import recording_duration
        try:
            duration = recording_duration(float(self.capture_seconds.get()))
        except ValueError as exc:
            self.status.set('Error: ' + str(exc))
            return
        self.submit('memory.save_preference', key='capture_seconds', value=duration, approved=True)

    def cancel_listening(self):
        with self.voice_dispatch_lock:
            if self.voice_cancel is not None:
                self.voice_cancel.set()
                self.speak_button.config(state='disabled')
                self.status.set('Cancelling voice request. No command will be executed.')

    def hear(self):
        if self.busy:
            if self.voice_cancel is not None:
                self.cancel_listening()
                return
            self.status.set('A task is running. Wait for its result.')
            return
        if self.device_consent is not True:
            self._request_permissions(self.hear)
            return
        if not os.getenv('GNANI_API_KEY'):
            self.status_label.configure(fg='#ffb4a9')
            self.status.set('Error: GNANI NOT CONNECTED — CHECK API KEY. Set GNANI_API_KEY in .env and restart KAAT.')
            return
        from voice import recording_duration
        try:
            duration = recording_duration(float(self.capture_seconds.get()))
        except ValueError as exc:
            self.status.set('Error: ' + str(exc))
            return
        self.heard.set('Waiting for a new spoken command…')
        self._dismiss_notice()
        self._show_notice('Getting microphone ready. Wait for Listening before speaking.')
        self.last_result = None
        self.mic.set('MIC OFF · PREPARING')
        cancelled = self.voice_cancel = threading.Event()
        def voice():
            from voice import hear_command, VoiceCancelled
            def progress(phase, message):
                if not cancelled.is_set():
                    self.events.put(({'phase':phase, 'message':message}, None))
            try:
                words = hear_command(seconds=duration, on_phase=progress, cancel_event=cancelled)
                with self.voice_dispatch_lock:
                    if cancelled.is_set():
                        raise VoiceCancelled('Voice request cancelled')
                    # Capture is over; cancellation cannot undo an already dispatched tool.
                    self.voice_cancel = None
                return {**self._execute_command(words), 'heard': words}
            except VoiceCancelled:
                return {'ok':True, 'tool':'voice.cancel', 'status':'cancelled', 'verified':False,
                        'data':{'message':'Listening cancelled. No command executed.'}}
        self.work(voice, 'Preparing microphone; wait for Listening before speaking…')
        self.speak_button.config(state='normal', text='\ue71a', command=self.cancel_listening)

    def selected(self, tool):
        selected = self.cut_list.curselection()
        if selected:
            self.submit(tool, cut_id=self.cached['cuts'][selected[0]]['id'])
        else:
            self.status.set('Select a proposed cut first.')

    def preview_cut(self):
        selected = self.cut_list.curselection()
        if not selected or not self.cached['source']:
            self.status.set('Select a proposed cut first.')
            return
        import subprocess
        from engine import _binary
        cut = self.cached['cuts'][selected[0]]
        try:
            subprocess.Popen([_binary('ffplay'), '-nodisp', '-autoexit', '-loglevel', 'error',
                '-ss', str(max(0,cut['start']-.35)), '-t', str(cut['end']-max(0,cut['start']-.35)+.35),
                self.cached['source']], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.status.set('Playing the proposed cut with a little surrounding audio. Approve only if it is correct.')
        except (OSError, RuntimeError) as exc:
            self.status.set('Error: '+str(exc))

    def propose(self):
        try:
            start, end = float(self.start_entry.get()), float(self.end_entry.get())
        except ValueError:
            self.status.set('Enter source start and end in seconds.')
            return
        self.submit('video.propose_cut', start=start, end=end)

    def remember(self):
        self.submit('memory.save_preference', key='pause_threshold', value=self._seconds(), approved=True)

    def export(self):
        if not self.cached['source']:
            self.status.set('Select a video first.')
            return
        source = Path(self.cached['source'])
        target = filedialog.asksaveasfilename(parent=self, title='Export a fresh edited copy', initialfile=source.stem+'_kaat_edit.mp4',
                                            initialdir=str(source.parent), defaultextension='.mp4', filetypes=[('MP4', '*.mp4')])
        if target:
            self.submit('video.export', output=target, subtitles=self.burn.get())

    def export_edl(self):
        target = filedialog.asksaveasfilename(parent=self, title='Export all decisions', defaultextension='.json', filetypes=[('JSON', '*.json')])
        if target:
            self.submit('video.export_edl', output=target)

    def close(self):
        if self.busy:
            self.status.set('Wait for the current operation to finish before closing.')
            return
        self.closed = True
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.controller.close()
        self.destroy()


Whisper = Kaat

if __name__ == '__main__':
    load_dotenv(Path(__file__).with_name('.env'))
    Whisper().mainloop()
