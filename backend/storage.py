import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def database_path() -> Path:
    configured = Path(os.getenv("DATABASE_PATH", ".data/forge-live.db"))
    return configured if configured.is_absolute() else ROOT / configured


@contextmanager
def connect():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                organization TEXT NOT NULL, role TEXT NOT NULL,
                password_hash TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
                owner TEXT NOT NULL, owner_id TEXT NOT NULL REFERENCES users(id),
                fields TEXT NOT NULL, confirmed TEXT NOT NULL,
                ai_evidence TEXT NOT NULL DEFAULT '{}',
                published INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS teams (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE REFERENCES users(id),
                name TEXT NOT NULL, skills TEXT NOT NULL,
                initials TEXT NOT NULL, points INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                team_id TEXT NOT NULL REFERENCES teams(id), idea TEXT NOT NULL,
                plan TEXT NOT NULL, deadline TEXT NOT NULL, link TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', progress_awarded INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS answers (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                field_key TEXT NOT NULL, question TEXT NOT NULL,
                answer TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ai_usage (
                id TEXT PRIMARY KEY, actor_id TEXT REFERENCES users(id), task_id TEXT REFERENCES tasks(id),
                operation TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'openai',
                input_tokens INTEGER NOT NULL DEFAULT 0, cached_input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0, estimated_cost_usd REAL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ai_usage_created_at ON ai_usage(created_at);
            CREATE TABLE IF NOT EXISTS role_audit (
                id TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES users(id),
                target_id TEXT NOT NULL REFERENCES users(id), old_role TEXT NOT NULL,
                new_role TEXT NOT NULL, created_at TEXT NOT NULL
            );
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)")}
        additions = {
            "extras": "TEXT NOT NULL DEFAULT '{}'",
            "extra_confirmed": "TEXT NOT NULL DEFAULT '{}'",
            "field_meta": "TEXT NOT NULL DEFAULT '{}'",
            "pack_version": "TEXT NOT NULL DEFAULT 'v0.1'",
            "handoff_result": "TEXT",
            "test_lab_result": "TEXT",
            "deadline": "TEXT NOT NULL DEFAULT ''",
            "industry": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in additions.items():
            if name not in columns:
                db.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")
        usage_columns = {row["name"] for row in db.execute("PRAGMA table_info(ai_usage)")}
        if "provider" not in usage_columns:
            db.execute("ALTER TABLE ai_usage ADD COLUMN provider TEXT NOT NULL DEFAULT 'openai'")
        proposal_columns = {row["name"] for row in db.execute("PRAGMA table_info(proposals)")}
        if "questions" not in proposal_columns:
            db.execute("ALTER TABLE proposals ADD COLUMN questions TEXT NOT NULL DEFAULT ''")


def task_from_row(row):
    if row is None:
        return None
    value = dict(row)
    value["fields"] = json.loads(value["fields"])
    value["confirmed"] = json.loads(value["confirmed"])
    value["ai_evidence"] = json.loads(value["ai_evidence"])
    value["extras"] = json.loads(value.get("extras") or "{}")
    value["extra_confirmed"] = json.loads(value.get("extra_confirmed") or "{}")
    value["field_meta"] = json.loads(value.get("field_meta") or "{}")
    value["handoff_result"] = json.loads(value.get("handoff_result") or "null")
    value["test_lab_result"] = json.loads(value.get("test_lab_result") or "null")
    value["published"] = bool(value["published"])
    return value


def team_from_row(row):
    value = dict(row)
    value["skills"] = json.loads(value["skills"])
    return value


def proposal_from_row(row):
    value = dict(row)
    value["progress_awarded"] = bool(value["progress_awarded"])
    return value


def user_from_row(row):
    if row is None:
        return None
    value = dict(row)
    value.pop("password_hash", None)
    return value
