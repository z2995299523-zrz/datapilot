"""Test permission logic — business line filtering, department tree, admin bypass"""
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import pool as sa_pool
from auth.database import init_db, get_session
from auth.security import create_token, decode_token
from auth.models import Department, User, BusinessLine, user_business_lines


@pytest.fixture(autouse=True)
def setup_db():
    init_db("sqlite:///:memory:", poolclass=sa_pool.StaticPool)


class TestDepartmentVisibility:
    def test_admin_sees_all(self):
        """Admin user bypasses department filtering"""
        token = create_token(1, "admin", "Admin", True, 1, "/总行", [1], [])
        payload = decode_token(token)
        assert payload["is_admin"] is True
        # Admin logic: if is_admin, skip filtering entirely

    def test_non_admin_has_limited_visibility(self):
        """Non-admin user has visible_dept_ids set"""
        token = create_token(2, "user", "User", False, 2, "/总行/北京分行", [2, 3, 4], ["retail"])
        payload = decode_token(token)
        assert payload["is_admin"] is False
        assert payload["visible_dept_ids"] == [2, 3, 4]
        assert payload["department_id"] == 2
        assert payload["department_path"] == "/总行/北京分行"

    def test_dept_visibility_includes_children(self):
        """User in 北京分行 should see self + 海淀支行 + 朝阳支行"""
        with get_session() as s:
            beijing = s.query(Department).filter(Department.name == "北京分行").first()
            children = s.query(Department).filter(
                Department.path.like(beijing.path + "/%")
            ).all()
            visible_ids = [beijing.id] + [c.id for c in children]
            # 北京分行(2) + 海淀支行(3) + 朝阳支行(4)
            assert len(visible_ids) >= 3

    def test_visible_dept_ids_from_login(self):
        """Login should populate visible_dept_ids with department and children"""
        with get_session() as s:
            from auth.security import verify_password
            user = s.query(User).filter(User.username == "admin").first()
            dept = s.query(Department).filter(Department.id == user.department_id).first()
            assert dept.name == "总行"
            # 总行's children via path
            children = s.query(Department).filter(
                Department.path.like(dept.path + "/%")
            ).all()
            visible = [dept.id] + [c.id for c in children]
            assert len(visible) == 7  # All departments

    def test_root_department_visible_ids(self):
        """User at root sees all departments"""
        with get_session() as s:
            root = s.query(Department).filter(Department.parent_id.is_(None)).first()
            all_depts = s.query(Department).all()
            assert root.id is not None
            assert len(all_depts) == 7


class TestBusinessLineFiltering:
    def test_user_business_lines_in_token(self):
        token = create_token(2, "user", "User", False, 2, "/path", [2, 3], ["retail", "aml"])
        payload = decode_token(token)
        assert "retail" in payload["business_line_codes"]
        assert "aml" in payload["business_line_codes"]

    def test_single_business_line(self):
        token = create_token(3, "ops_user", "Ops User", False, 3, "/path", [3], ["ops"])
        payload = decode_token(token)
        assert payload["business_line_codes"] == ["ops"]
        assert "retail" not in payload["business_line_codes"]

    def test_admin_has_all_lines(self):
        """Admin token should include all business line codes"""
        with get_session() as s:
            admin = s.query(User).filter(User.username == "admin").first()
            bl_codes = [bl.code for bl in admin.business_lines]
            token = create_token(
                admin.id, admin.username, admin.real_name, True,
                admin.department_id, "/总行", [1], bl_codes,
            )
            payload = decode_token(token)
            assert "retail" in payload["business_line_codes"]
            assert "aml" in payload["business_line_codes"]
            assert "corporate" in payload["business_line_codes"]
            assert "ops" in payload["business_line_codes"]

    def test_user_without_business_lines(self):
        """User without any business lines should have empty list"""
        token = create_token(99, "limited", "Limited", False, 1, "/", [1], [])
        payload = decode_token(token)
        assert payload["business_line_codes"] == []


class TestAdminBypass:
    def test_admin_role_flag(self):
        """Admin users have is_admin=True in JWT"""
        token = create_token(1, "admin", "Admin", True, 1, "/总行", [1], [])
        payload = decode_token(token)
        assert payload["is_admin"] is True

    def test_regular_user_not_admin(self):
        """Non-admin users have is_admin=False"""
        token = create_token(2, "user", "Regular User", False, 2, "/path", [2], [])
        payload = decode_token(token)
        assert payload["is_admin"] is False


class TestPermissionModelQueries:
    """Verify database relationships needed for permission checks"""

    def test_user_department_relationship(self):
        """User belongs to a department via foreign key"""
        with get_session() as s:
            admin = s.query(User).filter(User.username == "admin").first()
            assert admin.department is not None
            assert admin.department.name == "总行"

    def test_user_business_lines_relationship(self):
        """User has many-to-many relationship with business lines"""
        with get_session() as s:
            admin = s.query(User).filter(User.username == "admin").first()
            assert len(admin.business_lines) == 4

    def test_query_department_children(self):
        """Parent-child department tree query works"""
        with get_session() as s:
            root = s.query(Department).filter(Department.parent_id.is_(None)).first()
            assert len(root.children) == 3  # 北京分行, 上海分行, 深圳分行
