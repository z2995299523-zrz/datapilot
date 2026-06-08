"""Auth router — POST /api/auth/login, GET /api/auth/me"""
from fastapi import APIRouter, Depends, HTTPException, status

from backend.schemas import LoginRequest, LoginResponse, UserInfo
from backend.auth import get_current_user
from auth.database import get_session
from auth.security import verify_password, create_token
from auth.models import User, Department

router = APIRouter(prefix="/api/auth", tags=["认证"])


def _get_visible_dept_ids(session, department_id: int | None) -> list[int]:
    """Get department + all child department IDs via materialized path."""
    if department_id is None:
        return []
    dept = session.query(Department).filter(Department.id == department_id).first()
    if not dept:
        return []
    children = session.query(Department).filter(
        Department.path.like(dept.path + "/%")
    ).all()
    return [dept.id] + [c.id for c in children]


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """Authenticate user and return JWT token with permissions."""
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

        # Check department is active
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

        # Business lines (active only)
        business_line_codes = [
            bl.code for bl in user.business_lines if bl.is_active
        ]

        # Issue JWT
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
    """Return current user's permission info (for page refresh recovery)."""
    return UserInfo(
        user_id=int(user["sub"]),  # sub is string per RFC 7519
        username=user["username"],
        real_name=user["real_name"],
        is_admin=user["is_admin"],
        department_id=user.get("department_id"),
        department_path=user.get("department_path", ""),
        visible_dept_ids=user.get("visible_dept_ids", []),
        business_line_codes=user.get("business_line_codes", []),
    )
