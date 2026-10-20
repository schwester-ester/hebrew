"""Optional end-to-end check: pip install playwright; use a Chromium executable.

Runs an isolated local server with real parsers and a simulated Anki connection.
Does not access or modify a real Anki deck.
"""
import copy
import os
from pathlib import Path
import sys
import tempfile
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from app import create_app
from morphology import candidates
from test_reader import entry, FakeAnki

def main():
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(Path(directory) / 'db.sqlite')
        fake = FakeAnki()
        app.extensions['anki'].call = fake.call
        def lookup(word):
            kinds = ['noun','verb'] if word == 'ספר' else ['adjective'] if word == 'טוב' else ['irregular'] if word == 'שולחן' else ['noun'] if word == 'ספרים' else []
            entries = []
            for kind in kinds:
                e = copy.deepcopy(entry(kind))
                app.extensions['store'].entry(e)
                f = dict(e['canonical'],description='Matched form')
                e['analyses'] = [dict(base=word,prefix='',explanation='Original spelling',matches=[f])]
                entries.append(e)
            return dict(entries=entries,candidates=candidates(word),warnings=[])
        app.extensions['dictionary'].lookup = lookup
        server = make_server('127.0.0.1', 5051, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH','/snap/bin/chromium'), headless=True, args=['--no-sandbox'])
                page = browser.new_page(viewport={'width':1440,'height':1100})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto('http://127.0.0.1:5051')
                page.screenshot(path='/tmp/ivrit-initial.png',full_page=True)
                page.click('#connect')
                page.wait_for_function("document.getElementById('connection').textContent.startsWith('Connected')")
                page.fill('#input','ספר טוב ספר שולחן')
                page.click('#read')
                page.wait_for_selector('.token')
                page.locator('.token').nth(0).click(modifiers=['Control'])
                page.locator('.token').nth(1).click(modifiers=['Control'])
                assert page.inner_text('#selectedCount') == '2'
                page.click('#selected')
                page.wait_for_selector('[data-add="6104"]')
                page.click('[data-add="6104"]')
                page.click('[data-add="1409"]')
                page.keyboard.press('ArrowLeft')
                page.wait_for_selector('[data-add="5422"]')
                page.click('[data-add="5422"]')
                assert page.inner_text('#basketCount') == '3 meanings'
                with page.expect_download() as info:
                    page.click('#export')
                assert info.value.suggested_filename == 'hebrew-vocabulary.tsv'
                page.screenshot(path='/tmp/ivrit-reading.png',full_page=True)
                page.click('#import')
                page.wait_for_function("document.getElementById('basketCount').textContent === '0 meanings'")
                assert len(fake.notes) == 3
                assert 'Imported 3' in page.inner_text('#notice')
                page.click('#edit')
                page.fill('#input','שולחן ספרים')
                page.click('#read')
                page.wait_for_selector('.token')
                page.locator('.token').nth(0).click()
                page.wait_for_selector('[data-add="4939"]')
                assert 'Irregular plural' in page.inner_text('#results')
                page.click('#skip')
                page.wait_for_function("document.querySelectorAll('.token.known').length === 2")
                page.reload()
                page.fill('#input','שולחן ספר')
                page.click('#read')
                page.wait_for_selector('.token.known')
                assert 'שולחן' in page.inner_text('.token.known')
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path='/tmp/ivrit-mobile.png',full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                assert not errors, errors
                browser.close()
                print('Browser smoke passed: selection, arrows, canonical cards, TSV, import, known inflections, persistent skips, mobile, no JavaScript errors.')
        finally:
            server.shutdown()

if __name__ == '__main__':
    main()
