import base64
import io
import wave
import zipfile
import pytest
import requests
from app import create_app
from anki import card_fields, identity_tag
from manual import make_entries
from translation import translate
from test_reader import FakeAnki


def wav():
    out = io.BytesIO()
    with wave.open(out, 'wb') as f:
        f.setnchannels(1)
        f.setframerate(16000)
        f.setsampwidth(2)
        f.writeframes(b'\0\0' * 1600)
    return base64.b64encode(out.getvalue()).decode()


def test_manual_meanings_validation_and_safe_fields(tmp_path):
    client = create_app(tmp_path / 'db').test_client()
    assert client.post('/api/manual', json={'word': 'ספר', 'meanings': []}).status_code == 400
    assert client.post('/api/manual', json={'word': '', 'meanings': ['book']}).status_code == 400
    assert client.post('/api/manual', json={'word': 'ספר', 'meanings': ['book'], 'recording': 'invalid'}).status_code == 400
    assert client.post('/api/manual', json={'word': 'ספר', 'meanings': ['book'], 'genders': 'masculine'}).status_code == 400
    result = client.post('/api/manual', json=dict(word='סֵפֶר', meanings=['book', 'register', 'book'], pos='noun', genders=['masculine', 'feminine'], notes='<script>bad</script>'))
    assert result.status_code == 200
    first, second = result.json['entries']
    assert first['id'] != second['id'] and first['canonical']['plain'] == 'ספר'
    fields = card_fields(first)
    assert 'masculine' in fields['Grammar'] and 'feminine' in fields['Grammar']
    assert 'singular' not in fields['Grammar']  # Never guess grammar for user cards.
    assert fields['Source'] == 'Added manually'
    assert '<script>' not in fields['Forms'] and '&lt;script&gt;' in fields['Forms']
    assert 'recording' not in first
    # Entries survive a restart and export without requiring a dictionary lookup.
    client = create_app(tmp_path / 'db').test_client()
    tsv = client.post('/api/export', json={'ids': [first['id'], second['id']]}).text
    assert 'book' in tsv and 'register' in tsv and identity_tag(first) in tsv


def test_manual_audio_import_export_and_sense_identity(tmp_path, monkeypatch):
    app = create_app(tmp_path / 'db')
    fake = FakeAnki()
    def call(action, **params):
        if action == 'storeMediaFile':
            fake.actions.append((action, params))
            return params['filename']
        return fake.call(action, **params)
    monkeypatch.setattr(app.extensions['anki'], 'call', call)
    client = app.test_client()
    payload = dict(word='ספר', meanings=['book', 'register'], recording=wav())
    entries = client.post('/api/manual', json=payload).json['entries']
    ids = [e['id'] for e in entries]
    audio = client.get('/api/audio/' + ids[0])
    assert audio.data == base64.b64decode(payload['recording'])
    assert audio.content_type == 'audio/wav'
    archive = client.post('/api/export', json={'ids': ids})
    assert archive.content_type == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(archive.data)) as z:
        assert z.read(entries[0]['audio_filename']) == audio.data
        assert ('[sound:' + entries[0]['audio_filename'] + ']').encode() in z.read('hebrew-vocabulary.tsv')
    assert client.post('/api/sync', json={'deck': 'Hebrew'}).status_code == 200
    result = client.post('/api/import', json={'deck': 'Hebrew', 'ids': ids}).json
    assert result['imported'] == ids and not result['failed']
    assert len([a for a in fake.actions if a[0] == 'storeMediaFile']) == 2
    assert '[sound:' in fake.notes[1]['fields']['Pronunciation']['value']
    assert set(client.post('/api/sync', json={'deck': 'Hebrew'}).json['entries']) == set(ids)
    assert client.post('/api/import', json={'deck': 'Hebrew', 'ids': ids}).json['duplicates'] == ids
    assert len(fake.notes) == 2


def test_manual_can_add_intended_sense_despite_untagged_word():
    fake = FakeAnki()
    fake.notes[1] = dict(tags=[], modelName='Basic', fields={'Front': dict(value='ספר', order=0)})
    manual = make_entries(dict(word='ספר', meanings=['another sense']))[0]
    assert fake.add('Hebrew', [manual])['imported'] == [manual['id']]


def test_recording_limits():
    raw = io.BytesIO()
    with wave.open(raw, 'wb') as f:
        f.setnchannels(1); f.setframerate(16000); f.setsampwidth(2); f.writeframes(b'\0\0' * 16000 * 61)
    with pytest.raises(ValueError, match='at most 60 seconds'):
        make_entries(dict(word='ספר', meanings=['book'], recording=base64.b64encode(raw.getvalue()).decode()))


def test_translation_selection_order_and_chunking(monkeypatch, tmp_path):
    calls = []
    class Response:
        def raise_for_status(self): pass
        def json(self): return [calls[-1]]
    def get(url, params, timeout):
        assert url == 'https://clients5.google.com/translate_a/t'
        assert params['sl'] == 'he' and params['tl'] == 'en'
        calls.append(params['q'])
        return Response()
    monkeypatch.setattr('translation.requests.get', get)
    client = create_app(tmp_path / 'db').test_client()
    parts = ['שלום עולם', 'ספר ' * 1000, 'טוב']
    response = client.post('/api/translate', json={'parts': parts})
    assert response.status_code == 200
    assert response.json['translations'][0] == parts[0]
    assert response.json['translations'][-1] == parts[-1]
    assert ''.join(calls) == ''.join(parts)
    assert max(map(len, calls)) <= 1201
    for invalid in [[], [''], ['x' * 50001], 'text', [123]]:
        assert client.post('/api/translate', json={'parts': invalid}).status_code == 400


def test_translation_errors_are_actionable(monkeypatch, tmp_path):
    def unavailable(*args, **kwargs): raise requests.Timeout()
    monkeypatch.setattr('translation.requests.get', unavailable)
    client = create_app(tmp_path / 'db').test_client()
    result = client.post('/api/translate', json={'parts': ['שלום']})
    assert result.status_code == 400 and 'Google Translate' in result.json['error']
    class Blocked:
        def raise_for_status(self): pass
        def json(self): raise ValueError('HTML response')
    monkeypatch.setattr('translation.requests.get', lambda *a, **k: Blocked())
    with pytest.raises(ValueError, match='rate-limited'):
        translate(['שלום'])
