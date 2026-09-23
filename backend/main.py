"""FORGE API: accounts, AI-supported tasks, proposals and business decisions."""

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

from .ai import AIServiceError, AIUnavailable, analyze_task, generate_questions
from .auth import current_user, hash_password, issue_session, require_owner, require_role, user_with_team, verify_password
from .domain import FIELDS, enrich_task, valid_value
from .storage import ROOT, connect, init_db, proposal_from_row, task_from_row, team_from_row

load_dotenv(ROOT / ".env")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="FORGE API", version="2.0.0", lifespan=lifespan)
origins = [item.strip() for item in os.getenv("FRONTEND_ORIGIN", "http://localhost:3000,http://127.0.0.1:3000").split(",") if item.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type", "Authorization"])


class RegisterPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    name: str = Field(min_length=2, max_length=100)
    organization: str = Field(min_length=2, max_length=140)
    role: str
    skills: list[str] = Field(default_factory=list)


class LoginPayload(BaseModel):
    email: EmailStr
    password: str


class CreateTask(BaseModel):
    raw: str = Field(min_length=15, max_length=5000)


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, max_length=140)
    category: str | None = Field(default=None, max_length=40)
    fields: dict[str, str] | None = None
    confirmed: dict[str, bool] | None = None


class TeamPatch(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    skills: list[str] = Field(min_length=1, max_length=12)


class ProposalCreate(BaseModel):
    task_id: str
    idea: str = Field(min_length=12, max_length=3000)
    plan: str = Field(min_length=12, max_length=3000)
    deadline: str = Field(min_length=2, max_length=100)
    link: str = Field(min_length=10, max_length=500)


class Decision(BaseModel):
    status: str


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_task_or_404(db, task_id: str) -> dict:
    task = task_from_row(db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
    if task is None:
        raise HTTPException(404, "Задача не найдена")
    return task


def get_proposal_or_404(db, proposal_id: str) -> dict:
    row = db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Предложение не найдено")
    return proposal_from_row(row)


def ai_or_http(callable_, *args):
    try:
        return callable_(*args)
    except AIUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except (AIServiceError, ValueError) as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/health")
def health():
    return {"status": "ok", "ai_configured": bool(os.getenv("OPENAI_API_KEY", "").strip())}


@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterPayload):
    if payload.role not in {"business", "team"}:
        raise HTTPException(422, "Выберите роль бизнеса или команды")
    skills = list(dict.fromkeys(skill.strip()[:40] for skill in payload.skills if skill.strip()))[:12]
    if payload.role == "team" and not skills:
        raise HTTPException(422, "Укажите хотя бы один навык команды")
    user_id = str(uuid.uuid4())
    email = str(payload.email).lower()
    organization = payload.organization.strip()
    try:
        with connect() as db:
            db.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (user_id, email, payload.name.strip(), organization, payload.role,
                        hash_password(payload.password), now()))
            if payload.role == "team":
                initials = "".join(word[0] for word in organization.split()[:2]).upper()[:2] or "TM"
                db.execute("INSERT INTO teams VALUES (?, ?, ?, ?, ?, 0)",
                           (str(uuid.uuid4()), user_id, organization, json.dumps(skills, ensure_ascii=False), initials))
            token = issue_session(db, user_id)
            user = user_with_team(db, user_id)
            return {"token": token, "user": user}
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "Аккаунт с этой почтой уже существует") from exc


@app.post("/api/auth/login")
def login(payload: LoginPayload):
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (str(payload.email).lower(),)).fetchone()
        if row is None or not verify_password(payload.password, row["password_hash"]):
            raise HTTPException(401, "Неверная почта или пароль")
        token = issue_session(db, row["id"])
        return {"token": token, "user": user_with_team(db, row["id"])}


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return user


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None), _: dict = Depends(current_user)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))
    return {"ok": True}


@app.get("/api/tasks")
def list_tasks(published: bool = Query(default=True), user: dict = Depends(current_user)):
    with connect() as db:
        if published:
            rows = db.execute("SELECT * FROM tasks WHERE published = 1").fetchall()
        else:
            require_role(user, "business")
            rows = db.execute("SELECT * FROM tasks WHERE published = 0 AND owner_id = ?", (user["id"],)).fetchall()
    tasks = [enrich_task(task_from_row(row)) for row in rows]
    return sorted(tasks, key=lambda task: (task["readiness"]["score"], task["created_at"]), reverse=True)


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str, user: dict = Depends(current_user)):
    with connect() as db:
        task = get_task_or_404(db, task_id)
        if not task["published"]:
            require_owner(user, task)
        return enrich_task(task)


@app.post("/api/tasks", status_code=201)
def create_task(payload: CreateTask, user: dict = Depends(current_user)):
    require_role(user, "business")
    raw = payload.raw.strip()
    if len(raw) < 15:
        raise HTTPException(422, "Опишите задачу подробнее")
    task_id = str(uuid.uuid4())
    fields = {key: raw if key == "context" else "" for key in FIELDS}
    confirmed = {key: key == "context" and valid_value(key, raw) for key in FIELDS}
    title = raw.split(".")[0].split("\n")[0][:78]
    with connect() as db:
        db.execute("INSERT INTO tasks VALUES (?, ?, 'AI', ?, ?, ?, ?, '{}', 0, ?)",
                   (task_id, title, user["organization"], user["id"], json.dumps(fields, ensure_ascii=False),
                    json.dumps(confirmed), now()))
        return enrich_task(get_task_or_404(db, task_id))


@app.post("/api/tasks/{task_id}/analyze")
def analyze(task_id: str, user: dict = Depends(current_user)):
    with connect() as db:
        task = get_task_or_404(db, task_id)
        require_owner(user, task)
        result = ai_or_http(analyze_task, task)
        task["title"] = result["title"] or task["title"]
        task["category"] = result["category"]
        for key, value in result["suggestions"].items():
            if not task["fields"].get(key):
                task["fields"][key] = value
                task["confirmed"][key] = False
                task["ai_evidence"][key] = result["evidence"][key]
        db.execute("UPDATE tasks SET title = ?, category = ?, fields = ?, confirmed = ?, ai_evidence = ? WHERE id = ?",
                   (task["title"], task["category"], json.dumps(task["fields"], ensure_ascii=False),
                    json.dumps(task["confirmed"]), json.dumps(task["ai_evidence"], ensure_ascii=False), task_id))
        return {"task": enrich_task(task), "questions": result["questions"], "model": result["model"]}


@app.post("/api/tasks/{task_id}/interview")
def interview(task_id: str, user: dict = Depends(current_user)):
    with connect() as db:
        task = get_task_or_404(db, task_id)
        require_owner(user, task)
    return ai_or_http(generate_questions, task)


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: str, payload: TaskPatch, user: dict = Depends(current_user)):
    with connect() as db:
        task = get_task_or_404(db, task_id)
        require_owner(user, task)
        if payload.title is not None:
            task["title"] = payload.title.strip()
        if payload.category is not None:
            task["category"] = payload.category.strip()
        if payload.fields is not None:
            for key, value in payload.fields.items():
                if key not in FIELDS:
                    raise HTTPException(422, f"Неизвестное поле: {key}")
                if len(value) > 3000:
                    raise HTTPException(422, f"Слишком длинное поле: {key}")
                if value != task["fields"].get(key, ""):
                    task["fields"][key] = value.strip()
                    task["confirmed"][key] = False
                    task["ai_evidence"].pop(key, None)
        if payload.confirmed is not None:
            for key, value in payload.confirmed.items():
                if key not in FIELDS:
                    raise HTTPException(422, f"Неизвестное поле: {key}")
                if value and not valid_value(key, task["fields"].get(key, "")):
                    raise HTTPException(422, f"Заполните поле «{FIELDS[key][0]}» подробнее")
                task["confirmed"][key] = bool(value)
        db.execute("UPDATE tasks SET title = ?, category = ?, fields = ?, confirmed = ?, ai_evidence = ? WHERE id = ?",
                   (task["title"], task["category"], json.dumps(task["fields"], ensure_ascii=False),
                    json.dumps(task["confirmed"]), json.dumps(task["ai_evidence"], ensure_ascii=False), task_id))
        return enrich_task(task)


@app.post("/api/tasks/{task_id}/publish")
def publish_task(task_id: str, user: dict = Depends(current_user)):
    with connect() as db:
        task = get_task_or_404(db, task_id)
        require_owner(user, task)
        if not task["title"]:
            raise HTTPException(422, "Укажите название задачи")
        db.execute("UPDATE tasks SET published = 1 WHERE id = ?", (task_id,))
        task["published"] = True
        return enrich_task(task)


@app.get("/api/teams")
def list_teams(_: dict = Depends(current_user)):
    with connect() as db:
        return [team_from_row(row) for row in db.execute("SELECT * FROM teams ORDER BY name")]


@app.patch("/api/teams/me")
def update_my_team(payload: TeamPatch, user: dict = Depends(current_user)):
    require_role(user, "team")
    skills = list(dict.fromkeys(skill.strip()[:40] for skill in payload.skills if skill.strip()))[:12]
    if not skills:
        raise HTTPException(422, "Укажите хотя бы один навык")
    name = payload.name.strip()
    initials = "".join(word[0] for word in name.split()[:2]).upper()[:2] or "TM"
    with connect() as db:
        db.execute("UPDATE teams SET name = ?, skills = ?, initials = ? WHERE user_id = ?",
                   (name, json.dumps(skills, ensure_ascii=False), initials, user["id"]))
        db.execute("UPDATE users SET organization = ? WHERE id = ?", (name, user["id"]))
        return user_with_team(db, user["id"])


@app.get("/api/proposals")
def list_proposals(task_id: str | None = None, user: dict = Depends(current_user)):
    with connect() as db:
        if user["role"] == "business":
            if task_id:
                task = get_task_or_404(db, task_id)
                require_owner(user, task)
                rows = db.execute("SELECT * FROM proposals WHERE task_id = ? ORDER BY created_at DESC", (task_id,)).fetchall()
            else:
                rows = db.execute("SELECT p.* FROM proposals p JOIN tasks t ON t.id = p.task_id WHERE t.owner_id = ? ORDER BY p.created_at DESC", (user["id"],)).fetchall()
        else:
            team_id = user["team"]["id"]
            if task_id:
                rows = db.execute("SELECT * FROM proposals WHERE task_id = ? AND team_id = ? ORDER BY created_at DESC", (task_id, team_id)).fetchall()
            else:
                rows = db.execute("SELECT * FROM proposals WHERE team_id = ? ORDER BY created_at DESC", (team_id,)).fetchall()
        return [proposal_from_row(row) for row in rows]


@app.post("/api/proposals", status_code=201)
def create_proposal(payload: ProposalCreate, user: dict = Depends(current_user)):
    require_role(user, "team")
    parsed = urlparse(payload.link)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(422, "Укажите корректную ссылку на прототип")
    with connect() as db:
        task = get_task_or_404(db, payload.task_id)
        if not task["published"]:
            raise HTTPException(422, "Задача ещё не опубликована")
        proposal_id = str(uuid.uuid4())
        db.execute("INSERT INTO proposals VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)",
                   (proposal_id, payload.task_id, user["team"]["id"], payload.idea.strip(), payload.plan.strip(),
                    payload.deadline.strip(), payload.link.strip(), now()))
        return get_proposal_or_404(db, proposal_id)


def proposal_owner(db, proposal: dict, user: dict):
    task = get_task_or_404(db, proposal["task_id"])
    require_owner(user, task)


@app.patch("/api/proposals/{proposal_id}/decision")
def decide_proposal(proposal_id: str, payload: Decision, user: dict = Depends(current_user)):
    if payload.status not in {"accepted", "rejected"}:
        raise HTTPException(422, "Решение должно быть accepted или rejected")
    with connect() as db:
        proposal = get_proposal_or_404(db, proposal_id)
        proposal_owner(db, proposal, user)
        if proposal["progress_awarded"] and payload.status != "accepted":
            raise HTTPException(409, "Нельзя отменить выбор после подтверждения этапа")
        db.execute("UPDATE proposals SET status = ? WHERE id = ?", (payload.status, proposal_id))
        return get_proposal_or_404(db, proposal_id)


@app.post("/api/tasks/{task_id}/reject-all")
def reject_all(task_id: str, user: dict = Depends(current_user)):
    with connect() as db:
        task = get_task_or_404(db, task_id)
        require_owner(user, task)
        changed = db.execute("UPDATE proposals SET status = 'rejected' WHERE task_id = ? AND status = 'pending'", (task_id,)).rowcount
    return {"rejected": changed}


@app.post("/api/proposals/{proposal_id}/progress")
def confirm_progress(proposal_id: str, user: dict = Depends(current_user)):
    with connect() as db:
        proposal = get_proposal_or_404(db, proposal_id)
        proposal_owner(db, proposal, user)
        if proposal["status"] != "accepted":
            raise HTTPException(422, "Сначала выберите команду")
        if proposal["progress_awarded"]:
            raise HTTPException(409, "Баллы за этот этап уже начислены")
        db.execute("UPDATE proposals SET progress_awarded = 1 WHERE id = ?", (proposal_id,))
        db.execute("UPDATE teams SET points = points + 20 WHERE id = ?", (proposal["team_id"],))
        return {"proposal": get_proposal_or_404(db, proposal_id), "points_awarded": 20}
