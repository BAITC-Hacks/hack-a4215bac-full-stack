"""Account and server-side session helpers for business and team roles."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException

from .storage import connect, team_from_row, user_from_row

PASSWORD_ITERATIONS = 600_000
SESSION_DAYS = 7


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(candidate, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def issue_session(db, user_id: str) -> str:
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat()
    db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token_hash, user_id, expires))
    return token


def user_with_team(db, user_id: str) -> dict:
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    user = user_from_row(row)
    if user is None:
        raise HTTPException(401, "Сессия недействительна")
    team_row = db.execute("SELECT * FROM teams WHERE user_id = ?", (user_id,)).fetchone()
    user["team"] = team_from_row(team_row) if team_row else None
    return user


def current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Требуется вход в аккаунт")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Требуется вход в аккаунт")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with connect() as db:
        row = db.execute("SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (token_hash,)).fetchone()
        if row is None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(401, "Сессия истекла. Войдите снова")
        return user_with_team(db, row["user_id"])


def require_role(user: dict, role: str):
    if user["role"] != role:
        raise HTTPException(403, "Недостаточно прав для этого действия")


def require_owner(user: dict, task: dict):
    require_role(user, "business")
    if task["owner_id"] != user["id"]:
        raise HTTPException(403, "Эта задача принадлежит другому бизнес-аккаунту")
