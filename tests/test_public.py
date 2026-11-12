import io
import sqlite3
import zipfile
import pytest
from app import create_app
from portable import portable_entry
from test_features import wav
from test_reader import entry


def public_app(tmp_path, monkeypatch):
    monkeypatch.setenv('IVRIT_ALLOWED_HOSTS', 'ivrit.example')
    return create_app(tmp_path / 'public.sqlite3', public=True)


def test_public_host_health_and_origin_checks(tmp_path, monkeypatch):
    app = public_app(tmp_path, monkeypatch)
    client = app.test_client()
    assert client.get('/', base_url='https://ivrit.example').status_code == 200
    assert b'data-public="true"' in client.get('/').data
    assert client.get('/healthz', base_url='https://ivrit.example').json == {'status': 'ok'}
    assert client.get('/', base_url='https://untrusted.example').status_code == 400
    response = client.post('/api/text', json={'text': 'ספר'}, base_url='https://ivrit.example', headers={'Origin': 'https://evil.example'})
    assert response.status_code == 403
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.post('/api/text', json=[], base_url='https://ivrit.example').status_code == 400


def test_public_routes_never_reach_desktop_anki(tmp_path, monkeypatch):
    app = public_app(tmp_path, monkeypatch)
    monkeypatch.setattr(app.extensions['anki'], 'call', lambda *a, **kw: pytest.fail('Public service contacted desktop Anki'))
    client = app.test_client()
    for path, method in [('decks', 'get'), ('sync', 'post'), ('import', 'post'), ('skip', 'post'), ('audio/manual-'+'a'*32, 'get')]:
        result = getattr(client, method)('/api/' + path, **({'json': {}} if method == 'post' else {}))
        assert result.status_code == 404


def test_public_cards_are_stateless_and_export_after_restart(tmp_path, monkeypatch):
    app = public_app(tmp_path, monkeypatch)
    client = app.test_client()
    # Even a mistakenly reused local database must not expose local skips.
    app.extensions['store'].skip('ספר')
    assert not client.post('/api/text', json={'text': 'ספר'}).json['tokens'][0]['known']
    cards = client.post('/api/manual', json={'word': 'ספר', 'meanings': ['book', 'register'], 'recording': wav()}).json['entries']
    assert cards[0]['recording']
    with sqlite3.connect(app.extensions['store'].path) as db:
        assert db.execute('SELECT COUNT(*) FROM entries').fetchone()[0] == 0
    # A completely fresh server can export browser-supplied cards and audio.
    restarted = create_app(tmp_path / 'fresh.sqlite3', public=True).test_client()
    response = restarted.post('/api/export', json={'entries': cards + [entry('adjective')]})
    assert response.status_code == 200 and response.content_type == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert len([name for name in archive.namelist() if name.endswith('.wav')]) == 2
        tsv = archive.read('hebrew-vocabulary.tsv').decode()
        assert 'book' in tsv and 'register' in tsv and 'pealim::5422' in tsv
    # IDs never retrieve someone else's server-local entries.
    assert restarted.post('/api/export', json={'ids': ['6104']}).status_code == 400
    assert restarted.get('/api/audio/' + cards[0]['id']).status_code == 404


def test_public_export_validation_rejects_injection_and_bad_shapes(tmp_path, monkeypatch):
    client = public_app(tmp_path, monkeypatch).test_client()
    for field, value in [('url', 'javascript:alert(1)'), ('id', '../../secret'), ('canonical', []), ('forms', []), ('meaning', 42)]:
        card = entry()
        card[field] = value
        assert client.post('/api/export', json={'entries': [card]}).status_code == 400
    card = entry('adjective')
    card['meaning'] = '<script>alert(1)</script>'
    response = client.post('/api/export', json={'entries': [card]})
    assert '<script>' not in response.text and '&lt;script&gt;' in response.text
    assert client.post('/api/export', json={'entries': []}).status_code == 400
    assert client.post('/api/export', json={'entries': ['bad']}).status_code == 400
    manual = client.post('/api/manual', json={'word': 'ספר', 'meanings': ['book'], 'recording': wav()}).json['entries'][0]
    manual['audio_filename'] = '../../escape.wav'
    assert portable_entry(manual)['audio_filename'] == manual['id'] + '.wav'


def test_public_translation_limit_and_busy_slot_release(tmp_path, monkeypatch):
    app = public_app(tmp_path, monkeypatch)
    client = app.test_client()
    assert client.post('/api/translate', json={'parts': ['א' * 10001]}).status_code == 400
    monkeypatch.setattr('app.translate', lambda parts: ['hello'])
    # Invalid requests must not leak the external-request semaphore slots.
    for _ in range(5):
        assert client.post('/api/lookup', json={'word': ''}).status_code == 400
    assert client.post('/api/translate', json={'parts': ['שלום']}).json['translations'] == ['hello']
