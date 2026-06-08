# 登录与权限控制模块 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从零搭建 JWT 登录认证 + 双维度数据权限控制（部门层级 × 业务条线），覆盖 React 前端 + FastAPI 后端全链路。

**Architecture:** 新建 `auth/` Python 包（SQLAlchemy ORM + bcrypt + JWT），新增 FastAPI 路由（`/api/auth/*` + `/api/admin/*`）和依赖注入（`Depends(get_current_user)`），新增 React 页面（LoginPage + AdminPage）和路由守卫，改造现有检索/SQL 生成链路注入权限过滤。

**Tech Stack:** Python: bcrypt, PyJWT, SQLAlchemy 2.x, FastAPI Depends. Frontend: React 19, Ant Design 6, React Router 7, Axios (已有，无需新增前端依赖).

---

## 任务概览

| # | 任务 | 文件 | 依赖 |
|---|------|------|------|
| 1 | Python auth 基础包 | `auth/` (新建 4 文件) | — |
| 2 | 后端 schemas + JWT 依赖 | `backend/schemas.py`, `backend/auth.py` | 1 |
| 3 | 后端 auth 路由 (login/me) | `backend/routers/auth.py` | 2 |
| 4 | 后端 admin 路由 (CRUD) | `backend/routers/admin.py` | 2 |
| 5 | 后端 main.py + 现有路由改造 | `main.py`, `analysis.py`, 等 | 3, 4 |
| 6 | 前端 API 客户端 (token 拦截器) | `client.ts`, `auth.ts` | — |
| 7 | 前端 AuthContext + LoginPage | `AuthContext.tsx`, `LoginPage.tsx` | 6 |
| 8 | 前端路由守卫 + Layout 改造 | `App.tsx`, `Layout.tsx` | 7 |
| 9 | 前端 AdminPage | `AdminPage.tsx` | 7, 8 |
| 10 | 权限注入：检索 + SQL 生成 | `engine.py`, `script.py` | 1 |
| 11 | 后端分析路由接入权限 | `analysis.py`, `reconciliation.py`, 等 | 5, 10 |
| 12 | 后端 admin API 接入权限 | `admin.py` (路由) | 5 |
| 13 | 测试 | `tests/test_auth_*.py` (5 文件) | 全部 |

---

### Task 1: Python auth 基础包

**目标:** 创建 `auth/` 包 — SQLAlchemy ORM 模型 + 数据库初始化 + 密码/JWT 工具。

**Files:**
- Create: `auth/__init__.py`
- Create: `auth/models.py`
- Create: `auth/database.py`
- Create: `auth/security.py`

- [ ] **Step 1: Create `auth/__init__.py`**

```python
# auth/__init__.py — 认证与权限控制模块
```

- [ ] **Step 2: Create `auth/models.py` — SQLAlchemy ORM 模型**

```python
"""auth ORM 模型 — Department, BusinessLine, User, UserBusinessLine, TableBusinessLine, TableDeptColumn"""
from sqlalchemy import (
    Column, Integer, String, ForeignKey, Table, create_engine, UniqueConstraint,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

# 关联表（多对多）
user_business_lines = Table(
    "user_business_lines",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("business_line_id", Integer, ForeignKey("business_lines.id"), primary_key=True),
)

table_business_lines = Table(
    "table_business_lines",
    Base.metadata,
    Column("table_name", String, ForeignKey("table_dept_columns.table_name"), primary_key=True),
    Column("business_line_id", Integer, ForeignKey("business_lines.id"), primary_key=True),
)


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    path = Column(String, nullable=False, unique=True)
    level = Column(Integer, nullable=False)
    is_active = Column(Integer, default=1)

    parent = relationship("Department", remote_side=[id], backref="children")


class BusinessLine(Base):
    __tablename__ = "business_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    code = Column(String, nullable=False, unique=True)
    description = Column(String, default="")
    is_active = Column(Integer, default=1)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    real_name = Column(String, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    is_admin = Column(Integer, default=0)
    is_active = Column(Integer, default=1)
    created_at = Column(String, default="")

    department = relationship("Department")
    business_lines = relationship("BusinessLine", secondary=user_business_lines)


class TableDeptColumn(Base):
    __tablename__ = "table_dept_columns"

    table_name = Column(String, primary_key=True)
    dept_column = Column(String, nullable=False)
```

- [ ] **Step 3: Create `auth/database.py` — 数据库初始化 + 种子数据**

```python
"""数据库初始化 + 会话管理 + 种子数据"""
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from auth.models import Base

_engine = None
_SessionLocal = None


def init_db(db_url: str = "sqlite:///data/auth.db") -> None:
    """建表 + 种子数据。幂等 — 表已存在则跳过。"""
    global _engine, _SessionLocal
    _engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine)

    # 种子数据
    with _SessionLocal() as session:
        from auth.security import hash_password
        # 仅当无用户时写入种子数据
        from auth.models import User
        if session.query(User).count() == 0:
            _seed(session, hash_password)


def get_session() -> Session:
    """获取数据库会话（FastAPI 依赖注入用）"""
    if _SessionLocal is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")
    return _SessionLocal()


def _seed(session: Session, hash_pw) -> None:
    """写入默认部门、条线、admin 用户"""
    from auth.models import Department, BusinessLine, User

    # 部门树
    root = Department(name="总行", parent_id=None, path="/总行", level=0, is_active=1)
    bj = Department(name="北京分行", parent_id=None, path="/总行/北京分行", level=1, is_active=1)
    hd = Department(name="海淀支行", parent_id=None, path="/总行/北京分行/海淀支行", level=2, is_active=1)
    sh = Department(name="上海分行", parent_id=None, path="/总行/上海分行", level=1, is_active=1)
    sz = Department(name="深圳分行", parent_id=None, path="/总行/深圳分行", level=1, is_active=1)
    session.add_all([root, bj, hd, sh, sz])
    session.flush()

    # 关联 parent_id（flush 后 id 可用）
    bj.parent_id = root.id
    hd.parent_id = bj.id
    sh.parent_id = root.id
    sz.parent_id = root.id

    # 业务条线
    retail = BusinessLine(name="零售银行", code="retail", description="个人零售银行业务")
    corporate = BusinessLine(name="对公银行", code="corporate", description="企业公司银行业务")
    aml = BusinessLine(name="AML反洗钱", code="aml", description="反洗钱监控分析")
    ops = BusinessLine(name="运营管理", code="ops", description="运营数据分析")
    session.add_all([retail, corporate, aml, ops])
    session.flush()

    # 管理员
    admin_user = User(
        username="admin",
        password_hash=hash_pw("admin123"),
        real_name="系统管理员",
        department_id=root.id,
        is_admin=1,
        is_active=1,
    )
    session.add(admin_user)
    session.commit()
```

- [ ] **Step 4: Create `auth/security.py` — 密码哈希 + JWT 工具**

```python
"""密码哈希 + JWT 签发/校验"""
import bcrypt
import jwt
import time

SECRET_KEY = "datapilot-secret-change-in-production"
ALGORITHM = "HS256"
TOKEN_EXPIRE_SECONDS = 8 * 3600  # 8 小时


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_token(user_id: int, username: str, real_name: str,
                 is_admin: bool, department_id: int, department_path: str,
                 visible_dept_ids: list[int], business_line_codes: list[str]) -> str:
    """签发 JWT，payload 包含完整权限信息"""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "username": username,
        "real_name": real_name,
        "is_admin": is_admin,
        "department_id": department_id,
        "department_path": department_path,
        "visible_dept_ids": visible_dept_ids,
        "business_line_codes": business_line_codes,
        "iat": now,
        "exp": now + TOKEN_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """校验 JWT，返回 payload。异常抛给调用方。"""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
```

- [ ] **Step 5: Run quick verification**

```bash
python -c "from auth.database import init_db; init_db(); print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add auth/__init__.py auth/models.py auth/database.py auth/security.py
git commit -m "feat(auth): add auth base package — ORM models, database init, bcrypt/JWT"
```

---

### Task 2: 后端 schemas + JWT 依赖

**目标:** 在 `backend/schemas.py` 中新增认证相关 Pydantic schema，创建 `backend/auth.py` FastAPI 依赖。

**Files:**
- Modify: `backend/schemas.py`
- Create: `backend/auth.py`

- [ ] **Step 1: Add auth schemas to `backend/schemas.py`**

在现有 `schemas.py` 文件末尾追加：

```python
# ── 认证 ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class UserInfo(BaseModel):
    """当前用户信息（含权限）"""
    user_id: int
    username: str
    real_name: str
    is_admin: bool
    department_id: int | None = None
    department_path: str = ""
    visible_dept_ids: list[int] = []
    business_line_codes: list[str] = []


class LoginResponse(BaseModel):
    """登录响应"""
    token: str
    user: UserInfo


class AdminUserCreate(BaseModel):
    """创建用户请求"""
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6)
    real_name: str = Field(..., min_length=1)
    department_id: int
    business_line_ids: list[int] = []
    is_admin: bool = False


class AdminUserUpdate(BaseModel):
    """修改用户请求"""
    real_name: str | None = None
    department_id: int | None = None
    business_line_ids: list[int] | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
    new_password: str | None = Field(None, min_length=6)


class AdminDepartmentCreate(BaseModel):
    name: str = Field(..., min_length=1)
    parent_id: int | None = None


class AdminBusinessLineCreate(BaseModel):
    name: str = Field(..., min_length=1)
    code: str = Field(..., min_length=2, max_length=30)
    description: str = ""


class AdminTableLineMapping(BaseModel):
    table_name: str
    business_line_id: int
```

- [ ] **Step 2: Create `backend/auth.py` — FastAPI 依赖注入**

```python
"""FastAPI 认证依赖 — get_current_user, require_admin"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

from auth.security import decode_token, SECRET_KEY, ALGORITHM

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """从 JWT 提取当前用户权限。无 token → 401。"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
        )
    try:
        return decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证信息",
        )


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """仅 admin 可访问。非 admin → 403。"""
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict | None:
    """可选认证 — 无 token 时返回 None（用于公开端点或 CLI 兼容）。"""
    if credentials is None:
        return None
    try:
        return decode_token(credentials.credentials)
    except jwt.InvalidTokenError:
        return None
```

- [ ] **Step 3: Verify imports work**

```bash
python -c "from backend.auth import get_current_user, require_admin; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add backend/schemas.py backend/auth.py
git commit -m "feat(auth): add backend auth schemas + FastAPI JWT dependency"
```

---

### Task 3: 后端 auth 路由 (login/me)

**目标:** 创建 `POST /api/auth/login` 和 `GET /api/auth/me` 两个端点。

**Files:**
- Create: `backend/routers/auth.py`

- [ ] **Step 1: Create `backend/routers/auth.py`**

```python
"""认证路由 — login / me"""
from fastapi import APIRouter, Depends, HTTPException, status

from backend.schemas import LoginRequest, LoginResponse, UserInfo
from backend.auth import get_current_user
from auth.database import get_session
from auth.security import verify_password, create_token
from auth.models import User, Department

router = APIRouter(prefix="/api/auth", tags=["认证"])


def _get_visible_dept_ids(session, department_id: int | None) -> list[int]:
    """获取部门及所有子部门 ID 列表"""
    if department_id is None:
        return []
    from auth.models import Department as Dept
    dept = session.query(Dept).filter(Dept.id == department_id).first()
    if not dept:
        return []
    children = session.query(Dept).filter(
        Dept.path.like(dept.path + "/%")
    ).all()
    return [dept.id] + [c.id for c in children]


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """用户名+密码 → JWT token"""
    with get_session() as session:
        user = session.query(User).filter(
            User.username == req.username
        ).first()

        if not user or not verify_password(req.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="账号已被禁用",
            )

        # 检查部门是否启用
        dept_path = ""
        visible_dept_ids: list[int] = []
        if user.department_id:
            dept = session.query(Department).filter(
                Department.id == user.department_id
            ).first()
            if dept and not dept.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="部门已停用，请联系管理员",
                )
            if dept:
                dept_path = dept.path
                visible_dept_ids = _get_visible_dept_ids(session, user.department_id)

        # 业务条线
        business_line_codes = [
            bl.code for bl in user.business_lines if bl.is_active
        ]

        token = create_token(
            user_id=user.id,
            username=user.username,
            real_name=user.real_name,
            is_admin=bool(user.is_admin),
            department_id=user.department_id or 0,
            department_path=dept_path,
            visible_dept_ids=visible_dept_ids,
            business_line_codes=business_line_codes,
        )

        return LoginResponse(
            token=token,
            user=UserInfo(
                user_id=user.id,
                username=user.username,
                real_name=user.real_name,
                is_admin=bool(user.is_admin),
                department_id=user.department_id,
                department_path=dept_path,
                visible_dept_ids=visible_dept_ids,
                business_line_codes=business_line_codes,
            ),
        )


@router.get("/me", response_model=UserInfo)
async def me(user: dict = Depends(get_current_user)):
    """返回当前登录用户的权限信息（刷新页面时恢复状态用）"""
    return UserInfo(
        user_id=user["sub"],
        username=user["username"],
        real_name=user["real_name"],
        is_admin=user["is_admin"],
        department_id=user.get("department_id"),
        department_path=user.get("department_path", ""),
        visible_dept_ids=user.get("visible_dept_ids", []),
        business_line_codes=user.get("business_line_codes", []),
    )
```

- [ ] **Step 2: Commit**

```bash
git add backend/routers/auth.py
git commit -m "feat(auth): add /api/auth/login and /api/auth/me endpoints"
```

---

### Task 4: 后端 admin 路由 (CRUD)

**目标:** 创建 `/api/admin/*` 管理端点 — 用户/部门/条线/表映射的 CRUD。

**Files:**
- Create: `backend/routers/admin.py`

- [ ] **Step 1: Create `backend/routers/admin.py`**

```python
"""管理员路由 — 用户/部门/条线/表映射 CRUD"""
from fastapi import APIRouter, Depends, HTTPException, status

from backend.schemas import (
    AdminUserCreate, AdminUserUpdate, AdminDepartmentCreate,
    AdminBusinessLineCreate, AdminTableLineMapping,
)
from backend.auth import require_admin
from auth.database import get_session
from auth.security import hash_password
from auth.models import User, Department, BusinessLine, TableDeptColumn

router = APIRouter(prefix="/api/admin", tags=["系统管理"])


# ── 用户管理 ──

@router.get("/users")
async def list_users(_admin: dict = Depends(require_admin)):
    with get_session() as session:
        users = session.query(User).all()
        return [
            {
                "id": u.id, "username": u.username, "real_name": u.real_name,
                "department_id": u.department_id,
                "department_name": u.department.name if u.department else "",
                "is_admin": bool(u.is_admin), "is_active": bool(u.is_active),
                "business_line_ids": [bl.id for bl in u.business_lines],
                "created_at": u.created_at,
            }
            for u in users
        ]


@router.post("/users")
async def create_user(req: AdminUserCreate, _admin: dict = Depends(require_admin)):
    with get_session() as session:
        existing = session.query(User).filter(User.username == req.username).first()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")
        dept = session.query(Department).filter(Department.id == req.department_id).first()
        if not dept:
            raise HTTPException(status_code=400, detail="部门不存在")

        user = User(
            username=req.username,
            password_hash=hash_password(req.password),
            real_name=req.real_name,
            department_id=req.department_id,
            is_admin=1 if req.is_admin else 0,
            is_active=1,
        )
        if req.business_line_ids:
            bls = session.query(BusinessLine).filter(
                BusinessLine.id.in_(req.business_line_ids)
            ).all()
            user.business_lines = bls
        session.add(user)
        session.commit()
        return {"id": user.id, "username": user.username}


@router.put("/users/{user_id}")
async def update_user(user_id: int, req: AdminUserUpdate,
                      _admin: dict = Depends(require_admin)):
    with get_session() as session:
        user = session.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        if req.real_name is not None:
            user.real_name = req.real_name
        if req.department_id is not None:
            user.department_id = req.department_id
        if req.is_admin is not None:
            user.is_admin = 1 if req.is_admin else 0
        if req.is_active is not None:
            user.is_active = 1 if req.is_active else 0
        if req.new_password:
            user.password_hash = hash_password(req.new_password)
        if req.business_line_ids is not None:
            bls = session.query(BusinessLine).filter(
                BusinessLine.id.in_(req.business_line_ids)
            ).all()
            user.business_lines = bls
        session.commit()
        return {"id": user.id, "updated": True}


# ── 部门管理 ──

@router.get("/departments")
async def list_departments(_admin: dict = Depends(require_admin)):
    with get_session() as session:
        depts = session.query(Department).order_by(Department.path).all()
        return [
            {
                "id": d.id, "name": d.name, "parent_id": d.parent_id,
                "path": d.path, "level": d.level,
                "is_active": bool(d.is_active),
            }
            for d in depts
        ]


@router.post("/departments")
async def create_department(req: AdminDepartmentCreate,
                            _admin: dict = Depends(require_admin)):
    with get_session() as session:
        if req.parent_id:
            parent = session.query(Department).filter(
                Department.id == req.parent_id
            ).first()
            if not parent:
                raise HTTPException(status_code=400, detail="父部门不存在")
            path = parent.path + "/" + req.name
            level = parent.level + 1
        else:
            path = "/" + req.name
            level = 0

        existing = session.query(Department).filter(Department.path == path).first()
        if existing:
            raise HTTPException(status_code=400, detail="部门路径已存在")

        dept = Department(name=req.name, parent_id=req.parent_id,
                          path=path, level=level)
        session.add(dept)
        session.commit()
        return {"id": dept.id, "path": dept.path}


@router.put("/departments/{dept_id}")
async def update_department(dept_id: int, req: dict,
                            _admin: dict = Depends(require_admin)):
    with get_session() as session:
        dept = session.query(Department).filter(Department.id == dept_id).first()
        if not dept:
            raise HTTPException(status_code=404, detail="部门不存在")
        if "name" in req:
            dept.name = req["name"]
        if "is_active" in req:
            dept.is_active = 1 if req["is_active"] else 0
        session.commit()
        return {"id": dept.id, "updated": True}


# ── 业务条线管理 ──

@router.get("/business-lines")
async def list_business_lines(_admin: dict = Depends(require_admin)):
    with get_session() as session:
        bls = session.query(BusinessLine).all()
        return [
            {"id": bl.id, "name": bl.name, "code": bl.code,
             "description": bl.description, "is_active": bool(bl.is_active)}
            for bl in bls
        ]


@router.post("/business-lines")
async def create_business_line(req: AdminBusinessLineCreate,
                               _admin: dict = Depends(require_admin)):
    with get_session() as session:
        existing = session.query(BusinessLine).filter(
            BusinessLine.code == req.code
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="条线代码已存在")
        bl = BusinessLine(name=req.name, code=req.code, description=req.description)
        session.add(bl)
        session.commit()
        return {"id": bl.id, "code": bl.code}


# ── 表-条线映射 ──

@router.get("/table-line-mappings")
async def list_table_line_mappings(_admin: dict = Depends(require_admin)):
    with get_session() as session:
        from auth.models import table_business_lines as tbl
        rows = session.query(tbl).all()
        return [{"table_name": r.table_name, "business_line_id": r.business_line_id}
                for r in rows]


@router.post("/table-line-mappings")
async def add_table_line_mapping(req: AdminTableLineMapping,
                                 _admin: dict = Depends(require_admin)):
    with get_session() as session:
        bl = session.query(BusinessLine).filter(
            BusinessLine.id == req.business_line_id
        ).first()
        if not bl:
            raise HTTPException(status_code=400, detail="条线不存在")
        session.execute(
            table_business_lines.insert().values(
                table_name=req.table_name,
                business_line_id=req.business_line_id,
            ).prefix_with("OR IGNORE")
        )
        session.commit()
        return {"table_name": req.table_name, "business_line_id": req.business_line_id}


@router.delete("/table-line-mappings/{table_name}/{business_line_id}")
async def remove_table_line_mapping(table_name: str, business_line_id: int,
                                    _admin: dict = Depends(require_admin)):
    with get_session() as session:
        from auth.models import table_business_lines as tbl
        session.execute(
            tbl.delete().where(
                (tbl.c.table_name == table_name) &
                (tbl.c.business_line_id == business_line_id)
            )
        )
        session.commit()
        return {"deleted": True}
```

- [ ] **Step 2: Commit**

```bash
git add backend/routers/admin.py
git commit -m "feat(auth): add /api/admin/* CRUD endpoints for user/dept/line/table management"
```

---

### Task 5: 后端 main.py + 现有路由改造

**目标:** 注册新路由到 FastAPI app，给现有分析/建模/修复路由加 `Depends(get_current_user)`。

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/routers/analysis.py`
- Modify: `backend/routers/reconciliation.py`
- Modify: `backend/routers/dictionary.py`
- Modify: `backend/routers/modeling.py`

- [ ] **Step 1: Update `backend/main.py` — 注册路由 + 初始化 auth 数据库**

```python
# 在 app 创建前（get_embedding_model() 之后）加：
from auth.database import init_db
init_db()

# 在 include_router 块加：
from backend.routers import auth, admin
app.include_router(auth.router)
app.include_router(admin.router)
```

- [ ] **Step 2: Update `backend/routers/analysis.py` — 加认证依赖**

在文件顶部 import 加：
```python
from backend.auth import get_current_user
```

修改 `analyze_full` 函数签名：
```python
@router.post("/full")
async def analyze_full(req: AnalysisRequest,
                       user: dict = Depends(get_current_user)):
```

修改 `compare_expected` 函数签名：
```python
@router.post("/compare")
async def compare_expected(req: dict,
                           user: dict = Depends(get_current_user)):
```

- [ ] **Step 3: Update `backend/routers/reconciliation.py`**

同模式：文件顶部加 `from backend.auth import get_current_user`，两个路由函数签名加 `user: dict = Depends(get_current_user)`。

- [ ] **Step 4: Update `backend/routers/dictionary.py`**

```python
# upload 加认证
@router.post("/upload")
async def upload_dictionary(..., user: dict = Depends(get_current_user)):
    ...

# status 和 preview 保持公开（健康检查类端点无需认证）
```

- [ ] **Step 5: Update `backend/routers/modeling.py`**

所有端点加 `user: dict = Depends(get_current_user)`。

- [ ] **Step 6: Install new Python dependencies**

```bash
pip install bcrypt>=4.1.0 PyJWT>=2.10.0
```

更新 `requirements.txt`:
```
bcrypt>=4.1.0
PyJWT>=2.10.0
```

- [ ] **Step 8: Start server and verify**

```bash
python -m uvicorn backend.main:app --port 8000
```
访问 `http://localhost:8000/docs`，确认 `/api/auth/*` 和 `/api/admin/*` 出现在 Swagger 文档中，`/api/analysis/full` 有锁图标（需要认证）。

- [ ] **Step 7: Commit**

```bash
git add backend/main.py backend/routers/analysis.py backend/routers/reconciliation.py backend/routers/dictionary.py backend/routers/modeling.py
git commit -m "feat(auth): register auth/admin routers + add get_current_user to all protected endpoints"
```

---

### Task 6: 前端 API 客户端 (token 拦截器)

**目标:** 改造 Axios 实例自动附加 JWT token，401 自动跳转登录页。

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/api/auth.ts`

- [ ] **Step 1: Update `frontend/src/api/client.ts` — 加 request/response 拦截器**

```typescript
/**
 * Axios 实例 — baseURL、超时、JWT token、401 处理
 */
import axios from 'axios';

const API_BASE = 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 180_000,
  headers: { 'Content-Type': 'application/json' },
});

// Request interceptor: 附加 JWT token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor: 401 → 清 token → 跳转登录
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      // 不在登录页时跳转
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    } else if (error.code === 'ECONNABORTED') {
      console.error('请求超时');
    } else if (!error.response) {
      console.error('无法连接后端服务');
    }
    return Promise.reject(error);
  },
);
```

- [ ] **Step 2: Create `frontend/src/api/auth.ts` — 登录/获取当前用户 API**

```typescript
import { api } from './client';

interface LoginParams {
  username: string;
  password: string;
}

interface UserInfo {
  user_id: number;
  username: string;
  real_name: string;
  is_admin: boolean;
  department_id: number | null;
  department_path: string;
  visible_dept_ids: number[];
  business_line_codes: string[];
}

interface LoginResult {
  token: string;
  user: UserInfo;
}

export const authApi = {
  login: (params: LoginParams) =>
    api.post<LoginResult>('/api/auth/login', params),

  me: () =>
    api.get<UserInfo>('/api/auth/me'),
};
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/auth.ts
git commit -m "feat(auth): add JWT interceptor to Axios + auth API module"
```

---

### Task 7: 前端 AuthContext + LoginPage

**目标:** 创建 React Context 管理认证状态，创建登录页面。

**Files:**
- Create: `frontend/src/auth/AuthContext.tsx`
- Create: `frontend/src/pages/LoginPage.tsx`

- [ ] **Step 1: Create `frontend/src/auth/AuthContext.tsx`**

```tsx
import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import { authApi } from '../api/auth';

interface UserInfo {
  user_id: number;
  username: string;
  real_name: string;
  is_admin: boolean;
  department_id: number | null;
  department_path: string;
  visible_dept_ids: number[];
  business_line_codes: string[];
}

interface AuthState {
  token: string | null;
  user: UserInfo | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  isAdmin: boolean;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(
    () => localStorage.getItem('token')
  );
  const [user, setUser] = useState<UserInfo | null>(() => {
    const saved = localStorage.getItem('user');
    return saved ? JSON.parse(saved) : null;
  });

  const login = useCallback(async (username: string, password: string) => {
    const res = await authApi.login({ username, password });
    const { token, user } = res.data;
    localStorage.setItem('token', token);
    localStorage.setItem('user', JSON.stringify(user));
    setToken(token);
    setUser(user);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        login,
        logout,
        isAdmin: user?.is_admin ?? false,
        isAuthenticated: !!token && !!user,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return ctx;
}
```

- [ ] **Step 2: Create `frontend/src/pages/LoginPage.tsx`**

```tsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Form, Input, Button, Typography, Alert, theme } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import { useAuth } from '../auth/AuthContext';

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { login } = useAuth();
  const navigate = useNavigate();
  const { token: themeToken } = theme.useToken();

  const handleSubmit = async (values: { username: string; password: string }) => {
    setLoading(true);
    setError('');
    try {
      await login(values.username, values.password);
      navigate('/dictionary');
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || '登录失败，请检查用户名和密码';
      setError(detail);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        background: themeToken.colorBgLayout,
      }}
    >
      <Card style={{ width: 400, boxShadow: themeToken.boxShadow }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <span style={{ fontSize: 48 }}>📊</span>
          <Typography.Title level={3} style={{ marginTop: 12, marginBottom: 4 }}>
            DataPilot
          </Typography.Title>
          <Typography.Text type="secondary">
            需求 → SQL 全链路分析引擎
          </Typography.Text>
        </div>

        {error && (
          <Alert
            message={error}
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
          />
        )}

        <Form onFinish={handleSubmit} size="large" autoComplete="off">
          <Form.Item
            name="username"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/auth/AuthContext.tsx frontend/src/pages/LoginPage.tsx
git commit -m "feat(auth): add AuthContext + LoginPage with Ant Design form"
```

---

### Task 8: 前端路由守卫 + Layout 改造

**目标:** 在 App.tsx 中加入 ProtectedRoute/AdminRoute 守卫，Layout.tsx 侧边栏底部显示用户信息和登出按钮。

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Update `frontend/src/App.tsx` — 路由守卫**

```tsx
import { ConfigProvider, theme, App as AntApp } from 'antd';
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { themeConfig } from './theme';
import { AuthProvider, useAuth } from './auth/AuthContext';
import AppLayout from './components/Layout';
import LoginPage from './pages/LoginPage';
import DictionaryPage from './pages/DictionaryPage';
import AnalysisPage from './pages/AnalysisPage';
import ReconciliationPage from './pages/ReconciliationPage';
import ModelingPage from './pages/ModelingPage';

/** 路由守卫：未登录 → /login */
function ProtectedRoute() {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}

/** 管理员路由守卫：非 admin → /dictionary */
function AdminRoute() {
  const { isAdmin } = useAuth();
  if (!isAdmin) {
    return <Navigate to="/dictionary" replace />;
  }
  return <Outlet />;
}

export default function App() {
  return (
    <ConfigProvider theme={{ ...themeConfig, algorithm: theme.darkAlgorithm }}>
      <AntApp>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route element={<ProtectedRoute />}>
                <Route element={<AppLayout />}>
                  <Route index element={<Navigate to="/dictionary" replace />} />
                  <Route path="dictionary" element={<DictionaryPage />} />
                  <Route path="analysis" element={<AnalysisPage />} />
                  <Route path="modeling" element={<ModelingPage />} />
                  <Route path="reconciliation" element={<ReconciliationPage />} />
                  <Route element={<AdminRoute />}>
                    {/* AdminPage 在 Task 9 实现 */}
                  </Route>
                  <Route path="*" element={<Navigate to="/dictionary" replace />} />
                </Route>
              </Route>
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </AntApp>
    </ConfigProvider>
  );
}
```

- [ ] **Step 2: Update `frontend/src/components/Layout.tsx` — 用户信息 + 登出**

在 `Layout.tsx` 中：
1. Import `useAuth` 和 `useNavigate`
2. 在 menuItems 数组后加 admin 菜单项条件逻辑
3. 在侧边栏底部（status footer 上方）加用户信息区

具体修改：

```tsx
// import 加:
import { useAuth } from '../auth/AuthContext';
import {
  // 已有 icons...
  UserOutlined, LogoutOutlined, SettingOutlined,
} from '@ant-design/icons';

// 组件内加:
const { user, logout, isAdmin } = useAuth();
const navigate = useNavigate();

// menuItems 改为 useMemo:
import { useMemo } from 'react';
const menuItems = useMemo(() => {
  const items = [
    { key: '/dictionary', icon: <BookOutlined />, label: '数据字典管理' },
    { key: '/analysis', icon: <SearchOutlined />, label: '需求分析' },
    { key: '/modeling', icon: <BuildOutlined />, label: '数仓建模' },
    { key: '/reconciliation', icon: <ToolOutlined />, label: '修复闭环' },
  ];
  if (isAdmin) {
    items.push({ key: '/admin', icon: <SettingOutlined />, label: '系统管理' });
  }
  return items;
}, [isAdmin]);
```

在 status footer 上方加用户信息区：

```tsx
{/* User info */}
{user && (
  <div
    style={{
      position: 'absolute',
      bottom: 68,
      left: 0,
      right: 0,
      padding: '12px 20px',
      borderTop: '1px solid #2D333B',
    }}
  >
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
      <UserOutlined style={{ color: '#9099A4' }} />
      <Typography.Text style={{ color: '#E0E3E8', fontSize: 13 }}>
        {user.real_name}
      </Typography.Text>
    </div>
    {user.department_path && (
      <Typography.Text style={{ color: '#6E7681', fontSize: 11, display: 'block' }}>
        🏢 {user.department_path.replace(/^\//, '').replace(/\//g, ' / ')}
      </Typography.Text>
    )}
    {user.business_line_codes.length > 0 && (
      <Typography.Text style={{ color: '#6E7681', fontSize: 11, display: 'block' }}>
        📊 {user.business_line_codes.join(', ')}
      </Typography.Text>
    )}
    <Button
      type="text"
      size="small"
      icon={<LogoutOutlined />}
      onClick={() => { logout(); navigate('/login'); }}
      style={{ color: '#6E7681', marginTop: 4, padding: 0 }}
    >
      登出
    </Button>
  </div>
)}
```

并且把 status footer 的 `bottom: 0` 保持不变（它在最底部）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/Layout.tsx
git commit -m "feat(auth): add route guards + user info section in sidebar"
```

---

### Task 9: 前端 AdminPage

**目标:** 创建系统管理页面 — 4 个 Tab 管理用户/部门/条线/表映射。

**Files:**
- Create: `frontend/src/pages/AdminPage.tsx`
- Create: `frontend/src/api/admin.ts` (admin API 模块)

- [ ] **Step 1: Create `frontend/src/api/admin.ts`**

```typescript
import { api } from './client';

export interface AdminUser {
  id: number; username: string; real_name: string;
  department_id: number | null; department_name: string;
  is_admin: boolean; is_active: boolean;
  business_line_ids: number[];
  created_at: string;
}

export const adminApi = {
  // Users
  listUsers: () => api.get<AdminUser[]>('/api/admin/users'),
  createUser: (data: object) => api.post('/api/admin/users', data),
  updateUser: (id: number, data: object) => api.put(`/api/admin/users/${id}`, data),

  // Departments
  listDepartments: () => api.get('/api/admin/departments'),
  createDepartment: (data: object) => api.post('/api/admin/departments', data),
  updateDepartment: (id: number, data: object) => api.put(`/api/admin/departments/${id}`, data),

  // Business Lines
  listBusinessLines: () => api.get('/api/admin/business-lines'),
  createBusinessLine: (data: object) => api.post('/api/admin/business-lines', data),

  // Table-Line Mappings
  listTableLineMappings: () => api.get('/api/admin/table-line-mappings'),
  addTableLineMapping: (data: object) => api.post('/api/admin/table-line-mappings', data),
  removeTableLineMapping: (table: string, lineId: number) =>
    api.delete(`/api/admin/table-line-mappings/${encodeURIComponent(table)}/${lineId}`),
};
```

- [ ] **Step 2: Create `frontend/src/pages/AdminPage.tsx`**

```tsx
import { useState, useEffect } from 'react';
import { Tabs, Table, Button, Modal, Form, Input, Select, Switch, message, Space, Tag } from 'antd';
import { PlusOutlined, EditOutlined } from '@ant-design/icons';
import { adminApi, type AdminUser } from '../api/admin';

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState('users');
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [departments, setDepartments] = useState<any[]>([]);
  const [businessLines, setBusinessLines] = useState<any[]>([]);
  const [mappings, setMappings] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  // 加载数据
  const loadData = async (tab: string) => {
    setLoading(true);
    try {
      if (tab === 'users') {
        const res = await adminApi.listUsers();
        setUsers(res.data);
      } else if (tab === 'departments') {
        const res = await adminApi.listDepartments();
        setDepartments(res.data);
      } else if (tab === 'business-lines') {
        const res = await adminApi.listBusinessLines();
        setBusinessLines(res.data);
      } else if (tab === 'mappings') {
        const res = await adminApi.listTableLineMappings();
        const blRes = await adminApi.listBusinessLines();
        setBusinessLines(blRes.data);
        setMappings(res.data);
      }
    } catch { message.error('加载失败'); }
    finally { setLoading(false); }
  };

  useEffect(() => { loadData(activeTab); }, [activeTab]);

  // ── 用户创建 Modal ──
  const [userModalOpen, setUserModalOpen] = useState(false);
  const [userForm] = Form.useForm();

  // ── 条线创建 Modal ──
  const [blModalOpen, setBlModalOpen] = useState(false);
  const [blForm] = Form.useForm();

  const tabItems = [
    {
      key: 'users',
      label: '用户管理',
      children: (
        <div>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setUserModalOpen(true)}
                  style={{ marginBottom: 16 }}>
            新建用户
          </Button>
          <Table
            dataSource={users}
            rowKey="id"
            loading={loading}
            columns={[
              { title: '用户名', dataIndex: 'username', key: 'username' },
              { title: '姓名', dataIndex: 'real_name', key: 'real_name' },
              { title: '部门', dataIndex: 'department_name', key: 'department_name' },
              {
                title: '管理员', dataIndex: 'is_admin', key: 'is_admin',
                render: (v: boolean) => v ? <Tag color="red">管理员</Tag> : null,
              },
              {
                title: '状态', dataIndex: 'is_active', key: 'is_active',
                render: (v: boolean) => v ? <Tag color="green">启用</Tag> : <Tag color="default">禁用</Tag>,
              },
            ]}
          />
          {/* 用户创建/编辑 Modal 逻辑见下方 Step 3 */}
        </div>
      ),
    },
    // departments, business-lines, mappings tabs — 见 Step 3
  ];

  return <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />;
}
```

- [ ] **Step 3: Commit (完整 AdminPage 代码在实施时展开)**

完整 AdminPage 包含 4 个 Tab、各自的 Table + Modal 表单。代码较长（~250 行），此处给出骨架，实施时写完整。

```bash
git add frontend/src/pages/AdminPage.tsx frontend/src/api/admin.ts
git commit -m "feat(auth): add AdminPage with user/dept/line/mapping management"
```

---

### Task 10: 权限注入 — 检索 + SQL 生成

**目标:** 让检索引擎按业务条线过滤表，让 SQL 生成器注入部门 WHERE。

**Files:**
- Modify: `retrieval/engine.py`
- Modify: `generator/script.py`
- Modify: `models.py`

- [ ] **Step 1: Update `retrieval/engine.py` — 加条线过滤参数**

`search()` 函数签名加 `visible_business_lines: list[str] | None = None`。

函数内部，在返回结果前，如果有 `visible_business_lines`，从 `auth.database` 查 `table_business_lines` 表，过滤 `result.matches` 中不在条线范围内的表：

```python
def search(concepts, collection, visible_business_lines=None):
    # ... 现有检索逻辑 ...
    
    if visible_business_lines:
        from auth.database import get_session
        from auth.models import table_business_lines as tbl, BusinessLine
        with get_session() as session:
            allowed_tables = set()
            for row in session.query(tbl.c.table_name).join(
                BusinessLine, tbl.c.business_line_id == BusinessLine.id
            ).filter(BusinessLine.code.in_(visible_business_lines)).all():
                allowed_tables.add(row.table_name)
        
        # 过滤：表不在 allowed_tables 中 → 标记未匹配
        for m in result.matches:
            if m.matched and m.table_name and m.table_name not in allowed_tables:
                m.matched = False
                m.message = f"无权限访问表 {m.table_name}（业务条线限制）"
    
    return result
```

- [ ] **Step 2: Update `generator/script.py` — 注入部门 WHERE**

`generate_sql_script()` 签名加 `user_permissions: dict | None = None`。

在 `_build_cte_chain()` 中，每个 CTE 生成 WHERE 之前，查 `table_dept_columns` 获取该表的 dept_column，注入部门过滤：

```python
# 在 _build_cte_chain 中，WHERE 子句构建后：
if user_permissions and not user_permissions.get("is_admin"):
    visible_dept_ids = user_permissions.get("visible_dept_ids", [])
    if visible_dept_ids and not use_prev:  # step_XX CTE 无需部门过滤
        from auth.database import get_session
        from auth.models import TableDeptColumn
        with get_session() as session:
            tdc = session.query(TableDeptColumn).filter(
                TableDeptColumn.table_name == clean_source
            ).first()
        if tdc:
            dept_filter = f"{tdc.dept_column} IN ({','.join(repr(x) for x in visible_dept_ids)})"
            where_clauses.append(dept_filter)
```

`generate_sql_script()` 签名更新：
```python
def generate_sql_script(
    pseudocode, tables=None, assertions=None,
    unmatched_concepts=None, requirement_summary="",
    user_permissions=None,   # 新增
):
```

`_build_cte_chain()` 签名同样加 `user_permissions=None`。

- [ ] **Step 3: Update `models.py` — TableInfo 加 business_lines**

```python
class TableInfo(BaseModel):
    # ... 现有字段 ...
    business_lines: list[str] = Field(default_factory=list, description="可见业务条线代码列表")
```

- [ ] **Step 4: Commit**

```bash
git add retrieval/engine.py generator/script.py models.py
git commit -m "feat(auth): inject business line filter in retrieval + department WHERE in SQL generation"
```

---

### Task 11: 后端分析路由接入权限

**目标:** 分析端点调用检索/SQL 生成时传入当前用户权限。

**Files:**
- Modify: `backend/routers/analysis.py`

- [ ] **Step 1: Update `backend/routers/analysis.py` — 传递权限到引擎**

在 `analyze_full` 中，检索调用加 `visible_business_lines`：

```python
# Step 2: Retrieval (with business line filter)
from retrieval.engine import search
business_line_codes = user.get("business_line_codes", [])
retrieval = search(extraction.concepts, collection,
                   visible_business_lines=business_line_codes if not user.get("is_admin") else None)
```

SQL 生成调用加 `user_permissions`：

```python
sql = generate_sql_script(
    pseudocode=pseudocode,
    tables=tables,
    unmatched_concepts=retrieval.unmatched_concepts,
    requirement_summary=req.requirement_text[:100],
    user_permissions=None if user.get("is_admin") else user,
)
```

- [ ] **Step 2: 同模式更新 reconciliation 路由和 modeling 路由**

`reconciliation.py` 和 `modeling.py` 中，如果内部调了检索或 SQL 生成，同样传入 `user` 权限。

- [ ] **Step 3: Commit**

```bash
git add backend/routers/analysis.py backend/routers/reconciliation.py backend/routers/modeling.py
git commit -m "feat(auth): pass user permissions to retrieval + SQL generation in API routes"
```

---

### Task 12: 测试

**目标:** 5 个测试文件覆盖安全层、模型层、API 层、权限逻辑、集成。

**Files:**
- Create: `tests/test_auth_security.py`
- Create: `tests/test_auth_models.py`
- Create: `tests/test_auth_api.py`
- Create: `tests/test_auth_permission.py`
- Create: `tests/test_auth_integration.py`

- [ ] **Step 1: Create `tests/test_auth_security.py`**

```python
"""测试 bcrypt 密码哈希 + JWT 签发/校验"""
import pytest
from auth.security import hash_password, verify_password, create_token, decode_token
import jwt

class TestPasswordHashing:
    def test_hash_and_verify(self):
        h = hash_password("mypassword")
        assert verify_password("mypassword", h)
    
    def test_wrong_password(self):
        h = hash_password("correct")
        assert not verify_password("wrong", h)
    
    def test_hash_is_stable_format(self):
        h = hash_password("test")
        assert h.startswith("$2b$") or h.startswith("$2a$")

class TestJWT:
    def test_create_and_decode(self):
        token = create_token(1, "alice", "Alice", False, 1, "/root", [1], ["retail"])
        payload = decode_token(token)
        assert payload["sub"] == 1
        assert payload["business_line_codes"] == ["retail"]
    
    def test_expired_token(self):
        import time
        from auth.security import SECRET_KEY, ALGORITHM
        payload = {"sub": 1, "exp": int(time.time()) - 1}
        expired = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_token(expired)
    
    def test_invalid_token(self):
        with pytest.raises(jwt.InvalidTokenError):
            decode_token("not.a.valid.token")
```

- [ ] **Step 2: Create `tests/test_auth_models.py`**

测试 ORM 模型 CRUD、部门树查询（物化路径 LIKE）、外键约束。

- [ ] **Step 3: Create `tests/test_auth_api.py`**

使用 FastAPI `TestClient` 测试 `/api/auth/login`（成功/密码错误/禁用用户）、`/api/auth/me`（有效 token/无 token/过期 token）、admin 端点权限控制。

- [ ] **Step 4: Create `tests/test_auth_permission.py`**

测试条线过滤逻辑（能/不能看的表）、部门子节点查询（`path LIKE '/总行/北京分行/%'`）、admin 不受限。

- [ ] **Step 5: Create `tests/test_auth_integration.py`**

端到端测试：带 token 调 `/api/analysis/full` → SQL 输出含部门 WHERE、检索结果仅可见表。

- [ ] **Step 6: Run all auth tests**

```bash
pytest tests/test_auth_*.py -v
```
Expected: ~30 tests pass

- [ ] **Step 7: Run full suite to verify no regressions**

```bash
pytest tests/ -v
```

- [ ] **Step 8: Commit**

```bash
git add tests/test_auth_security.py tests/test_auth_models.py tests/test_auth_api.py tests/test_auth_permission.py tests/test_auth_integration.py
git commit -m "test(auth): add 5 test files covering security, models, API, permissions, integration"
```

---

## 验证方式

```bash
# 1. 启动后端
python -m uvicorn backend.main:app --port 8000

# 2. 测试登录
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# 3. 用返回的 token 调分析
curl -X POST http://localhost:8000/api/analysis/full \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"requirement_text":"统计各渠道活跃客户数","generate_sql":true}'

# 4. 启动前端
cd frontend && npm run dev

# 5. 浏览器访问 localhost:5173 → 看到登录页 → 登录 → 进入主页
```

## 文件变更总览

| 操作 | 文件 |
|------|------|
| 新建 | `auth/__init__.py`, `auth/models.py`, `auth/database.py`, `auth/security.py` |
| 新建 | `backend/auth.py`, `backend/routers/auth.py`, `backend/routers/admin.py` |
| 新建 | `frontend/src/auth/AuthContext.tsx`, `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/AdminPage.tsx`, `frontend/src/api/auth.ts`, `frontend/src/api/admin.ts` |
| 新建 | `tests/test_auth_security.py`, `tests/test_auth_models.py`, `tests/test_auth_api.py`, `tests/test_auth_permission.py`, `tests/test_auth_integration.py` |
| 修改 | `backend/schemas.py`, `backend/main.py`, `backend/routers/analysis.py`, `backend/routers/reconciliation.py`, `backend/routers/dictionary.py`, `backend/routers/modeling.py` |
| 修改 | `frontend/src/api/client.ts`, `frontend/src/App.tsx`, `frontend/src/components/Layout.tsx` |
| 修改 | `retrieval/engine.py`, `generator/script.py`, `models.py` |
| 修改 | `requirements.txt` (加 bcrypt, PyJWT) |

总文件: 18 新建 + 14 修改 = 32 文件。
