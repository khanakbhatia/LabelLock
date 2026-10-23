import base64
import binascii

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.auth import ALL_ROLES, make_token, require_roles, verify_password
from api.db import Case, Notice, User, get_db, now_iso, to_iso
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


@router.post("/actions/{action_id}/approve")
def approve_action(action_id: str, user: User = Depends(require_roles("qa_manager"))):
    # Placeholder until approvals land in M1/M2; the role check above is already real.
    raise ApiError(501, "NOT_IMPLEMENTED", "Approving actions is not implemented yet", {"action_id": action_id})
