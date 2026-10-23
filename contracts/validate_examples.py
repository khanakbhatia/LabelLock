"""Check that openapi.yaml is valid, matches enums.json, and that every example validates.

Run: python contracts/validate_examples.py   (needs pyyaml, jsonschema, openapi-spec-validator)
"""
import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate as validate_spec

HERE = Path(__file__).parent

# example file -> schema name, or ("array", schema name) for list responses
EXAMPLES = {
    "login.json": "LoginResponse",
    "me.json": "User",
    "inbox.json": ("array", "InboxItem"),
    "notice.json": "Notice",
    "case_summary_list.json": ("array", "CaseSummary"),
    "case_detail.json": "CaseDetail",
    "approvals.json": ("array", "Action"),
    "timeline.json": ("array", "AuditEvent"),
    "case_report.json": "CaseReport",
    "error_forbidden.json": "Error",
    "error_policy_violation.json": "Error",
    "ingest_email_request.json": "IngestEmailRequest",
    "ingest_email_response.json": "IngestEmailResponse",
    "ingest_email_duplicate.json": "IngestEmailResponse",
    "case_by_message.json": "CaseSummary",
    "benchmark.json": "Benchmark",
    "roi_summary.json": "RoiSummary",
}

# enums.json key -> openapi schema name
ENUMS = {
    "case_status": "CaseStatus",
    "field_status": "FieldStatus",
    "batch_decision": "BatchDecisionValue",
    "action_type": "ActionType",
    "action_status": "ActionStatus",
    "role": "Role",
    "uncertainty_flag": "UncertaintyFlag",
}


def load_spec():
    return yaml.safe_load((HERE / "openapi.yaml").read_text(encoding="utf-8"))


def validate_example(spec, data, target):
    ref = {"$ref": f"#/components/schemas/{target[1] if isinstance(target, tuple) else target}"}
    schema = {"type": "array", "items": ref} if isinstance(target, tuple) else ref
    # The whole spec is the root document so #/components/... refs resolve.
    root = {"components": spec["components"], **schema}
    validator = Draft202012Validator(root, format_checker=Draft202012Validator.FORMAT_CHECKER)
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in validator.iter_errors(data)]


def validate_all():
    errors = []
    spec = load_spec()
    try:
        validate_spec(spec)
    except Exception as e:  # report, don't crash, so the other checks still run
        errors.append(f"openapi.yaml invalid: {e}")

    enums = json.loads((HERE / "enums.json").read_text(encoding="utf-8"))
    for key, schema_name in ENUMS.items():
        if enums.get(key) != spec["components"]["schemas"][schema_name]["enum"]:
            errors.append(f"enums.json[{key}] does not match openapi {schema_name}")
    if set(enums) != set(ENUMS):
        errors.append(f"enums.json keys {sorted(enums)} differ from {sorted(ENUMS)}")

    files = {p.name for p in (HERE / "examples").glob("*.json")}
    for name in sorted(files - set(EXAMPLES)):
        errors.append(f"examples/{name}: no schema mapping in validate_examples.py")
    for name, target in EXAMPLES.items():
        path = HERE / "examples" / name
        if not path.exists():
            errors.append(f"examples/{name}: missing")
            continue
        for msg in validate_example(spec, json.loads(path.read_text(encoding="utf-8")), target):
            errors.append(f"examples/{name}: {msg}")
    return errors


if __name__ == "__main__":
    errs = validate_all()
    for e in errs:
        print("FAIL", e)
    print(f"{len(EXAMPLES)} examples checked, {len(errs)} problem(s)")
    sys.exit(1 if errs else 0)
