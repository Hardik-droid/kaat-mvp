"""Isolated ownership/close boundary units; no desktop windows are manipulated."""
from copy import deepcopy
import ctypes
import pytest
from tools import windows_apps as apps


def record(hwnd=10,nonce=123):
    return {'version':1,'hwnd':hwnd,'nonce':nonce,'pid':7,'image':'notepad.exe','app_id':'',
        'class':'Notepad','application':'notepad','target':'notepad','opened_at':1.,
        'application_identity':{'pid':7,'image':'notepad.exe','app_id':''}}


class FakeNative:
    def __init__(self):
        self.live={10,11};self.props={10:123,11:456};self.disabled=set();self.posted=[];self.tagged=[];self.mode='close'
    def IsWindow(self,hwnd):return hwnd in self.live
    def IsWindowEnabled(self,hwnd):return hwnd not in self.disabled
    def GetPropW(self,hwnd,_):return self.props.get(hwnd,0)
    def SetPropW(self,hwnd,_,nonce):self.props[hwnd]=nonce;self.tagged.append(hwnd);return True
    def PostMessageW(self,hwnd,message,*args):
        assert message==0x0010
        self.posted.append(hwnd)
        if self.mode=='close':self.live.remove(hwnd)
        elif self.mode=='forget':self.props.pop(hwnd,None)
        return True


@pytest.fixture
def native(monkeypatch):
    user=FakeNative()
    monkeypatch.setattr(apps,'_native',lambda:(user,None))
    monkeypatch.setattr(apps,'_windows',lambda:None)
    monkeypatch.setattr(apps,'_owned_identity_matches',lambda row:row['pid']==7)
    tick=iter(range(0,1000,2))
    monkeypatch.setattr(apps.time,'monotonic',lambda:next(tick))
    monkeypatch.setattr(apps.time,'sleep',lambda seconds:None)
    return user


def test_only_genuinely_new_windows_get_a_nonce(native,monkeypatch):
    native.props={}
    owner={'pid':7,'image':'notepad.exe','app_id':''}
    monkeypatch.setattr(apps,'_window_snapshot',lambda hwnd:{'hwnd':hwnd,'class':'Notepad','owner':owner,'processes':[owner]})
    rows=apps._tag_opened([{'hwnd':10},{'hwnd':11}],{10},'notepad','notepad')
    assert native.tagged==[11] and len(rows)==1 and rows[0]['hwnd']==11
    assert 0<rows[0]['nonce']<2**(ctypes.sizeof(ctypes.c_void_p)*8)
    assert native.props[11]==rows[0]['nonce']


def test_existing_nonce_is_never_overwritten(native,monkeypatch):
    monkeypatch.setattr(apps,'_window_snapshot',lambda hwnd:pytest.fail('Already tagged window must stay untouched'))
    assert apps._tag_opened([{'hwnd':10}],set(),'notepad','notepad')==[]
    assert native.tagged==[] and native.props[10]==123


def test_multiple_concurrent_new_windows_are_not_assumed_owned(native,monkeypatch):
    native.props={}
    monkeypatch.setattr(apps,'_window_snapshot',lambda hwnd:pytest.fail('Ambiguous windows must not be tagged'))
    assert apps._tag_opened([{'hwnd':10},{'hwnd':11}],set(),'notepad','notepad')==[]
    assert native.tagged==[]


def test_owned_close_is_verified_from_window_disappearance(native):
    result=apps.close_opened_windows([record()])
    assert native.posted==[10]
    assert len(result['closed'])==1 and result['verified'] is True and not result['pending']
    assert 11 in native.live


def test_reused_handle_or_changed_process_is_never_closed(native):
    wrong_nonce=record(nonce=999);wrong_process=record();wrong_process['pid']=99
    for row in (wrong_nonce,wrong_process):
        result=apps.close_opened_windows([row])
        assert result['skipped'] and not result['verified']
    assert native.posted==[] and native.live=={10,11}


def test_already_closed_record_needs_no_dispatch(native):
    native.live.remove(10)
    result=apps.close_opened_windows([record()])
    assert result['already_closed']==[record()] and result['verified'] is True
    assert native.posted==[]


def test_unsaved_work_keeps_pending_record(native):
    native.mode='keep'
    result=apps.close_opened_windows([record()])
    assert not result['closed'] and len(result['pending'])==1
    assert result['status']=='unverified' and not result['verified']
    assert native.posted==[10]


def test_existing_modal_prompt_is_not_sent_another_close(native):
    native.disabled.add(10)
    result=apps.close_opened_windows([record()])
    assert native.posted==[] and len(result['pending'])==1 and not result['verified']


def test_lost_nonce_on_surviving_window_is_not_fake_closed(native):
    native.mode='forget'
    result=apps.close_opened_windows([record()])
    assert not result['closed'] and result['skipped'] and not result['verified']


def test_invalid_record_never_dispatches(native):
    result=apps.close_opened_windows([{'hwnd':10,'nonce':123},record(hwnd=True)])
    assert len(result['skipped'])==2 and not result['verified'] and native.posted==[]


def test_ownership_status_is_read_only(native):
    assert apps.owned_window_status(record())=='owned'
    assert apps.owned_window_status(record(nonce=999))=='mismatch'
    assert apps.owned_window_status(record(hwnd=99))=='gone'
    assert native.posted==[]
