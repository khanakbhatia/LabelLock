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
