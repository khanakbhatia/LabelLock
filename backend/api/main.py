import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from api import errors
from api.auth import hash_password
from api.db import User, make_sessionmaker
from api.routes import router
from api.settings import Settings

DEMO_USERS = Path(__file__).resolve().parents[1] / "dev_seed" / "demo_users.json"


def seed_users(sessionmaker) -> None:
    """Insert the dev demo users that are not there yet. Passwords are hashed on insert."""
    with sessionmaker() as db:
        existing = set(db.scalars(select(User.username)))
        for u in json.loads(DEMO_USERS.read_text(encoding="utf-8")):
            if u["username"] not in existing:
                db.add(User(id=u["id"], username=u["username"], name=u["name"], role=u["role"],
                            password_hash=hash_password(u["password"])))
        db.commit()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="LabelLock API", version="0.1.0")
    app.state.settings = settings
    app.state.sessionmaker = make_sessionmaker(settings.database_url)
    seed_users(app.state.sessionmaker)

    errors.install(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.include_router(router)
    return app
