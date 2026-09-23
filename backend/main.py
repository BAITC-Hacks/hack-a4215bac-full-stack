"""FORGE API: accounts, AI-supported tasks, proposals and business decisions."""

import hashlib
import hmac
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

from .ai import AIServiceError, AIUnavailable, analyze_task, generate_questions, review_handoff, generate_test_scenarios
from .auth import current_user, hash_password, issue_session, require_owner, require_role, user_with_team, verify_password
from .compiler import EXTRAS, handoff_rules
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
    industry: str = Field(default="", max_length=80)
    deadline: str = Field(default="", max_length=100)


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, max_length=140)
    category: str | None = Field(default=None, max_length=40)
    fields: dict[str, str] | None = None
    confirmed: dict[str, bool] | None = None
    extras: dict[str, str] | None = None
    extra_confirmed: dict[str, bool] | None = None
    industry: str | None = Field(default=None, max_length=80)
    deadline: str | None = Field(default=None, max_length=100)


class AnswerPayload(BaseModel):
    field: str
    question: str = Field(min_length=10, max_length=300)
    answer: str = Field(min_length=5, max_length=3000)


class TeamPatch(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    skills: list[str] = Field(min_length=1, max_length=12)


class ProposalCreate(BaseModel):
    task_id: str
    idea: str = Field(min_length=12, max_length=3000)
    plan: str = Field(min_length=12, max_length=3000)
    deadline: str = Field(min_length=2, max_length=100)
    link: str = Field(default="", max_length=500)
    questions: str = Field(default="", max_length=1000)


class Decision(BaseModel):
    status: str


class BootstrapPayload(BaseModel):
    token: str


class RolePayload(BaseModel):
    role: str


class ScenarioDecision(BaseModel):
    confirmed: bool


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


def next_version(current: str, score: int) -> str:
    try:
        major, minor = (int(part) for part in current.removeprefix("v").split("."))
    except (ValueError, AttributeError):
        major, minor = 0, 1
    if major == 0 and score >= 70:
        return "v1.0"
    return f"v{major}.{minor + 1}"


def visible_task(task: dict, user: dict) -> dict:
    if user["role"] in {"business", "admin"} and task["owner_id"] == user["id"]:
        return task
    result = {**task}
    result["fields"] = {key: value if task["confirmed"].get(key) else "" for key, value in task["fields"].items()}
    result["extras"] = {key: value if task["extra_confirmed"].get(key) else "" for key, value in task["extras"].items()}
    result["ai_evidence"] = {}
    result["field_meta"] = {key: meta for key, meta in task["field_meta"].items()
                            if task["confirmed"].get(key) or task["extra_confirmed"].get(key)}
    lab = task.get("test_lab_result")
    result["test_lab_result"] = ({**lab, "items": [item for item in lab["items"] if item["confirmed"]]}
                                 if lab and lab.get("version") == task["pack_version"] else None)
    return result


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
    tasks = []
    with connect() as db:
        for row in rows:
            task = visible_task(task_from_row(row), user)
            task["proposal_count"] = db.execute("SELECT COUNT(*) FROM proposals WHERE task_id = ?", (task["id"],)).fetchone()[0]
            tasks.append(enrich_task(task))
    return sorted(tasks, key=lambda task: (task["readiness"]["score"], task["created_at"]), reverse=True)


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str, user: dict = Depends(current_user)):
    with connect() as db:
        task = get_task_or_404(db, task_id)
        if not task["published"]:
            require_owner(user, task)
        task["proposal_count"] = db.execute("SELECT COUNT(*) FROM proposals WHERE task_id = ?", (task_id,)).fetchone()[0]
        return enrich_task(visible_task(task, user))


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
        db.execute("""INSERT INTO tasks (id, title, category, owner, owner_id, fields, confirmed,
                   ai_evidence, published, created_at, deadline, industry, updated_at, field_meta)
                   VALUES (?, ?, 'AI', ?, ?, ?, ?, '{}', 0, ?, ?, ?, ?, ?)""",
                   (task_id, title, user["organization"], user["id"], json.dumps(fields, ensure_ascii=False),
                    json.dumps(confirmed), now(), payload.deadline.strip(), payload.industry.strip(), now(),
                    json.dumps({"context": {"source": "user", "answer_id": None, "updated_at": now()}}, ensure_ascii=False)))
        return enrich_task(get_task_or_404(db, task_id))


@app.post("/api/tasks/{task_id}/analyze")
def analyze(task_id: str, user: dict = Depends(current_user)):
    with connect() as db:
        task = get_task_or_404(db, task_id)
        require_owner(user, task)
        result = ai_or_http(analyze_task, task, user["id"])
        task["title"] = result["title"] or task["title"]
        task["category"] = result["category"]
        for key, value in result["suggestions"].items():
            if not task["fields"].get(key):
                task["fields"][key] = value
                task["confirmed"][key] = False
                task["ai_evidence"][key] = result["evidence"][key]
                task["field_meta"][key] = {"source": "ai", "source_quote": result["evidence"][key],
                                           "answer_id": None, "updated_at": now()}
        db.execute("UPDATE tasks SET title = ?, category = ?, fields = ?, confirmed = ?, ai_evidence = ?, field_meta = ?, updated_at = ? WHERE id = ?",
                   (task["title"], task["category"], json.dumps(task["fields"], ensure_ascii=False),
                    json.dumps(task["confirmed"]), json.dumps(task["ai_evidence"], ensure_ascii=False),
                    json.dumps(task["field_meta"], ensure_ascii=False), now(), task_id))
        return {"task": enrich_task(task), "questions": result["questions"], "model": result["model"]}


@app.post("/api/tasks/{task_id}/interview")
def interview(task_id: str, user: dict = Depends(current_user)):
    with connect() as db:
        task = get_task_or_404(db, task_id)
        require_owner(user, task)
    return ai_or_http(generate_questions, task, user["id"])


@app.get("/api/tasks/{task_id}/answers")
def list_answers(task_id: str, user: dict = Depends(current_user)):
    with connect() as db:
        require_owner(user, get_task_or_404(db, task_id))
        return [dict(row) for row in db.execute("SELECT * FROM answers WHERE task_id = ? ORDER BY created_at", (task_id,))]


@app.post("/api/tasks/{task_id}/answers", status_code=201)
def save_answer(task_id: str, payload: AnswerPayload, user: dict = Depends(current_user)):
    if payload.field not in FIELDS or payload.field == "context":
        raise HTTPException(422, "Неизвестный раздел ответа")
    answer = payload.answer.strip()
    if not valid_value(payload.field, answer):
        raise HTTPException(422, "Ответьте подробнее, чтобы подтвердить раздел")
    answer_id = str(uuid.uuid4())
    with connect() as db:
        task = get_task_or_404(db, task_id)
        require_owner(user, task)
        db.execute("INSERT INTO answers VALUES (?, ?, ?, ?, ?, ?)",
                   (answer_id, task_id, payload.field, payload.question.strip(), answer, now()))
        task["fields"][payload.field] = answer
        task["confirmed"][payload.field] = True
        task["ai_evidence"].pop(payload.field, None)
        task["field_meta"][payload.field] = {"source": "answer", "answer_id": answer_id, "updated_at": now()}
        task["pack_version"] = next_version(task["pack_version"], enrich_task(task)["readiness"]["score"])
        task["handoff_result"] = None
        task["test_lab_result"] = None
        db.execute("""UPDATE tasks SET fields = ?, confirmed = ?, ai_evidence = ?, field_meta = ?,
                   pack_version = ?, handoff_result = NULL, test_lab_result = NULL, updated_at = ? WHERE id = ?""",
                   (json.dumps(task["fields"], ensure_ascii=False), json.dumps(task["confirmed"]),
                    json.dumps(task["ai_evidence"], ensure_ascii=False), json.dumps(task["field_meta"], ensure_ascii=False),
                    task["pack_version"], now(), task_id))
        return {"answer_id": answer_id, "task": enrich_task(task)}


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: str, payload: TaskPatch, user: dict = Depends(current_user)):
    with connect() as db:
        task = get_task_or_404(db, task_id)
        require_owner(user, task)
        previous_confirmed = {key: task["fields"].get(key) for key, value in task["confirmed"].items() if value}
        previous_extra_confirmed = {key: (task.get("deadline") if key == "deadline" else task["extras"].get(key))
                                    for key, value in task["extra_confirmed"].items() if value}
        previous_flags = (task["confirmed"].copy(), task["extra_confirmed"].copy())
        changed = False
        if payload.title is not None:
            title = payload.title.strip()
            changed |= title != task["title"]
            task["title"] = title
        if payload.category is not None:
            category = payload.category.strip()
            if category not in {"AI", "Web", "Data", "Design", "Другое"}:
                raise HTTPException(422, "Неизвестная категория")
            changed |= category != task["category"]
            task["category"] = category
        if payload.industry is not None:
            changed |= payload.industry.strip() != task["industry"]
            task["industry"] = payload.industry.strip()
        if payload.deadline is not None:
            changed |= payload.deadline.strip() != task["deadline"]
            if payload.deadline.strip() != task["deadline"]:
                task["extra_confirmed"]["deadline"] = False
                task["field_meta"]["deadline"] = {"source": "user", "answer_id": None, "updated_at": now()}
            task["deadline"] = payload.deadline.strip()
        if payload.fields is not None:
            for key, value in payload.fields.items():
                if key not in FIELDS:
                    raise HTTPException(422, f"Неизвестное поле: {key}")
                if len(value) > 3000:
                    raise HTTPException(422, f"Слишком длинное поле: {key}")
                if value != task["fields"].get(key, ""):
                    changed = True
                    task["fields"][key] = value.strip()
                    task["confirmed"][key] = False
                    task["ai_evidence"].pop(key, None)
                    task["field_meta"][key] = {"source": "user", "answer_id": None, "updated_at": now()}
        if payload.extras is not None:
            for key, value in payload.extras.items():
                if key not in EXTRAS:
                    raise HTTPException(422, f"Неизвестное поле Task Pack: {key}")
                if len(value) > 3000:
                    raise HTTPException(422, f"Слишком длинное поле: {key}")
                if value.strip() != task["extras"].get(key, ""):
                    changed = True
                    task["extras"][key] = value.strip()
                    task["extra_confirmed"][key] = False
                    task["field_meta"][key] = {"source": "user", "answer_id": None, "updated_at": now()}
        if payload.confirmed is not None:
            for key, value in payload.confirmed.items():
                if key not in FIELDS:
                    raise HTTPException(422, f"Неизвестное поле: {key}")
                if value and not valid_value(key, task["fields"].get(key, "")):
                    raise HTTPException(422, f"Заполните поле «{FIELDS[key][0]}» подробнее")
                changed |= task["confirmed"].get(key) != bool(value)
                task["confirmed"][key] = bool(value)
                task["field_meta"].setdefault(key, {"source": "user", "answer_id": None})["updated_at"] = now()
        if payload.extra_confirmed is not None:
            for key, value in payload.extra_confirmed.items():
                if key not in EXTRAS and key != "deadline":
                    raise HTTPException(422, f"Неизвестное поле Task Pack: {key}")
                content = task["deadline"] if key == "deadline" else task["extras"].get(key, "")
                if value and len(content.strip()) < 3:
                    raise HTTPException(422, f"Заполните поле «{key}» подробнее")
                changed |= task["extra_confirmed"].get(key) != bool(value)
                task["extra_confirmed"][key] = bool(value)
                task["field_meta"].setdefault(key, {"source": "user", "answer_id": None})["updated_at"] = now()
        confirmed_change = (
            any(task["confirmed"].get(key) and not previous_flags[0].get(key) for key in task["confirmed"]) or
            any(task["extra_confirmed"].get(key) and not previous_flags[1].get(key) for key in task["extra_confirmed"]) or
            any(task["fields"].get(key) != value or not task["confirmed"].get(key)
                for key, value in previous_confirmed.items()) or
            any((task["deadline"] if key == "deadline" else task["extras"].get(key)) != value or
                not task["extra_confirmed"].get(key) for key, value in previous_extra_confirmed.items()))
        if confirmed_change:
            task["pack_version"] = next_version(task["pack_version"], enrich_task(task)["readiness"]["score"])
        if changed:
            task["handoff_result"] = None
            task["test_lab_result"] = None
        db.execute("""UPDATE tasks SET title = ?, category = ?, fields = ?, confirmed = ?, ai_evidence = ?,
                   extras = ?, extra_confirmed = ?, field_meta = ?, pack_version = ?, handoff_result = ?, test_lab_result = ?,
                   deadline = ?, industry = ?, updated_at = ? WHERE id = ?""",
                   (task["title"], task["category"], json.dumps(task["fields"], ensure_ascii=False),
                    json.dumps(task["confirmed"]), json.dumps(task["ai_evidence"], ensure_ascii=False),
                    json.dumps(task["extras"], ensure_ascii=False), json.dumps(task["extra_confirmed"]),
                    json.dumps(task["field_meta"], ensure_ascii=False), task["pack_version"],
                    json.dumps(task["handoff_result"], ensure_ascii=False), json.dumps(task["test_lab_result"], ensure_ascii=False),
                    task["deadline"], task["industry"], now(), task_id))
        return enrich_task(task)


@app.post("/api/tasks/{task_id}/handoff")
def run_handoff(task_id: str, user: dict = Depends(current_user)):
    with connect() as db:
        task = get_task_or_404(db, task_id)
        require_owner(user, task)
        result = handoff_rules(task)
        if os.getenv("OPENAI_API_KEY", "").strip():
            from .compiler import confirmed, value_of

            card = {key: value_of(task, key) for key in list(FIELDS) + list(EXTRAS) + ["deadline"]
                    if confirmed(task, key)}
            reviewers = []
            try:
                ai_checks = review_handoff(card, user["id"], task_id)
                reviewers.append("OpenAI")
                for check in result["checks"]:
                    ai_check = ai_checks[check["id"]]
                    if check["passed"] and not ai_check["passed"]:
                        check["passed"] = False
                        check["explanation"] = f"OpenAI: {ai_check['explanation']}"
                        check["consequence"] = "Формулировку можно трактовать по-разному."
            except (AIUnavailable, AIServiceError, ValueError):
                pass
            result["passed"] = sum(item["passed"] for item in result["checks"])
            result["mode"] = "+".join(reviewers).lower() if reviewers else "rules"
            result["notice"] = (f"Проверка по правилам и независимая рецензия: {', '.join(reviewers)}. Это не прогноз успеха." if reviewers
                                else "AI-рецензия недоступна; показана правиловая проверка подтверждённых данных.")
        result["version"] = task["pack_version"]
        result["checked_at"] = now()
        task["handoff_result"] = result
        db.execute("UPDATE tasks SET handoff_result = ? WHERE id = ?", (json.dumps(result, ensure_ascii=False), task_id))
        return result


@app.post("/api/tasks/{task_id}/test-lab")
def run_test_lab(task_id: str, user: dict = Depends(current_user)):
    with connect() as db:
        task = get_task_or_404(db, task_id)
        require_owner(user, task)
        from .compiler import confirmed, value_of
        card = {key: value_of(task, key) for key in list(FIELDS) + list(EXTRAS) + ["deadline"]
                if confirmed(task, key)}
        if not card.get("need") or not card.get("outcome"):
            raise HTTPException(422, "Для сценариев подтвердите проблему и ожидаемый результат в Task Pack")
        items = ai_or_http(generate_test_scenarios, card, user["id"], task_id)
        result = {"version": task["pack_version"], "generated_at": now(), "items": items}
        db.execute("UPDATE tasks SET test_lab_result = ? WHERE id = ?", (json.dumps(result, ensure_ascii=False), task_id))
        return result


@app.patch("/api/tasks/{task_id}/test-lab/{kind}")
def confirm_test_scenario(task_id: str, kind: str, payload: ScenarioDecision, user: dict = Depends(current_user)):
    with connect() as db:
        task = get_task_or_404(db, task_id)
        require_owner(user, task)
        result = task.get("test_lab_result")
        if not result or result.get("version") != task["pack_version"]:
            raise HTTPException(409, "Сначала создайте сценарии для текущей версии Task Pack")
        item = next((item for item in result["items"] if item["kind"] == kind), None)
        if item is None:
            raise HTTPException(404, "Сценарий не найден")
        item["confirmed"] = payload.confirmed
        db.execute("UPDATE tasks SET test_lab_result = ? WHERE id = ?", (json.dumps(result, ensure_ascii=False), task_id))
        return result


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
        if user["role"] == "admin":
            rows = db.execute("SELECT * FROM proposals" + (" WHERE task_id = ?" if task_id else "") + " ORDER BY created_at DESC", (task_id,) if task_id else ()).fetchall()
        elif user["role"] == "business":
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
    parsed = urlparse(payload.link.strip())
    if payload.link.strip() and (parsed.scheme not in {"http", "https"} or not parsed.netloc):
        raise HTTPException(422, "Укажите корректную ссылку на прототип")
    with connect() as db:
        task = get_task_or_404(db, payload.task_id)
        if not task["published"]:
            raise HTTPException(422, "Задача ещё не опубликована")
        proposal_id = str(uuid.uuid4())
        db.execute("""INSERT INTO proposals (id, task_id, team_id, idea, plan, deadline, link,
                   status, progress_awarded, created_at, questions)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)""",
                   (proposal_id, payload.task_id, user["team"]["id"], payload.idea.strip(), payload.plan.strip(),
                    payload.deadline.strip(), payload.link.strip(), now(), payload.questions.strip()))
        return get_proposal_or_404(db, proposal_id)


def proposal_owner(db, proposal: dict, user: dict):
    task = get_task_or_404(db, proposal["task_id"])
    require_owner(user, task)


@app.patch("/api/proposals/{proposal_id}/decision")
def decide_proposal(proposal_id: str, payload: Decision, user: dict = Depends(current_user)):
    if payload.status not in {"accepted", "rejected", "pending"}:
        raise HTTPException(422, "Решение должно быть accepted, rejected или pending")
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


@app.get("/api/admin/bootstrap-status")
def admin_bootstrap_status(_: dict = Depends(current_user)):
    configured = len(os.getenv("ADMIN_BOOTSTRAP_TOKEN", "").strip()) >= 24
    with connect() as db:
        available = db.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0] == 0
    return {"available": available, "configured": configured}


@app.post("/api/admin/bootstrap")
def bootstrap_admin(payload: BootstrapPayload, user: dict = Depends(current_user)):
    secret = os.getenv("ADMIN_BOOTSTRAP_TOKEN", "").strip()
    if len(secret) < 24:
        raise HTTPException(503, "Сначала задайте ADMIN_BOOTSTRAP_TOKEN (не менее 24 символов) в .env")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]:
            raise HTTPException(409, "Администратор уже назначен")
        if not hmac.compare_digest(payload.token, secret):
            raise HTTPException(403, "Неверный токен назначения администратора")
        db.execute("UPDATE users SET role = 'admin' WHERE id = ?", (user["id"],))
        db.execute("INSERT INTO role_audit VALUES (?, ?, ?, ?, ?, ?)",
                   (str(uuid.uuid4()), user["id"], user["id"], user["role"], "admin", now()))
        return user_with_team(db, user["id"])


@app.get("/api/admin/overview")
def admin_overview(user: dict = Depends(current_user)):
    require_role(user, "admin")
    with connect() as db:
        count = lambda sql: db.execute(sql).fetchone()[0]
        users = [dict(row) for row in db.execute("""SELECT u.id, u.email, u.name, u.organization, u.role, u.created_at,
                    (SELECT COUNT(*) FROM tasks t WHERE t.owner_id = u.id) AS tasks_count,
                    (SELECT COUNT(*) FROM ai_usage a WHERE a.actor_id = u.id) AS ai_calls
                    FROM users u ORDER BY u.created_at DESC""")]
        usage = [dict(row) for row in db.execute("""SELECT a.*, u.email AS actor_email, t.title AS task_title
                    FROM ai_usage a LEFT JOIN users u ON u.id = a.actor_id
                    LEFT JOIN tasks t ON t.id = a.task_id ORDER BY a.created_at DESC LIMIT 100""")]
        audit = [dict(row) for row in db.execute("""SELECT r.*, actor.email AS actor_email, target.email AS target_email
                    FROM role_audit r JOIN users actor ON actor.id = r.actor_id
                    JOIN users target ON target.id = r.target_id ORDER BY r.created_at DESC LIMIT 30""")]
        totals = dict(db.execute("""SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd,
                    COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_calls,
                    COALESCE(SUM(CASE WHEN estimated_cost_usd IS NULL AND status = 'completed' THEN 1 ELSE 0 END), 0) AS unpriced_calls
                    FROM ai_usage""").fetchone())
        return {"stats": {"users": count("SELECT COUNT(*) FROM users"),
                          "businesses": count("SELECT COUNT(*) FROM users WHERE role = 'business'"),
                          "teams": count("SELECT COUNT(*) FROM users WHERE role = 'team'"),
                          "admins": count("SELECT COUNT(*) FROM users WHERE role = 'admin'"),
                          "tasks": count("SELECT COUNT(*) FROM tasks"),
                          "published": count("SELECT COUNT(*) FROM tasks WHERE published = 1"),
                          "proposals": count("SELECT COUNT(*) FROM proposals"),
                          "pending_proposals": count("SELECT COUNT(*) FROM proposals WHERE status = 'pending'")},
                "usage": totals, "users": users, "recent_usage": usage, "role_audit": audit,
                "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                "ai_configured": bool(os.getenv("OPENAI_API_KEY", "").strip())}


@app.patch("/api/admin/users/{target_id}/role")
def admin_change_role(target_id: str, payload: RolePayload, user: dict = Depends(current_user)):
    require_role(user, "admin")
    if payload.role not in {"admin", "business", "team"}:
        raise HTTPException(422, "Недопустимая роль")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        target = db.execute("SELECT * FROM users WHERE id = ?", (target_id,)).fetchone()
        if target is None:
            raise HTTPException(404, "Пользователь не найден")
        if target["role"] == payload.role:
            return user_with_team(db, target_id)
        if target["role"] == "admin" and db.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0] <= 1:
            raise HTTPException(409, "Нельзя снять роль последнего администратора")
        if payload.role == "team" and db.execute("SELECT 1 FROM teams WHERE user_id = ?", (target_id,)).fetchone() is None:
            initials = "".join(word[0] for word in target["organization"].split()[:2]).upper()[:2] or "TM"
            db.execute("INSERT INTO teams VALUES (?, ?, ?, ?, ?, 0)",
                       (str(uuid.uuid4()), target_id, target["organization"], "[]", initials))
        db.execute("UPDATE users SET role = ? WHERE id = ?", (payload.role, target_id))
        db.execute("INSERT INTO role_audit VALUES (?, ?, ?, ?, ?, ?)",
                   (str(uuid.uuid4()), user["id"], target_id, target["role"], payload.role, now()))
        return user_with_team(db, target_id)
