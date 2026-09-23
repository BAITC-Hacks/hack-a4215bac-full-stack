import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.ai import FieldSuggestion, Question, TaskAnalysis, analyze_task, validate_questions
from backend.main import app


class ForgeFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("DATABASE_PATH")
        self.old_key = os.environ.get("OPENAI_API_KEY")
        os.environ["DATABASE_PATH"] = str(Path(self.temp.name) / "test.db")
        os.environ.pop("OPENAI_API_KEY", None)
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temp.cleanup()
        if self.old_db is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self.old_db
        if self.old_key is not None:
            os.environ["OPENAI_API_KEY"] = self.old_key

    def test_full_jury_flow(self):
        self.assertEqual(self.client.get("/api/tasks").status_code, 401)
        business = self.client.post("/api/auth/register", json={
            "email": "business@test.org", "password": "very-secure-password", "name": "Алия",
            "organization": "Qolda Service", "role": "business", "skills": [],
        })
        team = self.client.post("/api/auth/register", json={
            "email": "team@test.org", "password": "another-secure-password", "name": "Дана",
            "organization": "Nova Lab", "role": "team", "skills": ["Python", "AI"],
        })
        self.assertEqual(business.status_code, 201)
        self.assertEqual(team.status_code, 201)
        business_headers = {"Authorization": f"Bearer {business.json()['token']}"}
        team_headers = {"Authorization": f"Bearer {team.json()['token']}"}
        self.assertEqual(self.client.get("/api/tasks", headers=business_headers).json(), [])
        self.assertEqual(self.client.get("/api/tasks?published=false", headers=business_headers).json(), [])
        self.assertEqual(self.client.post("/api/tasks", headers=team_headers, json={"raw": "Сотрудники вручную распределяют обращения клиентов и теряют время."}).status_code, 403)

        created = self.client.post("/api/tasks", headers=business_headers, json={"raw": "Сотрудники вручную распределяют обращения клиентов и теряют время."})
        self.assertEqual(created.status_code, 201)
        task = created.json()
        task_id = task["id"]
        self.assertEqual(task["readiness"]["score"], 10)
        self.assertEqual(self.client.post(f"/api/tasks/{task_id}/analyze", headers=business_headers).status_code, 503)
        self.assertEqual(self.client.post(f"/api/tasks/{task_id}/interview", headers=business_headers).status_code, 503)
        self.assertEqual(self.client.get(f"/api/tasks/{task_id}", headers=team_headers).status_code, 403)
        with patch("backend.main.analyze_task", return_value={
            "title": "Сортировка обращений", "category": "AI",
            "suggestions": {"need": "Сократить время сортировки обращений клиентов."},
            "evidence": {"need": "теряют время"},
            "questions": [{"field": "data", "question": "Какие данные доступны для проверки решения?"},
                          {"field": "users", "question": "Кто будет пользоваться будущим решением?"},
                          {"field": "success", "question": "Как измерить успех готового решения?"}],
            "model": "test-model",
        }):
            analyzed = self.client.post(f"/api/tasks/{task_id}/analyze", headers=business_headers)
        self.assertEqual(analyzed.status_code, 200)
        self.assertEqual(analyzed.json()["task"]["fields"]["need"], "Сократить время сортировки обращений клиентов.")
        self.assertFalse(analyzed.json()["task"]["confirmed"]["need"])
        self.assertEqual(analyzed.json()["task"]["ai_evidence"]["need"], "теряют время")

        updated = self.client.patch(f"/api/tasks/{task_id}", headers=business_headers, json={
            "fields": {"need": "Сократить время ручной сортировки обращений клиентов."},
            "confirmed": {"need": True},
        }).json()
        self.assertEqual(updated["readiness"]["score"], 20)
        changed = self.client.patch(f"/api/tasks/{task_id}", headers=business_headers, json={
            "fields": {"need": "Снизить число ошибок при распределении обращений."}
        }).json()
        self.assertEqual(changed["readiness"]["score"], 10)
        self.assertFalse(changed["confirmed"]["need"])

        self.assertEqual(self.client.post(f"/api/tasks/{task_id}/publish", headers=team_headers).status_code, 403)
        self.assertEqual(self.client.post(f"/api/tasks/{task_id}/publish", headers=business_headers).status_code, 200)
        self.assertIn(task_id, [item["id"] for item in self.client.get("/api/tasks", headers=team_headers).json()])

        sent = self.client.post("/api/proposals", headers=team_headers, json={
            "task_id": task_id,
            "idea": "Соберём классификатор обращений с проверкой оператором.",
            "plan": "Подготовим CSV, создадим прототип и измерим точность.",
            "deadline": "14 дней", "link": "https://example.com/prototype",
        })
        self.assertEqual(sent.status_code, 201)
        proposal_id = sent.json()["id"]
        self.assertEqual(self.client.patch(f"/api/proposals/{proposal_id}/decision", headers=team_headers, json={"status": "accepted"}).status_code, 403)
        decision = self.client.patch(f"/api/proposals/{proposal_id}/decision", headers=business_headers, json={"status": "accepted"})
        self.assertEqual(decision.json()["status"], "accepted")
        progress = self.client.post(f"/api/proposals/{proposal_id}/progress", headers=business_headers)
        self.assertEqual(progress.json()["points_awarded"], 20)
        self.assertEqual(self.client.post(f"/api/proposals/{proposal_id}/progress", headers=business_headers).status_code, 409)
        updated_team = self.client.get("/api/auth/me", headers=team_headers).json()
        self.assertEqual(updated_team["team"]["points"], 20)
        self.assertEqual(self.client.post("/api/auth/logout", headers=team_headers).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me", headers=team_headers).status_code, 401)
        relogin = self.client.post("/api/auth/login", json={"email": "team@test.org", "password": "another-secure-password"})
        self.assertEqual(relogin.status_code, 200)

    def test_invalid_ai_questions_are_rejected(self):
        malformed = [
            Question(field="need", question="Что именно необходимо изменить?"),
            Question(field="need", question="Какая потребность есть у компании?"),
            Question(field="users", question="Для кого создаётся новое решение?"),
        ]
        with self.assertRaises(ValueError):
            validate_questions(malformed)

    def test_ai_suggestions_require_source_quote_and_human_confirmation(self):
        analysis = TaskAnalysis(
            title="Сортировка обращений", category="AI",
            suggestions=[
                FieldSuggestion(field="need", value="Сократить время ручной сортировки.", source_quote="теряют время"),
                FieldSuggestion(field="data", value="Доступны тысячи обращений в CSV.", source_quote="тысячи CSV"),
            ],
            questions=[
                Question(field="data", question="Какие данные вы сможете передать команде?"),
                Question(field="users", question="Кто будет пользоваться будущим решением?"),
                Question(field="success", question="Как вы будете измерять успех решения?"),
            ],
        )
        task = {"fields": {"context": "Сотрудники вручную распределяют обращения и теряют время."}}
        with patch("backend.ai.parse_response", return_value=analysis):
            result = analyze_task(task)
        self.assertEqual(result["suggestions"], {"need": "Сократить время ручной сортировки."})
        self.assertEqual(result["evidence"], {"need": "теряют время"})


if __name__ == "__main__":
    unittest.main()
