# Decisions log

Contract changes add a line here in the same pull request that changes `contracts/`.

## 2026-10-23 — Backend stack (Anvi)

Repository was empty, so per section F the backend is Python 3.12 + FastAPI + SQLAlchemy 2 + SQLite + pytest.
Passwords are hashed with stdlib PBKDF2-SHA256 and tokens are stdlib HMAC-SHA256 signed, so there are no extra auth dependencies.
The contract is OpenAPI 3.1 so schemas are plain JSON Schema 2020-12; `contracts/validate_examples.py` checks
the spec, that `enums.json` matches it, and that every example validates.

## 2026-10-23 — Gmail ingest endpoints, contract v0.2 (Anvi)

Contract changes:
- Added `POST /notices/ingest-email` (qa_specialist, qa_manager) and `GET /cases/by-message/{gmail_message_id}`
  (qa_*, shipping_supervisor), with schemas `IngestEmailRequest`, `IngestEmailResponse`, `IngestAttachment`
  and examples `ingest_email_request/response/duplicate.json`, `case_by_message.json`.
- New enum `uncertainty_flag` in `enums.json` (`UncertaintyFlag` in openapi) with `SUPPLIER_UNVERIFIED`.
  `Extraction.uncertainty_flags` and `BatchDecision.uncertainty_flags` now use it instead of free strings.
- `CaseSummary.uncertainty_flags` is new and required (so the inbox and panel can show an unverified
  sender before the agent runs); `CaseDetail.uncertainty_flags` is optional. `case_summary_list.json` updated.
- Ingest rules: idempotent on `gmail_message_id` (unique constraint; repeat = 200 + `duplicate: true`);
  attachments must be declared `application/pdf`, start with `%PDF-`, be <= 5 MB decoded, <= 10 per message,
  and use standard base64 (not base64url, no line breaks); any violation = 422 naming the file in
  `message` and `details.fields[].message`.

Backend decisions:
- Sender identity: `supplier_senders` maps either a full address or a bare domain to a supplier; an exact
  address wins. Never list a public webmail domain (gmail.com) as a domain match; list the demo
  Gmail address itself.
- Supplier Portal `POST /notices` was implemented now so both sources share `create_notice_case`.
- Stub supplier list in `backend/dev_seed/suppliers.json` until the loader for `/data/seed` lands.
- `users.supplier_id` column added. SQLite tables are created, not migrated: delete an old `labellock.db`.

## 2026-10-23 — M1 agent: sim, seed, adapters, rules, mock extraction, orchestrator (Anvi)

Contract changes:
- `uncertainty_flag` gains `LLM_UNCERTAIN`, `EVIDENCE_MISMATCH`, `CRITICAL_FIELD_UNRESOLVED`.
- No shape changes to existing schemas. New values inside free-text fields that the UI should know:
  - `CaseReport.batches[].final_state`: `NO_ACTION`, `HELD`, `HELD_PENDING_REMOVAL`, `REMOVED_FROM_SHIPMENT`,
    `VERIFY_FAILED`, `ESCALATED`, `IN_PROGRESS`.
  - `AuditEvent.kind`: `NOTICE_RECEIVED`, `RUN_STARTED`, `STEP_STARTED`, `STEP_COMPLETED`, `EXTRACTION_COMPLETED`,
    `RULE_FIRED`, `ADAPTER_CALL`, `TRACE_COMPLETED`, `ACTION_CREATED`, `ACTION_STATUS_CHANGED`, `APPROVAL_REQUESTED`,
    `VERIFICATION`, `VERIFY_MISMATCH`, `ESCALATED`, `POLICY_VIOLATION`, `STATUS_CHANGED`, `REPORT_GENERATED`, `RUN_FAILED`.
  - `AuditEvent.id` is `e_000123` (zero-padded sequence).

Decisions:
- The sim runs in the same FastAPI process under `/sim/*` with its own database (`SIM_DATABASE_URL`) and
  `X-Sim-Key`; adapters reach it over HTTP at `SIM_BASE_URL` (tests use an in-process TestClient).
- A hold is per (batch, location). Fault `wms_silent_hold_failure` skips the first location (by name) of each
  batch while still answering 201. A repeated hold with the same Idempotency-Key re-asserts the hold.
- A failed verification leaves the action at `VERIFY_FAILED` (an `ESCALATED` audit event records the escalation)
  and the case `ESCALATED`; this keeps the failed action visible. A later run re-verifies it.
- Trace follows only the named lot (the ERP has no "lots of a material" endpoint, so "from lot X onward" does
  not include later lots yet).
- `allergens_added` is computed by `rules.allergens_in(new_ingredient)`, never by the LLM. The LLM output can only
  lower confidence (`LLM_UNCERTAIN` turns an affected batch into `UNCERTAIN_ESCALATE`, never the reverse).
- Evidence check normalises whitespace only; a FOUND field whose quote is not in the email or cited PDF page
  becomes AMBIGUOUS. A notice with no recorded mock extraction escalates with every field MISSING.
- `SUPPLIER_UNVERIFIED` cases are extracted, traced and decided, then escalate before any write.
- Approvals table and the approve/reject flow are M2; the adapter gate already refuses non-APPROVED actions.
- New tables require deleting an old `labellock.db` (create_all does not migrate).
