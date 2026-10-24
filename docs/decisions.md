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

## 2026-10-23 — M2 backend: notice reads, approvals, execution, dispositions, release (Anvi)

No contract shape changes; every new response validates against `openapi.yaml`. Behaviour the UI relies on:
- `GET /inbox`, `GET /notices?mine=true` (only `mine=true`; supplier sees notices whose supplier is theirs),
  `GET /notices/{id}` and `/attachment` (a supplier gets 404, not 403, for other suppliers' notices; the PDF is
  served with `X-Content-Type-Options: nosniff` as a download).
- `GET /approvals?status=` lists actions with `requires_approval`, newest first.
- `POST /actions/{id}/approve` records the decision and returns the action as `APPROVED`; the agent then runs in
  the background: a new `execute` step (between act and verify, re-run every time) calls the sim through the
  adapter gate, and verify re-reads it (shipment line gone; holds RELEASED). If a run is already in progress the
  approval is kept and an `EXECUTION_DEFERRED` event is written; the next run executes it.
- The adapter gate now needs both `status == APPROVED` and an `approvals` row decided by a qa_manager.
- `POST /actions/{id}/reject` needs a non-empty `reason`. A rejected `REMOVE_FROM_SHIPMENT` escalates the case
  (affected stock may ship); a rejected `RELEASE_HOLD` just leaves the hold on.
- Dispositions: qa_manager, batch must belong to the case, latest one wins. Release requests: no disposition, or
  `DESTROY` / `RETURN_TO_SUPPLIER` → 409 `POLICY_VIOLATION` (audited). Releasable: `RELEASE_AS_IS`, `RELABEL`, `REWORK`.
- `RELEASE_HOLD.target` is `{batch_id, hold_ids}` with `hold_ids` comma-separated (the contract allows string
  values only); one release covers every location this case held.
- New audit kinds: `APPROVAL_DECIDED`, `DISPOSITION_RECORDED`, `EXECUTION_DEFERRED`.
- Holds are shared physical state: a second case on the same lot, without a demo reset, finds the stock already
  HELD by the first case and verifies it as held. Reset before each demo scenario.

## 2026-10-23 — Live Claude extraction (Anvi)

- `LLM_MODE=live` calls Claude (`LLM_MODEL`, default `claude-opus-5-5`, effort `medium`) through the official
  `anthropic` SDK with a JSON-schema structured output (`output_config.format`), so the reply always parses into the
  four fields. `LLM_MODE=record` does the same and saves the result as the `MockLLM` fixture for that notice, so a
  real extraction can be replayed in tests and demos without a key. `mock` stays the default.
- Refusals: server-side `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) retries a safety decline on
  Anthropic's recommended model; `Extraction.model` records the model that actually served it.
- The PDF is sent as the same pypdf page text the evidence check uses, so verbatim quotes can match; page N in the
  prompt is page N in evidence.
- Prompt injection: the notice is only in the user turn, wrapped in tags with a random per-call suffix that the
  system prompt names as untrusted data. The LLM still cannot act: allergens come from `rules`, writes from the agent,
  and the evidence check downgrades any quote not found verbatim.
- Failure handling: refusal, truncation or unparseable output -> every field MISSING + `LLM_UNCERTAIN` (the case
  escalates); API errors and missing credentials -> `UPSTREAM_FAILED`, the run fails and the case escalates with
  the reason in the `RUN_FAILED` event. A failed extraction is never recorded as a fixture.

## 2026-10-23 — Eval suite, benchmarks, ROI metrics (Anvi)

- `backend/scenarios/scenarios.json`: 20 scenarios (notice + expected status, per-batch decisions with allowed
  alternatives, batches that must stay untouched). PDFs are generated from text by `scenarios/pdf.py`, so content
  hashes are reproducible. Scenarios use the stub seed (extended; RM-114 / VL-2291 data unchanged).
- `python -m scenarios.runner` runs every scenario through the real API in mock mode (free, deterministic);
  `--record-missing` calls Claude only for notices with no recording and saves them. All 20 notices are recorded
  (16 live calls to claude-opus-5-5, $0.267 total). Only recording runs (or `--save`) write
  `scenarios/results/latest.json`, so the real-latency run is not overwritten by replays.
- Recorded result: 16/20 pass, 0 false holds, batch recall 0.909, decision accuracy 0.844, median agent time 4.5 s
  (live Claude). The 4 failures are kept as named `known_gap`s, not hidden by loosening expectations:
  - S03 / and S16, S17 (pass, but by escalating): `LLM_UNCERTAIN` -> `UNCERTAIN_ESCALATE` places no protective holds
    (M1 spec). Proposal: hold and escalate, since a hold is reversible.
  - S04: one-off lot deviation reads as AMBIGUOUS `effective_lot` (prompt defines it as the first lot of a change).
  - S11: a certificate ("lot X is soy lecithin") reads as AMBIGUOUS; safe but a false alarm.
  - S19: `may_contain` is extracted but rules ignore it; precautionary statements escalate instead of HOLD_RELABEL.
  The pytest gate fails on any unexpected failure and on a known gap that starts passing.
- `POST /benchmarks` (qa_*, admin): manual or agent timed runs; unknown scenario ids -> 422.
  `GET /metrics/roi`: `measured` = benchmark rows + the last eval file (agent timings only where Claude was live);
  `assumptions` from `backend/config/roi_assumptions.json` (editable inputs, never results).
- Contract examples added: `benchmark.json`, `roi_summary.json` (no schema changes).

## 2026-10-23 — Policy: uncertain batches are held, then escalated (Anvi; supersedes M1 item 13 for UNCERTAIN_ESCALATE)

- `UNCERTAIN_ESCALATE` batches now get protective `PLACE_HOLD` at every location with stock (holds are reversible),
  and the case still ends `ESCALATED` for a human. `REMOVE_FROM_SHIPMENT` is still only requested for confirmed
  decisions (`HOLD`, `HOLD_RELABEL`, `CLAIM_CONFLICT`); `SHIPPED_ESCALATE` still creates no writes.
- Why: the eval showed that a notice which only makes the model unsure (S03), or a prompt injection (S16, S17),
  left affected stock AVAILABLE while waiting for a human.
- Eval: scenarios gain `must_hold` (batches that must end with a VERIFIED hold); S03 is no longer a known gap.
  Mock rerun: 17/20 pass, 0 false holds, decision accuracy 0.911, escalation accuracy 0.75 (the 3 wrong escalations
  are the 3 remaining known gaps: S04, S11, S19). Escalation is scored correct when `ESCALATED` is an allowed outcome.
- `latest.json` from a replay run keeps each scenario's last live-measured `live_agent_seconds` (replays have no real
  Claude latency); `/metrics/roi` reads only those.

## 2026-10-23 — Known gaps closed; GET /scenarios and GET /demo/faults (Anvi)

- Precautionary statements (S19): `may_contain` allergens enter decisions as cross-contact. A new "may contain X"
  that the label does not already declare (in contains or may-contain) is `HOLD_RELABEL` with rule
  `LBL-MISSING-PRECAUTION`; it can also break a free-from claim. A notice that only adds a precautionary statement
  no longer counts as missing `new_ingredient`. Contract: `AllergenAdded.precautionary` (optional boolean, additive).
- Extraction prompt `extract-v2` (S04, S11): `effective_lot` covers the specific lot of a one-off deviation or
  certificate, and a plain statement ("lot X is soy lecithin") is not ambiguous. All 17 unique notices were
  re-recorded with v2 (17 calls to claude-opus-5-5, $0.278) so the suite measures the prompt that ships; fixtures
  now carry `prompt_version`, and replays report it.
- Result (live recording run): 20/20 pass, 0 false holds, decision accuracy 1.0, batch recall 1.0, escalation
  accuracy 1.0, median agent time 4.2 s. No known gaps remain. With v2, S03 and S17 are no longer flagged uncertain;
  only S16 (injection in the PDF) is, so the hold-and-escalate policy is now pinned by a model-independent agent test.
- `GET /scenarios` (qa_*, admin): id and notice subject only - titles and expected outcomes would give a manual
  tester the answer. `GET /demo/faults` (admin, DEMO_MODE): current fault state, via new `GET /sim/admin/faults`.

## 2026-10-23 — Relabel tickets, retailer notices, supplier queries (Anvi; P1)

Follows the role table: the agent may create tickets and drafts; anything sent outside the company needs a qa_manager.
- `CREATE_RELABEL_TICKET` (no approval): one per SKU whose batches are `HOLD_RELABEL` or `CLAIM_CONFLICT` (a label is
  per SKU), target `{sku}`, created in `/sim/tickets` during act and VERIFIED by re-reading the ticket.
  `result = {ticket_id, summary}`. Not for `HOLD`, `UNCERTAIN_ESCALATE` or `SHIPPED_ESCALATE`.
- `SEND_RETAILER_NOTICE` (approval): for each `SHIPPED_ESCALATE` batch on a departed/delivered shipment, target
  `{batch_id, shipment_id, to}`. Stock removed from a shipment before departure needs no notice.
- `SEND_SUPPLIER_QUERY` (approval): when the agent stops on a notice it cannot act on (critical field missing or
  ambiguous, lot not found, material mismatch), target `{notice_id, to}`; `to` is the sender address for Gmail
  notices or `supplier-portal:<supplier_id>`. Never for an unverified sender (`SUPPLIER_QUERY_SKIPPED` event):
  replying could reach an impersonator.
- Messages are drafted in `/sim/outbox` at once (`result = {draft_id, to, subject, body}`, so the UI can show the
  text before approving); approving runs the agent, which sends through the adapter gate and VERIFIES status SENT
  (`result.sent_at`). A rejected message stays a draft. All text is built from rules and case data, not the LLM.
- Fix: a case that stopped early (escalated) skipped every later step, so approvals on it were never carried out.
  `execute` and `verify` now always run (they only act on approved actions and re-read); a stopped case still
  decides nothing new.
- Eval: scenarios assert `tickets`, `retailer_notices` and `supplier_query`; 20/20 pass. The unverified-sender
  guard is covered by pytest (no eval scenario reaches it).

## 2026-10-24 — Governance fixes from the judge-style audit (Anvi)

- `GET /cases/{id}/audit/verify` (qa_*, shipping_supervisor): recomputes the case's hash chain oldest first and returns
  `{valid, events, first_invalid_event_id}`. Contract: new schema `AuditVerification`, example `audit_verification.json`.
  The case timeline shows the result. Demo reset still deletes audit events (it deletes the cases too).
- The `agent` service account can no longer sign in: `POST /auth/login` returns 403 `FORBIDDEN` (contract: 403 added).
  The account still exists for attribution; the agent acts in-process.
- The backend refuses to start with the shipped `AUTH_SECRET` or `SIM_API_KEY` unless `DEMO_MODE=true`.
- ROI defaults are labelled as unsourced illustrative placeholders in `roi_assumptions.json` and on the ROI page.
