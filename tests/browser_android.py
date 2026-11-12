"""Android companion contract, exports, and mobile UI; no real phone is contacted."""
import copy
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from app import create_app
from test_reader import entry
from test_features import wav


def main():
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(Path(directory) / 'public.sqlite3', public=True)
        app.extensions['anki'].call = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Server contacted desktop Anki'))
        def lookup(word):
            card = copy.deepcopy(entry())
            card['analyses'] = [dict(base=word, prefix='', explanation='Original spelling', matches=[dict(card['canonical'], description='Matched form')])]
            return dict(entries=[card], warnings=[], candidates=[])
        app.extensions['dictionary'].lookup = lookup
        server = make_server('127.0.0.1', 5055, app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', '/snap/bin/chromium'), headless=True, args=['--no-sandbox'])
                page = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True,
                    user_agent='Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/142.0.0.0 Mobile Safari/537.36')
                errors, actions, notes, media = [], [], [], {}
                decks, models = ['Existing Hebrew', 'Other'], []
                invalid_id = [False]
                def anki(route):
                    payload = route.request.post_data_json
                    action, params = payload['action'], payload.get('params', {})
                    actions.append(action)
                    if action == 'version': result = 6
                    elif action == 'deckNames': result = decks[:]
                    elif action == 'findNotes': result = []
                    elif action == 'notesInfo': result = []
                    elif action == 'modelNames': result = models[:]
                    elif action == 'modelFieldNames': result = ['Word', 'Meaning', 'Pronunciation', 'Grammar', 'Root', 'Forms', 'Source']
                    elif action == 'storeMediaFile':
                        # This renaming is required by the actual Android API.
                        result = params['filename'].replace('.wav', '_123456789.wav')
                        media[result] = params['data']
                    elif action == 'addNote':
                        if invalid_id[0]: result = -1
                        else: notes.append(params['note']);result = len(notes)
                    else: raise AssertionError('Unsupported Android action: ' + action)
                    route.fulfill(json={'result': result, 'error': None}, headers={'Access-Control-Allow-Origin': '*'})
                page.add_init_script('''
                    const originalFetch=window.fetch;
                    window.fetch=async (...args)=>{
                        const response=await originalFetch(...args);
                        if(String(args[0]).endsWith('/api/export'))window.exportBytes=Array.from(new Uint8Array(await response.clone().arrayBuffer()));
                        return response;
                    };
                ''')
                page.route('http://127.0.0.1:8765/**', anki)
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto('http://127.0.0.1:5055')
                page.wait_for_function("document.body.dataset.storageReady==='true'")
                assert not actions
                assert page.input_value('#connectionMode') == 'android'
                assert page.locator('#androidHelp').is_visible()
                page.click('#connect')
                page.wait_for_function("document.getElementById('connection').textContent.startsWith('Connected')")
                assert page.locator('#deck option').count() == 2
                page.select_option('#deck', 'Other')
                page.wait_for_function("syncedDeck==='Other'")
                page.fill('#input', 'ספר');page.click('#read');page.locator('.token').click();page.click('[data-add="6104"]')
                page.evaluate("""async recording => {
                    const {entries}=await api('manual',{word:'שלום',meanings:['hello'],recording});
                    for(const entry of entries)basket.set(entry.id,entry);renderBasket();
                }""", wav())
                assert page.inner_text('#basketCount') == '2 meanings'
                page.click('#syncCards')
                page.wait_for_function("document.getElementById('connection').textContent.includes('install the Hebrew Reader note type')")
                assert not notes and page.inner_text('#basketCount') == '2 meanings'
                # Package export supplies note type, chosen deck, all fields, media.
                page.fill('#newDeck', 'Mobile Hebrew');page.click('#createDeck')
                assert page.input_value('#packageDeck') == 'Mobile Hebrew'
                with page.expect_response('**/api/export') as exported, page.expect_download() as download: page.click('#exportPackage')
                assert download.value.suggested_filename == 'hebrew-vocabulary.apkg'
                with zipfile.ZipFile(io.BytesIO(bytes(page.evaluate('window.exportBytes')))) as archive:
                    assert 'collection.anki2' in archive.namelist()
                    assert len(json.loads(archive.read('media'))) == 1
                assert page.inner_text('#basketCount') == '2 meanings'
                # Model now exists after a one-time package import on the phone.
                models.append('Hebrew Reader')
                page.click('#syncCards')
                page.wait_for_function("document.getElementById('connection').textContent.startsWith('Imported 2')")
                assert len(notes) == 2 and len(media) == 1
                assert all(note['deckName'] == 'Other' for note in notes)
                assert notes[0]['fields']['Meaning'] == 'book'
                assert 'sefer' in notes[0]['fields']['Pronunciation']
                assert 'masculine' in notes[0]['fields']['Grammar']
                assert '[sound:' + next(iter(media)) + ']' in notes[1]['fields']['Pronunciation']
                assert not {'requestPermission', 'createModel', 'createDeck'} & set(actions)
                # Both TSV formats remain available with explicit field mapping.
                page.click('#addManual');page.fill('#manualWord', 'טוב');page.fill('#manualMeanings', 'good');page.click('#saveManual')
                page.wait_for_function("document.getElementById('basketCount').textContent==='1 meaning'")
                with page.expect_response('**/api/export') as full, page.expect_download(): page.click('#export')
                full_text = bytes(page.evaluate('window.exportBytes')).decode()
                assert '#notetype column:9' in full_text and '#tags column:8' in full_text
                rows = list(csv.reader(io.StringIO('\n'.join(line for line in full_text.splitlines() if not line.startswith('#'))), delimiter='\t'))
                assert len(rows[0]) == 9 and rows[0][1] == 'good'
                page.select_option('#exportFormat', 'basic-tsv')
                with page.expect_response('**/api/export') as basic, page.expect_download(): page.click('#export')
                assert '#notetype column:4' in bytes(page.evaluate('window.exportBytes')).decode()
                # AnkiDroid's -1 failure code must not clear the tray.
                invalid_id[0] = True;page.click('#syncCards')
                page.wait_for_function("document.getElementById('connection').textContent.includes('valid note ID')")
                assert page.inner_text('#basketCount') == '1 meaning'
                invalid_id[0] = False;page.click('#syncCards')
                page.wait_for_function("document.getElementById('connection').textContent.startsWith('Imported 1')")
                assert page.inner_text('#basketCount') == '0 meanings'
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path='/tmp/ivrit-android-mobile.png', full_page=True)
                assert not errors, errors
                browser.close()
                print('Android browser check passed: mode detection, companion-only API, existing decks, model bootstrap, full/Basic TSV, package/audio, renamed media, failure retry, mobile layout.')
        finally:
            server.shutdown()


if __name__ == '__main__':
    main()
