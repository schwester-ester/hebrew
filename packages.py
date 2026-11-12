"""Portable deck packages with complete note fields, templates, and recordings."""
import hashlib
from pathlib import Path
import tempfile
import genanki
from anki import FIELDS, MODEL, MODEL_CONFIG, card_fields, identity_tag
from manual import audio_bytes

PACKAGE_MODEL_ID = 1976031259


def export_package(entries, deck_name='Hebrew Reader'):
    if (not isinstance(deck_name, str) or not deck_name.strip() or len(deck_name) > 200
            or any(ord(c) < 32 for c in deck_name)):
        raise ValueError('Enter a package deck name between 1 and 200 characters.')
    deck_name = deck_name.strip()
    model = genanki.Model(PACKAGE_MODEL_ID, MODEL,
        fields=[{'name': name} for name in FIELDS], css=MODEL_CONFIG['css'],
        templates=[dict(name=t['Name'], qfmt=t['Front'], afmt=t['Back']) for t in MODEL_CONFIG['cardTemplates']])
    deck_id = int.from_bytes(hashlib.sha256(('ivrit-deck:' + deck_name).encode()).digest()[:6], 'big') + 2**32
    deck = genanki.Deck(deck_id, deck_name)
    with tempfile.TemporaryDirectory(prefix='ivrit-package-') as directory:
        media = []
        for entry in entries:
            fields = card_fields(entry)
            tag = identity_tag(entry)
            deck.add_note(genanki.Note(model=model, fields=[fields[name] for name in FIELDS],
                guid=genanki.guid_for('ivrit-v1', tag), tags=['hebrew-reader', tag]))
            if entry.get('recording'):
                # Never use a caller-provided path, including in local mode.
                filename = entry['id'] + '.wav'
                if entry['audio_filename'] != filename or '/' in filename or '\\' in filename:
                    raise ValueError('Invalid recording filename.')
                path = Path(directory) / filename
                path.write_bytes(audio_bytes(entry))
                media.append(str(path))
        package = genanki.Package(deck)
        package.media_files = media
        output = Path(directory) / 'hebrew-vocabulary.apkg'
        package.write_to_file(str(output))
        return output.read_bytes()
