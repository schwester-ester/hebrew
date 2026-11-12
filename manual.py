"""Validated user-authored meanings and portable WAV recordings."""
import base64
import binascii
import io
import uuid
import wave
from morphology import normalize, tokens


def audio_bytes(entry):
    return base64.b64decode(entry['recording']) if entry.get('recording') else b''


def validate_recording(recording):
    if not isinstance(recording, str) or len(recording) > 2700000:
        raise ValueError('Recording is too large. Use at most 60 seconds.')
    if recording:
        try:
            raw = base64.b64decode(recording, validate=True)
            with wave.open(io.BytesIO(raw)) as wav:
                if (wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 16000
                        or not 0 < wav.getnframes() <= 60 * 16000
                        or len(wav.readframes(wav.getnframes())) != wav.getnframes() * 2):
                    raise ValueError('Invalid recording')
        except (ValueError, binascii.Error, wave.Error, EOFError) as error:
            raise ValueError('Use a valid mono 16 kHz WAV recording of at most 60 seconds.') from error
    return recording


def make_entries(data):
    def field(name, limit=200):
        value = data.get(name, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f'{name.capitalize()} must be text shorter than {limit + 1} characters.')
        return value.strip()
    word = field('word')
    if not word or not tokens(word):
        raise ValueError('Enter the Hebrew word or phrase.')
    meanings = data.get('meanings')
    if (not isinstance(meanings, list) or not 1 <= len(meanings) <= 20
            or any(not isinstance(m, str) or not m.strip() or len(m) > 2000 for m in meanings)):
        raise ValueError('Enter 1–20 definitions, each shorter than 2,001 characters.')
    pos = field('pos')
    if pos not in ('', 'noun', 'verb', 'adjective', 'adverb', 'preposition', 'phrase', 'other'):
        raise ValueError('Choose a part of speech from the list.')
    genders = data.get('genders', [])
    if not isinstance(genders, list) or any(g not in ('masculine', 'feminine') for g in genders):
        raise ValueError('Choose masculine and/or feminine.')
    number = field('number')
    if number not in ('', 'singular', 'plural', 'both'):
        raise ValueError('Choose a number from the list.')
    vowelled, pronunciation, root, notes = field('vowelled'), field('pronunciation'), field('root'), field('notes', 4000)
    recording = validate_recording(data.get('recording', ''))
    entries = []
    for meaning in dict.fromkeys(m.strip() for m in meanings):
        identity = 'manual-' + uuid.uuid4().hex
        entries.append(dict(id=identity, source='manual', url='', pos=pos,
                            characteristics=' · '.join(filter(None, [pos.title(), *dict.fromkeys(genders), number])),
                            root=root, notes=notes, meaning=meaning,
                            canonical=dict(plain=normalize(word), vowelled=vowelled or word,
                                           pronunciation=pronunciation, stress='', audio=''),
                            plural=None, irregular_plural=False, plural_only=False, forms={},
                            importable=True, recording=recording,
                            audio_filename=identity + '.wav' if recording else ''))
    return entries


def summary(entry):
    return {k: v for k, v in entry.items() if k != 'recording'}
