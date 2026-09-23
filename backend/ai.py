"""OpenAI drafting and optional NVIDIA NIM second opinion, with usage records."""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

from .domain import FIELDS
from .storage import connect

logger = logging.getLogger(__name__)

QuestionField = Literal["need", "users", "data", "outcome", "success", "constraints", "contact", "collaboration"]


class AIUnavailable(Exception):
    pass


class AIServiceError(Exception):
    pass


class Question(BaseModel):
    field: QuestionField
    question: str


class Questions(BaseModel):
    questions: list[Question]


class FieldSuggestion(BaseModel):
    field: QuestionField
    value: str
    source_quote: str


class TaskAnalysis(BaseModel):
    title: str
    category: Literal["AI", "Web", "Data", "Design", "Другое"]
    suggestions: list[FieldSuggestion]
    questions: list[Question]


class HandoffItem(BaseModel):
    id: Literal["problem", "users", "data", "deliverable", "acceptance"]
    passed: bool
    explanation: str


class HandoffReview(BaseModel):
    checks: list[HandoffItem]


def validate_questions(questions: list[Question]) -> list[dict]:
    seen = set()
    clean = []
    for question in questions:
        if question.field in seen or not 15 <= len(question.question.strip()) <= 240:
            raise ValueError("AI returned invalid or duplicate questions")
        seen.add(question.field)
        clean.append({"field": question.field, "question": question.question.strip()})
    if not 3 <= len(clean) <= 5:
        raise ValueError("AI must return three to five questions")
    return sorted(clean, key=lambda item: FIELDS[item["field"]][1], reverse=True)


def get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AIUnavailable("OPENAI_API_KEY не задан. Добавьте ключ в .env и перезапустите FastAPI.")
    return OpenAI(api_key=api_key, timeout=20.0, max_retries=1)


def usage_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float | None:
    configured = [os.getenv(key, "").strip() for key in (
        "OPENAI_INPUT_USD_PER_MILLION", "OPENAI_CACHED_INPUT_USD_PER_MILLION", "OPENAI_OUTPUT_USD_PER_MILLION")]
    if all(configured):
        try:
            rates = [float(value) for value in configured]
            if any(rate < 0 for rate in rates):
                return None
        except ValueError:
            return None
    elif model in {"gpt-4.1-mini", "gpt-4.1-mini-2025-04-14"}:
        rates = [0.40, 0.10, 1.60]
    else:
        return None
    return round(((input_tokens - cached_tokens) * rates[0] + cached_tokens * rates[1] + output_tokens * rates[2]) / 1_000_000, 8)


def record_usage(operation: str, model: str, status: str, response=None, actor_id: str | None = None,
                 task_id: str | None = None, provider: str = "openai"):
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", 0) or 0)
    cached_tokens = min(input_tokens, int(getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0) or 0))
    cost = usage_cost(model, input_tokens, cached_tokens, output_tokens) if usage and provider == "openai" else None
    try:
        with connect() as db:
            db.execute("""INSERT INTO ai_usage (id, actor_id, task_id, operation, model, status, provider,
                       input_tokens, cached_input_tokens, output_tokens, estimated_cost_usd, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                       (str(uuid.uuid4()), actor_id, task_id, operation, model, status, provider,
                        input_tokens, cached_tokens, output_tokens, cost, datetime.now(timezone.utc).isoformat()))
    except Exception as exc:
        logger.warning("AI usage ledger unavailable: %s", type(exc).__name__)


def parse_response(schema, system: str, user: str, *, operation: str = "unknown",
                   actor_id: str | None = None, task_id: str | None = None):
    client = get_client()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    response = None
    try:
        response = client.responses.parse(
            model=model,
            input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            text_format=schema,
        )
        if response.status != "completed" or response.output_parsed is None:
            raise ValueError("AI returned an incomplete response")
        record_usage(operation, response.model or model, "completed", response, actor_id, task_id)
        return response.output_parsed
    except Exception as exc:
        record_usage(operation, getattr(response, "model", None) or model, "failed", response, actor_id, task_id)
        logger.warning("OpenAI request failed: %s", type(exc).__name__)
        raise AIServiceError("AI сейчас недоступен. Проверьте ключ, доступ к модели и соединение.") from exc


def analyze_task(task: dict, actor_id: str | None = None) -> dict:
    raw = task["fields"]["context"]
    prompt = (
        "Преобразуй исходное описание бизнес-проблемы в предварительную карточку задачи. "
        "Заполни только факты, явно присутствующие в исходном тексте. "
        "Каждое suggestion должно содержать точную короткую цитату source_quote из исходного текста, "
        "которая доказывает value. Если факта нет, не добавляй поле. "
        "Не придумывай данные, метрики, сроки, пользователей и контакты. "
        "Дай короткое название и одну подходящую категорию. "
        "Задай 3–5 разных конкретных вопросов по недостающим или неясным сведениям. "
        "Поля: need, users, data, outcome, success, constraints, contact, collaboration. "
        "Текст ответа на русском языке.\n"
        f"Исходный текст: {json.dumps(raw, ensure_ascii=False)}"
    )
    result = parse_response(TaskAnalysis, "Ты редактор задач для студенческих команд. Не добавляй неподтверждённых фактов.", prompt,
                            operation="analysis", actor_id=actor_id, task_id=task.get("id"))
    questions = validate_questions(result.questions)
    normalized_raw = " ".join(raw.lower().split())
    suggestions = {}
    evidence = {}
    for item in result.suggestions:
        quote = " ".join(item.source_quote.strip().split())
        value = item.value.strip()
        if item.field in FIELDS and 8 <= len(quote) and 5 <= len(value) <= 3000 and quote.lower() in normalized_raw:
            suggestions[item.field] = value
            evidence[item.field] = quote
    return {
        "title": result.title.strip()[:140],
        "category": result.category,
        "suggestions": suggestions,
        "evidence": evidence,
        "questions": questions,
        "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    }


def generate_questions(task: dict, actor_id: str | None = None) -> dict:
    fields = {key: value for key, value in task["fields"].items() if key == "context" or task["confirmed"].get(key)}

    prompt = (
        "Ты помогаешь представителю бизнеса сформулировать задачу для студенческой команды. "
        "Задай от 3 до 5 коротких уместных вопросов только о недостающей информации. "
        "Каждый вопрос связан с одним полем: need, users, data, outcome, success, constraints, contact, collaboration. "
        "Не добавляй фактов, которых не сообщил пользователь. Не выставляй рейтинг. "
        "Не повторяй уже ясные сведения. Ответ должен соответствовать заданной JSON-схеме.\n"
        f"Описание и подтверждённые данные: {json.dumps(fields, ensure_ascii=False)}"
    )
    result = parse_response(Questions, "Ты редактор технических задач. Задавай только проверяемые вопросы.", prompt,
                            operation="interview", actor_id=actor_id, task_id=task.get("id"))
    try:
        return {"questions": validate_questions(result.questions), "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini")}
    except ValueError as exc:
        raise AIServiceError("AI вернул некорректные вопросы. Попробуйте повторить запрос.") from exc


def review_handoff(confirmed_card: dict, actor_id: str | None = None, task_id: str | None = None) -> dict:
    """Independent clarity pass: only confirmed facts, never interview history."""
    prompt = (
        "Проверь, сможет ли независимая студенческая команда начать работу только по этой карточке. "
        "Верни ровно пять проверок с id problem, users, data, deliverable, acceptance, каждую один раз. "
        "Не используй внешние догадки. Если формулировка неоднозначна или факт отсутствует, passed=false. "
        "Для каждой проверки коротко объясни причину по-русски. Не обещай объективный прогноз успеха.\n"
        f"Подтверждённая карточка: {json.dumps(confirmed_card, ensure_ascii=False)}"
    )
    result = parse_response(HandoffReview, "Ты независимый рецензент ясности технической задачи.", prompt,
                            operation="handoff", actor_id=actor_id, task_id=task_id)
    expected = {"problem", "users", "data", "deliverable", "acceptance"}
    if len(result.checks) != 5 or {item.id for item in result.checks} != expected:
        raise AIServiceError("AI вернул некорректную проверку передачи.")
    return {item.id: {"passed": item.passed, "explanation": item.explanation.strip()[:500]}
            for item in result.checks}


def review_handoff_nvidia(confirmed_card: dict, actor_id: str | None = None, task_id: str | None = None) -> dict:
    """Optional second opinion from NVIDIA NIM, using only confirmed task facts."""
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        raise AIUnavailable("NVIDIA_API_KEY не задан")
    model = os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct").strip()
    client = OpenAI(api_key=api_key, base_url="https://integrate.api.nvidia.com/v1", timeout=25.0, max_retries=1)
    response = None
    try:
        response = client.chat.completions.create(
            model=model, temperature=0.2, max_tokens=750,
            messages=[
                {"role": "system", "content": "Ты второй независимый рецензент бизнес-задачи. Ответь только JSON-объектом с ключом checks: массив из ровно пяти объектов id, passed, explanation. id: problem, users, data, deliverable, acceptance. Пиши объяснения на русском, не выдумывай факты. Если сведений недостаточно, passed=false."},
                {"role": "user", "content": "Оцени, достаточно ли подтверждённых сведений для старта команды. Карточка: " + json.dumps(confirmed_card, ensure_ascii=False)},
            ],
        )
        content = response.choices[0].message.content or ""
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("NVIDIA returned no JSON")
        result = HandoffReview.model_validate_json(content[start:end + 1])
        expected = {"problem", "users", "data", "deliverable", "acceptance"}
        if len(result.checks) != 5 or {item.id for item in result.checks} != expected:
            raise ValueError("NVIDIA returned incomplete checks")
        record_usage("handoff_second_opinion", model, "completed", response, actor_id, task_id, "nvidia")
        return {item.id: {"passed": item.passed, "explanation": item.explanation.strip()[:500]} for item in result.checks}
    except Exception as exc:
        record_usage("handoff_second_opinion", model, "failed", response, actor_id, task_id, "nvidia")
        logger.warning("NVIDIA NIM request failed: %s", type(exc).__name__)
        raise AIServiceError("Независимая NVIDIA-проверка сейчас недоступна.") from exc
