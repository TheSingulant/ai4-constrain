"""V07-3A Candidate 2.2 continuity helpers and C2.2-M1 durability wording.

Inert helpers only. No install-time persistence on api.run.
Synthetic fixtures; no Beta prompts; no live/paid providers.
"""

from __future__ import annotations

import inspect
import itertools

import pytest

from ai4.constrain import evaluate, run
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.context import ContinuitySnapshot
from ai4.constrain._v07_3a.continuity import (
    FILE_SESSION_STORE_COMMIT_POINT,
    assert_continuity_not_reconciled_off,
    continuity_snapshot_from_persisted,
    durable_continuity_intent,
    hybrid_continuity_required,
    inspect_persisted_report_schema_0_2_0,
    inspect_persisted_semantic,
    reconcile_continuity_mirrors,
    tighten_continuity_state,
)
from ai4.constrain.api import run as run_fn
from ai4.constrain.session import FileSessionStore

CLEAN_RUN = "Please give a brief, checkable outline of options and limits."


def _snap(
    ever_on: bool = False,
    ever_required: bool = False,
    schema: bool = False,
    semantic: bool = False,
) -> ContinuitySnapshot:
    return ContinuitySnapshot(
        ever_on=ever_on,
        ever_required=ever_required,
        persisted_report_schema_0_2_0=schema,
        persisted_semantic=semantic,
    )


def test_candidate_2_2_truth_table():
    bits = (False, True)
    for ever_on, ever_required, schema, semantic in itertools.product(bits, repeat=4):
        snapshot = _snap(ever_on, ever_required, schema, semantic)
        expected = ever_on or ever_required or schema or semantic
        assert hybrid_continuity_required(snapshot) is expected
        assert durable_continuity_intent(snapshot) is ever_on
        assert durable_continuity_intent(snapshot) is snapshot.ever_on


def test_disagreement_only_tightens_never_off():
    required = reconcile_continuity_mirrors(ever_on=True, ever_required=False)
    assert required is True
    required = reconcile_continuity_mirrors(ever_on=False, ever_required=True)
    assert required is True
    assert reconcile_continuity_mirrors(ever_on=False, ever_required=False) is False

    durable, mirror = tighten_continuity_state(ever_on=True, ever_required=False)
    assert durable is True
    assert mirror is True
    durable, mirror = tighten_continuity_state(ever_on=False, ever_required=True)
    assert durable is False
    assert mirror is True

    with pytest.raises(HybridExecutionAbort) as exc:
        assert_continuity_not_reconciled_off(
            ever_on=True, ever_required=False, proposed_off=True
        )
    assert exc.value.abort_class == "continuity_required_not_ready"
    with pytest.raises(HybridExecutionAbort) as exc:
        assert_continuity_not_reconciled_off(
            ever_on=False, ever_required=True, proposed_off=True
        )
    assert exc.value.abort_class == "continuity_required_not_ready"
    assert_continuity_not_reconciled_off(
        ever_on=False, ever_required=False, proposed_off=True
    )


def test_persisted_schema_0_2_0_and_semantic_signals():
    assert inspect_persisted_report_schema_0_2_0({"schema_version": "0.2.0"}) is True
    assert inspect_persisted_report_schema_0_2_0({"schema_version": "0.1.0"}) is False
    assert inspect_persisted_report_schema_0_2_0("not-a-mapping") is False
    assert inspect_persisted_semantic({"semantic_success": {"status": "ok"}}) is True
    assert inspect_persisted_semantic({"report": {"semantic_abort": {"abort_class": "empty_parse"}}}) is True
    assert inspect_persisted_semantic({"schema_version": "0.1.0", "decision": "accept"}) is False

    snapshot = continuity_snapshot_from_persisted(
        ever_on=False,
        ever_required=False,
        payloads=({"schema_version": "0.2.0"},),
    )
    assert snapshot.persisted_report_schema_0_2_0 is True
    assert hybrid_continuity_required(snapshot) is True
    assert durable_continuity_intent(snapshot) is False

    semantic_only = continuity_snapshot_from_persisted(
        ever_on=False,
        payloads=({"semantic": {"block_kind": "success"}},),
    )
    assert semantic_only.persisted_semantic is True
    assert hybrid_continuity_required(semantic_only) is True


def test_ever_required_is_in_process_mirror_not_durable():
    snapshot = continuity_snapshot_from_persisted(ever_on=False, ever_required=True)
    assert snapshot.ever_required is True
    assert durable_continuity_intent(snapshot) is False
    assert hybrid_continuity_required(snapshot) is True


def test_api_run_does_not_persist_or_install_continuity():
    source = inspect.getsource(run_fn)
    for needle in (
        "ever_on",
        "ever_required",
        "hybrid_continuity_required",
        "FileSessionStore",
        "install_hybrid",
        "hybrid_ready",
        "ContinuitySnapshot",
    ):
        assert needle not in source
    report = run(CLEAN_RUN)
    assert report.schema_version == "0.1.0"
    scored = evaluate(
        "Here is a brief, checkable answer: I can outline options and limits, "
        "and I will mark anything I cannot verify."
    )
    assert scored.schema_version == "0.1.0"


def test_file_session_store_commit_point_wording():
    doc = FileSessionStore.__doc__ or ""
    normalized = " ".join(doc.split())
    save_src = inspect.getsource(FileSessionStore.save)
    assert "tmp write" in normalized
    assert "Path.replace" in doc
    assert "fsync" in normalized.lower()
    assert "WAL" in doc
    assert "power-loss" in normalized.lower()
    assert "does not fsync" in normalized.lower()
    assert "Path.replace" in save_src
    assert FILE_SESSION_STORE_COMMIT_POINT == (
        "FileSessionStore.save returning after tmp write + Path.replace"
    )
    session_doc = __import__("pathlib").Path("docs/constrain-session.md").read_text(encoding="utf-8")
    assert "Path.replace" in session_doc
    assert "fsync" in session_doc
    assert "power-loss" in session_doc
    assert "WAL" in session_doc or "wal" in session_doc
