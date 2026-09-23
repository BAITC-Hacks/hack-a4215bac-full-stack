"""Deterministic readiness diagnostics, Task Pack and handoff checks.

These rules never award points for AI drafts or invent missing business facts.
"""

from .domain import FIELDS, readiness, valid_value

EXTRAS = {
    "data_format": ("Формат данных", "STARTER DATA"),
    "data_volume": ("Примерный объём", "STARTER DATA"),
    "data_source": ("Источник данных", "STARTER DATA"),
    "data_access": ("Способ доступа", "STARTER DATA"),
    "data_kind": ("Тип данных: реальные или синтетические", "STARTER DATA"),
    "deliverable_format": ("Формат результата", "EXPECTED DELIVERABLE"),
    "in_scope": ("Что входит в объём", "EXPECTED DELIVERABLE"),
    "out_scope": ("Что не входит в объём", "EXPECTED DELIVERABLE"),
    "acceptance_input": ("Входные данные проверки", "DEFINITION OF DONE"),
    "acceptance_output": ("Ожидаемый выход", "DEFINITION OF DONE"),
    "acceptance_check": ("Как проверить результат", "DEFINITION OF DONE"),
    "acceptance_owner": ("Кто принимает результат", "DEFINITION OF DONE"),
    "acceptance_responsibility": ("Ответственность за критерии", "DEFINITION OF DONE"),
    "first_sprint": ("Первые шаги команды", "FIRST SPRINT"),
    "consultation_frequency": ("Частота консультаций", "COLLABORATION"),
    "feedback_process": ("Порядок обратной связи", "COLLABORATION"),
    "response_time": ("Ожидаемое время ответа", "COLLABORATION"),
    "technologies": ("Технологии", "RISKS AND CONSTRAINTS"),
    "risks": ("Известные риски", "RISKS AND CONSTRAINTS"),
}

SECTIONS = [
    ("TASK BRIEF", ["context", "need", "users", "business_goal"]),
    ("STARTER DATA", ["data", "data_format", "data_volume", "data_source", "data_access", "data_kind"]),
    ("EXPECTED DELIVERABLE", ["outcome", "deliverable_format", "in_scope", "out_scope"]),
    ("DEFINITION OF DONE", ["success", "acceptance_input", "acceptance_output", "acceptance_check", "acceptance_owner", "acceptance_responsibility"]),
    ("FIRST SPRINT", ["first_sprint"]),
    ("COLLABORATION", ["contact", "collaboration", "consultation_frequency", "feedback_process", "response_time"]),
    ("RISKS AND CONSTRAINTS", ["constraints", "deadline", "technologies", "risks"]),
]

EXTRAS["business_goal"] = ("Связь с бизнес-целью", "TASK BRIEF")

CRITICAL = [
    ("E01", "outcome", "Не определён результат", "Команда не знает, что передать по завершении.", "Опишите конкретный результат"),
    ("E02", "data", "Нет данных или материалов", "Нельзя спроектировать и проверить прототип на реальных входных данных.", "Укажите пример, источник и доступность данных"),
    ("E03", "acceptance_owner", "Не указан принимающий результат", "Неясно, кто принимает итоговую работу.", "Назовите ответственного за приёмку"),
    ("E04", "success", "Нет критериев приёмки", "Команда не сможет проверить, достигнут ли ожидаемый результат.", "Опишите наблюдаемую проверку результата"),
    ("E05", "contact", "Нет контакта бизнеса", "Команда не сможет быстро уточнить спорные моменты.", "Укажите ответственного и способ связи"),
    ("E06", "need", "Потребность не уточнена", "Сложно выбрать верный подход к задаче.", "Опишите, что именно нужно изменить"),
    ("E07", "users", "Не указаны пользователи", "Команда не знает, для кого проектирует решение.", "Назовите будущих пользователей"),
]

AMBIGUOUS = ("улучшить", "повысить качество", "удобный", "быстрый", "эффективный", "оптимизировать")


def value_of(task: dict, key: str) -> str:
    if key in FIELDS:
        return task["fields"].get(key, "")
    if key == "deadline":
        return task.get("deadline", "")
    return task.get("extras", {}).get(key, "")


def confirmed(task: dict, key: str) -> bool:
    if key in FIELDS:
        return bool(task["confirmed"].get(key) and valid_value(key, value_of(task, key)))
    if key == "deadline":
        return bool(task.get("extra_confirmed", {}).get(key) and value_of(task, key).strip())
    return bool(task.get("extra_confirmed", {}).get(key) and value_of(task, key).strip())


def field_status(task: dict, key: str) -> str:
    value = value_of(task, key).strip()
    if not value:
        return "missing"
    if not confirmed(task, key):
        return "ai_draft" if task.get("field_meta", {}).get(key, {}).get("source") == "ai" else "missing"
    if key == "data" and not confirmed(task, "data_access"):
        return "warning"
    if key == "collaboration" and not confirmed(task, "feedback_process"):
        return "warning"
    if key in {"outcome", "success"} and any(phrase in value.lower() for phrase in AMBIGUOUS):
        return "warning"
    return "confirmed"


def diagnostic(code, severity, key, title, consequence, action, points=0):
    return {"code": code, "severity": severity, "field": key, "title": title,
            "consequence": consequence, "action": action, "max_score_impact": points}


def compile_readiness(task: dict) -> dict:
    score = readiness(task["fields"], task["confirmed"])["score"]
    diagnostics = []
    for code, key, title, consequence, action in CRITICAL:
        if not confirmed(task, key):
            diagnostics.append(diagnostic(code, "error", key, title, consequence, action, FIELDS.get(key, (None, 0))[1]))
    if confirmed(task, "data") and not confirmed(task, "data_access"):
        diagnostics.append(diagnostic("W03", "warning", "data_access", "Доступность данных не подтверждена",
                                      "Команда может не получить материалы вовремя.", "Укажите способ доступа"))
    if confirmed(task, "success") and field_status(task, "success") == "warning":
        diagnostics.append(diagnostic("W05", "warning", "success", "Субъективный критерий успеха",
                                      "Приёмка результата может оказаться спорной.", "Опишите проверяемое условие"))
    if confirmed(task, "outcome") and field_status(task, "outcome") == "warning":
        diagnostics.append(diagnostic("W02", "warning", "outcome", "Неоднозначный ожидаемый результат",
                                      "Команды могут по-разному понять объём работы.", "Уточните конкретный результат"))
    if confirmed(task, "contact") and not confirmed(task, "feedback_process"):
        diagnostics.append(diagnostic("W04", "warning", "feedback_process", "Порядок обратной связи не указан",
                                      "Команда не знает, когда и как получать решение по вопросам.", "Опишите порядок обратной связи"))
    if not confirmed(task, "constraints"):
        diagnostics.append(diagnostic("W06", "warning", "constraints", "Ограничения не описаны",
                                      "Команда может предложить решение вне доступного срока или технологий.", "Укажите ограничения", 10))
    if not confirmed(task, "collaboration"):
        diagnostics.append(diagnostic("W07", "warning", "collaboration", "Формат взаимодействия не подтверждён",
                                      "Неясно, как часто команда сможет получить консультацию.", "Опишите взаимодействие", 5))
    for key, (label, points, _, _) in FIELDS.items():
        if confirmed(task, key):
            diagnostics.append(diagnostic("P-" + key.upper(), "passed", key, label + " подтверждены",
                                          "Раздел можно использовать для начала работы.", "", points))
    errors = sum(item["severity"] == "error" for item in diagnostics)
    warnings = sum(item["severity"] == "warning" for item in diagnostics)
    status = "failed" if errors else "warning" if warnings else "success"
    next_step = next((item for item in diagnostics if item["severity"] == "error"),
                     next((item for item in diagnostics if item["severity"] == "warning"), None))
    return {"status": status, "score": score, "errors": errors, "warnings": warnings,
            "diagnostics": diagnostics, "next_step": next_step}


def task_pack(task: dict) -> dict:
    sections = []
    for section_name, keys in SECTIONS:
        items = []
        for key in keys:
            label = FIELDS[key][0] if key in FIELDS else "Предполагаемый срок" if key == "deadline" else EXTRAS[key][0]
            meta = task.get("field_meta", {}).get(key, {})
            items.append({"key": key, "label": label, "value": value_of(task, key),
                          "status": field_status(task, key), "confirmed": confirmed(task, key),
                          "source": meta.get("source", "user" if value_of(task, key) else "none"),
                          "answer_id": meta.get("answer_id"), "updated_at": meta.get("updated_at"),
                          "points": FIELDS[key][1] if key in FIELDS else 0})
        sections.append({"name": section_name, "items": items})
    return {"version": task.get("pack_version", "v0.1"), "sections": sections}


HANDOFF_CHECKS = [
    ("problem", "Какую проблему нужно решить?", "need", "Уточните потребность, чтобы команда понимала проблему."),
    ("users", "Для кого создаётся результат?", "users", "Назовите будущих пользователей."),
    ("data", "С какими данными работать?", "data", "Укажите материал и способ доступа."),
    ("deliverable", "Что команда должна создать?", "outcome", "Опишите конкретный формат результата."),
    ("acceptance", "Как бизнес примет результат?", "success", "Опишите проверку и ответственного за приёмку."),
]


def handoff_rules(task: dict) -> dict:
    checks = []
    for check_id, question, key, fix in HANDOFF_CHECKS:
        ok = confirmed(task, key) and field_status(task, key) != "warning"
        target = key
        if check_id == "data":
            if confirmed(task, "data") and not confirmed(task, "data_access"):
                target = "data_access"
            ok = ok and confirmed(task, "data_access")
        if check_id == "acceptance":
            if confirmed(task, "success") and not confirmed(task, "acceptance_owner"):
                target = "acceptance_owner"
            ok = ok and confirmed(task, "acceptance_owner")
        checks.append({"id": check_id, "question": question, "passed": ok, "field": target,
                       "explanation": "Ответ есть в подтверждённой карточке." if ok else fix,
                       "consequence": "Потребуется дополнительная встреча для уточнения." if not ok else ""})
    return {"passed": sum(item["passed"] for item in checks), "total": 5,
            "checks": checks, "mode": "rules", "notice": "Правиловая проверка подтверждённых данных; не прогноз успеха проекта."}
