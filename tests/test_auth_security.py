"""Test password hashing (bcrypt) + JWT create/decode"""
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth.security import hash_password, verify_password, create_token, decode_token
import jwt


class TestPasswordHashing:
    def test_hash_and_verify_correct(self):
        h = hash_password("mypassword")
        assert verify_password("mypassword", h)

    def test_verify_wrong_password(self):
        h = hash_password("correct")
        assert not verify_password("wrong", h)

    def test_hash_is_bcrypt_format(self):
        h = hash_password("test")
        assert h.startswith("$2b$") or h.startswith("$2a$")

    def test_different_salts(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # Different salts

    def test_empty_password(self):
        h = hash_password("")
        assert verify_password("", h)

    def test_unicode_password(self):
        """Unicode characters in password should work"""
        pw = "密码123!@#"
        h = hash_password(pw)
        assert verify_password(pw, h)


class TestJWT:
    def test_create_and_decode_roundtrip(self):
        token = create_token(1, "alice", "Alice", False, 5, "/root/branch", [5, 6], ["retail"])
        payload = decode_token(token)
        assert payload["sub"] == "1"  # String per RFC 7519
        assert payload["username"] == "alice"
        assert payload["real_name"] == "Alice"
        assert payload["is_admin"] is False
        assert payload["business_line_codes"] == ["retail"]
        assert payload["visible_dept_ids"] == [5, 6]
        assert payload["department_id"] == 5
        assert payload["department_path"] == "/root/branch"

    def test_expired_token_raises(self):
        import time
        from auth.security import SECRET_KEY, ALGORITHM
        expired_payload = {"sub": "1", "exp": int(time.time()) - 3600}
        expired_token = jwt.encode(expired_payload, SECRET_KEY, algorithm=ALGORITHM)
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_token(expired_token)

    def test_invalid_token_raises(self):
        with pytest.raises(jwt.InvalidTokenError):
            decode_token("not.a.real.jwt.token")

    def test_admin_token(self):
        token = create_token(1, "admin", "Admin", True, 1, "/root", [1], [])
        payload = decode_token(token)
        assert payload["is_admin"] is True
        assert payload["username"] == "admin"

    def test_token_contains_iat_and_exp(self):
        """Token should have issued-at and expiration timestamps"""
        token = create_token(1, "u", "User", False, 1, "/", [1], [])
        payload = decode_token(token)
        assert "iat" in payload
        assert "exp" in payload
        assert payload["exp"] > payload["iat"]

    def test_tampered_token_raises(self):
        """Signature tampering should be detected"""
        token = create_token(1, "u", "User", False, 1, "/", [1], [])
        tampered = token + "x"  # Append garbage -> invalid base64 / signature
        with pytest.raises(jwt.InvalidTokenError):
            decode_token(tampered)

    def test_empty_business_lines(self):
        """Empty business line list should round-trip correctly"""
        token = create_token(1, "u", "User", False, 1, "/", [1], [])
        payload = decode_token(token)
        assert payload["business_line_codes"] == []

    def test_visible_dept_ids_roundtrip(self):
        """Large visible_dept_ids list should serialize/deserialize correctly"""
        dept_ids = list(range(1, 20))
        token = create_token(1, "u", "User", False, 1, "/", dept_ids, ["retail"])
        payload = decode_token(token)
        assert payload["visible_dept_ids"] == dept_ids
