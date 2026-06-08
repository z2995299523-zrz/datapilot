"""Test auth API endpoints with FastAPI TestClient"""
import sys
import pytest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Mock BGE embedding to avoid model download/loading during backend.main import
with mock.patch("embedding.get_embedding_model"):
    from backend.main import app

# Override database with in-memory SQLite for testing
# (must be after backend.main import, which calls init_db() with default file URL)
from sqlalchemy import pool as sa_pool
from auth.database import init_db
init_db("sqlite:///:memory:", poolclass=sa_pool.StaticPool)

from fastapi.testclient import TestClient

client = TestClient(app)


class TestLoginEndpoint:
    def test_login_success(self):
        resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["username"] == "admin"
        assert data["user"]["is_admin"] is True
        assert data["user"]["real_name"] == "系统管理员"

    def test_login_returns_user_info(self):
        """Login response should contain full user info with permissions"""
        resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        data = resp.json()
        user = data["user"]
        assert "user_id" in user
        assert user["username"] == "admin"
        assert user["is_admin"] is True
        assert isinstance(user["visible_dept_ids"], list)
        assert isinstance(user["business_line_codes"], list)
        # Admin should have all business lines
        assert "retail" in user["business_line_codes"]

    def test_login_wrong_password(self):
        resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "wrongpassword"
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self):
        resp = client.post("/api/auth/login", json={
            "username": "noone", "password": "whatever"
        })
        assert resp.status_code == 401

    def test_login_empty_username(self):
        resp = client.post("/api/auth/login", json={
            "username": "", "password": "admin123"
        })
        assert resp.status_code == 401


class TestMeEndpoint:
    def test_me_with_valid_token(self):
        # Login first
        login_resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        token = login_resp.json()["token"]

        resp = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token}"
        })
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin"

    def test_me_returns_permissions(self):
        """Me endpoint should return full permission info for page refresh recovery"""
        login_resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        token = login_resp.json()["token"]

        resp = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token}"
        })
        data = resp.json()
        assert data["username"] == "admin"
        assert data["is_admin"] is True
        assert "visible_dept_ids" in data
        assert "business_line_codes" in data
        assert "department_path" in data

    def test_me_without_token(self):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token(self):
        resp = client.get("/api/auth/me", headers={
            "Authorization": "Bearer invalid.token.here"
        })
        assert resp.status_code == 401

    def test_me_with_expired_token(self):
        """An expired JWT should return 401 with appropriate message"""
        import jwt, time
        from auth.security import SECRET_KEY, ALGORITHM

        expired = jwt.encode(
            {"sub": "1", "exp": int(time.time()) - 3600},
            SECRET_KEY, algorithm=ALGORITHM,
        )
        resp = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {expired}"
        })
        assert resp.status_code == 401


class TestProtectedEndpoints:
    def test_analysis_endpoint_requires_auth(self):
        resp = client.post("/api/analysis/full", json={
            "requirement_text": "test", "generate_sql": False
        })
        assert resp.status_code == 401

    def test_admin_list_users_with_admin(self):
        """Admin user can access admin endpoints"""
        login_resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        token = login_resp.json()["token"]
        resp = client.get("/api/admin/users", headers={
            "Authorization": f"Bearer {token}"
        })
        assert resp.status_code == 200

    def test_admin_list_departments(self):
        login_resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        token = login_resp.json()["token"]
        resp = client.get("/api/admin/departments", headers={
            "Authorization": f"Bearer {token}"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 7

    def test_admin_list_business_lines(self):
        login_resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        token = login_resp.json()["token"]
        resp = client.get("/api/admin/business-lines", headers={
            "Authorization": f"Bearer {token}"
        })
        assert resp.status_code == 200
        codes = [bl["code"] for bl in resp.json()]
        assert "retail" in codes
        assert "aml" in codes

    def test_admin_endpoint_without_token(self):
        resp = client.get("/api/admin/users")
        assert resp.status_code == 401

    def test_health_endpoint_no_auth_required(self):
        """Health endpoint should be public"""
        resp = client.get("/api/health")
        # Should return a response (might 200 or 5xx depending on chroma, but not 401)
        assert resp.status_code != 401
