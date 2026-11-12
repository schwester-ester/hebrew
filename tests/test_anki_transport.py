import json
import subprocess
import pytest
import requests
from anki import Anki


def windows(monkeypatch):
    monkeypatch.setattr('anki.platform.system', lambda: 'Linux')
    monkeypatch.setattr('anki.platform.release', lambda: '6.18-microsoft-standard-WSL2')
    monkeypatch.setattr('anki.shutil.which', lambda name: '/mnt/c/Windows/System32/curl.exe')


def test_wsl_fallback_sends_unicode_and_large_audio_via_stdin(monkeypatch):
    windows(monkeypatch)
    linux_calls, windows_calls = [], []
    def refused(*args, **kwargs):
        linux_calls.append(kwargs)
        raise requests.ConnectionError('refused')
    def run(command, **kwargs):
        windows_calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps({'result': ['עברית'], 'error': None}), '')
    monkeypatch.setattr('anki.requests.post', refused)
    monkeypatch.setattr('anki.subprocess.run', run)
    client = Anki()
    assert client.decks() == ['עברית']
    assert client.call('storeMediaFile', filename='recording.wav', data='A' * 100000) == ['עברית']
    assert len(linux_calls) == 1 and len(windows_calls) == 2
    command, kwargs = windows_calls[1]
    payload = json.loads(kwargs['input'])
    assert payload['params']['data'] == 'A' * 100000
    assert '@-' in command and not any(len(arg) > 100 for arg in command)
    assert kwargs['encoding'] == 'utf-8'
    assert command[command.index('--noproxy') + 1] == '*'


def test_native_linux_does_not_try_windows(monkeypatch):
    monkeypatch.setattr('anki.platform.system', lambda: 'Linux')
    monkeypatch.setattr('anki.platform.release', lambda: '6.18-generic')
    def refused(*args, **kwargs): raise requests.ConnectionError()
    monkeypatch.setattr('anki.requests.post', refused)
    monkeypatch.setattr('anki.subprocess.run', lambda *a, **k: pytest.fail('Unexpected Windows process'))
    with pytest.raises(ValueError, match='Restart Anki'):
        Anki().decks()


@pytest.mark.parametrize('body,code,message', [
    ('', 7, 'on Windows'), ('not JSON', 0, 'invalid response'),
    ('[]', 0, 'invalid response'),
    ('{"result": null, "error": "authentication required"}', 0, 'authentication required')])
def test_windows_errors_are_actionable(monkeypatch, body, code, message):
    windows(monkeypatch)
    def refused(*args, **kwargs): raise requests.ConnectionError()
    monkeypatch.setattr('anki.requests.post', refused)
    monkeypatch.setattr('anki.subprocess.run', lambda command, **kw: subprocess.CompletedProcess(command, code, body, ''))
    with pytest.raises(ValueError, match=message):
        Anki().decks()


def test_working_linux_connection_stays_native(monkeypatch):
    windows(monkeypatch)
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'result': 6, 'error': None}
    monkeypatch.setattr('anki.requests.post', lambda *a, **kw: Response())
    monkeypatch.setattr('anki.subprocess.run', lambda *a, **k: pytest.fail('Unexpected fallback'))
    assert Anki().call('version') == 6
