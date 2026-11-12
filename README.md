# Ivrit — Hebrew reading to Anki

A web app for turning Hebrew reading into a personal vocabulary deck. Paste text, click words or Ctrl/⌘-click a selection, review dictionary readings, and import the meanings you choose.

## Run

Python 3.11 or newer:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Open **http://127.0.0.1:5000**. Stop the server with Ctrl-C.

## Publish at schwester-ester.github.io/hebrew

GitHub Pages serves the interface at **https://schwester-ester.github.io/hebrew/**. A separate Python service runs dictionary lookups, translation, manual card validation, and Anki exports. The local desktop app still works as before.

1. Deploy the Python backend with the Render instructions below. The included `render.yaml` allows browser requests from exactly `https://schwester-ester.github.io` through `IVRIT_ALLOWED_ORIGINS`. For another host, also configure `IVRIT_ALLOWED_HOSTS` with the backend hostname.
2. In the GitHub repository, open **Settings → Secrets and variables → Actions → Variables**. Create the repository variable **`IVRIT_API_BASE`** with the backend HTTPS origin, such as `https://your-service.onrender.com` (no path).
3. In **Settings → Pages**, select **GitHub Actions** as the source. The repository must be public or use a GitHub plan that supports Pages for private repositories.
4. Run **Deploy GitHub Pages** from the Actions tab, or push to `main`. The workflow waits until `IVRIT_API_BASE` is configured. It publishes only the rendered interface and its static assets; Python source, databases, and recordings are excluded.

To preview the static build locally:

```bash
.venv/bin/python build_pages.py --api-base https://your-service.onrender.com
python3 -m http.server 8080 --directory dist
```

The preview can load the interface; API calls require explicitly adding `http://localhost:8080` to the backend's `IVRIT_ALLOWED_ORIGINS` for local testing. Browser storage belongs to the website origin, so cards saved on the backend website do not automatically appear on GitHub Pages.

## Publish a free shared website

The repository includes `render.yaml` for one **Free** Render web service. GitHub stores the code; Render runs the Python backend and provides the public HTTPS link. [GitHub Pages cannot run Python servers](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site).

1. Sign up or sign in at [Render](https://dashboard.render.com/).
2. Choose **New → Blueprint** and connect the GitHub repository `schwester-ester/hebrew`. Select the public repository through its GitHub connection.
3. Select the `main` branch and let Render read `render.yaml`. Check that the service plan is **Free**, then deploy. The configuration creates only a web service: no paid disk or database.
4. After the service is live, open the HTTPS `onrender.com` URL shown in its dashboard. This is the link to share. Later pushes to `main` trigger redeployment.

To keep this strictly free, use the Free service plan without adding a payment method. If usage limits are reached, Render suspends services or builds instead of charging for extra usage. Do not add a paid disk or database.

The [free tier](https://render.com/docs/free) sleeps after 15 minutes without traffic, and the first request can take about a minute to wake it. It has monthly usage limits; stay on the Free compute plan and check the workspace's usage/billing settings rather than adding paid extras. The server filesystem is temporary, so the public version keeps each visitor's vocabulary, recordings, draft, and skipped words in their own browser's IndexedDB. Exported cards continue working after server cache loss. There are no accounts or cross-device storage: clearing site data removes that browser's saved work, so export cards to retain a copy.

The public version supports **Export for Anki** (full-field TSV, Basic TSV, ZIP with recordings, or .apkg deck packages) and an optional direct connection from the visitor’s browser to their own Anki desktop or AnkiDroid through the Android companion. The shared Python server only validates and formats cards for import; it never calls AnkiConnect or exposes local stored recordings. Collection contents and AnkiConnect API keys stay in the visitor’s browser. Package export sends only the user-selected deck name and tray cards to the server to build a temporary download; temporary package/media files are removed after generation. Reading and manual-card requests are processed by the server without saving personal content; only public dictionary entries/pages are cached. Translation passes the selected text to Google on demand. Dictionary/translation availability still depends on Pealim and Google's public endpoints.

The public service accepts two concurrent dictionary/translation requests, returning a retry message when busy. Translation requests are limited to 10,000 characters and exports to a 32 MB request body. Recorded cards are validated, source links are restricted to Pealim, and ZIP audio filenames are generated from validated card identities.

To test this mode locally:

```bash
.venv/bin/pip install -r requirements-hosted.txt
IVRIT_PUBLIC=1 .venv/bin/gunicorn 'app:create_app()' --bind 127.0.0.1:5060 --workers 1 --threads 8 --timeout 180
```

Open `http://127.0.0.1:5060`. For a different host outside Render, set `IVRIT_ALLOWED_HOSTS` to a comma-separated list of exact hostnames. Render's `RENDER_EXTERNAL_HOSTNAME` is trusted automatically. Use one worker so dictionary throttling and request limits apply across its threads. The `.python-version` file selects the latest Python 3.13 patch available on Render, following [Render's version configuration](https://render.com/docs/python-version).

## Connect your deck

The **Your Anki** panel at the top works on the public website and in the local app. TSV/ZIP export remains available without connecting.

1. Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) in Anki desktop using add-on code `2055492159`, restart Anki, and keep a profile open on the same computer as your browser.
2. Click **Connect & sync**. On the public website, approve the AnkiConnect request in Anki. If the browser asks for local network access, allow it. The browser contacts only `http://127.0.0.1:8765`; the hosted Python service never connects to your desktop.
3. Choose an existing deck from the dropdown, or enter a **New deck name** and click **Create deck**. Selecting a deck reads its existing notes so known vocabulary can be skipped.
4. Choose meanings or add manual cards. Click **Sync cards to Anki** at the top or in the vocabulary tray to add all tray cards to the selected deck, including recordings. Already imported identities are skipped; failed cards stay in the tray for retry. This writes to Anki desktop; use Anki’s own Sync button to sync its collection with AnkiWeb.
5. Click **Connect & sync** again after changes made in Anki. A deck refresh resets the reading queue while retaining meanings that are not already in the deck.

By default, the first field of each existing untagged note is treated as its Hebrew front. If Hebrew lives elsewhere, expand **First-time setup & connection help**, enter the exact field name, and reconnect. That field must exist on every untagged note model in the selected deck. App-generated cards are recognized by their identity tags regardless of the field setting; separate meanings with the same spelling remain distinct.

If AnkiConnect requires an API key, enter it in connection help. It stays in the current tab, is sent only to local AnkiConnect, and is cleared on reload. No connection is attempted automatically when the website opens.

If access was denied, check this website’s local network permission in the browser. In Anki → Tools → Add-ons → AnkiConnect → Config, ensure `webCorsOriginList` includes `https://schwester-ester.github.io` (or the exact origin where you opened the app), remove that origin from `ignoreOriginList` if present, and restart Anki. Leave AnkiConnect bound to localhost. If the browser cannot connect to local services, TSV/ZIP export still works. Direct desktop connection requires Anki desktop and is not available through AnkiMobile or AnkiDroid alone. See [AnkiConnect permission documentation](https://github.com/ankicommunity/anki-desktop-addon-connect) and [Chrome local network access permissions](https://developer.chrome.com/blog/local-network-access).

When this app runs in WSL and Anki runs on Windows, Linux and Windows may have separate localhost interfaces. If the Linux connection fails, the app automatically uses Windows `curl.exe` (when available on PATH) to reach Windows AnkiConnect. It sends requests through stdin, including recorded audio, and keeps AnkiConnect bound to localhost. No firewall or AnkiConnect bind-address changes are needed. Keep your Windows Anki profile open. If connection still fails, restart Anki and check that AnkiConnect is enabled under Tools → Add-ons. You can verify the add-on from a Windows browser at `http://127.0.0.1:8765`. See [AnkiConnect setup](https://github.com/ankicommunity/anki-desktop-addon-connect#installation) and [Microsoft's WSL networking documentation](https://learn.microsoft.com/windows/wsl/networking).

## Android / AnkiDroid

The website cannot access AnkiDroid’s native Android database API on its own. Direct sync uses the free, unofficial [AnkiConnect Android companion](https://github.com/KamWithK/AnkiconnectAndroid), which exposes a local HTTP API. This mode is selected automatically on Android and can be selected manually under **Connect to**.

1. Install AnkiDroid and install the companion from its [releases](https://github.com/KamWithK/AnkiconnectAndroid/releases/latest). Open AnkiDroid, grant the companion its AnkiDroid permission, and start its service.
2. In the companion’s settings, set the CORS host to `https://schwester-ester.github.io` (or the exact origin shown by the website). Allow the browser’s local network permission if prompted. Keep the companion’s service running while using direct sync.
3. On first use, add at least one vocabulary card, enter a **Deck name for Anki package**, and tap **Download Anki package (.apkg)**. Open the file in AnkiDroid and confirm import. This supplies the Hebrew Reader note type, deck, cards, and any recordings.
4. Back on the website, select **AnkiDroid · Android companion** and tap **Connect & sync**. Pick an existing AnkiDroid deck from the dropdown, add more cards, and tap **Sync cards to Anki**. The browser reads and writes to AnkiDroid through the companion. Use AnkiDroid’s own Sync button separately for AnkiWeb.

The companion does not implement the desktop API’s permission prompt, note-type creation, or deck creation. Android mode uses its supported actions, asks for one-time package setup when the note type is absent, and adjusts recording references when the companion renames media. To create another deck, create it in AnkiDroid or enter the new package deck name, import that package, and reconnect. See the companion’s [supported API](https://github.com/KamWithK/AnkiconnectAndroid/blob/master/docs/api.md).

Without the companion, package export still works on mobile: choose the target deck name, download the package, open it in AnkiDroid, and confirm. This requires an import confirmation and does not enumerate the phone’s decks in the website. Reimporting the same package identities updates/skips those package notes rather than creating duplicates; notes imported earlier through TSV or desktop direct sync can have different Anki GUIDs and may be separate notes. No AnkiWeb credentials, paid hosting, or new hosted service are required.

## Read and import

- Paste a passage and choose **Start reading**. Punctuation, spaces, and vowel marks remain visible.
- Click any word to inspect and select it. **Review all** visits unknown words in text order. Ctrl/⌘-click toggles individual words; Shift-click selects a range from the last clicked word; Ctrl/⌘-Shift-click adds a range without clearing earlier selections. **Clear selection** restores full-text translation. Choose **Review selected** to limit the review queue. Use the on-screen arrows or your keyboard: left advances through the Hebrew text, right goes back.
- **Translate to English** beneath your text translates the whole passage by default. Before reading, highlight part of the text to translate only that part. In reading mode, use word/range selection to translate disjoint passages in their original order. Results appear below the text. Only the requested text is sent to Google when you click Translate. This uses Google's public, unofficial endpoint without credentials; Google may rate-limit or block it. Failures keep an **Open in Google Translate** link for the chosen text. Long passages are translated in chunks and may lose context across chunk boundaries.
- Each result shows its canonical word, vowelled spelling, pronunciation, stressed vowel, meaning, part of speech, root, binyan/pattern, matched text forms, and prefix interpretation. Pronunciation audio streams from Pealim when you play it.
- **Add meaning** selects a dictionary entry. Several meanings with the same spelling can be selected independently. The tray persists across refreshes and texts.
- **I know this word · skip** remembers that exact unpointed surface spelling across future texts. Undo it from **Previously skipped words** or by clicking the muted word.
- **Sync cards to Anki** creates a `Hebrew Reader` note type with a Hebrew-to-meaning card and adds notes to the selected deck. The answer contains pointed spelling, pronunciation, stress, meaning, grammatical information, root, useful noun/adjective forms, and a source link. Successful notes leave the tray; failed notes remain available for retry. Duplicate Pealim IDs in the selected deck are skipped. Distinct homographs are allowed.
- **Export for Anki** offers **TSV · Hebrew Reader fields** (the default), **TSV · Basic Front / Back**, and **Anki package (.apkg)**. The full TSV has separate Word, Meaning, Pronunciation, Grammar, Root, Forms, Source, Tags, and Notetype columns. The per-row Notetype requires Hebrew Reader; if it is missing, Anki reports that instead of silently losing fields. Confirm that each column maps to its matching field. If that note type is missing, first import a package from this app. Basic TSV explicitly requires Basic and combines the answer information in Back. Both TSV formats enable HTML with a file header. To repair an earlier empty-field import, re-export the affected cards, choose Hebrew Reader, and use “update existing notes” after reviewing the matches. If several notes share a Hebrew front, check the matches carefully. Choose “import as new notes” for new, distinct meanings with the same Hebrew front. Package import includes the note type, layout, and recordings without manual field mapping. Downloads retain the tray; reconnect after importing to recognize existing identities. See [Anki’s text import documentation](https://docs.ankiweb.net/importing/text-files.html).

## Add your own meanings

Choose **+ Add manually** in the dictionary panel, including when Pealim has no results or is unavailable. The active word is filled in if one is open. Only **Hebrew word or phrase** and **Meaning(s)** are required. Put each distinct definition on a separate line to create separate cards. Optional fields include part of speech, masculine and/or feminine checkboxes, number, pointed spelling, pronunciation, root, and notes (including examples or other forms). The app preserves the form and grammar you enter rather than guessing an infinitive or gender.

**Record pronunciation** requests microphone access. Stop the recording to preview it, record again, or remove it before saving. Recording stops after 60 seconds and is converted locally to mono 16 kHz WAV. Audio is stored locally with the manual entry, and direct imports copy it into Anki's media collection through [AnkiConnect's storeMediaFile](https://github.com/ankicommunity/anki-desktop-addon-connect#media-actions). Recording requires microphone support in a browser on localhost or HTTPS.

Manual entries join the same vocabulary tray and persist across reloads. They use separate identity tags, so different meanings with identical Hebrew fronts can be added independently, including words already present on older untagged cards. Retrying an import of the same manual entry skips its existing identity. A newly authored card gets a new identity.

When selected cards include recordings, **Export TSV** downloads a ZIP containing the TSV, WAV files, and instructions. Extract the ZIP, copy the WAV files into your Anki profile's `collection.media` folder, then import the TSV. Direct Anki imports and .apkg packages handle recordings automatically. TSV-only exports continue to work for cards without recordings.

## Canonical forms

Verbs are imported in the **infinitive**, adjectives in **masculine singular**, and nouns in **singular absolute state**. The front omits vowel marks; the answer includes them. For nouns whose plural ending goes against their grammatical gender (e.g. masculine שולחן → שולחנות), the front includes singular / plural and the answer explains the exception. Plural-only nouns are preserved in their attested form. Entries without a verified canonical form and pronunciation cannot be imported; the app does not guess an infinitive for a defective or passive paradigm.

The phrase “infinitive (for vowels)” in the request is interpreted as “infinitive for verbs.”

## Dictionary and grammar research

- [Pealim's vowelled vs. unvowelled writing guide](https://www.pealim.com/articles/writing-with-and-without-vowels/) explains why lookup must account for spelling variants.
- [Pealim's search for ספר](https://www.pealim.com/search/?q=%D7%A1%D7%A4%D7%A8) groups alternative dictionary entries and gives their matching inflections. The app scrapes these groups and their pagination, then follows only exact matching forms to entry tables. Related-word tables and multiword suggestions are excluded from single-word results.
- [Pealim's grammar case study](https://www.pealim.com/articles/declaration-of-independence-part-1/) covers roots, verb constructions, gender/number/definiteness agreement, construct state, pronominal endings, and article fusion. Inflection letters and suffixes are resolved using Pealim's forms, rather than removed as if they were prefixes.
- [Prefix order](https://elon.io/grammar/hebrew/spelling/prefix-letters): optional ו (“and”), optional ש / כש (“that/which” / “when”), an optional ב/כ/ל/מ preposition, then ה (“the”). Standard written ב/כ/ל absorb ה; מ retains it. The app also considers מש (“from when/since”). It always looks up the unchanged spelling because these letters may belong to the word itself. This candidate grammar generates possibilities; it does not determine which one your sentence intends.
- Verified canonical tables: [noun ספר](https://www.pealim.com/dict/6104-sefer/), [verb לספר](https://www.pealim.com/dict/1409-lesaper/), [adjective טוב](https://www.pealim.com/dict/5422-tov/), [irregular plural שולחן](https://www.pealim.com/dict/4939-shulchan/).

## Storage and limits

SQLite at `data/reader.sqlite3` stores fetched HTML, parsed entries, and skipped words. It is transactional and requires no pandas dependency; it can be queried from pandas with `read_sql_query` if needed. Set `HEBREW_DATA_DIR` to change the data directory. Dictionary pages expire after 30 days and outbound requests are spaced at least 0.8 seconds apart. First lookups can take time because every possible base and its canonical entries are checked. No whole-site crawling occurs.

Anki deck knowledge is held in memory until the next sync. For old notes with no Pealim tags, knowing a Hebrew front necessarily suppresses its homographs because the intended dictionary sense is unavailable. App-created notes preserve sense-level knowledge. A known lemma is detected after lookup even when the passage uses its inflected form. Skips apply to the exact surface spelling, avoiding suppression of unrelated prefix interpretations.

The app requires internet access for uncached dictionary results and translation. Pealim can omit slang, names, rare forms, and alternate spellings. Ambiguous words require your contextual choice; this app is not a contextual morphological analyzer. Dictionary errors are shown and do not mark words as known. A lookup can return partial results if one candidate fails. Page changes or access restrictions may require parser updates. Requests run locally; only candidate words are sent to Pealim, and translation sends only the chosen passages to Google on demand. Recordings stay local until imported into Anki (and can subsequently sync through Anki). The server binds to localhost and rejects cross-origin writes. This is a personal desktop app, not a multiuser server.

## Verify

```bash
.venv/bin/python -m pytest -q
```

Tests use compact fixtures from inspected Pealim pages and a simulated AnkiConnect API; they do not modify your real deck. They cover spelling ambiguity, prefixes, canonicalization, irregular plurals, persistence, existing deck recognition, duplicate prevention, and partial import failures.

Optional browser checks (require Playwright and Chromium; set `CHROMIUM_PATH` if needed):

```bash
.venv/bin/python tests/browser_smoke.py
.venv/bin/python tests/browser_features.py
.venv/bin/python tests/browser_public.py
.venv/bin/python tests/browser_anki.py
.venv/bin/python tests/browser_android.py
```

The feature browser check uses an isolated database, simulated translation/Anki services, and Chromium's synthetic microphone to exercise disjoint selections, recording conversion, media export/import, reload persistence, and mobile layout.

The public browser check uses two isolated browser contexts to verify that visitors cannot see each other's cards, audio, drafts, or skips. It also deletes the server cache before exporting browser-owned dictionary cards and recorded manual cards.

The hosted Anki browser check simulates AnkiConnect instead of accessing a real collection. It exercises permission/key handling, deck selection and creation, recorded-card import, duplicate protection, failed-card retries, custom Hebrew fields, browser-only collection data, and mobile layout.

The Android browser check emulates a phone browser and the companion’s documented API. It checks mode selection, existing decks, note-type bootstrap, complete TSV and package downloads, renamed audio, invalid-note retry, and mobile layout. It does not replace a test on a physical Android device.

Optional import verification uses the official Anki engine in a separate environment (the project’s own `anki.py` must not shadow that package):

```bash
python3 -m venv /tmp/ivrit-anki-verify
/tmp/ivrit-anki-verify/bin/pip install anki
ANKI_PYTHON=/tmp/ivrit-anki-verify/bin/python .venv/bin/python -m pytest -q tests/test_packages.py
```

This verifies the original TSV field-loss reproduction, both corrected TSV mappings, rendered package cards, bundled recordings, and repeat package import in temporary collections. It never opens your real Anki profile.
