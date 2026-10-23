"""Password hashing, signed tokens and the server-side role check. Stdlib only."""
import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from api.db import User, get_db
from api.errors import ApiError

ALL_ROLES = ("supplier", "qa_specialist", "qa_manager", "shipping_supervisor", "admin", "agent")
PBKDF2_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    _, iterations, salt, digest = stored.split("$")
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    return hmac.compare_digest(candidate.hex(), digest)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(user_id: str, secret: str, ttl_seconds: int) -> str:
    payload = _b64(json.dumps({"sub": user_id, "exp": int(time.time()) + ttl_seconds}).encode())
    sig = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str, secret: str) -> str | None:
    """Return the user id, or None if the token is malformed, tampered with or expired."""
    try:
        payload, sig = token.split(".")
        expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        claims = json.loads(_unb64(payload))
        return claims["sub"] if claims["exp"] > time.time() else None
    except (ValueError, KeyError, TypeError):
        return None


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "UNAUTHENTICATED", "Missing bearer token")
    user_id = read_token(token, request.app.state.settings.auth_secret)
    # Role comes from the database on every request, never from the token.
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise ApiError(401, "UNAUTHENTICATED", "Invalid or expired token")
    return user


def require_roles(*roles: str):
    """Dependency: the signed-in user must have one of `roles`, else 403 FORBIDDEN."""
    def check(request: Request, user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise ApiError(
                403, "FORBIDDEN",
                f"Role {user.role} cannot call {request.method} {request.url.path}",
                {"allowed_roles": list(roles)},
            )
        return user
    return check
