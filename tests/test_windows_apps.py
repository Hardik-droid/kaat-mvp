"""Launcher unit checks. Native integration is scripts/check_windows_apps.py."""
import pytest

from tools import windows_apps as apps


@pytest.mark.parametrize(('name','expected'),[
    (' Google Chrome ','chrome'),('CALC','calculator'),('File Explorer','explorer'),
    ('Windows Camera','camera'),('Photos','photos'),('Google Photos','google photos'),
])
def test_explicit_aliases(name,expected):
    assert apps.canonical_name(name)==expected


@pytest.mark.parametrize('url',[
    'file:///C:/Windows/System32/calc.exe','javascript:alert(1)','ms-settings:privacy-webcam',
    'https://user:password@example.com/','https://example.com/\nstart',
    'https://example.com:bad/','https://example.com:99999/','http://',
])
def test_unsafe_url_is_rejected(url):
    with pytest.raises(ValueError):apps.validate_url(url)


@pytest.mark.parametrize(('requested','observed','matches'),[
    ('https://www.youtube.com/','youtube.com',True),
    ('https://www.youtube.com/','https://youtube.com/',False),
    ('https://photos.google.com/','photos.google.com/u/0/',True),
    ('https://example.com/a','example.com/b',False),
    ('https://example.com/a?q=one','example.com/a?q=two',False),
    ('https://example.com/','example.com.evil.invalid',False),
    ('https://example.com/','http://example.com/',False),
    ('https://example.com:443/a','example.com/a',True),
    ('https://photos.google.com/','https://accounts.google.com/ServiceLogin?continue=https%3A%2F%2Fphotos.google.com%2F',True),
    ('https://photos.google.com/','https://accounts.google.com/?continue=https://evil.invalid/photos.google.com',False),
])
def test_browser_address_evidence(requested,observed,matches):
    assert apps._address_matches(requested,observed)==matches


@pytest.mark.parametrize('name',['cmd /c calc','cmd.exe /c anything','powershell -Command whoami','chrome;calc','chrome | calc','chrome --incognito'])
def test_command_line_cannot_be_dispatched(monkeypatch,name):
    monkeypatch.setattr(apps,'_windows',lambda:None)
    monkeypatch.setattr(apps,'_executables',lambda:{})
    monkeypatch.setattr(apps,'_registered_apps',lambda:[])
    monkeypatch.setattr(apps.subprocess,'Popen',lambda *a,**kw:pytest.fail('Unsafe dispatch'))
    with pytest.raises(ValueError):apps.open_application(name)


def test_missing_application_is_a_genuine_failure(monkeypatch):
    monkeypatch.setattr(apps,'_windows',lambda:None)
    monkeypatch.setattr(apps,'_executables',lambda:{})
    monkeypatch.setattr(apps,'_registered_apps',lambda:[{'name':'Example & Another','app_id':'installed'}])
    with pytest.raises(FileNotFoundError):apps.open_application('Nonexistent Application')


def test_ambiguous_application_is_not_guessed(monkeypatch):
    monkeypatch.setattr(apps,'_windows',lambda:None)
    monkeypatch.setattr(apps,'_executables',lambda:{})
    monkeypatch.setattr(apps,'_registered_apps',lambda:[{'name':'Example','app_id':'one'}, {'name':'Example','app_id':'two'}])
    with pytest.raises(ValueError,match='ambiguous'):apps.open_application('Example')


def test_launch_acceptance_is_not_verified_success(monkeypatch):
    monkeypatch.setattr(apps,'_windows',lambda:None)
    monkeypatch.setattr(apps,'_executables',lambda:{'notepad':'trusted.exe'})
    monkeypatch.setattr(apps,'_matching_windows',lambda *a:[])
    monkeypatch.setattr(apps.subprocess,'Popen',lambda *a,**kw:None)
    times=iter([0,8])
    monkeypatch.setattr(apps.time,'monotonic',lambda:next(times))
    result=apps.open_application('notepad')
    assert result['status']=='unverified' and result['verified'] is False
