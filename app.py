import os
import threading
from pathlib import Path
from flask import Flask, jsonify, request, render_template, Response
from anki import Anki, export_tsv
from morphology import normalize, tokens
from pealim import Pealim
from storage import Store

def create_app(data_path=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
    store = Store(data_path or Path(os.environ.get('HEBREW_DATA_DIR', 'data')) / 'reader.sqlite3')
    dictionary, anki = Pealim(store), Anki()
    known_by_deck = {}
    known_fields = {}
    import_lock = threading.Lock()
    app.extensions.update(store=store, dictionary=dictionary, anki=anki)

    @app.before_request
    def local_only():
        if request.host.split(':')[0] not in ('127.0.0.1', 'localhost'):
            return jsonify(error='This application accepts localhost requests only.'), 403
        if request.method == 'POST':
            origin = request.headers.get('Origin')
            if origin and origin not in ('http://' + request.host, 'https://' + request.host):
                return jsonify(error='Cross-origin requests are not allowed.'), 403
            if not request.is_json:
                return jsonify(error='Expected JSON.'), 415

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/decks')
    def decks():
        return jsonify(decks=anki.decks())

    @app.post('/api/sync')
    def sync():
        data = request.get_json()
        deck = data.get('deck', '')
        if deck not in anki.decks():
            raise ValueError('Select an existing deck first.')
        field = data.get('field', '').strip()
        words, entries = anki.known(deck, field)
        known_by_deck[deck] = (words, entries)
        known_fields[deck] = field
        return jsonify(words=sorted(words), entries=sorted(entries))

    @app.post('/api/text')
    def parse_text():
        data = request.get_json()
        text = data.get('text', '')
        if not isinstance(text, str) or len(text) > 50000:
            raise ValueError('Use a text shorter than 50,000 characters.')
        words, _ = known_by_deck.get(data.get('deck', ''), (set(), set()))
        skipped = store.skips()
        items = tokens(text)
        for item in items:
            item['known'] = item['key'] in words or item['key'] in skipped
            item['reason'] = 'Previously skipped' if item['key'] in skipped else 'In your Anki deck' if item['key'] in words else ''
        return jsonify(tokens=items, skipped=sorted(skipped))

    @app.post('/api/lookup')
    def lookup():
        data = request.get_json()
        word = data.get('word', '')
        if not isinstance(word, str) or len(word) > 100 or not tokens(word):
            raise ValueError('Choose a Hebrew word.')
        result = dictionary.lookup(word)
        words, ids = known_by_deck.get(data.get('deck', ''), (set(), set()))
        for entry in result['entries']:
            canonical = entry['canonical'] or {}
            entry['known'] = entry['id'] in ids or canonical.get('plain') in words
        return jsonify(result)

    @app.post('/api/skip')
    def skip():
        data = request.get_json()
        word = normalize(data.get('word', ''))
        if not word or len(word) > 100:
            raise ValueError('Choose a Hebrew word.')
        store.skip(word, bool(data.get('remove')))
        return jsonify(skipped=sorted(store.skips()))

    def selected(data):
        ids = data.get('ids', [])
        if not isinstance(ids, list) or not ids or len(ids) > 500 or not all(isinstance(i, str) for i in ids):
            raise ValueError('Select between 1 and 500 dictionary meanings.')
        return [store.get_entry(id) for id in dict.fromkeys(ids)]

    @app.post('/api/import')
    def import_notes():
        data = request.get_json()
        entries = selected(data)
        if any(not e['importable'] for e in entries):
            raise ValueError('A selected entry has no verified canonical form.')
        with import_lock:
            result = anki.add(data.get('deck', ''), entries, known_fields.get(data.get('deck', ''), ''))
            if data.get('deck', '') in known_by_deck:
                known_by_deck[data['deck']][1].update(result['imported'] + result['duplicates'])
        return jsonify(result)

    @app.post('/api/export')
    def export():
        return Response(export_tsv(selected(request.get_json())), content_type='text/tab-separated-values; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="hebrew-vocabulary.tsv"'})

    return app

if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5000, threaded=True)
