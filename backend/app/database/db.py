import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.getenv("DATABASE_PATH", str(Path(__file__).resolve().parents[2] / "studybuddy.db"))

@contextmanager
def connection():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    finally:
        db.close()

def initialize():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, title TEXT NOT NULL, subject TEXT NOT NULL, content TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL, due_date TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS quizzes (id INTEGER PRIMARY KEY, note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE, title TEXT NOT NULL, questions TEXT NOT NULL, score INTEGER, total INTEGER, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS flashcard_sets (id INTEGER PRIMARY KEY, note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE, title TEXT NOT NULL, cards TEXT NOT NULL, seen_cards TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS card_reviews (id INTEGER PRIMARY KEY, set_id INTEGER NOT NULL REFERENCES flashcard_sets(id) ON DELETE CASCADE, card_index INTEGER NOT NULL, due_at TEXT NOT NULL, interval_days REAL NOT NULL DEFAULT 0, repetitions INTEGER NOT NULL DEFAULT 0, ease REAL NOT NULL DEFAULT 2.5, last_rating TEXT, UNIQUE(set_id, card_index));
        CREATE TABLE IF NOT EXISTS quiz_attempts (id INTEGER PRIMARY KEY, quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE, score INTEGER NOT NULL, total INTEGER NOT NULL, answers TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS focus_sessions (id INTEGER PRIMARY KEY, task_id INTEGER, duration_seconds INTEGER NOT NULL, completed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, label TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(flashcard_sets)")}
        if "seen_cards" not in columns:
            db.execute("ALTER TABLE flashcard_sets ADD COLUMN seen_cards TEXT NOT NULL DEFAULT '[]'")

def record_activity(kind: str, label: str):
    from datetime import datetime, timezone
    with connection() as db:
        db.execute("INSERT INTO activity(kind,label,created_at) VALUES(?,?,?)", (kind, label, datetime.now(timezone.utc).isoformat()))

def row_dict(row):
    return dict(row) if row else None

def decode_json(value):
    return json.loads(value)
