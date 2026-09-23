import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.ai import FieldSuggestion, Question, TaskAnalysis, analyze_task, validate_questions, parse_response, generate_test_scenarios, usage_cost
from backend.compiler import compile_readiness, handoff_rules
from backend.domain import FIELDS
from backend.main import app
from backend.storage import connect


class ForgeFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("DATABASE_PATH")
        self.old_key = os.environ.get("OPENAI_API_KEY")
        self.old_nvidia_key = os.environ.get("NVIDIA_API_KEY")
        os.environ["DATABASE_PATH"] = str(Path(self.temp.name) / "test.db")
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("NVIDIA_API_KEY", None)
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
        if self.old_nvidia_key is not None:
            os.environ["NVIDIA_API_KEY"] = self.old_nvidia_key

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
        self.assertEqual(task["build"]["status"], "failed")
        self.assertGreaterEqual(task["build"]["errors"], 3)
        self.assertEqual(task["task_pack"]["version"], "v0.1")
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
        self.assertEqual(analyzed.json()["task"]["task_pack"]["version"], "v0.1")

        answer = self.client.post(f"/api/tasks/{task_id}/answers", headers=business_headers, json={
            "field": "users", "question": "Кто будет пользоваться будущим решением?",
            "answer": "Операторы поддержки и руководитель смены.",
        })
        self.assertEqual(answer.status_code, 201)
        self.assertEqual(answer.json()["task"]["field_meta"]["users"]["source"], "answer")
        self.assertEqual(len(self.client.get(f"/api/tasks/{task_id}/answers", headers=business_headers).json()), 1)

        pack_update = self.client.patch(f"/api/tasks/{task_id}", headers=business_headers, json={
            "extras": {"acceptance_owner": "Руководитель контакт-центра", "data_access": "Передадим CSV через защищённую папку"},
            "extra_confirmed": {"acceptance_owner": True, "data_access": True},
        })
        self.assertEqual(pack_update.status_code, 200)
        self.assertEqual(pack_update.json()["task_pack"]["sections"][3]["items"][-2]["status"], "confirmed")
        handoff = self.client.post(f"/api/tasks/{task_id}/handoff", headers=business_headers)
        self.assertEqual(handoff.status_code, 200)
        self.assertEqual(handoff.json()["total"], 5)
        self.assertEqual(handoff.json()["mode"], "rules")

        updated = self.client.patch(f"/api/tasks/{task_id}", headers=business_headers, json={
            "fields": {"need": "Сократить время ручной сортировки обращений клиентов."},
            "confirmed": {"need": True},
        }).json()
        self.assertEqual(updated["readiness"]["score"], 30)
        changed = self.client.patch(f"/api/tasks/{task_id}", headers=business_headers, json={
            "fields": {"need": "Снизить число ошибок при распределении обращений."}
        }).json()
        self.assertEqual(changed["readiness"]["score"], 20)
        self.assertFalse(changed["confirmed"]["need"])

        self.assertEqual(self.client.post(f"/api/tasks/{task_id}/publish", headers=team_headers).status_code, 403)
        self.assertEqual(self.client.post(f"/api/tasks/{task_id}/publish", headers=business_headers).status_code, 200)
        self.assertIn(task_id, [item["id"] for item in self.client.get("/api/tasks", headers=team_headers).json()])
        public_task = self.client.get(f"/api/tasks/{task_id}", headers=team_headers).json()
        self.assertEqual(public_task["fields"]["need"], "")
        self.assertEqual(public_task["ai_evidence"], {})

        sent = self.client.post("/api/proposals", headers=team_headers, json={
            "task_id": task_id,
            "idea": "Соберём классификатор обращений с проверкой оператором.",
            "plan": "Подготовим CSV, создадим прототип и измерим точность.",
            "deadline": "14 дней", "link": "https://example.com/prototype",
        })
        self.assertEqual(sent.status_code, 201)
        proposal_id = sent.json()["id"]
        no_prototype = self.client.post("/api/proposals", headers=team_headers, json={
            "task_id": task_id,
            "idea": "Проверим ручную разметку и соберём альтернативный подход.",
            "plan": "Согласуем данные, реализуем и сравним два варианта.",
            "deadline": "21 день",
        })
        self.assertEqual(no_prototype.status_code, 201)
        self.assertEqual(no_prototype.json()["link"], "")
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

    def test_compiler_and_handoff_fix_targets(self):
        fields = {key: "" for key in FIELDS}
        fields.update({
            "context": "Операторы вручную сортируют обращения клиентов.",
            "need": "Сократить ручную сортировку обращений.",
            "users": "Операторы службы поддержки.",
            "data": "Обезличенный CSV с обращениями клиентов.",
            "outcome": "Прототип классификации и отчёт с ошибками.",
            "success": "Проверить выгрузку CSV и ошибки классификации.",
        })
        task = {"fields": fields, "confirmed": {key: bool(value) for key, value in fields.items()},
                "extras": {}, "extra_confirmed": {}, "field_meta": {}, "deadline": ""}
        build = compile_readiness(task)
        self.assertEqual(build["score"], 80)
        self.assertEqual(build["status"], "failed")
        handoff = handoff_rules(task)
        self.assertEqual(handoff["passed"], 3)
        self.assertEqual(next(item for item in handoff["checks"] if item["id"] == "data")["field"], "data_access")
        self.assertEqual(next(item for item in handoff["checks"] if item["id"] == "acceptance")["field"], "acceptance_owner")
        task["extras"] = {"data_access": "CSV через защищённую папку", "acceptance_owner": "Руководитель поддержки"}
        task["extra_confirmed"] = {"data_access": True, "acceptance_owner": True}
        self.assertEqual(handoff_rules(task)["passed"], 5)

    def test_admin_bootstrap_roles_and_usage_ledger(self):
        first = self.client.post("/api/auth/register", json={
            "email": "owner@test.org", "password": "long-secure-password", "name": "Владелец",
            "organization": "FORGE", "role": "business", "skills": [],
        }).json()
        second = self.client.post("/api/auth/register", json={
            "email": "member@test.org", "password": "another-long-password", "name": "Участник",
            "organization": "Студия", "role": "team", "skills": ["Python"],
        }).json()
        owner_headers = {"Authorization": f"Bearer {first['token']}"}
        member_headers = {"Authorization": f"Bearer {second['token']}"}
        self.assertEqual(self.client.get("/api/admin/overview", headers=owner_headers).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/register", json={
            "email": "fake@test.org", "password": "long-secure-password", "name": "Фейк",
            "organization": "FORGE", "role": "admin", "skills": [],
        }).status_code, 422)
        with patch.dict(os.environ, {"ADMIN_BOOTSTRAP_TOKEN": "a-long-random-bootstrap-secret-12345"}):
            self.assertTrue(self.client.get("/api/admin/bootstrap-status", headers=owner_headers).json()["available"])
            self.assertEqual(self.client.post("/api/admin/bootstrap", headers=owner_headers, json={"token": "wrong"}).status_code, 403)
            boot = self.client.post("/api/admin/bootstrap", headers=owner_headers, json={"token": "a-long-random-bootstrap-secret-12345"})
            self.assertEqual(boot.status_code, 200)
            self.assertEqual(boot.json()["role"], "admin")
            self.assertEqual(self.client.post("/api/admin/bootstrap", headers=member_headers, json={"token": "a-long-random-bootstrap-secret-12345"}).status_code, 409)
        self.assertEqual(self.client.get("/api/admin/overview", headers=member_headers).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/admin/users/{first['user']['id']}/role", headers=owner_headers, json={"role": "business"}).status_code, 409)
        promoted = self.client.patch(f"/api/admin/users/{second['user']['id']}/role", headers=owner_headers, json={"role": "admin"})
        self.assertEqual(promoted.json()["role"], "admin")
        self.assertEqual(self.client.patch(f"/api/admin/users/{first['user']['id']}/role", headers=owner_headers, json={"role": "business"}).status_code, 200)
        self.assertEqual(self.client.get("/api/admin/overview", headers=owner_headers).status_code, 403)
        self.assertEqual(usage_cost("gpt-4.1-mini", 1000, 200, 500), 0.00114)
        sample = SimpleNamespace(status="completed", model="gpt-4.1-mini", output_parsed={"ok": True},
                                 usage=SimpleNamespace(input_tokens=1000, output_tokens=500,
                                                       input_tokens_details=SimpleNamespace(cached_tokens=200)))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch("backend.ai.get_client") as client:
            client.return_value.responses.parse.return_value = sample
            self.assertEqual(parse_response(dict, "system", "user", operation="interview", actor_id=second['user']['id']), {"ok": True})
        overview = self.client.get("/api/admin/overview", headers=member_headers).json()
        self.assertEqual(overview["usage"]["input_tokens"], 1000)
        self.assertEqual(overview["usage"]["output_tokens"], 500)
        self.assertEqual(overview["usage"]["estimated_cost_usd"], 0.00114)
        self.assertEqual(len(overview["role_audit"]), 3)

    def test_admin_main_workspace_is_available_and_other_business_decides(self):
        admin = self.client.post("/api/auth/register", json={
            "email": "admin@test.org", "password": "long-secure-password", "name": "Admin",
            "organization": "FORGE", "role": "business", "skills": [],
        }).json()
        business = self.client.post("/api/auth/register", json={
            "email": "other@test.org", "password": "long-secure-password", "name": "Owner",
            "organization": "Other", "role": "business", "skills": [],
        }).json()
        team = self.client.post("/api/auth/register", json={
            "email": "team2@test.org", "password": "long-secure-password", "name": "Team",
            "organization": "Builders", "role": "team", "skills": ["Python"],
        }).json()
        ah = {"Authorization": f"Bearer {admin['token']}"}
        bh = {"Authorization": f"Bearer {business['token']}"}
        th = {"Authorization": f"Bearer {team['token']}"}
        with patch.dict(os.environ, {"ADMIN_BOOTSTRAP_TOKEN": "a-long-random-bootstrap-secret-12345"}):
            self.assertEqual(self.client.post("/api/admin/bootstrap", headers=ah, json={"token": "a-long-random-bootstrap-secret-12345"}).status_code, 200)
        own = self.client.post("/api/tasks", headers=ah, json={"raw": "Нужно ускорить обработку писем клиентов и подготовить понятный план."})
        self.assertEqual(own.status_code, 201)
        other = self.client.post("/api/tasks", headers=bh, json={"raw": "Нужно ускорить обработку входящих звонков и подготовить понятный план."}).json()
        self.assertEqual(self.client.post(f"/api/tasks/{other['id']}/publish", headers=bh).status_code, 200)
        self.assertEqual(len(self.client.get("/api/tasks", headers=ah).json()), 1)
        self.assertEqual(len(self.client.get("/api/tasks?published=false", headers=ah).json()), 1)
        sent = self.client.post("/api/proposals", headers=th, json={"task_id": other["id"], "idea": "Сделаем маршрутизацию по темам.", "plan": "Соберём данные и протестируем модель.", "deadline": "10 дней"}).json()
        self.assertEqual(len(self.client.get("/api/proposals", headers=ah).json()), 1)
        self.assertEqual(self.client.patch(f"/api/proposals/{sent['id']}/decision", headers=ah, json={"status": "accepted"}).status_code, 403)
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test-nvidia-key"}), patch("backend.main.generate_test_scenarios") as generator:
            result = self.client.post(f"/api/tasks/{own.json()['id']}/handoff", headers=ah)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["mode"], "rules")
        generator.assert_not_called()

    def test_test_lab_confirmation_and_version_invalidation(self):
        business = self.client.post("/api/auth/register", json={
            "email": "lab-owner@test.org", "password": "very-secure-password", "name": "Алия",
            "organization": "Qolda Service", "role": "business", "skills": [],
        }).json()
        team = self.client.post("/api/auth/register", json={
            "email": "lab-team@test.org", "password": "very-secure-password", "name": "Дана",
            "organization": "Nova Lab", "role": "team", "skills": ["Python"],
        }).json()
        bh = {"Authorization": f"Bearer {business['token']}"}
        th = {"Authorization": f"Bearer {team['token']}"}
        task = self.client.post("/api/tasks", headers=bh, json={"raw": "Нужно ускорить сортировку обращений клиентов и уменьшить время ожидания."}).json()
        task_id = task["id"]
        self.assertEqual(self.client.post(f"/api/tasks/{task_id}/test-lab", headers=bh).status_code, 422)
        patched = self.client.patch(f"/api/tasks/{task_id}", headers=bh, json={
            "fields": {"need": "Ускорить сортировку обращений клиентов.", "outcome": "Рабочий прототип сортировки обращений для операторов."},
            "confirmed": {"need": True, "outcome": True},
        })
        self.assertEqual(patched.status_code, 200)
        examples = [{"kind": kind, "title": f"Сценарий {kind}", "steps": "Проверить прототип на обращении.",
                     "expected": "Показан вариант маршрутизации.", "open_question": "Какой порог точности нужен?", "confirmed": False}
                    for kind in ("normal", "edge", "failure")]
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key"}), patch("backend.main.generate_test_scenarios", return_value=examples) as generator:
            generated = self.client.post(f"/api/tasks/{task_id}/test-lab", headers=bh)
        self.assertEqual(generated.status_code, 200)
        self.assertEqual(len(generated.json()["items"]), 3)
        self.assertEqual(generator.call_args.args[0]["need"], "Ускорить сортировку обращений клиентов.")
        self.assertEqual(self.client.patch(f"/api/tasks/{task_id}/test-lab/normal", headers=th, json={"confirmed": True}).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/tasks/{task_id}/test-lab/normal", headers=bh, json={"confirmed": True}).status_code, 200)
        self.client.post(f"/api/tasks/{task_id}/publish", headers=bh)
        public = self.client.get(f"/api/tasks/{task_id}", headers=th).json()
        self.assertEqual([item["kind"] for item in public["test_lab_result"]["items"]], ["normal"])
        changed = self.client.patch(f"/api/tasks/{task_id}", headers=bh, json={"fields": {"need": "Нужна другая маршрутизация обращений клиентов."}})
        self.assertIsNone(changed.json()["test_lab_result"])
        self.assertIsNone(self.client.get(f"/api/tasks/{task_id}", headers=th).json()["test_lab_result"])

    def test_nvidia_usage_records_tokens_without_inventing_cost(self):
        content = '{"items":[' + ','.join(
            '{"kind":"' + kind + '","title":"Сценарий","steps":"Проверить ввод",'
            '"expected":"Получить результат","open_question":"Что считать успехом?"}'
            for kind in ["normal", "edge", "failure"]) + ']}'
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                                   usage=SimpleNamespace(prompt_tokens=180, completion_tokens=75))
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test-nvidia-key"}), patch("backend.ai.OpenAI") as client:
            client.return_value.chat.completions.create.return_value = response
            scenarios = generate_test_scenarios({"need": "Ускорить обработку запросов"})
        self.assertEqual(len(scenarios), 3)
        self.assertFalse(scenarios[0]["confirmed"])
        with connect() as db:
            row = db.execute("SELECT provider, model, input_tokens, output_tokens, estimated_cost_usd FROM ai_usage").fetchone()
        self.assertEqual(row["provider"], "nvidia")
        self.assertEqual(row["input_tokens"], 180)
        self.assertEqual(row["output_tokens"], 75)
        self.assertIsNone(row["estimated_cost_usd"])


if __name__ == "__main__":
    unittest.main()
