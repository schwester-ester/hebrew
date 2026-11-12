"""Validate browser-owned cards for stateless public exports.

Only accepted fields reach the existing escaped card renderer. The public
service never saves a visitor's cards, recordings, skips, or Anki credentials.
"""
import re
from manual import validate_recording
from morphology import tokens


def portable_entry(raw):
    if not isinstance(raw, dict):
        raise ValueError('Invalid vocabulary card.')

    def text(obj, key, limit=200):
        value = obj.get(key, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f'Invalid card field: {key}.')
        return value

    identity = text(raw, 'id', 50)
    manual = bool(re.fullmatch(r'manual-[a-f0-9]{32}', identity))
    if not manual and not re.fullmatch(r'\d{1,20}', identity):
        raise ValueError('Invalid card identity.')

    def form(value):
        if not isinstance(value, dict):
            raise ValueError('Invalid word form.')
        return {key: text(value, key) for key in ('plain', 'vowelled', 'pronunciation', 'stress')}

    canonical = form(raw.get('canonical'))
    meaning = text(raw, 'meaning', 2000)
    if not tokens(canonical['plain']) or not meaning.strip():
        raise ValueError('Each card needs a Hebrew word and meaning.')
    if not manual and not canonical['pronunciation']:
        raise ValueError('A dictionary card needs a canonical pronunciation.')
    url = text(raw, 'url', 500)
    if not manual and not re.fullmatch(r'https://www\.pealim\.com/dict/' + identity + r'-[a-zA-Z0-9-]+/', url):
        raise ValueError('Invalid dictionary source.')
    forms = raw.get('forms', {})
    if not isinstance(forms, dict):
        raise ValueError('Invalid card forms.')
    recording = validate_recording(raw.get('recording', '')) if manual else ''
    plural = form(raw['plural']) if raw.get('plural') is not None else None
    return dict(id=identity, source='manual' if manual else 'pealim', url='' if manual else url,
                canonical=canonical, meaning=meaning, pos=text(raw, 'pos'),
                characteristics=text(raw, 'characteristics', 1000), root=text(raw, 'root'),
                notes=text(raw, 'notes', 4000), forms={k: form(forms[k]) for k in ('fs-a', 'mp-a', 'fp-a') if k in forms},
                plural=plural, irregular_plural=raw.get('irregular_plural') is True and plural is not None,
                plural_only=raw.get('plural_only') is True, importable=True,
                recording=recording, audio_filename=identity + '.wav' if recording else '')
