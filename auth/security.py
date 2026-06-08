"""Password hashing (bcrypt) + JWT creation/validation."""
import bcrypt
import jwt
import time

SECRET_KEY = "datapilot-secret-change-in-production"  # TODO: env var in production
ALGORITHM = "HS256"
TOKEN_EXPIRE_SECONDS = 8 * 3600  # 8 hours


def hash_password(password: str) -> str:
    """Hash a password with bcrypt. Returns hash string."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_token(
    user_id: int, username: str, real_name: str,
    is_admin: bool, department_id: int, department_path: str,
    visible_dept_ids: list[int], business_line_codes: list[str],
) -> str:
    """Create a JWT token containing full permission info."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
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
    """Validate and decode a JWT token. Raises jwt exceptions on failure."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
