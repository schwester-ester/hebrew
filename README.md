# Ivrit — Hebrew reading to Anki

A local web app for turning Hebrew reading into a personal vocabulary deck. Paste text, click words or Ctrl/⌘-click a selection, review dictionary readings, and import the meanings you choose.

## Run

Python 3.11 or newer:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Open **http://127.0.0.1:5000**. Stop the server with Ctrl-C.

## Connect your deck

1. Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) in Anki desktop using add-on code `2055492159`, then restart Anki. Keep Anki open.
2. In **Deck & settings**, click **Connect & sync** and select your existing vocabulary deck. The app reads its notes through the local AnkiConnect service at port 8765.
3. By default, the first field of each existing note is treated as its Hebrew front. If Hebrew lives elsewhere, enter the exact field name and sync again. This field must exist on all untagged note types in the selected deck. App-generated cards are recognized by their Pealim identity tags regardless of that setting.
4. Sync after changes made in Anki. A sync resets the reading queue while retaining your selected meanings.

## Read and import

- Paste a passage and choose **Start reading**. Punctuation, spaces, and vowel marks remain visible.
- Click any word to inspect it. **Review all** visits unknown words in text order. Ctrl/⌘-click words, then **Review selected**, to limit the queue. Use the on-screen arrows or your keyboard: left advances through the Hebrew text, right goes back.
- Each result shows its canonical word, vowelled spelling, pronunciation, stressed vowel, meaning, part of speech, root, binyan/pattern, matched text forms, and prefix interpretation. Pronunciation audio streams from Pealim when you play it.
- **Add meaning** selects a dictionary entry. Several meanings with the same spelling can be selected independently. The tray persists across refreshes and texts.
- **I know this word · skip** remembers that exact unpointed surface spelling across future texts. Undo it from **Previously skipped words** or by clicking the muted word.
- **Import to Anki** creates a `Hebrew Reader` note type with a Hebrew-to-meaning card and adds notes to the selected deck. The answer contains pointed spelling, pronunciation, stress, meaning, grammatical information, root, useful noun/adjective forms, and a source link. Successful notes leave the tray; failed notes remain available for retry. Duplicate Pealim IDs in the selected deck are skipped. Distinct homographs are allowed.
- **Export TSV** works without Anki. Import the file as Basic with Front and Back mapped; its third column is automatically treated as tags. HTML is enabled by a file header. Choose the import option that adds duplicate fronts as new notes to preserve homographs. Sync after importing; exported cards carry the same Pealim identity tags as direct imports. Downloading alone does not mark words known. See [Anki's text import documentation](https://docs.ankiweb.net/manual/importing/text-files).

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

The app requires internet access for uncached dictionary results. Pealim can omit slang, names, rare forms, and alternate spellings. Ambiguous words require your contextual choice; this app is not a contextual morphological analyzer. Dictionary errors are shown and do not mark words as known. A lookup can return partial results if one candidate fails. Page changes or access restrictions may require parser updates. Requests run locally; only candidate words are sent to Pealim, and text is not sent to a language model. The server binds to localhost and rejects cross-origin writes. This is a personal desktop app, not a multiuser server.

## Verify

```bash
.venv/bin/python -m pytest -q
```

Tests use compact fixtures from inspected Pealim pages and a simulated AnkiConnect API; they do not modify your real deck. They cover spelling ambiguity, prefixes, canonicalization, irregular plurals, persistence, existing deck recognition, duplicate prevention, and partial import failures.
