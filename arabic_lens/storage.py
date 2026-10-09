import sqlite3
import threading
import time
import json
import hashlib
from pathlib import Path
from collections import OrderedDict
from .text import normalize, clean_translation, preserves_acronyms


def cache_key(text):
    # OCR soft wraps are grouped before caching. Remaining hard breaks belong
    # to lists/paragraphs and must not share a flattened document's cache key.
    return '\n'.join(normalize(line) for line in text.split('\n'))


class TranslationStore:
    """Bounded SQLite cache and optional history. No screenshots are stored."""
    def __init__(self, path, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.memory = OrderedDict()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, arabic TEXT NOT NULL, used REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, source TEXT, arabic TEXT, timestamp REAL, app TEXT);
          CREATE INDEX IF NOT EXISTS cache_used ON cache(used);
          CREATE TABLE IF NOT EXISTS seed_packs (id TEXT PRIMARY KEY, installed REAL NOT NULL);
        """)
        if 'origin' not in {row[1] for row in self.db.execute('PRAGMA table_info(cache)')}:
            self.db.execute("ALTER TABLE cache ADD COLUMN origin TEXT NOT NULL DEFAULT 'legacy'")
        self.prune()

    def namespace(self):
        if self.settings.provider == 'Built-in offline':
            from .offline import MODEL_ID
            return MODEL_ID
        details = (self.settings.provider, self.settings.endpoint, self.settings.model, self.settings.azure_region)
        return 'remote-' + hashlib.sha256(json.dumps(details).encode()).hexdigest()[:16]

    def seed_pack(self, path, force=False):
        """Exact reviewed phrases only; never overwrite a user's translations.

        Installation metadata survives Clear Cache, so clearing stays effective.
        No fuzzy matching or substitution of unknown prices/names takes place.
        """
        pack = json.loads(Path(path).read_text(encoding='utf-8'))
        if not self.settings.cache_enabled:
            return 0
        with self.lock:
            # Recognize earlier reviewed entries without discarding history or
            # silently trusting arbitrary output from the retired model.
            for entry in pack['entries']:
                for source in [entry['english']] + entry.get('ocr_aliases', []):
                    key = cache_key(source)
                    row = self.db.execute('SELECT arabic FROM cache WHERE key=?', (key,)).fetchone()
                    if row and clean_translation(row[0]) == clean_translation(entry['arabic']):
                        self.db.execute("UPDATE cache SET origin='reviewed' WHERE key=?", (key,))
            if not force and self.db.execute('SELECT 1 FROM seed_packs WHERE id=?', (pack['id'],)).fetchone():
                self.db.commit()
                return 0
            count = 0
            for entry in pack['entries']:
                for source in [entry['english']] + entry.get('ocr_aliases', []):
                    cursor = self.db.execute('INSERT OR IGNORE INTO cache(key,arabic,used,origin) VALUES(?,?,?,?)',
                        (cache_key(source), entry['arabic'], time.time(), 'reviewed'))
                    count += cursor.rowcount
            self.db.execute('INSERT OR REPLACE INTO seed_packs VALUES(?,?)', (pack['id'], time.time()))
            self.prune()
            return count

    def get(self, text):
        if not self.settings.cache_enabled:
            return None
        key = cache_key(text)
        memory_key = (self.namespace(), key)
        with self.lock:
            if memory_key in self.memory:
                self.memory.move_to_end(memory_key)
                arabic = clean_translation(self.memory[memory_key])
                return arabic if preserves_acronyms(text, arabic) else None
            row = self.db.execute("SELECT arabic,origin FROM cache WHERE key=?", (key,)).fetchone()
            if row:
                if row[1] not in ('reviewed', memory_key[0]):
                    return None
                self.db.execute("UPDATE cache SET used=? WHERE key=?", (time.time(), key))
                self.db.commit()
                self._remember(memory_key, row[0])
                arabic = clean_translation(row[0])
                return arabic if preserves_acronyms(text, arabic) else None

    def _remember(self, key, value):
        self.memory[key] = value
        self.memory.move_to_end(key)
        while len(self.memory) > 256:
            self.memory.popitem(last=False)

    def put(self, source, arabic):
        arabic = clean_translation(arabic)
        if not self.settings.cache_enabled:
            return
        with self.lock:
            key = cache_key(source)
            self._remember((self.namespace(), key), arabic)
            self.db.execute("INSERT OR REPLACE INTO cache(key,arabic,used,origin) VALUES(?,?,?,?)", (key, arabic, time.time(), self.namespace()))
            self.prune()

    def record(self, source, arabic, app):
        if not self.settings.history_enabled:
            return
        with self.lock:
            last = self.db.execute("SELECT source,app FROM history ORDER BY id DESC LIMIT 1").fetchone()
            if last != (source, app):
                self.db.execute("INSERT INTO history(source,arabic,timestamp,app) VALUES(?,?,?,?)", (source, arabic, time.time(), app))
            self.prune()

    def prune(self):
        with self.lock:
            self.db.execute("DELETE FROM cache WHERE key IN (SELECT key FROM cache ORDER BY used DESC LIMIT -1 OFFSET ?)", (self.settings.cache_limit,))
            self.db.execute("DELETE FROM history WHERE id IN (SELECT id FROM history ORDER BY id DESC LIMIT -1 OFFSET ?)", (self.settings.history_limit,))
            self.db.commit()
            live = {row[0] for row in self.db.execute("SELECT key FROM cache")}
            for key in list(self.memory):
                if key[1] not in live:
                    self.memory.pop(key)

    def history(self, query=""):
        with self.lock:
            q = "%" + query + "%"
            rows = self.db.execute("SELECT source,arabic,timestamp,app FROM history WHERE source LIKE ? OR arabic LIKE ? OR app LIKE ? ORDER BY id DESC LIMIT ?", (q, q, q, self.settings.history_limit)).fetchall()
            return [(source, clean_translation(arabic), timestamp, app) for source, arabic, timestamp, app in rows]

    def clear(self, table):
        assert table in ("cache", "history")
        with self.lock:
            self.db.execute(f"DELETE FROM {table}")
            self.db.commit()
            if table == "cache":
                self.memory.clear()
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.db.execute("VACUUM")

    def close(self):
        with self.lock:
            self.db.close()
