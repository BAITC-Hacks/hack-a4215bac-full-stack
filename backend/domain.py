"""Transparent, deterministic readiness scoring. AI never sets points."""

FIELDS = {
    "context": ("Контекст", 10, 15, "Контекст и потребность"),
    "need": ("Потребность", 10, 12, "Контекст и потребность"),
    "data": ("Данные и материалы", 20, 12, "Данные и материалы"),
    "outcome": ("Ожидаемый результат", 15, 12, "Ожидаемый результат"),
    "success": ("Критерии успеха", 15, 12, "Критерии успеха"),
    "constraints": ("Ограничения", 10, 10, "Ограничения"),
    "users": ("Пользователи", 10, 8, "Пользователи"),
    "contact": ("Контакт бизнеса", 5, 8, "Связь с бизнесом"),
    "collaboration": ("Формат взаимодействия", 5, 12, "Связь с бизнесом"),
}

GROUPS = [
    ("Контекст и потребность", 20),
    ("Данные и материалы", 20),
    ("Ожидаемый результат", 15),
    ("Критерии успеха", 15),
    ("Ограничения", 10),
    ("Пользователи", 10),
    ("Связь с бизнесом", 10),
]

EMPTY = {"нет", "не знаю", "н/д", "n/a", "позже", "пока нет", "не указано", "—", "-", "..."}


def valid_value(key: str, value: str) -> bool:
    if key not in FIELDS:
        return False
    clean = " ".join(str(value or "").split())
    return len(clean) >= FIELDS[key][2] and clean.lower() not in EMPTY


def readiness(fields: dict, confirmed: dict) -> dict:
    items = []
    for key, (label, possible, _, group) in FIELDS.items():
        value = fields.get(key, "")
        earned = possible if confirmed.get(key) and valid_value(key, value) else 0
        items.append({"key": key, "label": label, "group": group, "possible": possible, "earned": earned,
                      "confirmed": bool(confirmed.get(key)), "has_value": bool(str(value).strip())})
    score = sum(item["earned"] for item in items)
    groups = [{"name": name, "possible": possible,
               "earned": sum(item["earned"] for item in items if item["group"] == name)}
              for name, possible in GROUPS]
    level = "Приоритетная" if score >= 90 else "Готовая" if score >= 70 else "Рабочая" if score >= 40 else "Черновик"
    return {"score": score, "level": level, "items": items, "groups": groups,
            "missing": [item for item in items if not item["earned"]]}


def enrich_task(task: dict) -> dict:
    return {**task, "readiness": readiness(task["fields"], task["confirmed"])}
