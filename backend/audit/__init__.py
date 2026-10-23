"""Append-only, hash-chained audit log (one chain per case)."""
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import AuditEvent, now_iso


def event_hash(prev_hash: str | None, case_id: str, ts: str, actor: str, kind: str, payload: dict) -> str:
    body = json.dumps(
        {"prev_hash": prev_hash, "case_id": case_id, "ts": ts, "actor": actor, "kind": kind, "payload": payload},
        sort_keys=True, separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


def append_event(db: Session, case_id: str, actor: str, kind: str, payload: dict) -> AuditEvent:
    """Add an event to the session; the caller commits it with the change it records."""
    # ponytail: read-then-insert chain head, not safe under concurrent writers to one case;
    # add a per-case lock or a unique (case_id, prev_hash) constraint when the agent writes in parallel.
    prev = db.scalar(select(AuditEvent.hash).where(AuditEvent.case_id == case_id).order_by(AuditEvent.id.desc()).limit(1))
    ts = now_iso()
    event = AuditEvent(case_id=case_id, ts=ts, actor=actor, kind=kind, payload=payload, prev_hash=prev,
                       hash=event_hash(prev, case_id, ts, actor, kind, payload))
    db.add(event)
    return event
