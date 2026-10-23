import uuid
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

# Times are stored as ISO-8601 UTC strings ("2026-10-23T09:00:00Z"), the contract's format.


def now_iso() -> str:
    return to_iso(datetime.now(timezone.utc))


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Base(DeclarativeBase):
    pass


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)


class SupplierSender(Base):
    """A sender we trust for a supplier: a full address or a bare email domain."""
    __tablename__ = "supplier_senders"

    match: Mapped[str] = mapped_column(String, primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"))


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    password_hash: Mapped[str] = mapped_column(String)
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)


class Notice(Base):
    __tablename__ = "notices"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String)  # supplier_portal | gmail
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    from_address: Mapped[str | None] = mapped_column(String, nullable=True)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)  # untrusted supplier text, stored verbatim
    received_at: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String, index=True)
    # Unique: one notice per Gmail message, even under concurrent ingests. NULL for portal notices.
    gmail_message_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    gmail_thread_id: Mapped[str | None] = mapped_column(String, nullable=True)


class NoticeAttachment(Base):
    __tablename__ = "notice_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notice_id: Mapped[str] = mapped_column(ForeignKey("notices.id"), index=True)
    filename: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    notice_id: Mapped[str] = mapped_column(ForeignKey("notices.id"), unique=True)
    status: Mapped[str] = mapped_column(String)
    uncertainty_flags: Mapped[list] = mapped_column(JSON, default=list)
    duplicate_of: Mapped[str | None] = mapped_column(String, nullable=True)
    opened_at: Mapped[str] = mapped_column(String)
    contained_at: Mapped[str | None] = mapped_column(String, nullable=True)
    closed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    # agent run state: {step: DONE | STOPPED}; a second run resumes from here
    steps: Mapped[dict] = mapped_column(JSON, default=dict)
    running_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    elapsed_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)


class Extraction(Base):
    __tablename__ = "extractions"

    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), primary_key=True)
    fields: Mapped[dict] = mapped_column(JSON)
    allergens_added: Mapped[list] = mapped_column(JSON)
    uncertainty_flags: Mapped[list] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String)
    prompt_version: Mapped[str] = mapped_column(String)


class TraceResult(Base):
    __tablename__ = "trace_results"

    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), primary_key=True)
    material_lot_ids: Mapped[list] = mapped_column(JSON)
    batch_ids: Mapped[list] = mapped_column(JSON)
    graph: Mapped[dict] = mapped_column(JSON)  # {"batches": [contract TraceBatch], "labels": {sku: label}, "shipment_status": {id: status}}
    gaps: Mapped[list] = mapped_column(JSON)


class BatchDecision(Base):
    __tablename__ = "batch_decisions"

    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String, primary_key=True)
    decision: Mapped[str] = mapped_column(String)
    rule_ids: Mapped[list] = mapped_column(JSON)
    uncertainty_flags: Mapped[list] = mapped_column(JSON)
    rationale: Mapped[str] = mapped_column(Text)


class Action(Base):
    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    type: Mapped[str] = mapped_column(String)
    target: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String)
    requires_approval: Mapped[bool] = mapped_column(Boolean)
    # hash(case_id, type, target): one action per target, however often the agent runs
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    requested_by: Mapped[str] = mapped_column(String)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("actions.id"), index=True)
    decided_by: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String)  # APPROVED | REJECTED
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[str] = mapped_column(String)


class Disposition(Base):
    __tablename__ = "dispositions"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # latest wins; timestamps tie
    id: Mapped[str] = mapped_column(String, unique=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    batch_id: Mapped[str] = mapped_column(String)
    disposition: Mapped[str] = mapped_column(String)
    evidence: Mapped[str] = mapped_column(Text)
    recorded_by: Mapped[str] = mapped_column(String)
    recorded_at: Mapped[str] = mapped_column(String)


class Benchmark(Base):
    """A timed run of one scenario, by a person (manual) or the agent."""
    __tablename__ = "benchmarks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String, index=True)
    mode: Mapped[str] = mapped_column(String)  # manual | agent
    seconds: Mapped[float] = mapped_column(Float)
    batches_found: Mapped[int] = mapped_column(Integer)
    false_holds: Mapped[int] = mapped_column(Integer)
    operator: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("actions.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    expected: Mapped[dict] = mapped_column(JSON)
    observed: Mapped[dict] = mapped_column(JSON)
    passed: Mapped[bool] = mapped_column(Boolean)
    checked_at: Mapped[str] = mapped_column(String)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    ts: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    prev_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    hash: Mapped[str] = mapped_column(String)


def make_sessionmaker(database_url: str) -> sessionmaker[Session]:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def get_db(request: Request):
    with request.app.state.sessionmaker() as db:
        yield db
