import os
import threading
import io
import zipfile
import re
from pathlib import Path
from flask import Flask, jsonify, request, render_template, Response, g
from anki import Anki, export_tsv, card_fields, identity_tag, MODEL_CONFIG
from morphology import normalize, tokens
from pealim import Pealim
from storage import Store
from manual import make_entries, summary, audio_bytes
from translation import translate
from portable import portable_entry
from packages import export_package

def create_app(data_path=None, public=None):
    app = Flask(__name__)
    public = os.environ.get('IVRIT_PUBLIC') == '1' if public is None else public
    app.config.update(PUBLIC_MODE=public, MAX_CONTENT_LENGTH=(32 if public else 3) * 1024 * 1024)
    allowed_hosts = ['127.0.0.1', 'localhost']
    if public:
        allowed_hosts += [host.strip() for host in os.environ.get('IVRIT_ALLOWED_HOSTS', '').split(',') if host.strip()]
        if os.environ.get('RENDER_EXTERNAL_HOSTNAME'):
            allowed_hosts.append(os.environ['RENDER_EXTERNAL_HOSTNAME'])
    app.config['TRUSTED_HOSTS'] = allowed_hosts
    store = Store(data_path or Path(os.environ.get('HEBREW_DATA_DIR', 'data')) / ('public-cache.sqlite3' if public else 'reader.sqlite3'))
    dictionary, anki = Pealim(store), Anki()
    known_by_deck = {}
    known_fields = {}
    import_lock = threading.Lock()
    external_slots = threading.BoundedSemaphore(2)
    allowed_origins = set(filter(None, (origin.strip() for origin in os.environ.get('IVRIT_ALLOWED_ORIGINS', '').split(',')))) if public else set()
    app.extensions.update(store=store, dictionary=dictionary, anki=anki)

    @app.before_request
    def request_policy():
        if public and (request.path in ('/api/decks', '/api/create-deck', '/api/sync', '/api/import', '/api/skip') or request.path.startswith('/api/audio/')):
            return jsonify(error='Connect to Anki desktop directly from your browser, or use Export for Anki.'), 404
        origin = request.headers.get('Origin')
        if request.path.startswith('/api/') and request.method == 'OPTIONS':
            if origin not in allowed_origins:
                return jsonify(error='Cross-origin requests are not allowed.'), 403
            return Response(status=204)
        if request.method == 'POST':
            if origin and origin not in allowed_origins | {'http://' + request.host, 'https://' + request.host}:
                return jsonify(error='Cross-origin requests are not allowed.'), 403
            if not request.is_json:
                return jsonify(error='Expected JSON.'), 415
            if not isinstance(request.get_json(), dict):
                raise ValueError('Expected a JSON object.')
        if public and request.path in ('/api/lookup', '/api/translate'):
            if not external_slots.acquire(blocking=False):
                return jsonify(error='The dictionary and translation service is busy. Please retry shortly.'), 429, {'Retry-After': '5'}
            g.external_slot = True

    @app.teardown_request
    def release_slot(error):
        if g.pop('external_slot', False):
            external_slots.release()

    @app.after_request
    def response_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
            if request.headers.get('Origin') in allowed_origins:
                response.headers['Access-Control-Allow-Origin'] = request.headers['Origin']
                response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
                response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
                response.vary.add('Origin')
        return response

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error='This request is too large. Export fewer recorded cards at a time.'), 413

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.get('/')
    def index():
        return render_template('index.html', public=public)

    @app.get('/healthz')
    def health():
        return jsonify(status='ok')

    @app.post('/api/translate')
    def translate_text():
        parts = request.get_json().get('parts')
        if public and isinstance(parts, list) and sum(len(p) for p in parts if isinstance(p, str)) > 10000:
            raise ValueError('Translate at most 10,000 characters at a time on the shared website.')
        return jsonify(translations=translate(parts))

    @app.post('/api/manual')
    def manual():
        entries = make_entries(request.get_json())
        if public:
            return jsonify(entries=entries)
        for entry in entries:
            store.entry(entry)
        return jsonify(entries=[summary(e) for e in entries])

    @app.get('/api/audio/<identity>')
    def audio(identity):
        if not re.fullmatch(r'manual-[a-f0-9]{32}', identity):
            return jsonify(error='Recording not found.'), 404
        entry = store.get_entry(identity)
        return Response(audio_bytes(entry), content_type='audio/wav')

    @app.get('/api/decks')
    def decks():
        return jsonify(decks=anki.decks())

    @app.post('/api/create-deck')
    def create_deck():
        name = request.get_json().get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 200 or any(ord(c) < 32 for c in name):
            raise ValueError('Enter a deck name between 1 and 200 characters.')
        anki.call('createDeck', deck=name.strip())
        return jsonify(decks=anki.decks(), deck=name.strip())

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
        skipped = set() if public else store.skips()
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
        if public:
            entries = data.get('entries')
            if not isinstance(entries, list) or not 1 <= len(entries) <= 500:
                raise ValueError('Select between 1 and 500 vocabulary meanings.')
            validated = [portable_entry(e) for e in entries]
            return list({e['id']: e for e in validated}.values())
        ids = data.get('ids', [])
        if not isinstance(ids, list) or not ids or len(ids) > 500 or not all(isinstance(i, str) for i in ids):
            raise ValueError('Select between 1 and 500 dictionary meanings.')
        return [store.get_entry(id) for id in dict.fromkeys(ids)]

    @app.post('/api/anki-prepare')
    def prepare_anki():
        # Only render validated browser-owned cards. Desktop requests happen in
        # the visitor's browser, never from the shared server.
        entries = selected(request.get_json())
        return jsonify(model=MODEL_CONFIG, cards=[dict(
            id=e['id'], word=e['canonical']['plain'], manual=e.get('source') == 'manual',
            fields=card_fields(e), tags=['hebrew-reader', identity_tag(e)],
            recording=e.get('recording', ''), audio_filename=e.get('audio_filename', '')) for e in entries])

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
        data = request.get_json()
        entries = selected(data)
        format = data.get('format', 'tsv')
        if format not in ('tsv', 'basic-tsv', 'apkg'):
            raise ValueError('Choose TSV or Anki package export.')
        if format == 'apkg':
            return Response(export_package(entries, data.get('package_deck', 'Hebrew Reader')), content_type='application/apkg',
                            headers={'Content-Disposition': 'attachment; filename="hebrew-vocabulary.apkg"'})
        basic = format == 'basic-tsv'
        if any(e.get('recording') for e in entries):
            out = io.BytesIO()
            with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('hebrew-vocabulary.tsv', export_tsv(entries, basic=basic))
                for e in entries:
                    if e.get('recording'):
                        archive.writestr(e['audio_filename'], audio_bytes(e))
                archive.writestr('README.txt', 'Copy the WAV files into your Anki profile collection.media folder, then import hebrew-vocabulary.tsv. The file specifies ' + ('Basic with Front and Back' if basic else 'Hebrew Reader with Word, Meaning, Pronunciation, Grammar, Root, Forms, Source') + '. Enable HTML and import duplicate fronts as new notes to preserve different meanings. If Hebrew Reader is missing, first import an Anki package (.apkg) exported by this app; it includes the note type and recordings.\n')
            return Response(out.getvalue(), content_type='application/zip',
                            headers={'Content-Disposition': 'attachment; filename="hebrew-vocabulary.zip"'})
        return Response(export_tsv(entries, basic=basic), content_type='text/tab-separated-values; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="hebrew-vocabulary.tsv"'})

    return app

if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5000, threaded=True)
