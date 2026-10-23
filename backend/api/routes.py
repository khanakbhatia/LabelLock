import base64
import binascii

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.auth import ALL_ROLES, make_token, require_roles, verify_password
from api.db import Case, Notice, NoticeAttachment, User, get_db, now_iso, to_iso
from api.errors import ApiError
from api.notices import (
    MAX_ATTACHMENT_BYTES, Upload, case_summary, check_pdf, create_notice_case, reject_attachments, resolve_sender,
    validate_uploads,
)

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


@router.post("/notices", status_code=201)
def submit_notice(
    request: Request,
    subject: str = Form(min_length=1),
    body: str = Form(min_length=1),
    attachment: UploadFile = File(),
    user: User = Depends(require_roles("supplier")),
    db: Session = Depends(get_db),
):
    if user.supplier_id is None:
        raise ApiError(403, "FORBIDDEN", "Supplier account is not linked to a supplier")
    data = attachment.file.read(MAX_ATTACHMENT_BYTES + 1)
    upload = Upload(attachment.filename or "attachment", attachment.content_type or "", data)
    validate_uploads([upload], field_prefix="attachment")
    notice, case = create_notice_case(
        db, upload_dir=request.app.state.settings.upload_dir, actor=user.username, source="supplier_portal",
        supplier_id=user.supplier_id, subject=subject, body=body, received_at=now_iso(), uploads=[upload],
    )
    return {"notice_id": notice.id, "case_id": case.id, "case_status": case.status}


def notice_case(db: Session, notice: Notice) -> Case:
    return db.scalar(select(Case).where(Case.notice_id == notice.id))


def first_attachment(db: Session, notice: Notice) -> NoticeAttachment | None:
    return db.scalar(select(NoticeAttachment).where(NoticeAttachment.notice_id == notice.id).order_by(NoticeAttachment.id).limit(1))


def visible_notice(db: Session, notice_id: str, user: User) -> Notice:
    """QA sees every notice; a supplier only its own. Anything else is 404, not 403, so ids don't leak."""
    notice = db.get(Notice, notice_id)
    if notice is None or (user.role == "supplier" and notice.supplier_id != user.supplier_id):
        raise ApiError(404, "NOT_FOUND", f"Notice {notice_id} not found", {"notice_id": notice_id})
    return notice


@router.get("/notices")
def my_notices(mine: bool, user: User = Depends(require_roles("supplier")), db: Session = Depends(get_db)):
    if not mine:
        raise ApiError(422, "VALIDATION_ERROR", "Only mine=true is supported", {"fields": [{"field": "query.mine", "message": "must be true"}]})
    notices = db.scalars(select(Notice).where(Notice.supplier_id == user.supplier_id).order_by(Notice.received_at.desc(), Notice.id))
    out = []
    for n in notices:
        case = notice_case(db, n)
        out.append({"id": n.id, "subject": n.subject, "received_at": n.received_at,
                    "has_attachment": first_attachment(db, n) is not None, "case_id": case.id, "case_status": case.status})
    return out


@router.get("/inbox")
def inbox(user: User = Depends(require_roles("qa_specialist", "qa_manager", "admin")), db: Session = Depends(get_db)):
    rows = db.execute(select(Notice, Case).join(Case, Case.notice_id == Notice.id).order_by(Notice.received_at.desc(), Notice.id))
    out = []
    for n, case in rows:
        summary = case_summary(db, case)
        out.append({"notice_id": n.id, "case_id": case.id, "supplier": summary["supplier"], "subject": n.subject,
                    "received_at": n.received_at, "has_attachment": first_attachment(db, n) is not None,
                    "case_status": case.status})
    return out


@router.get("/notices/{notice_id}")
def get_notice(notice_id: str, user: User = Depends(require_roles("qa_specialist", "qa_manager", "supplier")),
               db: Session = Depends(get_db)):
    n = visible_notice(db, notice_id, user)
    att = first_attachment(db, n)
    case = notice_case(db, n)
    return {"id": n.id, "supplier_id": n.supplier_id, "supplier": case_summary(db, case)["supplier"], "subject": n.subject,
            "body": n.body, "received_at": n.received_at, "content_hash": n.content_hash, "case_id": case.id,
            "attachment": {"filename": att.filename, "mime_type": att.mime_type, "size_bytes": att.size_bytes} if att else None}


@router.get("/notices/{notice_id}/attachment")
def get_attachment(notice_id: str, user: User = Depends(require_roles("qa_specialist", "qa_manager", "supplier")),
                   db: Session = Depends(get_db)):
    att = first_attachment(db, visible_notice(db, notice_id, user))
    if att is None:
        raise ApiError(404, "NOT_FOUND", f"Notice {notice_id} has no attachment", {"notice_id": notice_id})
    # Untrusted supplier file: served as a download, never rendered inline by the browser.
    return FileResponse(att.path, media_type="application/pdf", filename=att.filename,
                        headers={"X-Content-Type-Options": "nosniff"})


class IngestAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1)
    mime_type: str  # checked per file below so the 422 names the file
    content_base64: str


class IngestEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gmail_message_id: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=256)
    from_: str = Field(alias="from", min_length=1)
    subject: str
    body_text: str
    received_at: AwareDatetime
    attachments: list[IngestAttachment] = Field(max_length=10)


# base64 is 4 chars per 3 bytes; anything longer than this cannot decode to <= 5 MB.
_MAX_B64_CHARS = (MAX_ATTACHMENT_BYTES + 2) // 3 * 4


def decode_attachments(items: list[IngestAttachment]) -> list[Upload]:
    uploads, problems = [], []
    for i, a in enumerate(items):
        if len(a.content_base64) > _MAX_B64_CHARS:
            problems.append((f"attachments.{i}", f"{a.filename}: larger than 5 MB"))
            continue
        try:
            data = base64.b64decode(a.content_base64, validate=True)
        except (binascii.Error, ValueError):
            problems.append((f"attachments.{i}", f"{a.filename}: content_base64 is not valid standard base64"))
            continue
        upload = Upload(a.filename, a.mime_type, data)
        if msg := check_pdf(upload):
            problems.append((f"attachments.{i}", msg))
        uploads.append(upload)
    reject_attachments(problems)
    return uploads


@router.post("/notices/ingest-email")
def ingest_email(
    body: IngestEmailRequest,
    request: Request,
    user: User = Depends(require_roles("qa_specialist", "qa_manager")),
    db: Session = Depends(get_db),
):
    uploads = decode_attachments(body.attachments)
    address, supplier_id = resolve_sender(db, body.from_)
    try:
        notice, case = create_notice_case(
            db, upload_dir=request.app.state.settings.upload_dir, actor=user.username, source="gmail",
            supplier_id=supplier_id, subject=body.subject, body=body.body_text, received_at=to_iso(body.received_at),
            uploads=uploads, from_address=address, gmail_message_id=body.gmail_message_id,
            gmail_thread_id=body.thread_id,
        )
        status, duplicate = 201, False
    except IntegrityError:
        # Same message ingested before (or concurrently): the unique constraint kept one notice.
        db.rollback()
        notice = db.scalar(select(Notice).where(Notice.gmail_message_id == body.gmail_message_id))
        if notice is None:
            raise
        case = db.scalar(select(Case).where(Case.notice_id == notice.id))
        status, duplicate = 200, True
    return JSONResponse(
        {"notice_id": notice.id, "case_id": case.id, "case_status": case.status, "duplicate": duplicate},
        status_code=status,
    )


@router.get("/cases/by-message/{gmail_message_id}")
def case_by_message(
    gmail_message_id: str,
    user: User = Depends(require_roles("qa_specialist", "qa_manager", "shipping_supervisor")),
    db: Session = Depends(get_db),
):
    case = db.scalar(select(Case).join(Notice, Case.notice_id == Notice.id).where(Notice.gmail_message_id == gmail_message_id))
    if case is None:
        raise ApiError(404, "NOT_FOUND", "No case for this Gmail message", {"gmail_message_id": gmail_message_id})
    return case_summary(db, case)
