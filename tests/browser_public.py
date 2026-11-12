"""Public-mode browser check: private browser storage survives server cache loss."""
import copy
import io
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from app import create_app
from test_reader import entry
from test_features import wav


def main():
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(Path(directory) / 'public.sqlite3', public=True)
        def lookup(word):
            card = copy.deepcopy(entry())
            card['analyses'] = [dict(base=word, prefix='', explanation='Original spelling', matches=[dict(card['canonical'], description='Matched form')])]
            return dict(entries=[card], warnings=[], candidates=[])
        app.extensions['dictionary'].lookup = lookup
        app.extensions['anki'].call = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Public site called Anki'))
        server = make_server('127.0.0.1', 5053, app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', '/snap/bin/chromium'), headless=True, args=['--no-sandbox'])
                alice = browser.new_context(viewport={'width': 1440, 'height': 1100})
                bob = browser.new_context()
                page = alice.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto('http://127.0.0.1:5053')
                page.wait_for_function("document.body.dataset.storageReady === 'true'")
                assert not page.locator('#connect').is_visible()
                assert not page.locator('#import').is_visible()
                page.fill('#input', 'ספר טוב')
                page.click('#read')
                page.locator('.token').nth(0).click()
                page.wait_for_selector('[data-add="6104"]')
                page.click('[data-add="6104"]')
                page.click('#skip')
                # Add manual audio through the same API and IndexedDB used by UI.
                page.evaluate("""async recording => {
                    const response=await fetch('/api/manual',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({word:'ספר',meanings:['my own sense'],recording})});
                    const {entries}=await response.json();
                    const existing=await IvritStorage.get('basket',[]);
                    await IvritStorage.set('basket',[...existing,...entries]);
                }""", wav())
                page.reload()
                page.wait_for_function("document.body.dataset.storageReady === 'true'")
                assert page.input_value('#input') == 'ספר טוב'
                assert page.inner_text('#basketCount') == '2 meanings'
                assert page.locator('#basket audio').count() == 1
                assert page.locator('#basket audio').evaluate('(audio)=>audio.src.startsWith("blob:")')
                # The server holds no visitor cards or audio; a new visitor is empty.
                other = bob.new_page()
                other.goto('http://127.0.0.1:5053')
                other.wait_for_function("document.body.dataset.storageReady === 'true'")
                assert other.inner_text('#basketCount') == '0 meanings'
                assert other.input_value('#input') == ''
                other.fill('#input', 'ספר')
                other.click('#read')
                other.wait_for_selector('.token')
                assert not other.locator('.token').evaluate('(node)=>node.classList.contains("known")')
                page.click('#read')
                page.wait_for_selector('.token.known')
                # Simulate Render clearing its ephemeral database.
                with sqlite3.connect(app.extensions['store'].path) as db:
                    for table in ('entries', 'skips', 'cache'):
                        db.execute('DELETE FROM ' + table)
                with page.expect_download() as download:
                    page.click('#export')
                assert download.value.suggested_filename == 'hebrew-vocabulary.zip'
                exported = page.evaluate("""async () => {
                    const entries=await IvritStorage.get('basket',[]);
                    const response=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({entries})});
                    return Array.from(new Uint8Array(await response.arrayBuffer()));
                }""")
                with zipfile.ZipFile(io.BytesIO(bytes(exported))) as archive:
                    tsv = archive.read('hebrew-vocabulary.tsv').decode()
                    assert 'my own sense' in tsv and 'pealim::6104' in tsv
                    assert len([n for n in archive.namelist() if n.endswith('.wav')]) == 1
                # A public manual form also persists through the normal UI path.
                page.click('#addManual')
                page.fill('#manualWord', 'טוב')
                page.fill('#manualMeanings', 'good\nwell')
                page.click('#saveManual')
                page.wait_for_function("document.getElementById('basketCount').textContent === '4 meanings'")
                page.reload()
                page.wait_for_function("document.body.dataset.storageReady === 'true'")
                assert page.inner_text('#basketCount') == '4 meanings'
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path='/tmp/ivrit-public-mobile.png', full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not errors, errors
                browser.close()
                print('Public browser check passed: per-browser isolation, IndexedDB audio/cards/draft/skips, local Anki disabled, export after cache loss, manual form, mobile layout.')
        finally:
            server.shutdown()

if __name__ == '__main__':
    main()
