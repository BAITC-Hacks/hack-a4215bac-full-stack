"""Exercise the Turso adapter against libsql's local driver without cloud secrets."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app


@unittest.skipUnless(importlib.util.find_spec("libsql"), "libsql is optional for local SQLite development")
class RemoteStorageTest(unittest.TestCase):
    def test_account_and_task_flow_with_libsql_driver(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = {"TURSO_DATABASE_URL": str(Path(temporary) / "remote-compatible.db"),
                   "TURSO_AUTH_TOKEN": "local-driver-test",
                   "ADMIN_BOOTSTRAP_TOKEN": "remote-driver-bootstrap-test-token"}
            with patch.dict(os.environ, env):
                with TestClient(app) as client:
                    payload = {"email": "remote@test.org", "password": "secure-password-12345", "name": "Алия",
                               "organization": "Qolda", "role": "business", "skills": []}
                    registered = client.post("/api/auth/register", json=payload)
                    self.assertEqual(registered.status_code, 201)
                    duplicate = client.post("/api/auth/register", json=payload)
                    self.assertEqual(duplicate.status_code, 409)
                    headers = {"Authorization": f"Bearer {registered.json()['token']}"}
                    task = client.post("/api/tasks", headers=headers, json={
                        "raw": "Нужно ускорить обработку клиентских обращений в службе поддержки."})
                    self.assertEqual(task.status_code, 201)
                    listed = client.get("/api/tasks?published=false", headers=headers)
                    self.assertEqual(listed.status_code, 200)
                    self.assertEqual(listed.json()[0]["id"], task.json()["id"])
                    bootstrap = client.post("/api/admin/bootstrap", headers=headers,
                                            json={"token": env["ADMIN_BOOTSTRAP_TOKEN"]})
                    self.assertEqual(bootstrap.status_code, 200)
                    self.assertEqual(bootstrap.json()["role"], "admin")


if __name__ == "__main__":
    unittest.main()
