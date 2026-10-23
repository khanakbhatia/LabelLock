from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import ALL_ROLES, make_token, require_roles, verify_password
from api.db import User, get_db
from api.errors import ApiError

router = APIRouter(prefix="/api")

# Verified against when the username is unknown, so both failures take the same time.
_DUMMY_HASH = "pbkdf2_sha256$100000$00$00"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


def user_out(user: User) -> dict:
    return {"id": user.id, "name": user.name, "role": user.role}


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/auth/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not (user and ok):
        raise ApiError(401, "UNAUTHENTICATED", "Invalid username or password")
    settings = request.app.state.settings
    return {"token": make_token(user.id, settings.auth_secret, settings.token_ttl_seconds), "user": user_out(user)}


@router.get("/auth/me")
def me(user: User = Depends(require_roles(*ALL_ROLES))):
    return user_out(user)


@router.post("/actions/{action_id}/approve")
def approve_action(action_id: str, user: User = Depends(require_roles("qa_manager"))):
    # Placeholder until approvals land in M1/M2; the role check above is already real.
    raise ApiError(501, "NOT_IMPLEMENTED", "Approving actions is not implemented yet", {"action_id": action_id})
