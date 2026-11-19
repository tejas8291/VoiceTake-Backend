"""Local persistence for immutable takes and editable creator preferences."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path


class Store:
    def __init__(self, root: Path):
        self.root = root

    def connect(self):
        return closing(sqlite3.connect(self.root / "studio.sqlite3"))

    def initialize(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.connect() as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS takes (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            for (payload,) in db.execute("SELECT payload FROM takes"):
                take = json.loads(payload)
                if take["status"] in {"queued", "running"}:
                    take.update(status="failed", error="Generation was interrupted. Try again.")
                    db.execute("UPDATE takes SET payload = ? WHERE id = ?",
                               (json.dumps(take), take["id"]))

    def save(self, take):
        with self.connect() as db, db:
            db.execute("INSERT OR REPLACE INTO takes VALUES (?, ?)",
                       (take["id"], json.dumps(take)))

    def get(self, take_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM takes WHERE id = ?", (take_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def settings(self, key, fallback):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else fallback

    def update(self, key, value):
        with self.connect() as db, db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))
