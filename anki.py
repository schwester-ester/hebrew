import csv
import html
import io
import re
import requests
from bs4 import BeautifulSoup
from morphology import normalize, tokens

MODEL = 'Hebrew Reader'
FIELDS = ['Word', 'Meaning', 'Pronunciation', 'Grammar', 'Root', 'Forms', 'Source']

def card_fields(entry):
    if not entry['importable']:
        raise ValueError('No verified canonical form and pronunciation available for this entry.')
    c = entry['canonical']
    word = c['plain']
    if entry['irregular_plural'] and entry['plural']:
        word += ' / ' + entry['plural']['plain']
    pronunciation = html.escape(c['vowelled']) + ' · ' + html.escape(c['pronunciation'])
    if c['stress']:
        pronunciation += ' (stress: ' + html.escape(c['stress']) + ')'
    grammar = entry['characteristics']
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
                Root=html.escape(entry['root']), Forms='<br>'.join(forms),
                Source=f'<a href="{html.escape(entry["url"], quote=True)}">Pealim · {entry["id"]}</a>')

def export_tsv(entries):
    out = io.StringIO()
    out.write('#separator:Tab\n#html:true\n#tags column:3\n#columns:Front\tBack\tTags\n')
    writer = csv.writer(out, delimiter='\t', lineterminator='\n')
    for entry in entries:
        fields = card_fields(entry)
        back = '<br>'.join(fields[k] for k in FIELDS[1:] if fields[k])
        writer.writerow([fields['Word'], back, 'hebrew-reader pealim::' + entry['id']])
    return out.getvalue()

class Anki:
    def call(self, action, **params):
        try:
            response = requests.post('http://127.0.0.1:8765', json=dict(action=action, version=6, params=params), timeout=20)
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as error:
            raise ValueError('Could not connect to Anki. Open Anki desktop with the AnkiConnect add-on installed.') from error
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
                own = [t.removeprefix('pealim::') for t in tags if re.fullmatch(r'pealim::\d+', t)]
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
            self.call('createModel', modelName=MODEL, inOrderFields=FIELDS,
                      css='.card {font-family:Arial;text-align:center;font-size:22px;color:#173d39;background:#faf9f4;} .word {font-size:40px;direction:rtl;} .meta {font-size:18px;margin-top:16px;line-height:1.7;} a {color:#22776d;}',
                      cardTemplates=[dict(Name='Hebrew → meaning', Front='<div class="word">{{Word}}</div>',
                                          Back='{{FrontSide}}<hr id="answer">{{Meaning}}<div class="meta">{{Pronunciation}}<br>{{Grammar}}<br>Root: {{Root}}<br>{{Forms}}<br>{{Source}}</div>')])
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
                tag = 'pealim::' + entry['id']
                canonical = entry.get('canonical') or {}
                if entry['id'] in known_ids or canonical.get('plain') in known_words or self.call('findNotes', query=self.deck_query(deck) + ' tag:' + tag):
                    duplicates.append(entry['id'])
                    continue
                note_id = self.call('addNote', note=dict(deckName=deck, modelName=MODEL, fields=card_fields(entry),
                                  options=dict(allowDuplicate=True), tags=['hebrew-reader', tag]))
                if not note_id:
                    raise ValueError('Anki did not return a note ID.')
                imported.append(entry['id'])
            except ValueError as error:
                failed.append(dict(id=entry['id'], error=str(error)))
        return dict(imported=imported, duplicates=duplicates, failed=failed)
