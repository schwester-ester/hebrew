import io
import csv
import json
import sqlite3
import os
from pathlib import Path
import subprocess
import zipfile
import pytest
from app import create_app
from anki import card_fields, FIELDS, MODEL_CONFIG, export_tsv
from packages import export_package, PACKAGE_MODEL_ID
from manual import make_entries
from test_features import wav
from test_reader import entry


def unpack(data, tmp_path, name='package'):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        database = tmp_path / (name + '.sqlite3')
        database.write_bytes(archive.read('collection.anki2'))
        media = json.loads(archive.read('media'))
        files = {filename: archive.read(index) for index, filename in media.items()}
    return sqlite3.connect(database), files


def test_package_has_all_fields_templates_media_and_stable_identities(tmp_path):
    cards = [entry(), entry('verb'), *make_entries({'word': 'ספר', 'meanings': ['another meaning'], 'recording': wav()})]
    first, media = unpack(export_package(cards, 'My Hebrew'), tmp_path)
    with first:
        models, decks = first.execute('SELECT models, decks FROM col').fetchone()
        model = json.loads(models)[str(PACKAGE_MODEL_ID)]
        assert [f['name'] for f in model['flds']] == FIELDS
        assert '{{Meaning}}' in model['tmpls'][0]['afmt']
        assert '{{Word}}' in model['tmpls'][0]['qfmt']
        assert any(d['name'] == 'My Hebrew' for d in json.loads(decks).values())
        rows = first.execute('SELECT guid, flds, tags FROM notes ORDER BY id').fetchall()
        assert len(rows) == 3
        assert rows[0][1].split('\x1f') == [card_fields(cards[0])[name] for name in FIELDS]
        assert 'pealim::6104' in rows[0][2]
        assert '[sound:' + cards[2]['audio_filename'] + ']' in rows[2][1]
        assert set(media) == {cards[2]['audio_filename']}
        assert len(media[cards[2]['audio_filename']]) > 40
    second, _ = unpack(export_package(cards, 'Another deck'), tmp_path, 'second')
    assert second.execute('SELECT guid FROM notes ORDER BY id').fetchall() == [(row[0],) for row in rows]
    first.close();second.close()


@pytest.mark.parametrize('name', ['', None, 5, 'x' * 201, 'bad\nname'])
def test_package_rejects_invalid_deck_names(name):
    with pytest.raises(ValueError):
        export_package([entry()], name)


def test_public_package_export_and_both_tsv_layouts_are_stateless(tmp_path, monkeypatch):
    app = create_app(tmp_path / 'public.sqlite3', public=True)
    monkeypatch.setattr(app.extensions['anki'], 'call', lambda *a, **kw: pytest.fail('Export contacted desktop Anki'))
    client = app.test_client()
    payload = {'entries': [entry('irregular')], 'format': 'apkg', 'package_deck': 'Existing deck'}
    response = client.post('/api/export', json=payload)
    assert response.status_code == 200 and response.content_type == 'application/apkg'
    database, _ = unpack(response.data, tmp_path)
    assert 'שולחן / שולחנות' in database.execute('SELECT flds FROM notes').fetchone()[0]
    database.close()
    payload['format'] = 'basic-tsv'
    assert '#notetype column:4' in client.post('/api/export', json=payload).text
    payload['format'] = 'tsv'
    assert '#columns:Word\tMeaning\tPronunciation\tGrammar\tRoot\tForms\tSource\tTags\tNotetype' in client.post('/api/export', json=payload).text
    payload['format'] = 'unknown'
    assert client.post('/api/export', json=payload).status_code == 400
    with sqlite3.connect(app.extensions['store'].path) as database:
        assert database.execute('SELECT COUNT(*) FROM entries').fetchone()[0] == 0


@pytest.mark.skipif(not os.environ.get('ANKI_PYTHON'), reason='Set ANKI_PYTHON to a separate Python containing the official anki package')
def test_exports_with_real_anki_importer(tmp_path):
    cards = [entry(), entry('adjective'), *make_entries(dict(word='שלום', meanings=['hello'], recording=wav(), pos='phrase', notes='A note\twith tabs\nand newlines')), *make_entries(dict(word='ספר', meanings=['another book sense', 'a different book sense']))]
    (tmp_path / 'full.tsv').write_text(export_tsv(cards), encoding='utf-8')
    (tmp_path / 'basic.tsv').write_text(export_tsv(cards, basic=True), encoding='utf-8')
    old = io.StringIO()
    old.write('#separator:Tab\n#html:true\n#tags column:3\n#columns:Front\tBack\tTags\n')
    writer = csv.writer(old, delimiter='\t', lineterminator='\n')
    for card in cards:
        fields = card_fields(card)
        writer.writerow([fields['Word'], '<br>'.join(fields[name] for name in FIELDS[1:] if fields[name]), 'hebrew-reader'])
    (tmp_path / 'old.tsv').write_text(old.getvalue(), encoding='utf-8')
    (tmp_path / 'cards.apkg').write_bytes(export_package(cards, 'My Hebrew'))
    (tmp_path / 'expected.json').write_text(json.dumps(dict(model=MODEL_CONFIG, fields=FIELDS, cards=[card_fields(e) for e in cards])), encoding='utf-8')
    result = subprocess.run([os.environ['ANKI_PYTHON'], str(Path(__file__).with_name('import_anki_exports.py').resolve()), str(tmp_path)], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
