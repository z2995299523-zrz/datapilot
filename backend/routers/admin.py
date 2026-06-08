"""Admin router — user/dept/business line/table mapping CRUD"""
from fastapi import APIRouter, Depends, HTTPException, status

from backend.schemas import (
    AdminUserCreate, AdminUserUpdate, AdminDepartmentCreate,
    AdminBusinessLineCreate, AdminTableLineMapping,
)
from backend.auth import require_admin
from auth.database import get_session
from auth.security import hash_password
from auth.models import (
    User, Department, BusinessLine, TableDeptColumn,
    table_business_lines,
)

router = APIRouter(prefix="/api/admin", tags=["系统管理"])


# ── USERS ───────────────────────────────────────────────────

@router.get("/users")
async def list_users(_admin: dict = Depends(require_admin)):
    """List all users with department and business line info."""
    with get_session() as session:
        users = session.query(User).order_by(User.id).all()
        return [
            {
                "id": u.id,
                "username": u.username,
                "real_name": u.real_name,
                "department_id": u.department_id,
                "department_name": u.department.name if u.department else "",
                "is_admin": bool(u.is_admin),
                "is_active": bool(u.is_active),
                "business_line_ids": [bl.id for bl in u.business_lines],
                "created_at": u.created_at,
            }
            for u in users
        ]


@router.post("/users")
async def create_user(req: AdminUserCreate, _admin: dict = Depends(require_admin)):
    """Create a new user."""
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
        return {"id": user.id, "username": user.username, "created": True}


@router.put("/users/{user_id}")
async def update_user(user_id: int, req: AdminUserUpdate,
                      _admin: dict = Depends(require_admin)):
    """Update user fields. All fields optional — only provided fields are changed."""
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


# ── DEPARTMENTS ─────────────────────────────────────────────

@router.get("/departments")
async def list_departments(_admin: dict = Depends(require_admin)):
    """List departments as a flat list (ordered by path for tree reconstruction)."""
    with get_session() as session:
        depts = session.query(Department).order_by(Department.path).all()
        return [
            {
                "id": d.id,
                "name": d.name,
                "parent_id": d.parent_id,
                "path": d.path,
                "level": d.level,
                "is_active": bool(d.is_active),
            }
            for d in depts
        ]


@router.post("/departments")
async def create_department(req: AdminDepartmentCreate,
                            _admin: dict = Depends(require_admin)):
    """Create a department under a parent."""
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
        return {"id": dept.id, "path": dept.path, "created": True}


@router.put("/departments/{dept_id}")
async def update_department(dept_id: int, req: dict,
                            _admin: dict = Depends(require_admin)):
    """Update department name or active status."""
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


# ── BUSINESS LINES ─────────────────────────────────────────

@router.get("/business-lines")
async def list_business_lines(_admin: dict = Depends(require_admin)):
    """List all business lines."""
    with get_session() as session:
        bls = session.query(BusinessLine).order_by(BusinessLine.id).all()
        return [
            {
                "id": bl.id, "name": bl.name, "code": bl.code,
                "description": bl.description, "is_active": bool(bl.is_active),
            }
            for bl in bls
        ]


@router.post("/business-lines")
async def create_business_line(req: AdminBusinessLineCreate,
                               _admin: dict = Depends(require_admin)):
    """Create a new business line."""
    with get_session() as session:
        existing = session.query(BusinessLine).filter(
            BusinessLine.code == req.code
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="条线代码已存在")
        bl = BusinessLine(
            name=req.name, code=req.code, description=req.description,
        )
        session.add(bl)
        session.commit()
        return {"id": bl.id, "code": bl.code, "created": True}


# ── TABLE-LINE MAPPINGS ────────────────────────────────────

@router.get("/table-line-mappings")
async def list_table_line_mappings(_admin: dict = Depends(require_admin)):
    """List all table to business_line mappings."""
    with get_session() as session:
        rows = session.query(table_business_lines).all()
        return [
            {"table_name": r.table_name, "business_line_id": r.business_line_id}
            for r in rows
        ]


@router.post("/table-line-mappings")
async def add_table_line_mapping(req: AdminTableLineMapping,
                                 _admin: dict = Depends(require_admin)):
    """Add a table to business_line mapping."""
    with get_session() as session:
        bl = session.query(BusinessLine).filter(
            BusinessLine.id == req.business_line_id
        ).first()
        if not bl:
            raise HTTPException(status_code=400, detail="条线不存在")

        from sqlalchemy import insert
        stmt = (
            insert(table_business_lines)
            .prefix_with("OR IGNORE")
            .values(
                table_name=req.table_name,
                business_line_id=req.business_line_id,
            )
        )
        session.execute(stmt)
        session.commit()
        return {"table_name": req.table_name, "business_line_id": req.business_line_id, "created": True}


@router.delete("/table-line-mappings/{table_name}/{business_line_id}")
async def remove_table_line_mapping(table_name: str, business_line_id: int,
                                    _admin: dict = Depends(require_admin)):
    """Remove a table to business_line mapping."""
    with get_session() as session:
        session.execute(
            table_business_lines.delete().where(
                (table_business_lines.c.table_name == table_name) &
                (table_business_lines.c.business_line_id == business_line_id)
            )
        )
        session.commit()
        return {"deleted": True}
