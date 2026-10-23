"""HTTP surface of the simulated systems. Only backend adapters call these (X-Sim-Key)."""
import hmac
import uuid

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.db import now_iso
from api.errors import ApiError
from sim.db import (
    Batch, Fault, OutboxMessage, Ticket, Genealogy, Hold, Inventory, Label, LineRemoval, Material, MaterialLot, Product, Recipe, Shipment,
    ShipmentLine,
)
from sim.seed import reset_sim

WMS_SILENT_HOLD_FAILURE = "wms_silent_hold_failure"
SHIPPED_STATUSES = {"DEPARTED", "DELIVERED"}


def require_sim_key(request: Request, x_sim_key: str = Header(default="")):
    if not hmac.compare_digest(x_sim_key, request.app.state.settings.sim_api_key):
        raise ApiError(401, "UNAUTHENTICATED", "Missing or invalid X-Sim-Key")


def get_sim_db(request: Request):
    with request.app.state.sim_sessionmaker() as db:
        yield db


router = APIRouter(prefix="/sim", dependencies=[Depends(require_sim_key)], include_in_schema=False)


def not_found(what: str, key: str):
    return ApiError(404, "NOT_FOUND", f"{what} {key} not found", {"id": key})


def fault_on(db: Session, name: str) -> bool:
    fault = db.get(Fault, name)
    return bool(fault and fault.enabled)


def inventory_out(row: Inventory) -> dict:
    return {"batch_id": row.batch_id, "location": row.location, "qty": row.qty, "status": row.status}


def hold_out(h: Hold) -> dict:
    return {"hold_id": h.hold_id, "batch_id": h.batch_id, "location": h.location, "reason": h.reason,
            "case_ref": h.case_ref, "status": h.status, "created_at": h.created_at, "released_at": h.released_at}


def shipment_out(db: Session, s: Shipment) -> dict:
    lines = db.scalars(select(ShipmentLine).where(ShipmentLine.shipment_id == s.shipment_id).order_by(ShipmentLine.batch_id))
    return {"shipment_id": s.shipment_id, "destination": s.destination, "departs_at": s.departs_at, "status": s.status,
            "lines": [{"batch_id": ln.batch_id, "qty": ln.qty} for ln in lines]}


# ---- ERP

@router.get("/erp/material-lots/{lot_id}")
def material_lot(lot_id: str, db: Session = Depends(get_sim_db)):
    lot = db.get(MaterialLot, lot_id)
    if lot is None:
        raise not_found("Material lot", lot_id)
    material = db.get(Material, lot.material_id)
    return {"lot_id": lot.lot_id, "material_id": lot.material_id, "material_name": material.name,
            "supplier_id": material.supplier_id, "received_at": lot.received_at}


@router.get("/erp/products")
def products(material_id: str, db: Session = Depends(get_sim_db)):
    rows = db.scalars(select(Product).join(Recipe, Recipe.sku == Product.sku)
                      .where(Recipe.material_id == material_id).order_by(Product.sku))
    return [{"sku": p.sku, "name": p.name, "label_version": p.label_version} for p in rows]


@router.get("/erp/genealogy")
def genealogy(material_lot_id: str, db: Session = Depends(get_sim_db)):
    rows = db.execute(select(Genealogy.batch_id, Batch.sku).join(Batch, Batch.batch_id == Genealogy.batch_id)
                      .where(Genealogy.material_lot_id == material_lot_id).order_by(Genealogy.batch_id))
    return [{"batch_id": b, "sku": sku, "material_lot_id": material_lot_id} for b, sku in rows]


@router.get("/erp/batches/{batch_id}")
def batch(batch_id: str, db: Session = Depends(get_sim_db)):
    b = db.get(Batch, batch_id)
    if b is None:
        raise not_found("Batch", batch_id)
    lots = db.scalars(select(Genealogy.material_lot_id).where(Genealogy.batch_id == batch_id).order_by(Genealogy.material_lot_id))
    product = db.get(Product, b.sku)
    return {"batch_id": b.batch_id, "sku": b.sku, "product": product.name if product else None,
            "produced_at": b.produced_at, "material_lot_ids": list(lots)}


# ---- WMS

@router.get("/wms/inventory")
def inventory(batch_id: str, db: Session = Depends(get_sim_db)):
    rows = db.scalars(select(Inventory).where(Inventory.batch_id == batch_id).order_by(Inventory.location))
    return [inventory_out(r) for r in rows]


class HoldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str = Field(min_length=1)
    location: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    case_ref: str = Field(min_length=1)


def apply_hold(db: Session, hold: Hold) -> None:
    """Mark the held location HELD, unless the silent-failure fault swallows it.

    The fault hits one location per batch (the first by name), and the call still reports success.
    """
    if fault_on(db, WMS_SILENT_HOLD_FAILURE):
        first = db.scalar(select(Inventory.location).where(Inventory.batch_id == hold.batch_id).order_by(Inventory.location).limit(1))
        if hold.location == first:
            return
    db.get(Inventory, (hold.batch_id, hold.location)).status = "HELD"


@router.post("/wms/holds")
def place_hold(body: HoldRequest, idempotency_key: str = Header(min_length=1), db: Session = Depends(get_sim_db)):
    hold = db.scalar(select(Hold).where(Hold.idempotency_key == idempotency_key))
    status = 200
    if hold is None:
        if db.get(Inventory, (body.batch_id, body.location)) is None:
            raise not_found("Inventory", f"{body.batch_id}@{body.location}")
        hold = Hold(hold_id=f"H-{uuid.uuid4().hex[:8].upper()}", idempotency_key=idempotency_key, status="ACTIVE",
                    created_at=now_iso(), **body.model_dump())
        db.add(hold)
        try:
            db.flush()
            status = 201
        except IntegrityError:  # same key raced in; return that hold
            db.rollback()
            hold = db.scalar(select(Hold).where(Hold.idempotency_key == idempotency_key))
    elif (hold.batch_id, hold.location) != (body.batch_id, body.location):
        raise ApiError(409, "CONFLICT", "Idempotency-Key reused for a different hold", {"hold_id": hold.hold_id})
    if hold.status == "ACTIVE":
        apply_hold(db, hold)  # a repeat re-asserts the hold (idempotent effect)
    db.commit()
    return JSONResponse(hold_out(hold), status_code=status)


@router.get("/wms/holds")
def holds(batch_id: str, db: Session = Depends(get_sim_db)):
    return [hold_out(h) for h in db.scalars(select(Hold).where(Hold.batch_id == batch_id).order_by(Hold.created_at))]


@router.post("/wms/holds/{hold_id}/release")
def release_hold(hold_id: str, db: Session = Depends(get_sim_db)):
    hold = db.get(Hold, hold_id)
    if hold is None:
        raise not_found("Hold", hold_id)
    if hold.status == "ACTIVE":
        hold.status, hold.released_at = "RELEASED", now_iso()
        others = db.scalar(select(Hold).where(Hold.batch_id == hold.batch_id, Hold.location == hold.location,
                                              Hold.status == "ACTIVE", Hold.hold_id != hold.hold_id).limit(1))
        if others is None:
            db.get(Inventory, (hold.batch_id, hold.location)).status = "AVAILABLE"
        db.commit()
    return hold_out(hold)


@router.get("/wms/shipments")
def shipments(batch_id: str, db: Session = Depends(get_sim_db)):
    rows = db.scalars(select(Shipment).join(ShipmentLine, ShipmentLine.shipment_id == Shipment.shipment_id)
                      .where(ShipmentLine.batch_id == batch_id).order_by(Shipment.departs_at))
    return [shipment_out(db, s) for s in rows]


@router.get("/wms/shipments/{shipment_id}")
def shipment(shipment_id: str, db: Session = Depends(get_sim_db)):
    s = db.get(Shipment, shipment_id)
    if s is None:
        raise not_found("Shipment", shipment_id)
    return shipment_out(db, s)


class RemoveLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str = Field(min_length=1)


@router.post("/wms/shipments/{shipment_id}/remove-line")
def remove_line(shipment_id: str, body: RemoveLineRequest, idempotency_key: str = Header(min_length=1),
                db: Session = Depends(get_sim_db)):
    done = db.scalar(select(LineRemoval).where(LineRemoval.idempotency_key == idempotency_key))
    if done is None:
        s = db.get(Shipment, shipment_id)
        if s is None:
            raise not_found("Shipment", shipment_id)
        if s.status in SHIPPED_STATUSES:
            raise ApiError(409, "CONFLICT", f"Shipment {shipment_id} has already {s.status.lower()}")
        line = db.get(ShipmentLine, (shipment_id, body.batch_id))
        if line is None:
            raise not_found("Shipment line", f"{shipment_id}/{body.batch_id}")
        done = LineRemoval(shipment_id=shipment_id, batch_id=body.batch_id, qty=line.qty,
                           idempotency_key=idempotency_key, removed_at=now_iso())
        db.delete(line)
        db.add(done)
        db.commit()
    return {"shipment_id": done.shipment_id, "batch_id": done.batch_id, "qty": done.qty, "removed_at": done.removed_at}


# ---- Tickets (relabel work orders)

class TicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=1)
    batch_id: str | None = None
    summary: str = Field(min_length=1)
    case_ref: str = Field(min_length=1)


def ticket_out(t: Ticket) -> dict:
    return {"ticket_id": t.ticket_id, "sku": t.sku, "batch_id": t.batch_id, "summary": t.summary,
            "case_ref": t.case_ref, "status": t.status, "created_at": t.created_at}


@router.post("/tickets")
def create_ticket(body: TicketRequest, idempotency_key: str = Header(min_length=1), db: Session = Depends(get_sim_db)):
    ticket = db.scalar(select(Ticket).where(Ticket.idempotency_key == idempotency_key))
    if ticket:
        return JSONResponse(ticket_out(ticket), status_code=200)
    ticket = Ticket(ticket_id=f"T-{uuid.uuid4().hex[:8].upper()}", status="OPEN", created_at=now_iso(),
                    idempotency_key=idempotency_key, **body.model_dump())
    db.add(ticket)
    db.commit()
    return JSONResponse(ticket_out(ticket), status_code=201)


@router.get("/tickets")
def tickets(case_ref: str, db: Session = Depends(get_sim_db)):
    return [ticket_out(t) for t in db.scalars(select(Ticket).where(Ticket.case_ref == case_ref).order_by(Ticket.created_at))]


@router.get("/tickets/{ticket_id}")
def ticket(ticket_id: str, db: Session = Depends(get_sim_db)):
    t = db.get(Ticket, ticket_id)
    if t is None:
        raise not_found("Ticket", ticket_id)
    return ticket_out(t)


# ---- Outbox (external messages; nothing leaves the machine)

class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    case_ref: str = Field(min_length=1)


def message_out(m: OutboxMessage) -> dict:
    return {"message_id": m.message_id, "to": m.to, "subject": m.subject, "body": m.body, "case_ref": m.case_ref,
            "status": m.status, "created_at": m.created_at, "sent_at": m.sent_at}


@router.post("/outbox")
def create_draft(body: DraftRequest, idempotency_key: str = Header(min_length=1), db: Session = Depends(get_sim_db)):
    msg = db.scalar(select(OutboxMessage).where(OutboxMessage.idempotency_key == idempotency_key))
    if msg:
        return JSONResponse(message_out(msg), status_code=200)
    msg = OutboxMessage(message_id=f"M-{uuid.uuid4().hex[:8].upper()}", status="DRAFT", created_at=now_iso(),
                        idempotency_key=idempotency_key, **body.model_dump())
    db.add(msg)
    db.commit()
    return JSONResponse(message_out(msg), status_code=201)


@router.post("/outbox/{message_id}/send")
def send_message(message_id: str, db: Session = Depends(get_sim_db)):
    msg = db.get(OutboxMessage, message_id)
    if msg is None:
        raise not_found("Message", message_id)
    if msg.status == "DRAFT":  # sending twice is a no-op
        msg.status, msg.sent_at = "SENT", now_iso()
        db.commit()
    return message_out(msg)


@router.get("/outbox")
def outbox(case_ref: str, db: Session = Depends(get_sim_db)):
    rows = db.scalars(select(OutboxMessage).where(OutboxMessage.case_ref == case_ref).order_by(OutboxMessage.created_at))
    return [message_out(m) for m in rows]


@router.get("/outbox/{message_id}")
def message(message_id: str, db: Session = Depends(get_sim_db)):
    m = db.get(OutboxMessage, message_id)
    if m is None:
        raise not_found("Message", message_id)
    return message_out(m)


# ---- Labels

@router.get("/labels/{sku}")
def label(sku: str, db: Session = Depends(get_sim_db)):
    product = db.get(Product, sku)
    lbl = db.get(Label, (sku, product.label_version)) if product else None
    if lbl is None:
        raise not_found("Label", sku)
    return {"sku": lbl.sku, "version": lbl.version, "ingredient_statement": lbl.ingredient_statement,
            "contains": lbl.contains, "may_contain": lbl.may_contain, "claims": lbl.claims}


# ---- Admin

class Faults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wms_silent_hold_failure: bool


@router.get("/admin/faults")
def get_faults(db: Session = Depends(get_sim_db)):
    return {"wms_silent_hold_failure": fault_on(db, WMS_SILENT_HOLD_FAILURE)}


@router.put("/admin/faults")
def set_faults(body: Faults, db: Session = Depends(get_sim_db)):
    for name, enabled in body.model_dump().items():
        db.merge(Fault(name=name, enabled=enabled))
    db.commit()
    return {"ok": True}


@router.post("/admin/reset")
def reset(request: Request):
    source = reset_sim(request.app.state.sim_sessionmaker, request.app.state.settings.seed_dir)
    return {"ok": True, "seed_source": str(source)}
