import json
import sqlite3
import time
from pathlib import Path

class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS cache (url TEXT PRIMARY KEY, body TEXT, fetched REAL);
                CREATE TABLE IF NOT EXISTS entries (id TEXT PRIMARY KEY, body TEXT);
                CREATE TABLE IF NOT EXISTS skips (word TEXT PRIMARY KEY);
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def cached(self, url):
        with self.connect() as db:
            row = db.execute('SELECT body, fetched FROM cache WHERE url=?', (url,)).fetchone()
        return row[0] if row and time.time() - row[1] < 30 * 86400 else None

    def cache(self, url, body):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)', (url, body, time.time()))

    def entry(self, entry):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO entries VALUES (?,?)', (entry['id'], json.dumps(entry, ensure_ascii=False)))

    def get_entry(self, id):
        with self.connect() as db:
            row = db.execute('SELECT body FROM entries WHERE id=?', (id,)).fetchone()
        if not row:
            raise ValueError('This dictionary entry has not been looked up.')
        return json.loads(row[0])

    def skips(self):
        with self.connect() as db:
            return {r[0] for r in db.execute('SELECT word FROM skips')}

    def skip(self, word, remove=False):
        with self.connect() as db:
            db.execute('DELETE FROM skips WHERE word=?' if remove else 'INSERT OR IGNORE INTO skips VALUES (?)', (word,))
