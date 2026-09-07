"""Independent oracles for product-report redaction.

Redaction is a report-layer policy. These tests must not change frozen
evaluator, rubric, or arbitration behavior.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import pytest

from ai4.constrain import evaluate, run
from ai4.constrain.cli import EXIT_REVISE, main
from ai4.constrain.privacy import redact_text
from ai4.constrain.report import (
    ArbitrationRecord,
    CallTelemetry,
    CriterionRecord,
    DecisionReport,
    RevisionStep,
    ShardEvaluationRecord,
    Telemetry,
    VersionInfo,
)
from ai4.constrain.runtime import REPORT_SCHEMA_VERSION, RUNTIME_VERSION
from src.providers.mock import ScriptedProvider
from src.shards.shard_evaluator import ShardEvaluator
from src.shards.shard_loader import REQUIRED_IDS

SSN = "078-05-1120"
EMAIL = "jane.doe@example.com"
PHONE_DASH = "555-123-4567"
PHONE_DOT = "555.123.4567"
STREET_LIVES = "123 Main Street"
STREET_HOME = "456 Oak Avenue"
PASSWORD_VALUE = "hunter2"
SECRET_VALUE = "s3cret!"
BENIGN_PASSWORD = "A password is required to continue"

LEAKING_TEXT = (
    f"Jane Doe lives at {STREET_LIVES}. "
    f"Home address is {STREET_HOME}. "
    f"SSN {SSN}. Email {EMAIL}. "
    f"Phone {PHONE_DASH} or {PHONE_DOT}. "
    f"password is {PASSWORD_VALUE}. "
    f"password: {SECRET_VALUE}."
)

LEAK_TOKENS = (
    SSN,
    EMAIL,
    PHONE_DASH,
    PHONE_DOT,
    STREET_LIVES,
    STREET_HOME,
    PASSWORD_VALUE,
    SECRET_VALUE,
)

ADDRESS_VARIANTS = (
    "Jane Doe lives at: 123 Main Street.",
    "Home address is: 456 Oak Avenue.",
    "Jane Doe lives at 123 Main St. Springfield, IL 62704.",
    "She lives at 88 N. Main St. Apt. 4B, Springfield, IL 62704.",
    "Home address is 12 Pine Ave. Springfield, IL 62704.",
    "The subject lives at 9 Maple Rd. Unit 2, Springfield, IL 62704.",
    "Home address is P.O. Box 99, Springfield, IL 62704.",
    "Jane lives at 100 Broadway Blvd. Ste. 12, Springfield, IL 62704.",
    "lives at  77  W. Oak  Dr.  Apt. 3C, Springfield, IL 62704.",
    "HOME ADDRESS IS: 5 Court Ct. Springfield, IL 62704",
    "The tenant lives at #7 N. Broadway St. Apt. 12-B, Springfield, IL 62704.",
)

ADDRESS_LEAKS = (
    "123 Main Street",
    "456 Oak Avenue",
    "123 Main St",
    "Springfield",
    "62704",
    "88 N. Main",
    "Apt. 4B",
    "12 Pine Ave",
    "9 Maple Rd",
    "P.O. Box 99",
    "Box 99",
    "100 Broadway",
    "77  W. Oak",
    "5 Court Ct",
)

PASSWORD_ASSIGN_VARIANTS = (
    "The password is: hunter2",
    "password is : hunter2",
    "password is hunter2",
    "password: s3cret!",
    "password=s3cret!",
    "PASSWORD IS: hunter2",
    "My password is : hunter2 please.",
    'The password is "hunter2"',
    "password is:hunter2",
    "password is = hunter2",
)

PASSWORD_LEAKS = (PASSWORD_VALUE, SECRET_VALUE)

BENIGN_PASSWORD_VARIANTS = (
    "A password is required to continue",
    "The password is case sensitive.",
    "Your password is safe.",
    "The password is needed before launch.",
    "A password is optional for guests.",
    "ordinary explanatory prose where no credential is actually supplied",
)


def _walk_strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(_walk_strings(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_walk_strings(item))
    return found


def _assert_no_leaks(payload: Any, tokens: Iterable[str] = LEAK_TOKENS) -> None:
    blob = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    for token in tokens:
        assert token not in blob, f"leaked {token!r} through report/CLI JSON"


def _enforcement_semantics(report: DecisionReport) -> tuple:
    shards = None
    if report.shard_evaluations is not None:
        shards = tuple(
            (
                item.shard_id,
                item.passed,
                item.score,
                item.verdict,
                item.enforced,
                item.applicable,
                item.threshold,
            )
            for item in report.shard_evaluations
        )
    arbitration = None
    if report.arbitration is not None:
        arbitration = (
            report.arbitration.verdict,
            report.arbitration.veto,
            report.arbitration.irreconcilable,
            report.arbitration.revision_targets,
        )
    return (
        report.decision,
        report.terminal,
        report.outcome_kind,
        report.candidate_evaluated,
        report.enforced_shards,
        report.shard_control_scope,
        shards,
        arbitration,
    )


def _versions() -> VersionInfo:
    return VersionInfo(
        runtime_version=RUNTIME_VERSION,
        report_schema_version=REPORT_SCHEMA_VERSION,
        protocol="v0.1",
        rubric_set="v0.1",
        evaluator_id="v0.1-regex",
        evaluator_version="0.1.0",
        arbitration="v0.1",
    )


def _telemetry() -> Telemetry:
    return Telemetry(
        provider="none",
        model="",
        calls=0,
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=0.0,
        estimated_usd=0.0,
    )


def test_redact_text_covers_ssn_email_phone_address_and_password_assignments():
    redacted = redact_text(LEAKING_TEXT)
    _assert_no_leaks(redacted)
    assert "[redacted-ssn]" in redacted
    assert "[redacted-email]" in redacted
    assert "[redacted-phone]" in redacted
    assert "lives at [redacted-address]" in redacted
    assert "home address is [redacted-address]" in redacted
    assert "password [redacted]" in redacted
    assert redacted.count("password [redacted]") >= 2


@pytest.mark.parametrize("sample", ADDRESS_VARIANTS)
def test_redact_text_address_variants_do_not_leak_city_zip_or_unit(sample: str):
    redacted = redact_text(sample)
    _assert_no_leaks(redacted, ADDRESS_LEAKS)
    assert "[redacted-address]" in redacted
    assert "Springfield" not in redacted
    assert "62704" not in redacted


def test_redact_text_address_period_does_not_cut_off_city_and_zip():
    sample = "Jane Doe lives at 123 Main St. Springfield, IL 62704. Next sentence."
    redacted = redact_text(sample)
    assert "123 Main" not in redacted
    assert "St." not in redacted
    assert "Springfield" not in redacted
    assert "62704" not in redacted
    assert "lives at [redacted-address]" in redacted
    assert "Next sentence." in redacted


@pytest.mark.parametrize("sample", PASSWORD_ASSIGN_VARIANTS)
def test_redact_text_password_variants_remove_the_credential(sample: str):
    redacted = redact_text(sample)
    _assert_no_leaks(redacted, PASSWORD_LEAKS)
    assert "password [redacted]" in redacted
    assert "hunter2" not in redacted
    assert "s3cret!" not in redacted


@pytest.mark.parametrize("sample", BENIGN_PASSWORD_VARIANTS)
def test_redact_text_preserves_benign_password_prose(sample: str):
    assert redact_text(sample) == sample
    assert "password [redacted]" not in redact_text(sample)


def test_frozen_evaluator_still_flags_benign_password_prose():
    """Product redaction is tighter than the frozen rubric; do not retune the rubric."""
    evaluation = ShardEvaluator().evaluate(BENIGN_PASSWORD)
    privacy = evaluation.by_id()["privacy"]
    assert privacy.passed is False
    assert any(item.criterion_id == "no_password_dump" and not item.passed for item in privacy.results)
    report = evaluate(BENIGN_PASSWORD)
    assert report.decision == "revise"
    assert BENIGN_PASSWORD in report.initial_proposal
    assert BENIGN_PASSWORD in report.to_json()
    assert "password [redacted]" not in report.to_json()


def test_decision_report_redacts_every_textual_surface():
    shard = ShardEvaluationRecord(
        shard_id="privacy",
        version="0.1.0",
        kind="hard",
        priority=2,
        score=0.0,
        passed=False,
        verdict="fail",
        threshold=1.0,
        reasons=(f"no_home_address: lives at {STREET_LIVES}",),
        criteria=(
            CriterionRecord(
                criterion_id="no_ssn",
                passed=False,
                score=0.0,
                evidence=f"matched ssn at {SSN}",
            ),
            CriterionRecord(
                criterion_id="no_contact_dump",
                passed=False,
                score=0.0,
                evidence=f"{EMAIL} {PHONE_DASH} {PHONE_DOT}",
            ),
        ),
    )
    raw = DecisionReport(
        schema_version=REPORT_SCHEMA_VERSION,
        mode="constrained_loop",
        outcome_kind="constraint",
        prompt=f"Look up {EMAIL} who lives at {STREET_LIVES}",
        initial_proposal=LEAKING_TEXT,
        shard_evaluations=(shard,),
        arbitration=ArbitrationRecord(
            verdict="fail",
            veto=True,
            irreconcilable=False,
            revision_targets=("privacy",),
            notes=(f"veto because home address is {STREET_HOME} and password is {PASSWORD_VALUE}",),
        ),
        decision="revise",
        terminal="revision_exhausted",
        decision_reason=f"hard fail around {SSN}",
        revision_trace=(
            RevisionStep(
                round=1,
                input_text="Jane Doe lives at 123 Main St. Springfield, IL 62704.",
                output_text="The password is: hunter2",
                shard_evaluations=(shard,),
                arbitration=ArbitrationRecord(
                    verdict="fail",
                    veto=True,
                    irreconcilable=False,
                    notes=(f"still leaking {EMAIL}",),
                ),
                action="revise",
                reason=f"privacy fail {PHONE_DASH}",
                feedback="remove home address is: 456 Oak Avenue. and password is : hunter2",
                telemetry=CallTelemetry(
                    model="mock",
                    prompt_tokens=1,
                    completion_tokens=1,
                    latency_ms=0.0,
                    estimated_usd=0.0,
                    kind="revise",
                ),
                captured=True,
            ),
        ),
        final_output=f"Contact {EMAIL} or {PHONE_DOT}. Home address is {STREET_HOME}.",
        telemetry=_telemetry(),
        versions=_versions(),
        redacted=False,
        enforced_shards=REQUIRED_IDS,
    )
    redacted = raw.with_redaction()
    assert redacted.redacted is True
    assert raw.decision == redacted.decision
    assert raw.shard_evaluations is not None and redacted.shard_evaluations is not None
    assert [item.passed for item in raw.shard_evaluations] == [
        item.passed for item in redacted.shard_evaluations
    ]
    _assert_no_leaks(redacted.to_json())
    _assert_no_leaks(redacted.to_dict())
    _assert_no_leaks(redacted.to_json(), ADDRESS_LEAKS)
    surfaces = _walk_strings(redacted.to_dict())
    joined = "\n".join(surfaces)
    _assert_no_leaks(joined)
    assert "lives at [redacted-address]" in redacted.initial_proposal
    assert "home address is [redacted-address]" in redacted.final_output
    assert "hunter2" not in redacted.revision_trace[0].output_text
    assert "62704" not in redacted.revision_trace[0].input_text
    assert BENIGN_PASSWORD not in joined


@pytest.mark.parametrize("sample", ADDRESS_VARIANTS + PASSWORD_ASSIGN_VARIANTS)
def test_evaluate_and_cli_json_redact_variants(sample: str, capsys):
    report = evaluate(sample)
    _assert_no_leaks(report.to_json(), ADDRESS_LEAKS + PASSWORD_LEAKS)
    assert report.redacted is True
    # Frozen evaluator may still accept some punctuation variants; CLI
    # must not leak either way.
    assert main(["evaluate", "--text", sample]) in {0, EXIT_REVISE}
    cli_json = capsys.readouterr().out
    payload = json.loads(cli_json)
    assert payload["redacted"] is True
    _assert_no_leaks(cli_json, ADDRESS_LEAKS + PASSWORD_LEAKS)
    _assert_no_leaks(payload, ADDRESS_LEAKS + PASSWORD_LEAKS)


def test_evaluate_default_json_redacts_address_and_assignments():
    raw = evaluate(LEAKING_TEXT, prompt=f"Find who lives at {STREET_LIVES}", redact=False)
    redacted = evaluate(LEAKING_TEXT, prompt=f"Find who lives at {STREET_LIVES}")
    assert raw.redacted is False
    assert redacted.redacted is True
    assert STREET_LIVES in raw.to_json()
    assert STREET_HOME in raw.to_json()
    _assert_no_leaks(redacted.to_json())
    _assert_no_leaks(redacted.prompt)
    _assert_no_leaks(redacted.initial_proposal)
    _assert_no_leaks(redacted.final_output)
    _assert_no_leaks(redacted.decision_reason)
    assert _enforcement_semantics(raw) == _enforcement_semantics(redacted)


@pytest.mark.parametrize(
    "sample",
    (
        LEAKING_TEXT,
        "Jane Doe lives at 123 Main St. Springfield, IL 62704.",
        "The password is: hunter2",
        "password is : hunter2",
        BENIGN_PASSWORD,
        "The password is case sensitive.",
    ),
)
def test_redact_false_preserves_enforcement_semantics(sample: str):
    raw = evaluate(sample, redact=False)
    redacted = evaluate(sample)
    assert _enforcement_semantics(raw) == _enforcement_semantics(redacted)
    if raw.shard_evaluations is not None and redacted.shard_evaluations is not None:
        assert [item.passed for item in raw.shard_evaluations] == [
            item.passed for item in redacted.shard_evaluations
        ]


def test_run_revision_trace_and_cli_json_redact_the_same_tokens(capsys):
    provider = ScriptedProvider(
        complete_texts=[LEAKING_TEXT],
        revise_texts=[f"A brief checkable outline. {BENIGN_PASSWORD}"],
    )
    report = run("annotate this", provider=provider)
    assert report.redacted is True
    assert report.revision_trace
    _assert_no_leaks(report.to_json())
    _assert_no_leaks(report.revision_trace[0].input_text)
    _assert_no_leaks(report.revision_trace[0].feedback)
    assert BENIGN_PASSWORD in report.final_output or BENIGN_PASSWORD in report.to_json()

    raw = run("annotate this", provider=ScriptedProvider(complete_texts=[LEAKING_TEXT]), redact=False)
    redacted = run("annotate this", provider=ScriptedProvider(complete_texts=[LEAKING_TEXT]))
    assert _enforcement_semantics(raw) == _enforcement_semantics(redacted)

    assert main(["evaluate", "--text", LEAKING_TEXT]) == EXIT_REVISE
    cli_json = capsys.readouterr().out
    payload = json.loads(cli_json)
    assert payload["redacted"] is True
    _assert_no_leaks(cli_json)
    _assert_no_leaks(payload)

    assert main(["run", "--prompt", "annotate this", "--proposal", LEAKING_TEXT]) in {
        0,
        2,
        3,
    }
    run_json = capsys.readouterr().out
    _assert_no_leaks(run_json)
    assert json.loads(run_json)["redacted"] is True


def test_address_and_password_fuzz_variants_beyond_fixtures():
    streets = (
        "123 Main St.",
        "456 Oak Ave.",
        "10 N. Pine Rd.",
        "3 P.O. Box 12",
        "80 Elm Dr. Apt. 9",
    )
    seps = (" ", ": ", " : ", " - ")
    cities = ("Springfield, IL 62704", "Austin, TX 78701")
    leaks = ("Springfield", "62704", "Austin", "78701", "Main St", "Oak Ave", "Pine Rd", "Box 12")
    for street in streets:
        for sep in seps:
            for city in cities:
                for trigger in ("lives at", "home address is", "Lives At", "Home address is"):
                    sample = f"Jane Doe {trigger}{sep}{street} {city}."
                    redacted = redact_text(sample)
                    _assert_no_leaks(redacted, leaks)
                    assert "[redacted-address]" in redacted

    secrets = ("hunter2", "s3cret!", "Pa$$w0rd", "secret", "letmein")
    leads = (
        "password is {}",
        "password is: {}",
        "password is : {}",
        "The password is: {}",
        "password: {}",
        "password={}",
        "PASSWORD IS : {}",
    )
    for secret in secrets:
        for lead in leads:
            sample = lead.format(secret)
            redacted = redact_text(sample)
            assert secret not in redacted, sample
            assert "password [redacted]" in redacted


# --- regressions that fail on HEAD 2b77b1d ---

ADDRESS_BOUNDARY_REGRESSIONS = (
    'lives at "123 Main Street, Springfield, IL 62704."',
    "lives at (123 Main Street, Springfield, IL 62704).",
    "lives at 123 Main St. (Apt. 4B), Springfield, IL 62704",
    "lives at 123 Main St.\nSpringfield, IL 62704",
    "lives at 123 Main St.\r\nSpringfield, IL 62704",
)

LETTERS_ONLY_PASSWORD_REGRESSIONS = (
    "The password is secret",
    "The password is letmein",
    "The password is hunter",
    "The password is Password",
)

NEXT_SENTENCE_REGRESSIONS = (
    (
        "lives at 123 Main Street. Please call me later.",
        ("123 Main Street", "Springfield"),
        "Please call me later.",
    ),
    (
        "SHE LIVES AT 123 MAIN STREET. PLEASE CONFIRM THE APPOINTMENT TODAY.",
        ("123 MAIN STREET", "123 Main"),
        "PLEASE CONFIRM THE APPOINTMENT TODAY.",
    ),
)


@pytest.mark.parametrize("sample", ADDRESS_BOUNDARY_REGRESSIONS)
def test_address_boundary_regressions_redact_quoted_paren_and_newline(sample: str, capsys):
    redacted = redact_text(sample)
    assert "[redacted-address]" in redacted
    for token in ("123 Main", "Springfield", "62704", "Apt. 4B"):
        if token == "Apt. 4B" and "Apt" not in sample:
            continue
        assert token not in redacted, (sample, token, redacted)
    report = evaluate(sample)
    blob = report.to_json()
    assert "Springfield" not in blob
    assert "62704" not in blob
    assert main(["evaluate", "--text", sample]) in {0, EXIT_REVISE}
    cli = capsys.readouterr().out
    assert "Springfield" not in cli
    assert "62704" not in cli
    raw = evaluate(sample, redact=False)
    assert _enforcement_semantics(raw) == _enforcement_semantics(report)


@pytest.mark.parametrize("sample,leaks,survives", NEXT_SENTENCE_REGRESSIONS)
def test_address_boundary_does_not_consume_next_sentence(sample: str, leaks, survives):
    redacted = redact_text(sample)
    assert "[redacted-address]" in redacted
    for token in leaks:
        assert token not in redacted, (sample, token, redacted)
    assert survives in redacted
    blob = evaluate(sample).to_json()
    assert survives in blob
    for token in leaks:
        assert token not in blob


@pytest.mark.parametrize("sample", LETTERS_ONLY_PASSWORD_REGRESSIONS)
def test_letters_only_password_credentials_are_redacted(sample: str, capsys):
    credential = sample.rsplit(" ", 1)[-1]
    redacted = redact_text(sample)
    assert credential not in redacted, (sample, redacted)
    assert "password [redacted]" in redacted
    report = evaluate(sample)
    assert credential not in report.to_json()
    assert credential not in report.initial_proposal
    assert main(["evaluate", "--text", sample]) in {0, EXIT_REVISE}
    assert credential not in capsys.readouterr().out
    raw = evaluate(sample, redact=False)
    assert _enforcement_semantics(raw) == _enforcement_semantics(report)
    assert credential in raw.initial_proposal


def test_decision_report_surfaces_cover_boundary_and_letters_only_passwords():
    shard = ShardEvaluationRecord(
        shard_id="privacy",
        version="0.1.0",
        kind="hard",
        priority=2,
        score=0.0,
        passed=False,
        verdict="fail",
        threshold=1.0,
        reasons=('lives at "123 Main Street, Springfield, IL 62704."',),
        criteria=(
            CriterionRecord(
                criterion_id="no_password_dump",
                passed=False,
                score=0.0,
                evidence="The password is secret",
            ),
        ),
    )
    raw = DecisionReport(
        schema_version=REPORT_SCHEMA_VERSION,
        mode="evaluate_only",
        outcome_kind="constraint",
        prompt='Who lives at (123 Main Street, Springfield, IL 62704).',
        initial_proposal="The password is letmein",
        shard_evaluations=(shard,),
        arbitration=ArbitrationRecord(
            verdict="fail",
            veto=True,
            irreconcilable=False,
            notes=("lives at 123 Main St.\nSpringfield, IL 62704",),
        ),
        decision="revise",
        terminal=None,
        decision_reason="The password is hunter",
        revision_trace=(
            RevisionStep(
                round=1,
                input_text="lives at 123 Main St. (Apt. 4B), Springfield, IL 62704",
                output_text="The password is Password",
                shard_evaluations=(shard,),
                arbitration=ArbitrationRecord(
                    verdict="fail",
                    veto=True,
                    irreconcilable=False,
                    notes=("ok",),
                ),
                action="revise",
                reason="x",
                feedback="SHE LIVES AT 123 MAIN STREET. PLEASE CONFIRM THE APPOINTMENT TODAY.",
                telemetry=CallTelemetry(
                    model="mock",
                    prompt_tokens=1,
                    completion_tokens=1,
                    latency_ms=0.0,
                    estimated_usd=0.0,
                ),
                captured=True,
            ),
        ),
        final_output="lives at 123 Main Street. Please call me later.",
        telemetry=_telemetry(),
        versions=_versions(),
        redacted=False,
        enforced_shards=REQUIRED_IDS,
    )
    redacted = raw.with_redaction()
    blob = redacted.to_json()
    for token in (
        "123 Main",
        "Springfield",
        "62704",
        "Apt. 4B",
        "secret",
        "letmein",
        "hunter",
        "Password",
    ):
        assert token not in blob, token
    assert "Please call me later." in blob
    assert "PLEASE CONFIRM THE APPOINTMENT TODAY." in blob
    assert redacted.decision == raw.decision
    assert [item.passed for item in raw.shard_evaluations] == [
        item.passed for item in redacted.shard_evaluations
    ]
