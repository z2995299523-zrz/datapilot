"""Database initialization, session management, and seed data."""
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from auth.models import Base

_engine = None
_SessionLocal = None


def init_db(db_url: str = "sqlite:///data/auth.db") -> None:
    """Create tables and seed data. Idempotent — skips if tables exist."""
    global _engine, _SessionLocal
    import os
    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)
    _engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine)
    # Seed only if no users exist
    with _SessionLocal() as session:
        from auth.models import User
        from auth.security import hash_password
        if session.query(User).count() == 0:
            _seed(session, hash_password)


def get_session() -> Session:
    """Get a new database session. Raises RuntimeError if init_db wasn't called."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _SessionLocal()


def _seed(session: Session, hash_pw) -> None:
    """Write default departments, business lines, and admin user."""
    from auth.models import Department, BusinessLine, User

    # Department tree
    root = Department(name="总行", parent_id=None, path="/总行", level=0, is_active=1)
    bj = Department(name="北京分行", parent_id=None, path="/总行/北京分行", level=1, is_active=1)
    hd = Department(name="海淀支行", parent_id=None, path="/总行/北京分行/海淀支行", level=2, is_active=1)
    cy = Department(name="朝阳支行", parent_id=None, path="/总行/北京分行/朝阳支行", level=2, is_active=1)
    sh = Department(name="上海分行", parent_id=None, path="/总行/上海分行", level=1, is_active=1)
    pd = Department(name="浦东支行", parent_id=None, path="/总行/上海分行/浦东支行", level=2, is_active=1)
    sz = Department(name="深圳分行", parent_id=None, path="/总行/深圳分行", level=1, is_active=1)
    session.add_all([root, bj, hd, cy, sh, pd, sz])
    session.flush()
    # Set parent_ids after flush (ids now available)
    bj.parent_id = root.id
    hd.parent_id = bj.id
    cy.parent_id = bj.id
    sh.parent_id = root.id
    pd.parent_id = sh.id
    sz.parent_id = root.id

    # Business lines
    retail = BusinessLine(name="零售银行", code="retail", description="个人零售银行业务")
    corporate = BusinessLine(name="对公银行", code="corporate", description="企业公司银行业务")
    aml = BusinessLine(name="AML反洗钱", code="aml", description="反洗钱监控分析")
    ops = BusinessLine(name="运营管理", code="ops", description="运营数据分析")
    session.add_all([retail, corporate, aml, ops])
    session.flush()

    # Admin user
    admin_user = User(
        username="admin",
        password_hash=hash_pw("admin123"),
        real_name="系统管理员",
        department_id=root.id,
        is_admin=1,
        is_active=1,
    )
    session.add(admin_user)
    # Assign all business lines to admin
    admin_user.business_lines = [retail, corporate, aml, ops]
    session.commit()
