"""Conservative Modern Hebrew clitic candidates; never remove inflection letters."""
import re
import unicodedata
from itertools import product

WORD = re.compile(r"[א-ת][א-ת\u0591-\u05bd\u05bf-\u05c7]*(?:[׳'״\"][א-ת][א-ת\u0591-\u05bd\u05bf-\u05c7]*)*")

def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text)
                   if 'א' <= c <= 'ת' or c.isspace() or c in "׳'״\"").strip().replace('׳', "'").replace('״', '"')

def tokens(text):
    return [dict(text=m.group(), key=normalize(m.group()), start=m.start(), end=m.end()) for m in WORD.finditer(text)]

def candidates(word):
    """ו → ש/כש → ב/כ/ל/מ → ה. ב/כ/ל fuse with ה; מ retains it.

    Also admit מש־ ('from when/that'), a lexicalized relative sequence.
    Unprefixed original remains first, since every prefix can be a root letter.
    """
    word = normalize(word)
    patterns = [('', [])]
    labels = {'ו': 'and', 'ש': 'that / which', 'כש': 'when', 'ב': 'in / with',
              'כ': 'like / as', 'ל': 'to / for', 'מ': 'from', 'ה': 'the', 'מש': 'from when / since'}
    for conjunction, relative, prep, article in product(('', 'ו'), ('', 'ש', 'כש', 'מש'), ('', 'ב', 'כ', 'ל', 'מ'), ('', 'ה')):
        if article and prep in ('ב', 'כ', 'ל'):
            continue  # The article disappears in standard unpointed spelling.
        if relative == 'מש' and prep:
            continue
        parts = [p for p in (conjunction, relative, prep, article) if p]
        if parts:
            patterns.append((''.join(parts), [labels[p] for p in parts]))
    results = []
    for prefix, gloss in sorted(patterns, key=lambda x: len(x[0])):
        if word.startswith(prefix) and len(word) > len(prefix):
            base = word[len(prefix):]
            if not any(r['base'] == base and r['prefix'] == prefix for r in results):
                if prefix and prefix[-1] in 'בכל':
                    gloss = gloss + ['possibly definite (the absorbed article)']
                results.append(dict(base=base, prefix=prefix, explanation=' + '.join(gloss) or 'Original spelling'))
    return results
