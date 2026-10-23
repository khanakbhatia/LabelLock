"""LiveLLM against a fake Anthropic client: request shape, parsing, refusals, errors, recording. No network."""
import json
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx
import pytest

import agent.llm as llm_mod
from agent.extract import check_evidence, pdf_pages
from agent.llm import FIELDS, OUTPUT_SCHEMA, LiveLLM, MockLLM, RecordingLLM, get_llm
from api.errors import ApiError

NOTICES = Path(__file__).parent / "fixtures" / "notices"
BODY = (NOTICES / "vl2291_body.txt").read_text(encoding="utf-8")
PAGES = pdf_pages([NOTICES / "RM-114_spec_rev4.pdf"])

GOOD = {
    "fields": {
        "material": {"value": "Lecithin (RM-114)", "status": "FOUND", "confidence": 0.97,
                     "evidence": {"source": "attachment", "page": 1, "quote": "Product: Lecithin, code RM-114"}},
        "new_ingredient": {"value": "soy lecithin", "status": "FOUND", "confidence": 1.4,
                           "evidence": {"source": "email", "page": None, "quote": "will be supplied as soy lecithin"}},
        "effective_lot": {"value": "VL-2291", "status": "FOUND", "confidence": 0.99,
                          "evidence": {"source": "email", "page": None, "quote": "from lot VL-2291 onward"}},
        "may_contain": {"value": "junk", "status": "MISSING", "confidence": 0.2, "evidence": None},
    },
    "uncertainty_flags": [],
}


class FakeClient:
    """Stands in for anthropic.Anthropic: records the request, returns a canned response or raises."""

    def __init__(self, response=None, error=None):
        self.calls, self.response, self.error = [], response, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def reply(data, stop_reason="end_turn", model="claude-opus-5-5"):
    text = data if isinstance(data, str) else json.dumps(data)
    content = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=content, stop_reason=stop_reason, model=model)


def extract(client):
    return LiveLLM(client=client).extract(content_hash="sha256:abc", email_text=BODY, pages=PAGES)


def test_request_shape():
    client = FakeClient(reply(GOOD))
    extract(client)
    req = client.calls[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["output_config"]["effort"] == "medium"
    assert req["output_config"]["format"] == {"type": "json_schema", "schema": OUTPUT_SCHEMA}
    assert (req["fallbacks"], req["betas"]) == ("default", ["server-side-fallback-2026-07-01"])
    assert "thinking" not in req and "temperature" not in req and "tool_choice" not in req
    # notice text only in the user turn, fenced with a per-call random boundary the system prompt names
    user = req["messages"][0]["content"]
    assert BODY in user and PAGES[0] in user and "Lecithin" not in req["system"]
    tag = user.split(">", 1)[0].lstrip("<")             # e.g. email_3f9c...
    assert tag.startswith("email_") and tag.split("_", 1)[1] in req["system"]
    assert 'page="1"' in user and 'page="2"' in user


def test_boundary_changes_every_call():
    client = FakeClient(reply(GOOD))
    extract(client)
    extract(client)
    first, second = (c["messages"][0]["content"].split(">", 1)[0] for c in client.calls)
    assert first != second


def test_good_reply_is_cleaned_and_passes_the_evidence_check():
    result = extract(FakeClient(reply(GOOD, model="claude-opus-5-5")))
    assert set(result["fields"]) == set(FIELDS) and result["model"] == "claude-opus-5-5"
    assert result["fields"]["new_ingredient"]["confidence"] == 1.0          # clamped
    assert result["fields"]["may_contain"] == {"value": None, "status": "MISSING", "confidence": None, "evidence": None}
    checked, downgraded = check_evidence(result["fields"], BODY, PAGES)
    assert downgraded == []


def test_fallback_model_is_reported():
    assert extract(FakeClient(reply(GOOD, model="claude-opus-4-8")))["model"] == "claude-opus-4-8"


@pytest.mark.parametrize("response", [
    reply("", stop_reason="refusal"),
    reply('{"fields": {', stop_reason="max_tokens"),
    reply("not json"),
    reply({"fields": {}, "uncertainty_flags": []}),
])
def test_unusable_replies_escalate_instead_of_guessing(response):
    result = extract(FakeClient(response))
    assert result["uncertainty_flags"] == ["LLM_UNCERTAIN"]
    assert all(f["status"] == "MISSING" for f in result["fields"].values())


def _status_error(cls, status):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=request, headers={"request-id": "req_x"}), body=None)


@pytest.mark.parametrize("error,needle", [
    (_status_error(anthropic.AuthenticationError, 401), "ANTHROPIC_API_KEY"),
    (_status_error(anthropic.RateLimitError, 429), "rate limit"),
    (_status_error(anthropic.InternalServerError, 500), "500"),
    (anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")), "reach"),
    (TypeError("Could not resolve authentication method. Expected one of api_key, ..."), "No Claude credentials"),
])
def test_api_errors_become_upstream_failed(error, needle):
    with pytest.raises(ApiError) as e:
        extract(FakeClient(error=error))
    assert (e.value.status, e.value.code) == (502, "UPSTREAM_FAILED") and needle in e.value.message


def test_api_error_reason_is_kept():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": "Your credit balance is too low"}}
    err = anthropic.BadRequestError("Error code: 400", response=httpx.Response(400, request=request), body=body)
    with pytest.raises(ApiError) as e:
        extract(FakeClient(error=err))
    assert e.value.message == "Claude API error 400: Your credit balance is too low"


def test_unrelated_type_errors_are_not_swallowed():
    with pytest.raises(TypeError, match="unexpected keyword"):
        extract(FakeClient(error=TypeError("create() got an unexpected keyword argument 'fallbacks'")))


def test_live_run_without_credentials_escalates_with_a_clear_reason(tmp_path, monkeypatch):
    """End to end through the agent: LLM_MODE=live with no key -> RUN_FAILED with the reason, case ESCALATED."""
    from fastapi.testclient import TestClient
    from api.main import create_app
    from api.settings import Settings
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(llm_mod, "LiveLLM", lambda model: LiveLLM(model, client=FakeClient(
        error=TypeError("Could not resolve authentication method."))))
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'a.db').as_posix()}", auth_secret="t", llm_mode="live",
                        sim_database_url=f"sqlite:///{(tmp_path / 's.db').as_posix()}", sim_api_key="k",
                        upload_dir=tmp_path / "u", seed_dir=tmp_path / "none")
    app = create_app(settings)
    app.state.sim_http = TestClient(app)
    c = TestClient(app)
    tok = lambda u: {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": u, "password": "demo"}).json()["token"]}
    case_id = c.post("/api/notices", data={"subject": "s", "body": BODY}, headers=tok("valley.ingredients"),
                     files={"attachment": ("a.pdf", (NOTICES / "RM-114_spec_rev4.pdf").read_bytes(), "application/pdf")}).json()["case_id"]
    c.post(f"/api/cases/{case_id}/run", headers=tok("priya.qa"))
    case = c.get(f"/api/cases/{case_id}", headers=tok("priya.qa")).json()
    failed = [e for e in c.get(f"/api/cases/{case_id}/timeline", headers=tok("priya.qa")).json() if e["kind"] == "RUN_FAILED"]
    assert case["status"] == "ESCALATED" and case["actions"] == []
    assert "No Claude credentials" in failed[0]["payload"]["message"]


def test_record_mode_saves_a_fixture_mock_replays(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_mod, "FIXTURES", tmp_path)
    recorded = RecordingLLM(client=FakeClient(reply(GOOD))).extract(content_hash="sha256:feed", email_text=BODY, pages=PAGES)
    assert (tmp_path / "feed.json").exists()
    replayed = MockLLM().extract(content_hash="sha256:feed", email_text="", pages=[])
    assert replayed["fields"] == recorded["fields"]

    RecordingLLM(client=FakeClient(reply("", stop_reason="refusal"))).extract(content_hash="sha256:bad", email_text="", pages=[])
    assert not (tmp_path / "bad.json").exists()  # never record a failed extraction


def test_get_llm_modes():
    assert isinstance(get_llm("mock"), MockLLM)
    with pytest.raises(ValueError):
        get_llm("other")


def test_schema_is_strict_enough_for_structured_outputs():
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "object" in (node.get("type") or []):
                assert node.get("additionalProperties") is False and set(node["required"]) == set(node["properties"])
            for v in node.values():
                walk(v)
    walk(OUTPUT_SCHEMA)
