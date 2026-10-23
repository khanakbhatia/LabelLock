import uuid
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import JSON, ForeignKey, Integer, String, Text, create_engine
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
