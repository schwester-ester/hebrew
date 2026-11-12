"""Browser integration: range selection, translation, manual senses and real WAV encoding.

Uses Chromium's synthetic microphone, isolated SQLite, mocked translation and Anki.
Run: .venv/bin/python tests/browser_features.py
"""
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import wave
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as app_module
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from test_reader import FakeAnki


def main():
    with tempfile.TemporaryDirectory() as directory:
        app = app_module.create_app(Path(directory) / 'db')
        fake = FakeAnki()
        media = {}
        def call(action, **params):
            if action == 'storeMediaFile':
                media[params['filename']] = params['data']
                return params['filename']
            return fake.call(action, **params)
        app.extensions['anki'].call = call
        app.extensions['dictionary'].lookup = lambda word: dict(entries=[], warnings=[], candidates=[])
        translations = []
        def translate(parts):
            translations.append(parts)
            return ['English: ' + p for p in parts]
        app_module.translate = translate
        server = make_server('127.0.0.1', 5052, app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', '/snap/bin/chromium'), headless=True,
                                            args=['--no-sandbox', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'])
                page = browser.new_page(permissions=['microphone'], viewport={'width': 1440, 'height': 1100})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto('http://127.0.0.1:5052')
                page.fill('#input', '📚 ספר טוב בבית ילדים ספרים חדשים')
                page.click('#translate')
                page.wait_for_selector('#translationOutput p')
                assert translations[-1] == ['📚 ספר טוב בבית ילדים ספרים חדשים']
                page.evaluate("document.getElementById('input').setSelectionRange(3,9)")
                page.click('#translate')
                page.wait_for_function("document.getElementById('translationOutput').textContent === 'English: ספר טו'")
                assert translations[-1] == ['ספר טו']
                page.click('#read')
                tokens = page.locator('.token')
                page.wait_for_selector('.token')
                assert tokens.count() == 6
                assert '📚' in page.inner_text('#passage')
                tokens.nth(0).click(modifiers=['Control'])
                tokens.nth(1).click(modifiers=['Shift'])
                assert page.inner_text('#selectedCount') == '2'
                tokens.nth(4).click(modifiers=['Control'])
                tokens.nth(5).click(modifiers=['Control', 'Shift'])
                assert page.inner_text('#selectedCount') == '4'
                page.click('#translate')
                page.wait_for_function("document.querySelectorAll('#translationOutput p').length === 2")
                assert translations[-1] == ['ספר טוב', 'ספרים חדשים']
                tokens.nth(1).click(modifiers=['Control'])
                assert page.inner_text('#selectedCount') == '3'
                page.click('#clear')
                assert page.inner_text('#translationScope') == 'Full text · Google Translate'
                # Manual cards remain available without any lookup result.
                page.click('#addManual')
                page.fill('#manualWord', 'סֵפֶר')
                page.fill('#manualMeanings', 'book\nregister')
                page.click('#manualOptions summary')
                page.select_option('#manualPos', 'noun')
                page.check('#manualMasculine')
                page.check('#manualFeminine')
                page.fill('#manualNotes', 'A custom example')
                page.click('#record')
                page.wait_for_function("document.getElementById('record').textContent.includes('Stop')")
                # Wait for the synthetic microphone to produce actual samples.
                page.wait_for_timeout(800)
                page.click('#record')
                page.wait_for_selector('#recordPreview:visible')
                assert page.locator('#recordPreview').evaluate('(a)=>a.src.startsWith("blob:")')
                page.click('#saveManual')
                page.wait_for_function("document.getElementById('basketCount').textContent === '2 meanings'")
                assert page.locator('#basket audio').count() == 2
                page.reload()
                assert page.inner_text('#basketCount') == '2 meanings'
                with page.expect_download() as download:
                    page.click('#export')
                assert download.value.suggested_filename.endswith('.zip')
                # Verify binary bytes within the browser; Snap Chromium's
                # private /tmp makes download paths inaccessible to Python.
                exported_body = bytes(page.evaluate("""async () => {
                    const entries=JSON.parse(localStorage.getItem('ivrit-basket'));
                    const response=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids:entries.map(e=>e.id)})});
                    return Array.from(new Uint8Array(await response.arrayBuffer()));
                }"""))
                with zipfile.ZipFile(io.BytesIO(exported_body)) as z:
                    wavs = [n for n in z.namelist() if n.endswith('.wav')]
                    assert len(wavs) == 2
                    with wave.open(io.BytesIO(z.read(wavs[0]))) as audio:
                        assert audio.getframerate() == 16000 and audio.getnframes() > 0
                page.click('#connect')
                page.wait_for_function("document.getElementById('connection').textContent.startsWith('Connected')")
                page.click('#import')
                page.wait_for_function("document.getElementById('basketCount').textContent === '0 meanings'")
                assert len(fake.notes) == 2 and len(media) == 2
                page.click('#addManual')
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path='/tmp/ivrit-features-mobile.png', full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                # Recoverable translation failure keeps a direct Google link.
                def fail(parts): raise ValueError('Google is temporarily unavailable.')
                app_module.translate = fail
                page.fill('#input', 'שלום')
                page.click('#translate')
                page.wait_for_function("document.getElementById('translationStatus').textContent.includes('temporarily unavailable')")
                assert 'text=' in page.get_attribute('#googleTranslate', 'href')
                assert not errors, errors
                browser.close()
                print('Features passed: full/partial/disjoint translation, range selection, emoji offsets, multiple manual senses, microphone → WAV → ZIP/Anki, reload persistence, failure fallback, mobile layout.')
        finally:
            server.shutdown()

if __name__ == '__main__':
    main()
