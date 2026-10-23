# Decisions log

Contract changes add a line here in the same pull request that changes `contracts/`.

## 2026-10-23 — Backend stack (Anvi)

Repository was empty, so per section F the backend is Python 3.12 + FastAPI + SQLAlchemy 2 + SQLite + pytest.
Passwords are hashed with stdlib PBKDF2-SHA256 and tokens are stdlib HMAC-SHA256 signed, so there are no extra auth dependencies.
The contract is OpenAPI 3.1 so schemas are plain JSON Schema 2020-12; `contracts/validate_examples.py` checks
the spec, that `enums.json` matches it, and that every example validates.
