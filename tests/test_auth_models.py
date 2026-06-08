"""Test auth ORM models — CRUD, department tree, constraints"""
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import pool as sa_pool
from auth.database import init_db, get_session
from auth.models import User, Department, BusinessLine, TableDeptColumn
from auth.security import hash_password


@pytest.fixture(autouse=True)
def setup_db():
    """Use in-memory SQLite for tests (StaticPool shares one connection across sessions)"""
    init_db("sqlite:///:memory:", poolclass=sa_pool.StaticPool)


class TestDepartmentTree:
    def test_seed_creates_departments(self):
        with get_session() as s:
            depts = s.query(Department).all()
            # 总行 + 北京分行 + 海淀支行 + 朝阳支行 + 上海分行 + 浦东支行 + 深圳分行 = 7
            assert len(depts) >= 7

    def test_seed_root_department(self):
        with get_session() as s:
            root = s.query(Department).filter(Department.parent_id.is_(None)).first()
            assert root is not None
            assert root.name == "总行"
            assert root.path == "/总行"
            assert root.level == 0

    def test_materialized_path_query_finds_children(self):
        """path LIKE prefix finds all descendants"""
        with get_session() as s:
            beijing = s.query(Department).filter(Department.name == "北京分行").first()
            assert beijing is not None
            children = s.query(Department).filter(
                Department.path.like(beijing.path + "/%")
            ).all()
            assert len(children) >= 2  # 海淀支行, 朝阳支行

    def test_department_parent_relationship(self):
        with get_session() as s:
            hd = s.query(Department).filter(Department.name == "海淀支行").first()
            assert hd is not None
            assert hd.parent is not None
            assert hd.parent.name == "北京分行"

    def test_unique_path_constraint(self):
        """Duplicate path should be rejected"""
        import sqlalchemy.exc
        with get_session() as s:
            dup = Department(name="Duplicate", path="/总行", level=0)
            s.add(dup)
            with pytest.raises((sqlalchemy.exc.IntegrityError, Exception)):
                s.commit()

    def test_department_levels_correct(self):
        with get_session() as s:
            root = s.query(Department).filter(Department.name == "总行").first()
            leaf = s.query(Department).filter(Department.name == "浦东支行").first()
            assert root.level == 0
            assert leaf.level == 2


class TestUserCRUD:
    def test_seed_creates_admin(self):
        with get_session() as s:
            admin = s.query(User).filter(User.username == "admin").first()
            assert admin is not None
            assert admin.is_admin == 1

    def test_admin_password_verifies(self):
        with get_session() as s:
            admin = s.query(User).filter(User.username == "admin").first()
            from auth.security import verify_password
            assert verify_password("admin123", admin.password_hash)

    def test_create_user(self):
        with get_session() as s:
            dept = s.query(Department).first()
            user = User(
                username="testuser", password_hash=hash_password("pass"),
                real_name="Test", department_id=dept.id, is_admin=0,
            )
            s.add(user)
            s.commit()
            assert user.id is not None

    def test_create_user_without_department(self):
        """Department_id can be null"""
        with get_session() as s:
            user = User(
                username="nodepartment", password_hash=hash_password("pass"),
                real_name="No Dept", department_id=None, is_admin=0,
            )
            s.add(user)
            s.commit()
            assert user.id is not None

    def test_unique_username(self):
        with get_session() as s:
            dept = s.query(Department).first()
            s.add(User(username="unique", password_hash="x", real_name="U1", department_id=dept.id))
            s.commit()
            s.add(User(username="unique", password_hash="x", real_name="U2", department_id=dept.id))
            import sqlalchemy.exc
            with pytest.raises((sqlalchemy.exc.IntegrityError, Exception)):
                s.commit()

    def test_read_user(self):
        """Query a user by id returns correct fields"""
        with get_session() as s:
            dept = s.query(Department).first()
            s.add(User(username="readtest", password_hash="h", real_name="Reader",
                       department_id=dept.id, is_admin=0))
            s.commit()
            user = s.query(User).filter(User.username == "readtest").first()
            assert user.real_name == "Reader"
            assert user.is_admin == 0
            assert user.is_active == 1  # default

    def test_delete_user_cascade(self):
        """Deleting a user should not cascade to department"""
        with get_session() as s:
            dept = s.query(Department).first()
            user = User(username="deleteme", password_hash="h", real_name="Del",
                        department_id=dept.id)
            s.add(user)
            s.commit()
            s.delete(user)
            s.commit()
            # Department should still exist
            assert s.query(Department).filter(Department.id == dept.id).count() == 1


class TestBusinessLine:
    def test_seed_creates_lines(self):
        with get_session() as s:
            lines = s.query(BusinessLine).all()
            codes = {bl.code for bl in lines}
            assert "retail" in codes
            assert "aml" in codes
            assert "corporate" in codes
            assert "ops" in codes

    def test_unique_code_constraint(self):
        import sqlalchemy.exc
        with get_session() as s:
            s.add(BusinessLine(name="Dup", code="retail"))
            with pytest.raises((sqlalchemy.exc.IntegrityError, Exception)):
                s.commit()

    def test_admin_has_all_business_lines(self):
        """Admin user should be assigned all business lines"""
        with get_session() as s:
            admin = s.query(User).filter(User.username == "admin").first()
            assert admin is not None
            codes = {bl.code for bl in admin.business_lines}
            assert "retail" in codes
            assert "corporate" in codes
            assert "aml" in codes
            assert "ops" in codes


class TestTableDeptColumn:
    def test_empty_on_seed(self):
        """TableDeptColumn should be empty after seed (no mappings defined)"""
        with get_session() as s:
            mappings = s.query(TableDeptColumn).all()
            assert len(mappings) == 0

    def test_create_mapping(self):
        with get_session() as s:
            mapping = TableDeptColumn(table_name="dm_customer_active", dept_column="branch_code")
            s.add(mapping)
            s.commit()
            result = s.query(TableDeptColumn).filter(
                TableDeptColumn.table_name == "dm_customer_active"
            ).first()
            assert result is not None
            assert result.dept_column == "branch_code"
