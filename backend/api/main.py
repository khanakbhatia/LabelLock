import json
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from api import errors
from api.auth import hash_password
from api.cases import router as cases_router
from api.db import Supplier, SupplierSender, User, make_sessionmaker
from api.routes import router
from api.settings import Settings
from sim.db import Batch as SimBatch, make_sim_sessionmaker
from sim.routes import router as sim_router
from sim.seed import reset_sim

DEV_SEED = Path(__file__).resolve().parents[1] / "dev_seed"


def seed_dev_data(sessionmaker) -> None:
    """Insert dev suppliers and demo users that are not there yet. Passwords are hashed on insert."""
    with sessionmaker() as db:
        # ponytail: stub supplier list until the loader for Khanak's /data/seed lands (M1).
        for s in json.loads((DEV_SEED / "suppliers.json").read_text(encoding="utf-8")):
            if db.get(Supplier, s["id"]) is None:
                db.add(Supplier(id=s["id"], name=s["name"]))
            for match in s["senders"]:
                if db.get(SupplierSender, match.lower()) is None:
                    db.add(SupplierSender(match=match.lower(), supplier_id=s["id"]))
        db.flush()

        existing = set(db.scalars(select(User.username)))
        for u in json.loads((DEV_SEED / "demo_users.json").read_text(encoding="utf-8")):
            if u["username"] not in existing:
                db.add(User(id=u["id"], username=u["username"], name=u["name"], role=u["role"],
                            supplier_id=u.get("supplier_id"), password_hash=hash_password(u["password"])))
        db.commit()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="LabelLock API", version="0.1.0")
    app.state.settings = settings
    app.state.sessionmaker = make_sessionmaker(settings.database_url)
    seed_dev_data(app.state.sessionmaker)
    app.state.sim_sessionmaker = make_sim_sessionmaker(settings.sim_database_url)
    with app.state.sim_sessionmaker() as sim_db:
        if sim_db.scalar(select(SimBatch.batch_id).limit(1)) is None:
            reset_sim(app.state.sim_sessionmaker, settings.seed_dir)
    # Adapters reach the sim over HTTP (tests swap in a TestClient bound to this app).
    app.state.sim_http = httpx.Client(base_url=settings.sim_base_url, timeout=5.0)

    errors.install(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.include_router(router)
    app.include_router(cases_router)
    app.include_router(sim_router)
    return app
