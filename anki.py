import csv
import html
import io
import re
import json
import platform
import shutil
import subprocess
import requests
from bs4 import BeautifulSoup
from morphology import normalize, tokens

MODEL = 'Hebrew Reader'
FIELDS = ['Word', 'Meaning', 'Pronunciation', 'Grammar', 'Root', 'Forms', 'Source']
MODEL_CONFIG = dict(modelName=MODEL, inOrderFields=FIELDS,
    css='.card {font-family:Arial;text-align:center;font-size:22px;color:#173d39;background:#faf9f4;} .word {font-size:40px;direction:rtl;} .meta {font-size:18px;margin-top:16px;line-height:1.7;} a {color:#22776d;}',
    cardTemplates=[dict(Name='Hebrew → meaning', Front='<div class="word">{{Word}}</div>',
        Back='{{FrontSide}}<hr id="answer">{{Meaning}}<div class="meta">{{Pronunciation}}<br>{{Grammar}}<br>Root: {{Root}}<br>{{Forms}}<br>{{Source}}</div>')])

def identity_tag(entry):
    return ('hebrew-reader::' if entry.get('source') == 'manual' else 'pealim::') + entry['id']

def card_fields(entry):
    if not entry['importable']:
        raise ValueError('No verified canonical form and pronunciation available for this entry.')
    c = entry['canonical']
    word = c['plain']
    if entry['irregular_plural'] and entry['plural']:
        word += ' / ' + entry['plural']['plain']
    pronunciation = ' · '.join(html.escape(v) for v in (c['vowelled'], c['pronunciation']) if v)
    if entry.get('audio_filename'):
        pronunciation += ' [sound:' + entry['audio_filename'] + ']'
    if c['stress']:
        pronunciation += ' (stress: ' + html.escape(c['stress']) + ')'
    grammar = entry['characteristics']
    if entry.get('source') != 'manual':
        grammar += ' · infinitive' if entry['pos'] == 'verb' else ' · masculine singular' if entry['pos'] == 'adjective' else ' · plural-only noun' if entry['plural_only'] else ' · singular' if entry['pos'] == 'noun' else ''
    forms = []
    if entry['plural']:
        p = entry['plural']
        forms.append('Plural: ' + html.escape(p['vowelled'] + ' · ' + p['pronunciation']))
    if entry['irregular_plural']:
        forms.append('Irregular plural ending: gender remains ' + html.escape(entry['characteristics']))
    for fid, label in [('fs-a', 'Feminine singular'), ('mp-a', 'Masculine plural'), ('fp-a', 'Feminine plural')]:
        if entry['pos'] == 'adjective' and fid in entry['forms']:
            f = entry['forms'][fid]
            forms.append(html.escape(label + ': ' + f['vowelled'] + ' · ' + f['pronunciation']))
    return dict(Word=html.escape(word), Meaning=html.escape(entry['meaning']),
                Pronunciation=pronunciation, Grammar=html.escape(grammar),
                Root=html.escape(entry['root']), Forms='<br>'.join(forms + ([html.escape(entry['notes'])] if entry.get('notes') else [])),
                Source='Added manually' if entry.get('source') == 'manual' else f'<a href="{html.escape(entry["url"], quote=True)}">Pealim · {entry["id"]}</a>')

def export_tsv(entries, basic=False):
    out = io.StringIO()
    columns = ['Front', 'Back'] if basic else FIELDS
    # A global #notetype preset is silently ignored if the model is missing.
    # A per-row type makes Anki report a missing model instead of importing
    # only the first field into whichever model was previously selected.
    out.write('#separator:Tab\n#html:true\n#notetype column:' + str(len(columns) + 2) + '\n')
    out.write('#tags column:' + str(len(columns) + 1) + '\n#columns:' + '\t'.join(columns + ['Tags', 'Notetype']) + '\n')
    writer = csv.writer(out, delimiter='\t', lineterminator='\n')
    for entry in entries:
        fields = card_fields(entry)
        values = [fields['Word'], '<br>'.join(fields[k] for k in FIELDS[1:] if fields[k])] if basic else [fields[k] for k in FIELDS]
        writer.writerow(values + ['hebrew-reader ' + identity_tag(entry), 'Basic' if basic else MODEL])
    return out.getvalue()

class Anki:
    @staticmethod
    def windows_curl():
        # WSL's Linux loopback may be separate from Windows loopback. A native
        # Windows client can reach Anki without opening its port to the network.
        if platform.system() == 'Linux' and 'microsoft' in platform.release().lower():
            return shutil.which('curl.exe')
        return None

    def call_windows(self, executable, payload):
        response = subprocess.run(
            [executable, '--silent', '--show-error', '--fail', '--noproxy', '*',
             '--max-time', '20', 'http://127.0.0.1:8765',
             '--header', 'Content-Type: application/json', '--data-binary', '@-'],
            input=json.dumps(payload, ensure_ascii=False), capture_output=True,
            encoding='utf-8', errors='replace', timeout=25, check=False)
        if response.returncode:
            raise ValueError('Could not reach AnkiConnect on Windows at 127.0.0.1:8765. '
                             'Restart Anki, open a profile, and check that AnkiConnect is enabled in Tools → Add-ons.')
        return json.loads(response.stdout)

    def call(self, action, **params):
        payload = dict(action=action, version=6, params=params)
        try:
            if getattr(self, '_windows_client', None):
                result = self.call_windows(self._windows_client, payload)
            else:
                try:
                    response = requests.post('http://127.0.0.1:8765', json=payload, timeout=20)
                except (requests.ConnectionError, requests.Timeout):
                    executable = self.windows_curl()
                    if not executable:
                        raise
                    result = self.call_windows(executable, payload)
                    self._windows_client = executable
                else:
                    response.raise_for_status()
                    result = response.json()
        except (requests.RequestException, OSError, subprocess.TimeoutExpired) as error:
            raise ValueError('Could not reach AnkiConnect at 127.0.0.1:8765. '
                             'Restart Anki, open a profile, and check that AnkiConnect is enabled in Tools → Add-ons.') from error
        except (ValueError, TypeError) as error:
            if str(error).startswith('Could not reach AnkiConnect on Windows'):
                raise
            raise ValueError('AnkiConnect returned an invalid response. Check its configuration and restart Anki.') from error
        if not isinstance(result, dict) or 'result' not in result or 'error' not in result:
            raise ValueError('AnkiConnect returned an invalid response. Check its configuration and restart Anki.')
        if result.get('error'):
            raise ValueError(str(result['error']))
        return result.get('result')

    def decks(self):
        return self.call('deckNames')

    @staticmethod
    def deck_query(deck):
        return 'deck:"' + deck.replace('\\', '\\\\').replace('"', '\\"') + '"'

    def known(self, deck, field=''):
        ids = self.call('findNotes', query=self.deck_query(deck))
        words, entries = set(), set()
        for offset in range(0, len(ids), 200):
            notes = self.call('notesInfo', notes=ids[offset:offset + 200])
            for note in notes:
                tags = note.get('tags', [])
                own = [t.split('::', 1)[1] for t in tags if re.fullmatch(r'pealim::\d+|hebrew-reader::manual-[a-f0-9]{32}', t)]
                if own:
                    entries.update(own)
                    continue  # Knowing one sense must not suppress its homographs.
                fields = note.get('fields', {})
                value = fields.get(field) if field else min(fields.values(), key=lambda f: f.get('order', 0), default={})
                if value is None:
                    raise ValueError(f'Field {field!r} does not exist in note model {note.get("modelName", "")}.')
                front = BeautifulSoup(value.get('value', ''), 'html.parser').get_text(' ', strip=True)
                # A whole front is a word/phrase, never all words from a sentence.
                parts = re.split(r'\s*[/;|]\s*', front)
                for part in parts:
                    if tokens(part) and not re.search('[A-Za-z]', part):
                        words.add(normalize(part))
        return words, entries

    def ensure_model(self):
        if MODEL not in self.call('modelNames'):
            self.call('createModel', **MODEL_CONFIG)
        elif self.call('modelFieldNames', modelName=MODEL) != FIELDS:
            raise ValueError('An existing Hebrew Reader model has incompatible fields. Rename it in Anki, then retry.')

    def add(self, deck, entries, field=''):
        if deck not in self.decks():
            raise ValueError('Select an existing Anki deck.')
        known_words, known_ids = self.known(deck, field)
        self.ensure_model()
        imported, duplicates, failed = [], [], []
        for entry in entries:
            try:
                tag = identity_tag(entry)
                canonical = entry.get('canonical') or {}
                if entry['id'] in known_ids or (entry.get('source') != 'manual' and canonical.get('plain') in known_words) or self.call('findNotes', query=self.deck_query(deck) + ' tag:' + tag):
                    duplicates.append(entry['id'])
                    continue
                fields = card_fields(entry)
                if entry.get('recording'):
                    filename = self.call('storeMediaFile', filename=entry['audio_filename'], data=entry['recording'])
                    if filename != entry['audio_filename']:
                        raise ValueError('Anki could not save the recording. Retry this card.')
                note_id = self.call('addNote', note=dict(deckName=deck, modelName=MODEL, fields=fields,
                                  options=dict(allowDuplicate=True), tags=['hebrew-reader', tag]))
                if not note_id:
                    raise ValueError('Anki did not return a note ID.')
                imported.append(entry['id'])
            except ValueError as error:
                failed.append(dict(id=entry['id'], error=str(error)))
        return dict(imported=imported, duplicates=duplicates, failed=failed)
