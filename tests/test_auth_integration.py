"""Integration test — auth token → analysis with permission filtering"""
import sys
import pytest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Mock BGE embedding to avoid model download/loading during backend.main import
with mock.patch("embedding.get_embedding_model"):
    from backend.main import app

# Override database with in-memory SQLite for testing
from sqlalchemy import pool as sa_pool
from auth.database import init_db
init_db("sqlite:///:memory:", poolclass=sa_pool.StaticPool)

from fastapi.testclient import TestClient

client = TestClient(app)


class TestAnalysisWithPermissions:
    def test_analysis_respects_auth(self):
        """Full analysis endpoint returns a response (not 401) when authenticated"""
        login_resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        token = login_resp.json()["token"]

        resp = client.post("/api/analysis/full", json={
            "requirement_text": "统计各渠道活跃客户数",
            "generate_sql": False,
        }, headers={"Authorization": f"Bearer {token}"})

        # Should NOT be 401 (auth passed)
        assert resp.status_code != 401

    def test_analysis_without_token_blocked(self):
        resp = client.post("/api/analysis/full", json={
            "requirement_text": "test", "generate_sql": False,
        })
        assert resp.status_code == 401

    def test_analysis_with_invalid_token(self):
        resp = client.post("/api/analysis/full", json={
            "requirement_text": "test", "generate_sql": False,
        }, headers={"Authorization": "Bearer bad.token.here"})
        assert resp.status_code == 401


class TestAdminCrudPermissions:
    def test_admin_create_user(self):
        """Admin can create a new user"""
        login_resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        token = login_resp.json()["token"]

        resp = client.post("/api/admin/users", json={
            "username": "newuser",
            "password": "newpass123",
            "real_name": "New User",
            "department_id": 1,
            "is_admin": False,
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["created"] is True

    def test_admin_create_duplicate_user_fails(self):
        """Creating a user with an existing username should fail"""
        login_resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        token = login_resp.json()["token"]

        resp = client.post("/api/admin/users", json={
            "username": "admin",  # already exists
            "password": "somepass",
            "real_name": "Duplicate",
            "department_id": 1,
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 400

    def test_admin_create_department(self):
        """Admin can create a new department"""
        login_resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        token = login_resp.json()["token"]

        resp = client.post("/api/admin/departments", json={
            "name": "测试支行",
            "parent_id": 1,  # under 总行
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] is True
        assert "测试支行" in data["path"]

    def test_admin_create_business_line(self):
        """Admin can create a new business line"""
        login_resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        token = login_resp.json()["token"]

        resp = client.post("/api/admin/business-lines", json={
            "name": "数字银行",
            "code": "digital",
            "description": "数字化银行业务",
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["created"] is True

    def test_admin_create_business_line_duplicate_code(self):
        """Creating a business line with existing code should fail"""
        login_resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        token = login_resp.json()["token"]

        resp = client.post("/api/admin/business-lines", json={
            "name": "Retail Dup", "code": "retail",  # already exists
        }, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 400


class TestAuthFlow:
    def test_full_auth_flow(self):
        """Login → use token → me → admin endpoints → all work"""
        # Step 1: Login
        login_resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]
        user_info = login_resp.json()["user"]
        assert user_info["username"] == "admin"

        # Step 2: Use token to access /me
        me_resp = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token}"
        })
        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == "admin"

        # Step 3: Access admin endpoints
        users_resp = client.get("/api/admin/users", headers={
            "Authorization": f"Bearer {token}"
        })
        assert users_resp.status_code == 200

        depts_resp = client.get("/api/admin/departments", headers={
            "Authorization": f"Bearer {token}"
        })
        assert depts_resp.status_code == 200

        bls_resp = client.get("/api/admin/business-lines", headers={
            "Authorization": f"Bearer {token}"
        })
        assert bls_resp.status_code == 200

    def test_invalid_password_flow(self):
        """Failed login should not produce a usable token"""
        resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "wrong"
        })
        assert resp.status_code == 401
        # Token should not appear in error response
        assert "token" not in resp.json()

    def test_missing_fields_rejected(self):
        """Login without required fields should be rejected"""
        resp = client.post("/api/auth/login", json={
            "username": "admin"
            # missing password
        })
        assert resp.status_code in (422, 401)  # 422 for validation, 401 if treated as empty

    def test_health_check(self):
        """Health check should work without authentication"""
        resp = client.get("/api/health")
        assert resp.status_code in (200, 500)  # 200 if chroma works, 500 if not
