"""Simulated ERP / WMS / labels / tickets / outbox state. Separate database from the app.

The sim knows nothing about cases, roles or approvals: `case_ref` is an opaque string.
"""
from sqlalchemy import JSON, Boolean, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class SimBase(DeclarativeBase):
    pass


class Supplier(SimBase):
    __tablename__ = "suppliers"
    supplier_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)


class Material(SimBase):
    __tablename__ = "materials"
    material_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    supplier_id: Mapped[str] = mapped_column(String)


class MaterialLot(SimBase):
    __tablename__ = "material_lots"
    lot_id: Mapped[str] = mapped_column(String, primary_key=True)
    material_id: Mapped[str] = mapped_column(String, index=True)
    received_at: Mapped[str] = mapped_column(String)


class Product(SimBase):
    __tablename__ = "products"
    sku: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    label_version: Mapped[str] = mapped_column(String)


class Recipe(SimBase):
    __tablename__ = "recipes"
    sku: Mapped[str] = mapped_column(String, primary_key=True)
    material_id: Mapped[str] = mapped_column(String, primary_key=True)


class Label(SimBase):
    __tablename__ = "labels"
    sku: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String, primary_key=True)
    ingredient_statement: Mapped[str] = mapped_column(String)
    contains: Mapped[list] = mapped_column(JSON)
    may_contain: Mapped[list] = mapped_column(JSON)
    claims: Mapped[list] = mapped_column(JSON)


class Batch(SimBase):
    __tablename__ = "batches"
    batch_id: Mapped[str] = mapped_column(String, primary_key=True)
    sku: Mapped[str] = mapped_column(String)
    produced_at: Mapped[str] = mapped_column(String)


class Genealogy(SimBase):
    __tablename__ = "genealogy"
    batch_id: Mapped[str] = mapped_column(String, primary_key=True)
    material_lot_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)


class Inventory(SimBase):
    __tablename__ = "inventory"
    batch_id: Mapped[str] = mapped_column(String, primary_key=True)
    location: Mapped[str] = mapped_column(String, primary_key=True)
    qty: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)  # AVAILABLE | HELD


class Hold(SimBase):
    __tablename__ = "holds"
    hold_id: Mapped[str] = mapped_column(String, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String, index=True)
    location: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    case_ref: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String)  # ACTIVE | RELEASED
    created_at: Mapped[str] = mapped_column(String)
    released_at: Mapped[str | None] = mapped_column(String, nullable=True)


class Shipment(SimBase):
    __tablename__ = "shipments"
    shipment_id: Mapped[str] = mapped_column(String, primary_key=True)
    destination: Mapped[str] = mapped_column(String)
    departs_at: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # PLANNED | LOADING | DEPARTED | DELIVERED


class ShipmentLine(SimBase):
    __tablename__ = "shipment_lines"
    shipment_id: Mapped[str] = mapped_column(String, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    qty: Mapped[int] = mapped_column(Integer)


class LineRemoval(SimBase):
    __tablename__ = "shipment_line_removals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_id: Mapped[str] = mapped_column(String)
    batch_id: Mapped[str] = mapped_column(String)
    qty: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    removed_at: Mapped[str] = mapped_column(String)


class Ticket(SimBase):
    __tablename__ = "tickets"
    ticket_id: Mapped[str] = mapped_column(String, primary_key=True)
    sku: Mapped[str] = mapped_column(String)
    batch_id: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str] = mapped_column(String)
    case_ref: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)


class OutboxMessage(SimBase):
    __tablename__ = "outbox"
    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    to: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(String)
    case_ref: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # DRAFT | SENT
    created_at: Mapped[str] = mapped_column(String)


class Fault(SimBase):
    __tablename__ = "faults"
    name: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)


def make_sim_sessionmaker(database_url: str) -> sessionmaker[Session]:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    SimBase.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
