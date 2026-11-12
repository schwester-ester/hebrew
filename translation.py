"""On-demand Hebrew → English via Google's public, unofficial endpoint."""
import re
import requests


def translate(parts):
    if (not isinstance(parts, list) or not parts or len(parts) > 500
            or any(not isinstance(p, str) or not p.strip() for p in parts)
            or sum(map(len, parts)) > 50000):
        raise ValueError('Choose text between 1 and 50,000 characters.')
    translated = []
    try:
        for part in parts:
            # Stay below URL limits, splitting at whitespace where possible.
            chunks = re.findall(r'[\s\S]{1,1200}(?:\s|$)|[\s\S]{1,1200}', part)
            output = []
            for chunk in chunks:
                response = requests.get('https://clients5.google.com/translate_a/t',
                                        params=dict(client='dict-chrome-ex', sl='he', tl='en', q=chunk), timeout=25)
                response.raise_for_status()
                result = response.json()
                text = result[0]
                if not isinstance(text, str) or not text:
                    raise ValueError('Empty translation')
                output.append(text)
            translated.append(' '.join(output))
    except (requests.RequestException, ValueError, TypeError, IndexError, KeyError) as error:
        raise ValueError('Google translation is unavailable or rate-limited. Retry, or open this text in Google Translate below.') from error
    return translated
