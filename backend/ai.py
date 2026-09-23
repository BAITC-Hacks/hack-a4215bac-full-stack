"""OpenAI analysis and interview. No synthetic AI output is shown as real AI."""

import json
import logging
import os
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

from .domain import FIELDS

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
    return clean


def get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AIUnavailable("OPENAI_API_KEY не задан. Добавьте ключ в .env и перезапустите FastAPI.")
    return OpenAI(api_key=api_key, timeout=20.0, max_retries=1)


def parse_response(schema, system: str, user: str):
    client = get_client()
    try:
        response = client.responses.parse(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            text_format=schema,
        )
        if response.status != "completed" or response.output_parsed is None:
            raise ValueError("AI returned an incomplete response")
        return response.output_parsed
    except Exception as exc:
        logger.warning("OpenAI request failed: %s", type(exc).__name__)
        raise AIServiceError("AI сейчас недоступен. Проверьте ключ, доступ к модели и соединение.") from exc


def analyze_task(task: dict) -> dict:
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
    result = parse_response(TaskAnalysis, "Ты редактор задач для студенческих команд. Не добавляй неподтверждённых фактов.", prompt)
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


def generate_questions(task: dict) -> dict:
    fields = task["fields"]

    prompt = (
        "Ты помогаешь представителю бизнеса сформулировать задачу для студенческой команды. "
        "Задай от 3 до 5 коротких уместных вопросов только о недостающей информации. "
        "Каждый вопрос связан с одним полем: need, users, data, outcome, success, constraints, contact, collaboration. "
        "Не добавляй фактов, которых не сообщил пользователь. Не выставляй рейтинг. "
        "Не повторяй уже ясные сведения. Ответ должен соответствовать заданной JSON-схеме.\n"
        f"Описание и уже подтверждённые данные: {json.dumps(fields, ensure_ascii=False)}"
    )
    result = parse_response(Questions, "Ты редактор технических задач. Задавай только проверяемые вопросы.", prompt)
    try:
        return {"questions": validate_questions(result.questions), "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini")}
    except ValueError as exc:
        raise AIServiceError("AI вернул некорректные вопросы. Попробуйте повторить запрос.") from exc
