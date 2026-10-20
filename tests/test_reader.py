from pathlib import Path
import csv
import io
import pytest
from anki import Anki, FIELDS, card_fields, export_tsv
from app import create_app
from morphology import candidates, normalize, tokens
from pealim import Pealim, parse_entry, parse_search
from storage import Store

FIXTURES = Path(__file__).parent / 'fixtures'

def entry(kind='noun'):
    paths = {'noun': '6104-sefer', 'verb': '1409-lesaper', 'adjective': '5422-tov', 'irregular': '4939-shulchan'}
    return parse_entry((FIXTURES / (kind + '.html')).read_text(), 'https://www.pealim.com/dict/' + paths[kind] + '/')

def test_tokens_preserve_punctuation_and_niqqud():
    text = '“וְהַסֵּפֶר”, בית־ספר! צה״ל'
    result = tokens(text)
    assert [w['key'] for w in result] == ['והספר', 'בית', 'ספר', 'צה"ל']
    assert all(text[w['start']:w['end']] == w['text'] for w in result)

def test_legal_prefix_candidates_keep_root_letters():
    assert candidates('מלך')[0]['base'] == 'מלך'
    assert any(c['base'] == 'ספר' and c['prefix'] == 'ושמה' for c in candidates('ושמהספר'))
    assert any(c['base'] == 'בית' and c['prefix'] == 'וכשב' for c in candidates('וכשבבית'))
    assert not any(c['prefix'] == 'בה' for c in candidates('בהספר'))
    assert not any(c['prefix'] == 'שו' for c in candidates('שוהספר'))
    assert not any(c['prefix'] == 'וו' for c in candidates('ווספר'))
    assert any('absorbed' in c['explanation'] for c in candidates('בבית') if c['prefix'] == 'ב')

def test_search_retains_homographs_and_matched_inflections():
    results, _ = parse_search((FIXTURES / 'search.html').read_text())
    assert len(results) == 5
    assert results[1]['matches'][0]['pronunciation'] == 'sefer'
    assert results[2]['matches'][0]['pronunciation'] == 'sapar'
    assert any(f['plain'] == 'סיפר' for f in results[3]['matches'])

@pytest.mark.parametrize('kind,plain,pos', [('noun','ספר','noun'), ('verb','לספר','verb'), ('adjective','טוב','adjective')])
def test_canonical_cards(kind, plain, pos):
    e = entry(kind)
    assert e['canonical']['plain'] == plain
    assert e['importable']
    f = card_fields(e)
    assert f['Word'] == plain
    assert pos.title() in f['Grammar']
    assert e['canonical']['pronunciation'] in f['Pronunciation']
    assert e['root'] in f['Root']
    if kind == 'verb':
        assert 'PI' in f['Grammar'] and 'infinitive' in f['Grammar']
    if kind == 'adjective':
        assert 'masculine singular' in f['Grammar'] and 'Feminine singular' in f['Forms']

def test_irregular_plural_preserves_gender():
    e = entry('irregular')
    assert e['irregular_plural']
    f = card_fields(e)
    assert f['Word'] == 'שולחן / שולחנות'
    assert 'masculine' in f['Grammar'] and 'Irregular plural' in f['Forms']

def test_no_infinitive_does_not_import_participle():
    html = (FIXTURES / 'verb.html').read_text().replace('id="INF-L"', 'id="unsupported"')
    e = parse_entry(html, 'https://www.pealim.com/dict/1409-lesaper/')
    assert not e['importable']
    with pytest.raises(ValueError):
        card_fields(e)

@pytest.mark.parametrize('kind,id,plain,pronunciation', [('adverb','5998-hayom','היום','hayom'), ('preposition','6012-al','על','al')])
def test_uninflected_bases_are_not_personal_forms(kind,id,plain,pronunciation):
    e = parse_entry((FIXTURES / (kind + '.html')).read_text(), 'https://www.pealim.com/dict/' + id + '/')
    assert e['canonical']['plain'] == plain
    assert e['canonical']['pronunciation'] == pronunciation
    assert e['importable']

def test_tsv_preserves_identity_and_html():
    content = export_tsv([entry(), entry('verb')])
    assert '#html:true' in content and '#tags column:3' in content
    rows = list(csv.reader(io.StringIO('\n'.join(line for line in content.splitlines() if not line.startswith('#'))), delimiter='\t'))
    assert len(rows) == 2 and len(rows[0]) == 3
    assert 'pealim::6104' in rows[0][2] and 'סֵפֶר' in rows[0][1]

def test_lookup_filters_phrase_suggestions_and_deduplicates(tmp_path, monkeypatch):
    store = Store(tmp_path / 'db.sqlite')
    dictionary = Pealim(store)
    noun_url = 'https://www.pealim.com/dict/6104-sefer/'
    def fetch(url):
        if '/search/' in url:
            soup = (FIXTURES / 'search.html').read_text()
            # Restrict to the book and phrase so both canonical fixtures are enough.
            from bs4 import BeautifulSoup
            parsed = BeautifulSoup(soup, 'html.parser')
            return '<h3>Results for ספר</h3>' + str(parsed.select('.verb-search-result')[1]) + str(parsed.select('.verb-search-result')[4])
        assert url == noun_url
        return (FIXTURES / 'noun.html').read_text()
    monkeypatch.setattr(dictionary, 'fetch', fetch)
    result = dictionary.lookup('והספר')
    assert len(result['entries']) == 1
    assert result['entries'][0]['analyses'][0]['prefix'] == 'וה'
    assert not result['warnings']
    assert store.get_entry('6104')['canonical']['plain'] == 'ספר'

def test_persistent_skips_cache_and_api(tmp_path):
    app = create_app(tmp_path / 'db.sqlite')
    client = app.test_client()
    assert client.post('/api/skip',json={'word':'סֵפֶר'}).status_code == 200
    response = client.post('/api/text',json={'text':'ספר, טוב. ספר!'})
    assert [w['known'] for w in response.json['tokens']] == [True,False,True]
    other = create_app(tmp_path / 'db.sqlite').test_client()
    assert other.post('/api/text',json={'text':'ספר'}).json['tokens'][0]['known']
    assert client.post('/api/skip',json={'word':'ספר','remove':True}).json['skipped'] == []
    assert client.post('/api/import',json={'ids':['untrusted'], 'deck':'Hebrew'}).status_code == 400
    assert client.post('/api/skip',json={'word':'ספר'},headers={'Origin':'https://example.com'}).status_code == 403
    assert client.get('/').status_code == 200

class FakeAnki(Anki):
    def __init__(self):
        self.notes = {}; self.actions = []; self.fail = False
    def call(self, action, **params):
        self.actions.append((action,params))
        if action == 'deckNames': return ['Hebrew']
        if action == 'modelNames': return []
        if action == 'createModel': return 1
        if action == 'findNotes':
            return [i for i,n in self.notes.items() if ' tag:' not in params['query'] or params['query'].split(' tag:')[1] in n['tags']]
        if action == 'notesInfo': return [self.notes[i] for i in params['notes']]
        if action == 'addNote':
            if self.fail: raise ValueError('Simulated failure')
            note = params['note']; i=len(self.notes)+1
            self.notes[i] = dict(tags=note['tags'],modelName='Hebrew Reader',fields={k:dict(value=v,order=offset) for offset,(k,v) in enumerate(note['fields'].items())})
            return i
        raise AssertionError(action)

def test_import_duplicates_and_partial_failures():
    anki = FakeAnki()
    result = anki.add('Hebrew',[entry(), entry('verb')])
    assert result['imported'] == ['6104','1409']
    assert anki.add('Hebrew',[entry()])['duplicates'] == ['6104']
    assert len(anki.notes) == 2
    words, ids = anki.known('Hebrew')
    assert words == set() and ids == {'6104','1409'}
    anki.fail = True
    result = anki.add('Hebrew',[entry(),entry('adjective')])
    assert result['duplicates'] == ['6104'] and result['failed'][0]['id'] == '5422'

def test_existing_deck_fronts_and_custom_fields():
    anki=FakeAnki()
    anki.notes[1]=dict(tags=[],modelName='Basic',fields={'Meaning':dict(value='book',order=0),'Hebrew':dict(value='<b>סֵפֶר</b>',order=1)})
    assert anki.known('Hebrew','Hebrew')[0] == {'ספר'}
    with pytest.raises(ValueError):
        anki.known('Hebrew','Typo')

def test_import_does_not_duplicate_older_untagged_front():
    anki=FakeAnki()
    anki.notes[1]=dict(tags=[],modelName='Basic',fields={'Front':dict(value='סֵפֶר',order=0),'Back':dict(value='book',order=1)})
    result=anki.add('Hebrew',[entry()])
    assert result['duplicates']==['6104'] and result['imported']==[]
    assert len(anki.notes)==1
    anki.notes[1]['fields']={'Meaning':dict(value='book',order=0),'Hebrew':dict(value='ספר',order=1)}
    assert anki.add('Hebrew',[entry()],field='Hebrew')['duplicates']==['6104']

def test_api_import_tracks_only_success(tmp_path, monkeypatch):
    app=create_app(tmp_path/'db.sqlite')
    fake=FakeAnki()
    real=app.extensions['anki']
    monkeypatch.setattr(real,'call',fake.call)
    store=app.extensions['store']
    store.entry(entry());store.entry(entry('adjective'))
    client=app.test_client()
    assert client.post('/api/sync',json={'deck':'Hebrew'}).status_code==200
    assert client.post('/api/import',json={'deck':'Hebrew','ids':['6104']}).json['imported']==['6104']
    fake.fail=True
    assert client.post('/api/import',json={'deck':'Hebrew','ids':['5422']}).json['failed'][0]['id']=='5422'
    synced=client.post('/api/sync',json={'deck':'Hebrew'}).json
    assert synced['entries']==['6104']
