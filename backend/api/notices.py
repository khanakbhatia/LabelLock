"""The single notice -> case creation path, used by the Supplier Portal and Gmail ingest.

Notice bodies and attachments are untrusted supplier data: they are stored verbatim and never
read here for routing, roles or policy.
"""
import hashlib
from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.db import Action, Case, Notice, NoticeAttachment, Supplier, SupplierSender, new_id, now_iso
from api.errors import ApiError
from audit import append_event

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
PDF_MIME = "application/pdf"
SUPPLIER_UNVERIFIED = "SUPPLIER_UNVERIFIED"


@dataclass
class Upload:
    filename: str
    mime_type: str
    data: bytes


def check_pdf(upload: Upload) -> str | None:
    """Return a problem message naming the file, or None if it is an acceptable PDF."""
    if upload.mime_type != PDF_MIME:
        return f"{upload.filename}: only {PDF_MIME} is accepted (got {upload.mime_type})"
    if len(upload.data) > MAX_ATTACHMENT_BYTES:
        return f"{upload.filename}: larger than 5 MB"
    if not upload.data.startswith(b"%PDF-"):
        return f"{upload.filename}: not a PDF file"
    return None


def reject_attachments(problems: list[tuple[str, str]]) -> None:
    """problems: (field, message) pairs. Raises 422 VALIDATION_ERROR if there are any."""
    if problems:
        names = ", ".join(msg.split(":", 1)[0] for _, msg in problems)
        raise ApiError(422, "VALIDATION_ERROR", f"Attachment rejected: {names}",
                       {"fields": [{"field": f, "message": m} for f, m in problems]})


def validate_uploads(uploads: list[Upload], field_prefix: str = "attachments") -> None:
    reject_attachments([(f"{field_prefix}.{i}", msg) for i, u in enumerate(uploads) if (msg := check_pdf(u))])


def resolve_sender(db: Session, from_header: str) -> tuple[str, str | None]:
    """Return (address, supplier_id or None). Exact address match wins over domain match."""
    address = parseaddr(from_header)[1].strip().lower()
    domain = address.rpartition("@")[2]
    candidates = [address] + ([domain] if domain else [])
    rows = dict(db.execute(select(SupplierSender.match, SupplierSender.supplier_id).where(SupplierSender.match.in_(candidates))).all())
    supplier_id = rows.get(address) or rows.get(domain)
    return address, supplier_id


def notice_content_hash(subject: str, body: str, attachments: list[bytes]) -> str:
    """Identity of a notice's content; MockLLM fixtures are keyed by it."""
    digests = [hashlib.sha256(a).hexdigest() for a in attachments]
    return "sha256:" + hashlib.sha256("\n".join([subject, body, *digests]).encode()).hexdigest()


def store_file(upload_dir: Path, data: bytes) -> tuple[str, str]:
    """Content-addressed storage; returns (path, sha256). Writing the same bytes twice is harmless."""
    digest = hashlib.sha256(data).hexdigest()
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{digest}.pdf"
    if not path.exists():
        path.write_bytes(data)
    return str(path), digest


def create_notice_case(
    db: Session,
    *,
    upload_dir: Path,
    actor: str,
    source: str,
    supplier_id: str | None,
    subject: str,
    body: str,
    received_at: str,
    uploads: list[Upload],
    from_address: str | None = None,
    gmail_message_id: str | None = None,
    gmail_thread_id: str | None = None,
) -> tuple[Notice, Case]:
    """Store the notice, its attachments, a RECEIVED case and a NOTICE_RECEIVED audit event, then commit.

    Uploads must already be validated. Raises sqlalchemy IntegrityError (after rollback by the
    caller) when gmail_message_id already exists.
    """
    stored = [(u, *store_file(upload_dir, u.data)) for u in uploads]
    content_hash = notice_content_hash(subject, body, [u.data for u in uploads])
    flags = [] if supplier_id else [SUPPLIER_UNVERIFIED]

    notice = Notice(id=new_id("n"), source=source, supplier_id=supplier_id, from_address=from_address,
                    subject=subject, body=body, received_at=received_at, content_hash=content_hash,
                    gmail_message_id=gmail_message_id, gmail_thread_id=gmail_thread_id)
    db.add(notice)
    db.flush()  # hits the gmail_message_id unique constraint before anything else is written
    for u, path, digest in stored:
        db.add(NoticeAttachment(notice_id=notice.id, filename=u.filename, mime_type=u.mime_type,
                                size_bytes=len(u.data), sha256=digest, path=path))
    case = Case(id=new_id("c"), notice_id=notice.id, status="RECEIVED", uncertainty_flags=flags, opened_at=now_iso())
    db.add(case)
    db.flush()

    payload = {"source": source, "notice_id": notice.id, "supplier_id": supplier_id,
               "attachments": [u.filename for u in uploads], "uncertainty_flags": flags}
    if source == "gmail":
        payload |= {"gmail_message_id": gmail_message_id, "gmail_thread_id": gmail_thread_id, "from": from_address}
    append_event(db, case.id, actor, "NOTICE_RECEIVED", payload)
    db.commit()
    return notice, case


def case_summary(db: Session, case: Case) -> dict:
    notice = db.get(Notice, case.notice_id)
    supplier = db.get(Supplier, notice.supplier_id) if notice.supplier_id else None
    return {
        "id": case.id,
        "notice_id": notice.id,
        "status": case.status,
        "supplier": supplier.name if supplier else (notice.from_address or "Unverified sender"),
        "subject": notice.subject,
        "opened_at": case.opened_at,
        "contained_at": case.contained_at,
        "duplicate_of": case.duplicate_of,
        "pending_approvals": db.scalar(select(func.count()).select_from(Action)
                                       .where(Action.case_id == case.id, Action.status == "PENDING_APPROVAL")),
        "uncertainty_flags": case.uncertainty_flags,
    }
