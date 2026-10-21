import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','viewer','publisher'))
            );
            CREATE TABLE IF NOT EXISTS sessions (
                hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                expires INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, platform TEXT NOT NULL,
                external_id TEXT, niche TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '#2563eb', status TEXT NOT NULL DEFAULT 'paused',
                access_token TEXT, refresh_token TEXT, expires INTEGER,
                token_status TEXT NOT NULL DEFAULT 'disconnected',
                UNIQUE(platform, external_id)
            );
            CREATE TABLE IF NOT EXISTS oauth_states (
                hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, profile_id INTEGER NOT NULL
                REFERENCES profiles(id) ON DELETE CASCADE, verifier TEXT NOT NULL,
                expires INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, kind TEXT NOT NULL, profile_id INTEGER,
                message TEXT NOT NULL, created INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL
            );
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def query(self, sql, params=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, params).fetchall()]

    def execute(self, sql, params=()):
        with self.connect() as db:
            return db.execute(sql, params).lastrowid

    def record(self, kind, body):
        return self.execute('INSERT INTO records(kind,body) VALUES (?,?)', (kind, json.dumps(body)))

    def records(self, kind):
        return [dict(json.loads(r['body']), id=r['id']) for r in self.query(
            'SELECT id,body FROM records WHERE kind=? ORDER BY id', (kind,))]
