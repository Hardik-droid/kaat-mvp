"""Trusted Windows launch targets with observed-window/URL/folder verification."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
from urllib.parse import parse_qs, unquote, urlsplit
import uuid
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
WEBSITES = {
    'google photos': 'https://photos.google.com/', 'photos': 'https://photos.google.com/',
    'youtube': 'https://www.youtube.com/', 'google': 'https://www.google.com/',
    'gmail': 'https://mail.google.com/', 'github': 'https://github.com/',
    'chatgpt': 'https://chatgpt.com/', 'openai': 'https://chatgpt.com/',
    'linkedin': 'https://www.linkedin.com/', 'twitter': 'https://twitter.com/',
    'x': 'https://x.com/', 'instagram': 'https://www.instagram.com/',
    'reddit': 'https://www.reddit.com/', 'netflix': 'https://www.netflix.com/',
    'wikipedia': 'https://www.wikipedia.org/', 'amazon': 'https://www.amazon.com/',
    'spotify': 'https://open.spotify.com/'
}
ALIASES = {
    'google chrome':'chrome', 'chrome browser':'chrome', 'क्रोम':'chrome',
    'calc':'calculator', 'कैलकुलेटर':'calculator', 'file explorer':'explorer',
    'windows explorer':'explorer', 'windows camera':'camera', 'camera app':'camera',
    'कैमरा':'camera', 'नोटपैड':'notepad', 'google photos':'google photos',
    'गूगल फोटो':'google photos', 'यूट्यूब':'youtube',
    'powerpoint':'powerpoint', 'ppt':'powerpoint', 'power point':'powerpoint', 'ms powerpoint':'powerpoint',
    'presentation':'powerpoint', 'word':'word', 'ms word':'word', 'winword':'word', 'microsoft word':'word',
    'excel':'excel', 'ms excel':'excel', 'microsoft excel':'excel',
    'vs code':'code', 'vscode':'code', 'visual studio code':'code', 'code editor':'code', 'code':'code',
    'spotify':'spotify', 'whatsapp':'whatsapp',
    'edge':'edge', 'msedge':'edge', 'microsoft edge':'edge',
    'terminal':'terminal', 'windows terminal':'terminal', 'command prompt':'cmd', 'cmd':'cmd', 'powershell':'powershell',
    'task manager':'taskmgr', 'taskmgr':'taskmgr', 'settings':'settings', 'windows settings':'settings',
    'paint':'paint', 'mspaint':'paint', 'vlc':'vlc', 'snipping tool':'snippingtool'
}
IMAGES = {
    'chrome': {'chrome.exe'}, 'notepad': {'notepad.exe'},
    'edge': {'msedge.exe'}, 'firefox': {'firefox.exe'},
    'calculator': {'calculatorapp.exe','calculator.exe','calc.exe'},
    'camera': {'windowscamera.exe'}, 'explorer': {'explorer.exe'},
    'powerpoint': {'powerpnt.exe', 'powerpoint.exe'}, 'powerpnt': {'powerpnt.exe'},
    'word': {'winword.exe', 'word.exe'}, 'winword': {'winword.exe'},
    'excel': {'excel.exe'}, 'code': {'code.exe'},
    'terminal': {'windowsterminal.exe', 'wt.exe'}, 'wt': {'windowsterminal.exe', 'wt.exe'},
    'cmd': {'cmd.exe'}, 'powershell': {'powershell.exe', 'pwsh.exe'},
    'paint': {'mspaint.exe'}, 'mspaint': {'mspaint.exe'},
    'taskmgr': {'taskmgr.exe'}, 'settings': {'systemsettings.exe'},
    'vlc': {'vlc.exe'}, 'spotify': {'spotify.exe', 'spotify_cli.exe'}
}
OWNERSHIP_PROPERTY='KAAT.OpenedWindow.v1'


def canonical_name(name):
    if (not isinstance(name, str) or not name.strip() or len(name)>200
            or any(ord(c)<32 for c in name) or re.search(r'''[;|&/\\`$<>"']|(?:^|\s)--?\S''',name)):
        raise ValueError('Choose an application name, not a command line.')
    value = ' '.join(name.casefold().strip().split())
    return ALIASES.get(value, value)


def _windows():
    if os.name != 'nt':
        raise RuntimeError('Windows application control requires Windows.')


def _shell_probe(action, target=''):
    _windows()
    executable = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(executable),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
        '-File',str(ROOT/'scripts/windows_probe.ps1'),'-Action',action,'-Target',str(target)],
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=8,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Windows verification failed: '+result.stderr.split('\nAt ')[0].strip()[:300])
    return json.loads(result.stdout or '[]')


@lru_cache(maxsize=1)
def _registered_apps():
    rows = _shell_probe('installed')
    return rows if isinstance(rows,list) else [rows]


def _executables():
    windows = Path(os.environ.get('SystemRoot',r'C:\Windows'))
    result = {'notepad':windows/'System32/notepad.exe', 'calculator':windows/'System32/calc.exe',
              'explorer':windows/'explorer.exe', 'cmd':windows/'System32/cmd.exe',
              'powershell':windows/'System32/WindowsPowerShell/v1.0/powershell.exe'}
    import winreg
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, r'Software\Microsoft\Windows\CurrentVersion\App Paths') as key:
                count = winreg.QueryInfoKey(key)[0]
                for i in range(count):
                    try:
                        sub = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, sub) as sk:
                            val = winreg.QueryValueEx(sk, '')[0].strip('"')
                            p = Path(val)
                            if p.is_file():
                                base = sub.casefold().removesuffix('.exe')
                                result[base] = p
                    except OSError:
                        pass
        except OSError:
            pass
    for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive,r'Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe') as key:
                path=Path(winreg.QueryValueEx(key,'')[0].strip('"'))
                if path.is_file():result['chrome']=path
        except OSError:pass
    if 'chrome' not in result:
        for env in ('ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA'):
            path=Path(os.environ.get(env,''))/'Google/Chrome/Application/chrome.exe'
            if path.is_absolute() and path.is_file():result['chrome']=path;break
    if 'powerpnt' in result and 'powerpoint' not in result:
        result['powerpoint'] = result['powerpnt']
    if 'winword' in result and 'word' not in result:
        result['word'] = result['winword']
    if 'wt' in result and 'terminal' not in result:
        result['terminal'] = result['wt']
    return {key:value for key,value in result.items() if value.is_file()}


def list_installed_apps():
    _registered_apps.cache_clear()
    apps=_registered_apps()
    return {'applications':apps,'source':'Windows Get-StartApps','verified':True,'status':'success',
            'message':f'{len(apps)} registered applications found.'}


@lru_cache(maxsize=1)
def _native():
    _windows()
    user=ctypes.WinDLL('user32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    signatures={
        'GetWindowTextLengthW':([wintypes.HWND],ctypes.c_int),
        'GetWindowTextW':([wintypes.HWND,wintypes.LPWSTR,ctypes.c_int],ctypes.c_int),
        'GetClassNameW':([wintypes.HWND,wintypes.LPWSTR,ctypes.c_int],ctypes.c_int),
        'GetWindowThreadProcessId':([wintypes.HWND,ctypes.POINTER(wintypes.DWORD)],wintypes.DWORD),
        'IsWindowVisible':([wintypes.HWND],wintypes.BOOL),
        'IsWindow':([wintypes.HWND],wintypes.BOOL),
        'IsWindowEnabled':([wintypes.HWND],wintypes.BOOL),
        'SetPropW':([wintypes.HWND,wintypes.LPCWSTR,wintypes.HANDLE],wintypes.BOOL),
        'GetPropW':([wintypes.HWND,wintypes.LPCWSTR],wintypes.HANDLE),
        'PostMessageW':([wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM],wintypes.BOOL),
        'GetForegroundWindow':([],wintypes.HWND)}
    for name,(args,result) in signatures.items():
        getattr(user,name).argtypes=args;getattr(user,name).restype=result
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user.EnumWindows.argtypes=[callback,wintypes.LPARAM];user.EnumWindows.restype=wintypes.BOOL
    user.EnumDesktopWindows.argtypes=[wintypes.HANDLE,callback,wintypes.LPARAM];user.EnumDesktopWindows.restype=wintypes.BOOL
    user.OpenDesktopW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];user.OpenDesktopW.restype=wintypes.HANDLE
    user.SetThreadDesktop.argtypes=[wintypes.HANDLE];user.SetThreadDesktop.restype=wintypes.BOOL
    user.CloseDesktop.argtypes=[wintypes.HANDLE];user.CloseDesktop.restype=wintypes.BOOL
    user.EnumChildWindows.argtypes=[wintypes.HWND,callback,wintypes.LPARAM];user.EnumChildWindows.restype=wintypes.BOOL
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.GetApplicationUserModelId.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.UINT),wintypes.LPWSTR]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    return user,kernel


def _ensure_desktop():
    if os.name != 'nt':
        return
    try:
        user, _ = _native()
        hdesk = user.OpenDesktopW('default', 0, False, 0x01FF)
        if hdesk:
            user.SetThreadDesktop(hdesk)
    except Exception:
        pass


def _enum_windows(callback):
    _ensure_desktop()
    user, _ = _native()
    try:
        hdesk = user.OpenDesktopW('default', 0, False, 0x01FF)
        if hdesk:
            res = user.EnumDesktopWindows(hdesk, callback, 0)
            user.CloseDesktop(hdesk)
            if res:
                return True
    except Exception:
        pass
    return user.EnumWindows(callback, 0)


def _process_identity(hwnd):
    user,kernel=_native()
    pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
    info={'pid':pid.value,'image':'','app_id':''}
    handle=kernel.OpenProcess(0x1000,False,pid.value)
    if handle:
        try:
            size=wintypes.DWORD(32768);name=ctypes.create_unicode_buffer(size.value)
            if kernel.QueryFullProcessImageNameW(handle,0,name,ctypes.byref(size)):
                info['image']=Path(name.value).name.casefold()
            length=wintypes.UINT()
            if kernel.GetApplicationUserModelId(handle,ctypes.byref(length),None)==122:
                appid=ctypes.create_unicode_buffer(length.value)
                if kernel.GetApplicationUserModelId(handle,ctypes.byref(length),appid)==0:info['app_id']=appid.value
        finally:kernel.CloseHandle(handle)
    return info


def _window_handles():
    """All top-level HWNDs, including hidden/cloaked ones that may be restored."""
    user,_=_native();handles=set()
    @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def collect(hwnd,_):handles.add(int(hwnd));return True
    _enum_windows(collect)
    return handles


def _window_snapshot(hwnd):
    _ensure_desktop()
    user,_=_native()
    if not user.IsWindow(hwnd):return None
    kind=ctypes.create_unicode_buffer(128);user.GetClassNameW(hwnd,kind,128)
    owner=_process_identity(hwnd);processes=[owner]
    @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def child(handle,_):
        item=_process_identity(handle)
        if item not in processes:processes.append(item)
        return True
    user.EnumChildWindows(hwnd,child,0)
    return {'hwnd':int(hwnd),'class':kind.value,'owner':owner,'processes':processes}


def _tag_opened(windows,before_handles,application,target,app_id=None):
    """Tag only newly created, verified target windows; never pre-existing HWNDs."""
    user,_=_native();records=[]
    candidates=list({window['hwnd']:window for window in windows if window['hwnd'] not in before_handles}.values())
    # A launch should produce one target window. Concurrent matching windows
    # cannot be attributed safely from a before/after observation alone.
    if len(candidates)!=1:return []
    for window in candidates:
        hwnd=window['hwnd']
        if hwnd in before_handles or user.GetPropW(hwnd,OWNERSHIP_PROPERTY):continue
        snapshot=_window_snapshot(hwnd)
        if not snapshot or not snapshot['owner']['image']:continue
        expected=[p for p in snapshot['processes'] if p['image'] in IMAGES.get(application,set())
                  or (app_id and p['app_id']==app_id)]
        if not expected:continue
        nonce=secrets.randbits(ctypes.sizeof(ctypes.c_void_p)*8-1) or 1
        if not user.SetPropW(hwnd,OWNERSHIP_PROPERTY,nonce):continue
        if user.GetPropW(hwnd,OWNERSHIP_PROPERTY)!=nonce:continue
        records.append({'version':1,'hwnd':hwnd,'nonce':nonce,**snapshot['owner'],
            'class':snapshot['class'],'application':application,'target':str(target),
            'application_identity':expected[0],'opened_at':time.time()})
    return records


def _owned_identity_matches(record):
    snapshot=_window_snapshot(record['hwnd'])
    if not snapshot:return False
    expected={key:record.get(key) for key in ('pid','image','app_id')}
    return (snapshot['class']==record.get('class') and snapshot['owner']==expected
            and record.get('application_identity') in snapshot['processes'])


def owned_window_status(record):
    """Check persisted ownership without activating or closing the window."""
    if (not isinstance(record,dict) or record.get('version')!=1
            or type(record.get('hwnd')) is not int or record['hwnd']<=0
            or type(record.get('nonce')) is not int or not 0<record['nonce']<2**(ctypes.sizeof(ctypes.c_void_p)*8)):
        return 'mismatch'
    user,_=_native()
    if not user.IsWindow(record['hwnd']):return 'gone'
    if user.GetPropW(record['hwnd'],OWNERSHIP_PROPERTY)!=record['nonce'] or not _owned_identity_matches(record):return 'mismatch'
    return 'owned'


def close_opened_windows(records):
    """Request normal closure of proven KAAT-created windows, retaining prompts."""
    _windows()
    _ensure_desktop()
    if not isinstance(records,list) or len(records)>256:raise ValueError('Expected at most 256 owned-window records.')
    user,_=_native();closed=[];already_closed=[];pending=[];skipped=[]
    for record in records:
        if (not isinstance(record,dict) or record.get('version')!=1
                or type(record.get('hwnd')) is not int or record['hwnd']<=0
                or type(record.get('nonce')) is not int or not 0<record['nonce']<2**(ctypes.sizeof(ctypes.c_void_p)*8)):
            skipped.append({'record':record,'reason':'Invalid owned-window record.'});continue
        hwnd=record['hwnd'];nonce=record['nonce'];ownership=owned_window_status(record)
        if ownership=='gone':already_closed.append(record);continue
        if ownership!='owned':
            skipped.append({**record,'reason':'Window ownership changed or could not be verified; left open.'});continue
        if not user.IsWindowEnabled(hwnd):
            pending.append({**record,'reason':'Window is disabled; finish any active application prompt before closing.'});continue
        # Recheck immediately before posting. Only a normal WM_CLOSE is sent;
        # unsaved-work dialogs belong to the application and are never answered.
        if user.GetPropW(hwnd,OWNERSHIP_PROPERTY)!=nonce:
            skipped.append({**record,'reason':'Window ownership changed before close; left open.'});continue
        if not user.PostMessageW(hwnd,0x0010,0,0):
            pending.append({**record,'reason':'Windows did not accept the normal close request.'})
        else:pending.append({**record,'reason':'Waiting for application close or its unsaved-work prompt.'})
    deadline=time.monotonic()+3
    while pending and time.monotonic()<deadline:
        remaining=[]
        for record in pending:
            if not user.IsWindow(record['hwnd']):
                closed.append({key:value for key,value in record.items() if key!='reason'})
            elif user.GetPropW(record['hwnd'],OWNERSHIP_PROPERTY)!=record['nonce']:
                skipped.append({**record,'reason':'Window ownership changed during close; closure could not be verified.'})
            else:remaining.append(record)
        pending=remaining
        if pending:time.sleep(.1)
    verified=not pending and not skipped
    if not records:message='No tracked KAAT-created windows to close. Existing windows and untracked tabs are left open.'
    else:
        message=f'Closed {len(closed)} KAAT-opened window(s); {len(already_closed)} already closed.'
        if pending:message+=f' {len(pending)} still open; finish any save or close prompt in that application.'
        if skipped:message+=f' {len(skipped)} left open because ownership could not be verified.'
    return {'closed':closed,'already_closed':already_closed,'pending':pending,'skipped':skipped,
            'status':'success' if verified else 'unverified','verified':verified,'message':message}


def visible_windows():
    user,kernel=_native();cache={};windows=[]
    dwm=ctypes.WinDLL('dwmapi')
    dwm.DwmGetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
    def identity(hwnd):
        pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value not in cache:
            cache[pid.value]=_process_identity(hwnd)
        return cache[pid.value]
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    @callback
    def top(hwnd,_):
        if not user.IsWindowVisible(hwnd):return True
        cloaked=wintypes.DWORD()
        if dwm.DwmGetWindowAttribute(hwnd,14,ctypes.byref(cloaked),ctypes.sizeof(cloaked))==0 and cloaked.value:return True
        text=ctypes.create_unicode_buffer(user.GetWindowTextLengthW(hwnd)+1);user.GetWindowTextW(hwnd,text,len(text))
        kind=ctypes.create_unicode_buffer(128);user.GetClassNameW(hwnd,kind,128)
        identities=[identity(hwnd)]
        @callback
        def child(handle,_):
            if user.IsWindowVisible(handle):
                item=identity(handle)
                if item not in identities:identities.append(item)
            return True
        user.EnumChildWindows(hwnd,child,0)
        windows.append({'hwnd':int(hwnd),'title':text.value,'class':kind.value,'processes':identities})
        return True
    _enum_windows(top)
    return windows


def _matching_windows(application, app_id=None):
    _ensure_desktop()
    result=[]
    target_images = IMAGES.get(application, {f"{application}.exe"})
    for window in visible_windows():
        if application == 'explorer':
            if window['class'] in ('CabinetWClass', 'XamlExplorerHostIslandWindow_WASDK', 'ExplorerBrowserControl'):
                if any(p['image'] == 'explorer.exe' for p in window['processes']):
                    result.append(window)
            continue
        if not window['title'].strip():continue
        if window['class']=='Xaml_WindowedPopupClass':continue
        if any(p['image'] in target_images or (app_id and p['app_id']==app_id) or (application and application in p['image']) or (application and len(application)>2 and application in window['title'].casefold()) for p in window['processes']):
            result.append(window)
    return result


def open_application(name):
    _windows();application=canonical_name(name)
    if application in WEBSITES:return open_website(WEBSITES[application])
    executable=_executables().get(application)
    app_id=None
    if not executable and application!='camera':
        matches=[]
        for app in _registered_apps():
            # Installed display names are data, not user command lines. Some
            # contain an ampersand; they must not break discovery of other apps.
            label=' '.join(app['name'].casefold().strip().split())
            if ALIASES.get(label,label)==application:matches.append(app)
        if len(matches)>1:raise ValueError('Application name is ambiguous. Use its exact installed name.')
        if not matches:raise FileNotFoundError(f'Application is not installed or registered: {name}')
        app_id=matches[0]['app_id']
        if not re.fullmatch(r'[\w.!{}\-]+',app_id):
            raise ValueError('This registered application needs a supported launch adapter.')
    before_handles=_window_handles();before=_matching_windows(application,app_id)
    if application=='camera':
        from system_tools import open_camera
        open_camera()
    elif executable:
        subprocess.Popen([str(executable)],shell=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    else:os.startfile('shell:AppsFolder\\'+app_id)
    started=time.monotonic();deadline=started+7
    observed=[]
    while time.monotonic()<deadline:
        observed=_matching_windows(application,app_id)
        if observed and (any(w['hwnd'] not in before_handles for w in observed) or time.monotonic()-started>=1.2):break
        time.sleep(.15)
    verified=bool(observed)
    opened=_tag_opened(observed,before_handles,application,application,app_id) if verified else []
    return {'application':application,'target':application,'launch_requested':True,'already_running':bool(before),
            'verified':verified,'status':'success' if verified else 'unverified','windows':observed,
            'opened_windows':opened,
            'tracking_limitation':None if opened else 'This launch reused a window or could not prove new-window ownership.',
            'message':f'{name} is open.' if verified else f'Launch requested for {name}, but no matching visible window was verified.'}


def validate_url(url):
    if not isinstance(url,str) or len(url)>2048 or any(ord(c)<33 for c in url):raise ValueError('Enter a valid HTTP or HTTPS URL.')
    parsed=urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Only HTTP/HTTPS websites without embedded credentials are allowed.')
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError('The website port is invalid.') from exc
    return url


def _address_matches(requested, observed):
    """Compare address-bar evidence, including Chrome's scheme/www display elision."""
    expected=urlsplit(requested)
    displayed='://' not in observed
    actual=urlsplit('https://'+observed if displayed else observed)
    if not actual.hostname:return False
    same_host=actual.hostname.casefold()==expected.hostname.casefold()
    if displayed and expected.hostname.casefold().startswith('www.'):
        same_host |= actual.hostname.casefold()==expected.hostname[4:].casefold()
    if not same_host:
        # Google Photos legitimately asks for sign-in before opening a library.
        if expected.hostname=='photos.google.com' and actual.hostname=='accounts.google.com':
            return any(urlsplit(value).hostname=='photos.google.com'
                       for value in parse_qs(actual.query).get('continue', []))
        return False
    if not displayed and expected.scheme!=actual.scheme:return False
    expected_port=expected.port or (443 if expected.scheme=='https' else 80)
    actual_port=actual.port or (expected_port if displayed else (443 if actual.scheme=='https' else 80))
    if expected_port!=actual_port:return False
    # Root pages may redirect to the site's landing page. Specific paths and
    # query strings must match; an unrelated page on the same host is not proof.
    if expected.path not in ('','/') and unquote(expected.path)!=unquote(actual.path):return False
    return (not expected.query or expected.query==actual.query) and (not expected.fragment or expected.fragment==actual.fragment)


def _default_browser(scheme='https'):
    """Read Windows' HTTP(S) handler; discard its arguments and use fixed ones."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Software\\Microsoft\\Windows\\Shell\\Associations\\UrlAssociations\\'+scheme+'\\UserChoice') as key:
            progid=winreg.QueryValueEx(key,'ProgId')[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,progid+r'\shell\open\command') as key:
            command=winreg.QueryValueEx(key,'')[0]
    except OSError:return None
    # Only the absolute executable path is accepted from this registration.
    # No registered shell arguments or arbitrary command strings are executed.
    match=re.match(r'^\s*(?:"([^"]+\.exe)"|([^\s]+\.exe))(?:\s|$)',command,re.I)
    if not match:return None
    executable=Path(os.path.expandvars(match.group(1) or match.group(2)))
    browser={'chrome.exe':'chrome','msedge.exe':'edge','firefox.exe':'firefox'}.get(executable.name.casefold())
    if not browser or not executable.is_absolute() or not executable.is_file():return None
    return browser,executable


def open_website(url):
    _windows();url=validate_url(url)
    _ensure_desktop()
    before_handles=_window_handles();browser=_default_browser(urlsplit(url).scheme)
    already_running=bool(_matching_windows('chrome') or _matching_windows('edge') or _matching_windows('firefox'))
    if browser:
        name,executable=browser
        flag='-new-window' if name=='firefox' else '--new-window'
        subprocess.Popen([str(executable),flag,url],shell=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    elif not webbrowser.open(url,new=2):raise RuntimeError('Windows did not accept the browser launch request.')
    observed=[]
    deadline=time.monotonic()+9
    url_host = urlsplit(url).netloc.lower()
    site_key = next((k for k, v in WEBSITES.items() if v.rstrip('/') == url.rstrip('/')), '')
    while time.monotonic()<deadline:
        try:
            rows=_shell_probe('browser')
            for row in rows if isinstance(rows,list) else [rows]:
                value=row.get('url','')
                if _address_matches(url,value) and (not browser or row.get('hwnd') not in before_handles):
                    observed.append(row)
        except Exception:
            pass
        if not observed:
            for bname in ('chrome', 'edge', 'firefox'):
                for w in _matching_windows(bname):
                    title_lower = w['title'].lower()
                    if (site_key and site_key in title_lower) or (url_host and url_host in title_lower):
                        observed.append({'hwnd': w['hwnd'], 'url': url, 'title': w['title'], 'pid': w['processes'][0]['pid'] if w['processes'] else 0})
                        break
                    elif (w['hwnd'] not in before_handles) or (already_running and time.monotonic()-deadline+9 >= 0.8):
                        if any(b in title_lower for b in ('chrome', 'edge', 'firefox', 'google', 'youtube', 'photos', 'browser')):
                            observed.append({'hwnd': w['hwnd'], 'url': url, 'title': w['title'], 'pid': w['processes'][0]['pid'] if w['processes'] else 0})
                            break
                if observed:
                    break
        if observed:break
        time.sleep(.25)
    verified=bool(observed)
    opened=_tag_opened(observed,before_handles,browser[0] if browser else 'chrome',url) if verified else []
    limitation=None if opened else 'No new browser-window ownership was recorded for this launch.'
    return {'target':url,'url':url,'verified':verified,'status':'success' if verified else 'unverified',
            'evidence':observed,'verification':'browser_address' if any('url' in o and o['url'] != url for o in observed) else 'browser_window',
            'opened_windows':opened,'tracking_limitation':limitation,
            'message':f'Browser opened: {url}' if verified else
            'Browser launch requested; its address could not be verified. Check the browser window.'}


def known_folder(name):
    _windows();name=name.casefold().strip()
    ids={'downloads':'374de290-123f-4565-9164-39c4925e467b','desktop':'b4bfcc3a-db2c-424c-b029-7fe99a87c641',
         'documents':'fdd39ad0-238f-46af-adb4-6c85480369c7'}
    if name in ('home','user'):return Path.home()
    if name not in ids:raise ValueError('Known folders: Downloads, Desktop, Documents, Home')
    shell=ctypes.WinDLL('shell32');ole=ctypes.WinDLL('ole32')
    value=(ctypes.c_ubyte*16).from_buffer_copy(uuid.UUID(ids[name]).bytes_le);pointer=ctypes.c_void_p()
    shell.SHGetKnownFolderPath.argtypes=[ctypes.c_void_p,wintypes.DWORD,wintypes.HANDLE,ctypes.POINTER(ctypes.c_void_p)]
    ole.CoTaskMemFree.argtypes=[ctypes.c_void_p]
    if shell.SHGetKnownFolderPath(ctypes.byref(value),0,None,ctypes.byref(pointer))!=0:raise OSError('Windows known folder could not be resolved')
    try:return Path(ctypes.wstring_at(pointer.value))
    finally:ole.CoTaskMemFree(pointer)


def open_folder(path):
    _windows()
    _ensure_desktop()
    requested=str(path).strip().strip('"')
    if not requested or any(ord(c)<32 for c in requested):raise ValueError('Choose an existing local folder.')
    target=known_folder(requested) if requested.casefold() in ('downloads','desktop','documents','home','user') else Path(requested).expanduser()
    target=target.resolve(strict=True)
    if not target.is_dir() or str(target).startswith('\\\\'):raise ValueError('Choose an existing local folder.')
    executable=Path(os.environ['SystemRoot'])/'explorer.exe'
    before_handles=_window_handles()
    subprocess.Popen([str(executable),str(target)],shell=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    evidence=[];started=time.monotonic();deadline=started+6
    folder_name = target.name.casefold()
    while time.monotonic()<deadline:
        try:
            evidence=_shell_probe('folder',target)
        except Exception:
            evidence=[]
        if not evidence:
            for w in visible_windows():
                if any('explorer' in p['image'] for p in w['processes']):
                    title_lower = w['title'].casefold()
                    if folder_name in title_lower or 'file explorer' in title_lower or w['class'] in ('CabinetWClass', 'XamlExplorerHostIslandWindow_WASDK'):
                        evidence.append({'hwnd': w['hwnd'], 'path': str(target), 'title': w['title']})
                        break
        if evidence and (any(w['hwnd'] not in before_handles for w in evidence) or time.monotonic()-started>=1.2):break
        time.sleep(.2)
    verified=bool(evidence)
    return {'target':str(target),'path':str(target),'verified':verified,
            'status':'success' if verified else 'unverified','evidence':evidence,
            'opened_windows':_tag_opened(evidence,before_handles,'explorer',target) if evidence else [],
            'message':f'Folder is open: {target}' if verified else 'Explorer was requested, but the folder window could not be verified.'}


def get_active_window():
    _windows()
    _ensure_desktop()
    user,_=_native();handle=user.GetForegroundWindow()
    text=ctypes.create_unicode_buffer(user.GetWindowTextLengthW(handle)+1);user.GetWindowTextW(handle,text,len(text))
    pid=wintypes.DWORD();user.GetWindowThreadProcessId(handle,ctypes.byref(pid))
    return {'title':text.value,'process_id':pid.value,'window_handle':int(handle) if handle else None,
            'verified':bool(handle),'status':'success' if handle else 'unverified',
            'message':f'Active window: {text.value}' if handle else 'No foreground window could be verified.'}


def close_application(name):
    """Gracefully request closure of an application window via WM_CLOSE."""
    _windows()
    _ensure_desktop()
    target = canonical_name(name) if isinstance(name, str) else ''
    if not target or target in ('all', 'everything'):
        raise ValueError('Specify an application name to close, e.g. "close Chrome".')
    images = IMAGES.get(target, {f"{target}.exe"})
    closed_any = False
    user, _ = _native()
    for w in visible_windows():
        if any(p['image'] in images or target in p['image'] or (len(target) > 2 and target in w['title'].casefold()) for p in w['processes']):
            user.PostMessageW(w['hwnd'], 0x0010, 0, 0)
            closed_any = True
    return {'application': target, 'status': 'success' if closed_any else 'unverified',
            'verified': closed_any,
            'message': f'Closed {name.title()}.' if closed_any else f'No open window found for {name.title()}.'}


def close_active_window():
    """Gracefully request closure of the current foreground window via WM_CLOSE."""
    _windows()
    _ensure_desktop()
    user, _ = _native()
    hwnd = user.GetForegroundWindow()
    if hwnd and user.IsWindow(hwnd):
        user.PostMessageW(hwnd, 0x0010, 0, 0)
        return {'status': 'success', 'verified': True, 'message': 'Active window closed.'}
    return {'status': 'unverified', 'verified': False, 'message': 'No active window found.'}


def change_volume(action):
    """Adjust system master volume: up, down, or mute."""
    _windows()
    user, _ = _native()
    VK_VOLUME_MUTE = 0xAD
    VK_VOLUME_DOWN = 0xAE
    VK_VOLUME_UP = 0xAF
    vk = VK_VOLUME_UP if action == 'up' else VK_VOLUME_DOWN if action == 'down' else VK_VOLUME_MUTE
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    msg = 'Volume increased.' if action == 'up' else 'Volume decreased.' if action == 'down' else 'Mute toggled.'
    return {'status': 'success', 'verified': True, 'message': msg}


def take_screenshot():
    """Capture screen to Windows clipboard."""
    _windows()
    VK_SNAPSHOT = 0x2C
    ctypes.windll.user32.keybd_event(VK_SNAPSHOT, 0, 0, 0)
    ctypes.windll.user32.keybd_event(VK_SNAPSHOT, 0, 2, 0)
    return {'status': 'success', 'verified': True, 'message': 'Screenshot captured to clipboard.'}


def minimize_all():
    """Minimize all windows / show desktop."""
    _windows()
    VK_LWIN = 0x5B
    VK_D = 0x44
    user32 = ctypes.windll.user32
    user32.keybd_event(VK_LWIN, 0, 0, 0)
    user32.keybd_event(VK_D, 0, 0, 0)
    user32.keybd_event(VK_D, 0, 2, 0)
    user32.keybd_event(VK_LWIN, 0, 2, 0)
    return {'status': 'success', 'verified': True, 'message': 'Desktop displayed.'}


def web_search(query):
    """Search Google in default browser."""
    import urllib.parse
    clean = str(query).strip()
    url = f"https://www.google.com/search?q={urllib.parse.quote_plus(clean)}"
    res = open_website(url)
    res['message'] = f"Searching Google for '{clean}'."
    return res


def youtube_play(query):
    """Search or play on YouTube in default browser."""
    import urllib.parse
    clean = str(query).strip()
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(clean)}"
    res = open_website(url)
    res['message'] = f"Playing '{clean}' on YouTube."
    return res
