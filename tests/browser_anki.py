"""Hosted-site Anki flow with a simulated local AnkiConnect; never touches Anki."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import request
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from app import create_app
from test_reader import entry
from test_features import wav


def main():
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(Path(directory) / 'public.sqlite3', public=True)
        app.extensions['anki'].call = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Hosted backend contacted desktop Anki'))
        server_requests = []
        @app.before_request
        def track():
            if request.path.startswith('/api/'):
                server_requests.append((request.path, request.get_json(silent=True)))
        def lookup(word):
            card = copy.deepcopy(entry())
            card['analyses'] = [dict(base=word, prefix='', explanation='Original spelling', matches=[dict(card['canonical'], description='Matched form')])]
            return dict(entries=[card], warnings=[], candidates=[])
        app.extensions['dictionary'].lookup = lookup
        server = make_server('127.0.0.1', 5054, app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', '/snap/bin/chromium'), headless=True, args=['--no-sandbox'])
                page = browser.new_page(viewport={'width': 1440, 'height': 1100})
                errors, actions, notes, media = [], [], {}, {}
                decks, models = ['Hebrew', 'Other'], []
                permission, fail_add = ['denied'], [False]
                def anki(route):
                    payload = route.request.post_data_json
                    actions.append(payload)
                    action, params = payload['action'], payload.get('params', {})
                    result, error = None, None
                    if action == 'requestPermission':
                        result = dict(permission=permission[0], requireApikey=True, version=6)
                    elif payload.get('key') != 'test-tab-secret':
                        error = 'valid api key must be provided'
                    elif action == 'deckNames': result = decks[:]
                    elif action == 'createDeck':
                        if params['deck'] not in decks: decks.append(params['deck'])
                        result = len(decks)
                    elif action == 'findNotes':
                        query = params['query']
                        result = [identity for identity, note in notes.items() if query.startswith('deck:"' + note['deck'] + '"') and (' tag:' not in query or query.split(' tag:')[1] in note['tags'])]
                    elif action == 'notesInfo': result = [notes[identity] for identity in params['notes']]
                    elif action == 'modelNames': result = models[:]
                    elif action == 'modelFieldNames': result = ['Word', 'Meaning', 'Pronunciation', 'Grammar', 'Root', 'Forms', 'Source']
                    elif action == 'createModel': models.append(params['modelName']);result = {}
                    elif action == 'storeMediaFile': media[params['filename']] = params['data'];result = params['filename']
                    elif action == 'addNote':
                        if fail_add[0]: error = 'Simulated Anki failure'
                        else:
                            note = params['note'];result = len(notes) + 1
                            notes[result] = dict(deck=note['deckName'], modelName=note['modelName'], tags=note['tags'], fields={name: dict(value=value, order=index) for index, (name, value) in enumerate(note['fields'].items())})
                    else: raise AssertionError(action)
                    route.fulfill(json=dict(result=result, error=error), headers={'Access-Control-Allow-Origin': '*'})
                page.route('http://127.0.0.1:8765/**', anki)
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto('http://127.0.0.1:5054')
                page.wait_for_function("document.body.dataset.storageReady==='true'")
                assert not actions, 'Must not contact desktop on page load'
                assert page.locator('#connect').is_visible()
                assert page.locator('#syncCards').is_disabled()
                page.click('#connect')
                page.wait_for_function("document.getElementById('connection').textContent.includes('denied')")
                permission[0] = 'granted'
                page.click('#connect')
                page.wait_for_function("document.getElementById('connection').textContent.includes('requires your API key')")
                page.locator('.anki-help summary').click()
                page.fill('#ankiKey', 'test-tab-secret')
                page.click('#connect')
                page.wait_for_function("document.getElementById('connection').textContent.startsWith('Connected')")
                assert page.locator('#deck option').count() == 2
                page.select_option('#deck', 'Other')
                page.wait_for_function("syncedDeck==='Other'")
                page.fill('#newDeck', 'Private Hebrew deck')
                page.click('#createDeck')
                page.wait_for_function("syncedDeck==='Private Hebrew deck'")
                assert 'Private Hebrew deck' in decks
                page.fill('#input', 'ספר')
                page.click('#read')
                page.locator('.token').click()
                page.click('[data-add="6104"]')
                # Add a recorded card through the same API used by the form.
                page.evaluate("""async recording => {
                    const {entries}=await api('manual',{word:'שלום',meanings:['hello'],recording});
                    for(const entry of entries)basket.set(entry.id,entry);
                    renderBasket();
                }""", wav())
                assert page.inner_text('#basketCount') == '2 meanings'
                with page.expect_download() as download: page.click('#export')
                assert download.value.suggested_filename == 'hebrew-vocabulary.zip'
                page.click('#syncCards')
                page.wait_for_function("document.getElementById('connection').textContent.startsWith('Imported 2')")
                assert len(notes) == 2 and len(media) == 1
                assert page.inner_text('#basketCount') == '0 meanings'
                assert all(note['deck'] == 'Private Hebrew deck' for note in notes.values())
                assert any('[sound:' in note['fields']['Pronunciation']['value'] for note in notes.values())
                # Retrying the same identities must never create duplicates.
                page.evaluate("""async () => {
                    const card=(await api('lookup',{word:'ספר'})).entries[0];
                    basket.set(card.id,card);renderBasket();
                }""")
                page.click('#syncCards')
                page.wait_for_function("document.getElementById('connection').textContent.includes('1 already in deck')")
                assert len(notes) == 2
                # Failed notes stay in the tray, then import successfully on retry.
                page.click('#addManual');page.fill('#manualWord', 'טוב');page.fill('#manualMeanings', 'good');page.click('#saveManual')
                page.wait_for_function("document.getElementById('basketCount').textContent==='1 meaning'")
                fail_add[0] = True
                page.click('#syncCards')
                page.wait_for_function("document.getElementById('connection').textContent.includes('Simulated Anki failure')")
                assert page.inner_text('#basketCount') == '1 meaning'
                fail_add[0] = False
                page.click('#syncCards')
                page.wait_for_function("document.getElementById('connection').textContent.startsWith('Imported 1')")
                assert len(notes) == 3
                # Sync recognizes an untagged word in a selected custom field.
                notes[4] = dict(deck='Other', modelName='Basic', tags=[], fields={'Front': dict(value='English', order=0), 'Hebrew': dict(value='טוב', order=1)})
                page.fill('#knownField', 'Hebrew')
                page.select_option('#deck', 'Other')
                page.wait_for_function("syncedDeck==='Other'")
                page.click('#edit');page.fill('#input', 'טוב');page.click('#read')
                page.wait_for_selector('.token.known')
                # A collection with no decks can still create its first deck.
                decks.clear();notes.clear()
                page.fill('#knownField', '')
                page.click('#connect')
                page.wait_for_function("document.getElementById('connection').textContent.includes('enter a new deck')")
                assert page.locator('#createDeck').is_enabled()
                page.fill('#newDeck', 'First deck');page.click('#createDeck')
                page.wait_for_function("syncedDeck==='First deck'")
                # Mobile layout and tab-only API key handling.
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path='/tmp/ivrit-anki-mobile.png', full_page=True)
                page.reload();page.wait_for_function("document.body.dataset.storageReady==='true'")
                assert page.input_value('#ankiKey') == ''
                assert page.locator('#syncCards').is_disabled()
                assert not any(path in ('/api/decks', '/api/sync', '/api/import', '/api/create-deck') for path, _ in server_requests)
                assert not any('test-tab-secret' in json.dumps(data) or 'Private Hebrew deck' in json.dumps(data) for _, data in server_requests)
                assert not errors, errors
                browser.close()
                print('Hosted Anki browser check passed: permission/key, select/create/empty decks, canonical cards, audio, duplicate retry, partial failure, custom Hebrew field, TSV/ZIP, privacy, mobile.')
        finally:
            server.shutdown()


if __name__ == '__main__':
    main()
