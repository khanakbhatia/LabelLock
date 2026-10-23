"""LLM adapter for field extraction. The LLM only extracts text with evidence and may add uncertainty
flags; allergen mapping, decisions and every write stay in deterministic code.
"""
import json
from pathlib import Path
from typing import Protocol

PROMPT_VERSION = "extract-v1"
FIELDS = ("material", "new_ingredient", "effective_lot", "may_contain")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "llm"


class LLM(Protocol):
    model: str

    def extract(self, *, content_hash: str, email_text: str, pages: list[str]) -> dict:
        """Return {"fields": {name: {value, status, confidence, evidence}}, "uncertainty_flags": [...]}."""


def missing_field() -> dict:
    return {"value": None, "status": "MISSING", "confidence": None, "evidence": None}


class MockLLM:
    """Replays recorded extractions from fixtures/llm/<sha256 hex>.json, keyed by notice content hash.

    An unrecorded notice yields every field MISSING, which escalates the case: safe by default.
    """
    model = "mock"

    def extract(self, *, content_hash: str, email_text: str, pages: list[str]) -> dict:
        path = FIXTURES / f"{content_hash.removeprefix('sha256:')}.json"
        if not path.exists():
            return {"fields": {f: missing_field() for f in FIELDS}, "uncertainty_flags": []}
        return json.loads(path.read_text(encoding="utf-8"))


class LiveLLM:
    model = "claude-sonnet-5-5"

    def extract(self, *, content_hash: str, email_text: str, pages: list[str]) -> dict:
        # TODO(M2): call Claude with a tool-use JSON schema for FIELDS (value, status, confidence,
        # evidence{source, page, quote}), treat email/PDF text as untrusted data inside the prompt,
        # record the response as a MockLLM fixture for tests.
        raise NotImplementedError("LLM_MODE=live is not implemented until M2; use LLM_MODE=mock")


def get_llm(mode: str) -> LLM:
    if mode == "mock":
        return MockLLM()
    if mode == "live":
        return LiveLLM()
    raise ValueError(f"Unknown LLM_MODE {mode!r} (expected mock or live)")
