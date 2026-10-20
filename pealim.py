"""Parse Pealim's search groups and canonical inflection tables, not related words."""
import re
import threading
import time
from urllib.parse import urlencode, urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from morphology import candidates, normalize

BASE = 'https://www.pealim.com'

def text(node):
    return node.get_text(' ', strip=True) if node else ''

def form(node):
    heb = node.select_one('.menukad')
    if not heb:
        return None
    # Pealim's optional full spelling sits immediately after the pointed span.
    variant = heb.next_sibling
    full = text(variant).lstrip('~ ').strip() if getattr(variant, 'get_text', None) else ''
    pronunciation = node.select_one('.transcription')
    stress = pronunciation.find('b') if pronunciation else None
    audio = node.select_one('[data-audio]')
    return dict(vowelled=text(heb), plain=normalize(full or text(heb)),
                pronunciation=pronunciation.get_text('', strip=True) if pronunciation else '',
                stress=text(stress), audio=audio.get('data-audio', '') if audio else '')

def parse_search(html):
    soup = BeautifulSoup(html, 'html.parser')
    if not soup.select_one('h3') or 'Results for' not in soup.get_text():
        raise ValueError('Pealim returned an unexpected search page. Please retry later.')
    results = []
    for group in soup.select('.verb-search-result'):
        link = group.select_one('.verb-search-lemma a')
        if not link:
            continue
        matches = []
        for row in group.select('.vf-search-result'):
            f = form(row)
            if f:
                f['description'] = text(row.select_one('.vf-search-tpgn')).rstrip(': ')
                matches.append(f)
        results.append(dict(url=urljoin(BASE, link['href'].split('#')[0]), matches=matches))
    pages = {urljoin(BASE, a['href']) for a in soup.select('.pagination a[href]')}
    return results, sorted(pages)

def parse_entry(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    header = soup.select_one('h2.page-header')
    if not header:
        raise ValueError('Pealim entry structure changed; card generation stopped.')
    pos_node = header.find_next_sibling('p')
    characteristics = text(pos_node)
    pos = characteristics.split('–')[0].strip().lower()
    meaning_header = next((h for h in soup.find_all('h3') if text(h) == 'Meaning'), None)
    meaning = text(meaning_header.find_next_sibling()) if meaning_header else ''
    root_node = next((p for p in header.parent.find_all('p', recursive=False) if text(p).startswith('Root:')), None)
    forms = {}
    for cell in soup.select('td.conj-td > div[id]'):
        f = form(cell)
        if f:
            forms[cell['id']] = f
    canonical_id = 'INF-L' if pos == 'verb' else 'ms-a' if pos == 'adjective' else 's' if pos == 'noun' else None
    canonical = forms.get(canonical_id)
    plural_only = False
    if pos == 'noun' and not canonical and forms.get('p'):
        canonical = forms['p']
        plural_only = True
    if pos not in ('verb', 'adjective', 'noun'):
        # Prepositions expose their unaffixed base outside the personal-form table.
        # Uninflected adverbs/conjunctions have a standalone .lead form block.
        base = header.parent.select_one('div#b')
        canonical = form(base) if base else None
        if canonical is None:
            for block in header.parent.find_all('div', class_='lead', recursive=False):
                if block.select_one('.menukad') and block.select_one('.transcription'):
                    canonical = form(block)
                    break
    plural = forms.get('p') if pos == 'noun' else None
    genders = [g for g in ('masculine', 'feminine') if g in characteristics.lower()]
    gender = genders[0] if len(genders) == 1 else ''
    irregular = bool(plural and ((gender == 'masculine' and plural['plain'].endswith('ות')) or
                                 (gender == 'feminine' and plural['plain'].endswith('ים'))))
    entry_id = re.search(r'/dict/(\d+)-', url)
    if not entry_id or not meaning:
        raise ValueError('Incomplete dictionary entry; refusing to make a card.')
    return dict(id=entry_id.group(1), url=url, pos=pos, characteristics=characteristics,
                root=text(root_node).removeprefix('Root:').strip(), meaning=meaning,
                canonical=canonical, plural=plural, irregular_plural=irregular,
                plural_only=plural_only, forms=forms,
                importable=bool(canonical and canonical['pronunciation']))

class Pealim:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.last = 0

    def fetch(self, url):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.netloc != 'www.pealim.com' or not parsed.path.startswith(('/search/', '/dict/')):
            raise ValueError('Invalid dictionary URL')
        cached = self.store.cached(url)
        if cached is not None:
            return cached
        with self.lock:
            cached = self.store.cached(url)
            if cached is not None:
                return cached
            time.sleep(max(0, 0.8 - (time.monotonic() - self.last)))
            try:
                response = requests.get(url, timeout=25, headers={'User-Agent': 'HebrewReader/1.0 (personal vocabulary study)'})
                response.raise_for_status()
                response.encoding = 'utf-8'
                html = response.text
                if 'menukad' not in html or 'captcha' in html.lower():
                    raise ValueError('Pealim is unavailable or requesting browser verification.')
                self.store.cache(url, html)
                return html
            finally:
                self.last = time.monotonic()

    def lookup(self, word):
        entries = {}
        warnings = []
        variants = candidates(word)
        for variant in variants:
            url = BASE + '/search/?' + urlencode({'q': variant['base']})
            pending, visited = [url], set()
            try:
                while pending:
                    page = pending.pop(0)
                    if page in visited:
                        continue
                    visited.add(page)
                    results, pages = parse_search(self.fetch(page))
                    pending.extend(p for p in pages if p not in visited)
                    for result in results:
                        # Search can return phrase/partial suggestions; require an exact form.
                        matches = [f for f in result['matches'] if f['plain'] == variant['base'] or normalize(f['vowelled']) == variant['base']]
                        if not matches:
                            continue
                        entry = entries.get(result['url'])
                        if entry is None:
                            entry = parse_entry(self.fetch(result['url']), result['url'])
                            self.store.entry(entry)
                            entry['analyses'] = []
                            entries[result['url']] = entry
                        entry['analyses'].append(dict(**variant, matches=matches))
            except (requests.RequestException, ValueError) as error:
                warnings.append(f"{variant['base']}: {error}")
        return dict(entries=list(entries.values()), candidates=variants, warnings=warnings)
