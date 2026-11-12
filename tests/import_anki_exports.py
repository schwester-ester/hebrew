"""Run with a separate Python containing the official `anki` distribution.

The caller supplies export fixtures; this process touches only temporary
collections. Its sys.path deliberately excludes the project's own anki.py.
"""
import json
from pathlib import Path
import sys
import tempfile
from anki.collection import Collection
from anki.import_export_pb2 import CsvMetadata, ImportCsvRequest, ImportAnkiPackageRequest


def main(root):
    root = Path(root)
    expected = json.loads((root / 'expected.json').read_text())
    with tempfile.TemporaryDirectory() as directory:
        fresh = Collection(str(Path(directory) / 'fresh.anki2'))
        try:
            path = str(root / 'full.tsv')
            metadata = fresh.get_csv_metadata(path, None)
            result = fresh.import_csv(ImportCsvRequest(path=path, metadata=metadata))
            assert not fresh.note_count(), 'A missing model silently imported incomplete notes'
            assert len(result.log.missing_notetype) == len(expected['cards'])
        finally:
            fresh.close()
        col = Collection(str(Path(directory) / 'collection.anki2'))
        try:
            model = col.models.new(expected['model']['modelName'])
            for name in expected['fields']:
                col.models.add_field(model, col.models.new_field(name))
            model['css'] = expected['model']['css']
            for source in expected['model']['cardTemplates']:
                template = col.models.new_template(source['Name'])
                template.update(qfmt=source['Front'], afmt=source['Back'])
                col.models.add_template(model, template)
            col.models.add(model)
            col.models.set_current(model)

            def import_tsv(name):
                metadata = col.get_csv_metadata(str(root / name), None)
                metadata.dupe_resolution = CsvMetadata.DUPLICATE
                col.import_csv(ImportCsvRequest(path=str(root / name), metadata=metadata))
                notes = [col.get_note(nid) for nid in col.find_notes('')]
                assert len(notes) == len(expected['cards'])
                return notes

            # Reproduce the reported failure with the old Front/Back export
            # while the multi-field note type is selected in Anki.
            notes = import_tsv('old.tsv')
            assert all(note['Word'] and not note['Meaning'] and not note['Pronunciation'] for note in notes)
            col.remove_notes(col.find_notes(''))

            notes = import_tsv('full.tsv')
            for note, fields in zip(notes, expected['cards']):
                assert dict(note.items()) == fields, (dict(note.items()), fields)
                assert fields['Meaning'] in note.cards()[0].answer()
            col.remove_notes(col.find_notes(''))

            notes = import_tsv('basic.tsv')
            assert all(note.note_type()['name'] == 'Basic' for note in notes)
            for note, fields in zip(notes, expected['cards']):
                assert note['Front'] == fields['Word']
                assert fields['Meaning'] in note['Back'] and fields['Pronunciation'] in note['Back']
            col.remove_notes(col.find_notes(''))

            col.import_anki_package(ImportAnkiPackageRequest(package_path=str(root / 'cards.apkg')))
            notes = [col.get_note(nid) for nid in col.find_notes('')]
            assert len(notes) == len(expected['cards'])
            for note, fields in zip(notes, expected['cards']):
                assert dict(note.items()) == fields
                assert fields['Meaning'] in note.cards()[0].answer()
            assert list(Path(col.media.dir()).glob('*.wav'))
            col.import_anki_package(ImportAnkiPackageRequest(package_path=str(root / 'cards.apkg')))
            assert col.note_count() == len(notes), 'Reimporting a package created duplicate notes'
        finally:
            col.close()
    print('Real Anki importer passed: reproduced old loss, full TSV mapping, Basic TSV, package fields/audio/rendering, repeat import.')


if __name__ == '__main__':
    main(sys.argv[1])
