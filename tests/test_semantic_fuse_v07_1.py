"""V07-1 packaged mapping + packaged_fuse_v2.

Fresh synthetic fixtures only. Do not use frozen Beta prompts.
Creates and tests the fusion primitive; does not activate production fusion.
Semantic examiner mode stays non-operational: run()/evaluate() are unchanged.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

import ai4.constrain as public
from ai4.constrain import (
    SEMANTIC_EXAMINER_OPERATIONAL,
    SemanticFindingsError,
    SemanticFuseError,
    bind_semantic_findings,
    evaluate,
    finding_policy_map_sha256,
    finding_registry_sha256,
    load_finding_policy_map_v1,
    load_finding_registry_v1,
    map_and_fuse_v2,
    packaged_fuse_v2,
    run,
)
from ai4.constrain.api import evaluate as evaluate_fn
from ai4.constrain.api import run as run_fn
from ai4.constrain.semantic_findings import (
    FINDINGS_SCHEMA_VERSION,
    BoundFinding,
    FindingSpan,
    SemanticFinding,
    quote_sha256_for_span,
)
from ai4.constrain.semantic_fuse import (
    LOCKED_POLICY_MAP_SHA256,
    LOCKED_REGISTRY_SHA256,
    PACKAGED_FUSE_ID,
    PACKAGED_SOURCE,
    SYNTHETIC_TEST_SOURCE,
    _map_and_fuse_v2_for_tests,
)
from ai4.constrain.semantic_taxonomy import (
    FindingClassMapping,
    ShardCap,
    packaged_finding_policy_map_bytes,
    packaged_finding_registry_bytes,
)
from src.shards.shard_loader import REQUIRED_IDS

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "ai4/data/semantic_v07/finding_registry_v1.json"
POLICY_MAP_PATH = ROOT / "ai4/data/semantic_v07/finding_policy_map_v1.json"

REGISTRY_SHA256 = "e817eb246889cd19e090f96f005b577252b90b87028c50860e03cacbcee94535"
POLICY_MAP_SHA256 = "c84c613d7811fd0701ac90051d4f5b9640b90e8e978430bbd64f4cca81215a78"

OBSERVATION_PROMPT = "synthetic-v07-1-observation-prompt"
OBSERVATION_PROMPT_SHA256 = hashlib.sha256(OBSERVATION_PROMPT.encode("utf-8")).hexdigest()

# Distinct synthetic spans; not Beta prompts.
CANDIDATE = "Alpha office stated a count. Beta bureau certified a limit."
SPAN_A = (0, 12)  # "Alpha office"
SPAN_B = (32, 43)  # "Beta bureau"
SPAN_C = (13, 31)  # "stated a count."

CLEAN_EVAL = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)
CLEAN_RUN = "Please give a brief, checkable outline of options and limits."


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _quote(start: int, end: int, candidate: str = CANDIDATE) -> str:
    return quote_sha256_for_span(candidate, start, end)


def _finding(
    *,
    finding_id: str,
    class_id: str,
    confidence_bin: str,
    start: int,
    end: int,
    observation_code: str,
    candidate: str = CANDIDATE,
) -> dict[str, object]:
    return {
        "finding_id": finding_id,
        "class_id": class_id,
        "confidence_bin": confidence_bin,
        "span": {"start": start, "end": end},
        "quote_sha256": _quote(start, end, candidate),
        "observation_code": observation_code,
        "injection_signal_codes": [],
    }


def _payload(findings: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "schema_version": FINDINGS_SCHEMA_VERSION,
        "examiner_id": "synthetic-examiner-v07-1",
        "examiner_version": "0.7.1-test",
        "model_id": "synthetic-model",
        "provider_id": "synthetic-provider",
        "observation_prompt_sha256": OBSERVATION_PROMPT_SHA256,
        "temperature": 0,
        "status": "ok",
        "findings": findings if findings is not None else [],
    }


def _bind(findings: list[dict[str, object]] | None = None, candidate: str = CANDIDATE):
    return bind_semantic_findings(_payload(findings), candidate=candidate)


def _det(**overrides: float) -> dict[str, float]:
    scores = {shard_id: 1.0 for shard_id in REQUIRED_IDS}
    scores.update(overrides)
    return scores


def _delta(class_id: str, confidence_bin: str, shard_id: str) -> float:
    policy_map = load_finding_policy_map_v1()
    mapping = next(item for item in policy_map.mappings if item.class_id == class_id)
    return dict(dict(mapping.overlay_deltas)[confidence_bin])[shard_id]


def _cap(shard_id: str) -> float:
    policy_map = load_finding_policy_map_v1()
    return next(item.cap for item in policy_map.shard_caps if item.shard_id == shard_id)


def _hand_finding(
    *,
    finding_id: str,
    class_id: str,
    confidence_bin: str,
    claim_fingerprint: str,
    observation_code: str = "ungrounded_authority_cue",
) -> BoundFinding:
    return BoundFinding(
        finding=SemanticFinding(
            finding_id=finding_id,
            class_id=class_id,
            confidence_bin=confidence_bin,
            span=FindingSpan(start=0, end=1),
            quote_sha256="ab" * 32,
            observation_code=observation_code,
            injection_signal_codes=(),
        ),
        claim_fingerprint=claim_fingerprint,
    )


# --- empty findings / identity ----------------------------------------------


def test_no_findings_fused_equals_det():
    det = _det(truth=0.82, autonomy=0.71)
    result = map_and_fuse_v2(det, ())
    assert result.fused_map() == det
    assert result.overlay_map() == {shard_id: 0.0 for shard_id in REQUIRED_IDS}
    assert result.provenance.findings_consumed == ()
    bound_empty = _bind([])
    again = map_and_fuse_v2(det, bound_empty)
    assert again.fused_map() == det
    assert again.to_canonical_json() == result.to_canonical_json()


def test_packaged_penalty_lowers_applicable_det():
    bound = _bind(
        [
            _finding(
                finding_id="f-auth",
                class_id="fabricated_authority",
                confidence_bin="medium",
                start=SPAN_A[0],
                end=SPAN_A[1],
                observation_code="ungrounded_authority_cue",
            )
        ]
    )
    det = _det(truth=0.80)
    result = map_and_fuse_v2(det, bound)
    expected = _delta("fabricated_authority", "medium", "truth")
    assert expected == pytest.approx(0.15)
    assert result.overlay_map()["truth"] == pytest.approx(expected)
    assert result.fused_map()["truth"] == pytest.approx(0.65)
    assert result.fused_map()["truth"] < det["truth"]
    for shard_id in REQUIRED_IDS:
        if shard_id != "truth":
            assert result.overlay_map()[shard_id] == 0.0
            assert result.fused_map()[shard_id] == det[shard_id]


def test_fused_never_exceeds_det_and_never_negative():
    bound = _bind(
        [
            _finding(
                finding_id="f-gov",
                class_id="governance_manipulation_claim",
                confidence_bin="high",
                start=SPAN_A[0],
                end=SPAN_A[1],
                observation_code="governance_override_cue",
            ),
            _finding(
                finding_id="f-auth",
                class_id="fabricated_authority",
                confidence_bin="high",
                start=SPAN_B[0],
                end=SPAN_B[1],
                observation_code="ungrounded_authority_cue",
            ),
        ]
    )
    det = _det(truth=0.12, autonomy=0.05, compassion=0.0, privacy=1.0, harm_aversion=0.4)
    result = map_and_fuse_v2(det, bound)
    for shard_id in REQUIRED_IDS:
        fused = result.fused_map()[shard_id]
        assert fused >= 0.0
        assert fused <= det[shard_id]


def test_packaged_fuse_v2_clamps_overlay_past_det_to_zero():
    det = _det(truth=0.10)
    overlay = {shard_id: 0.0 for shard_id in REQUIRED_IDS}
    overlay["truth"] = 0.40
    fused = packaged_fuse_v2(det, overlay)
    assert fused["truth"] == 0.0
    assert all(0.0 <= fused[shard_id] <= det[shard_id] for shard_id in REQUIRED_IDS)


# --- caps, zero, failing det ------------------------------------------------


def test_aggregate_cannot_exceed_packaged_shard_cap():
    # fabricated_authority high truth=0.3 + deceptive_claim high truth=0.25 = 0.55
    # packaged truth cap is 0.4.
    bound = _bind(
        [
            _finding(
                finding_id="f-auth",
                class_id="fabricated_authority",
                confidence_bin="high",
                start=SPAN_A[0],
                end=SPAN_A[1],
                observation_code="ungrounded_authority_cue",
            ),
            _finding(
                finding_id="f-deceptive",
                class_id="deceptive_claim",
                confidence_bin="high",
                start=SPAN_B[0],
                end=SPAN_B[1],
                observation_code="deceptive_framing_cue",
            ),
        ]
    )
    uncapped = _delta("fabricated_authority", "high", "truth") + _delta(
        "deceptive_claim", "high", "truth"
    )
    assert uncapped == pytest.approx(0.55)
    assert _cap("truth") == pytest.approx(0.4)
    det = _det(truth=0.95)
    result = map_and_fuse_v2(det, bound)
    assert result.overlay_map()["truth"] == pytest.approx(0.4)
    assert result.overlay_map()["truth"] == pytest.approx(_cap("truth"))
    assert result.fused_map()["truth"] == pytest.approx(0.55)
    assert result.provenance.packaged_caps[REQUIRED_IDS.index("truth")][1] == pytest.approx(0.4)


def test_det_zero_remains_zero():
    bound = _bind(
        [
            _finding(
                finding_id="f-auth",
                class_id="fabricated_authority",
                confidence_bin="high",
                start=SPAN_A[0],
                end=SPAN_A[1],
                observation_code="ungrounded_authority_cue",
            )
        ]
    )
    det = _det(truth=0.0)
    result = map_and_fuse_v2(det, bound)
    assert result.fused_map()["truth"] == 0.0
    assert result.overlay_map()["truth"] > 0.0


def test_det_failing_score_cannot_be_improved():
    bound = _bind(
        [
            _finding(
                finding_id="f-auth",
                class_id="fabricated_authority",
                confidence_bin="low",
                start=SPAN_A[0],
                end=SPAN_A[1],
                observation_code="ungrounded_authority_cue",
            )
        ]
    )
    failing = 0.20
    det = _det(truth=failing)
    result = map_and_fuse_v2(det, bound)
    assert result.fused_map()["truth"] <= failing
    assert result.fused_map()["truth"] == pytest.approx(failing - 0.05)
    empty = map_and_fuse_v2(det, ())
    assert empty.fused_map()["truth"] == failing


# --- aggregation and duplicates ---------------------------------------------


def test_multiple_legitimate_findings_aggregate_deterministically():
    findings = [
        _finding(
            finding_id="f-auth",
            class_id="fabricated_authority",
            confidence_bin="medium",
            start=SPAN_A[0],
            end=SPAN_A[1],
            observation_code="ungrounded_authority_cue",
        ),
        _finding(
            finding_id="f-certain",
            class_id="unsupported_certainty",
            confidence_bin="medium",
            start=SPAN_B[0],
            end=SPAN_B[1],
            observation_code="ungrounded_certainty_cue",
        ),
        _finding(
            finding_id="f-gov",
            class_id="governance_manipulation_claim",
            confidence_bin="medium",
            start=SPAN_C[0],
            end=SPAN_C[1],
            observation_code="governance_override_cue",
        ),
    ]
    det = _det(truth=0.90, autonomy=0.80)
    first = map_and_fuse_v2(det, _bind(findings))
    second = map_and_fuse_v2(det, _bind(list(reversed(findings))))
    expected_truth = (
        _delta("fabricated_authority", "medium", "truth")
        + _delta("unsupported_certainty", "medium", "truth")
        + _delta("governance_manipulation_claim", "medium", "truth")
    )
    expected_autonomy = _delta("governance_manipulation_claim", "medium", "autonomy")
    assert first.overlay_map()["truth"] == pytest.approx(expected_truth)
    assert first.overlay_map()["autonomy"] == pytest.approx(expected_autonomy)
    assert first.fused_map()["truth"] == pytest.approx(0.90 - expected_truth)
    assert first.fused_map() == second.fused_map()
    assert first.overlay_map() == second.overlay_map()
    assert first.to_canonical_json() == second.to_canonical_json()
    assert [item.class_id for item in first.provenance.findings_consumed] == [
        "fabricated_authority",
        "governance_manipulation_claim",
        "unsupported_certainty",
    ]
    assert [item.finding_id for item in first.provenance.findings_consumed] == [
        "f-auth",
        "f-gov",
        "f-certain",
    ]


def test_duplicate_equivalents_do_not_multiply():
    same = _finding(
        finding_id="f-1",
        class_id="fabricated_authority",
        confidence_bin="low",
        start=SPAN_A[0],
        end=SPAN_A[1],
        observation_code="ungrounded_authority_cue",
    )
    duplicate_high = _finding(
        finding_id="f-2",
        class_id="fabricated_authority",
        confidence_bin="high",
        start=SPAN_A[0],
        end=SPAN_A[1],
        observation_code="invented_credential_cue",
    )
    bound = _bind([same, duplicate_high])
    assert bound.findings[0].claim_fingerprint == bound.findings[1].claim_fingerprint
    det = _det(truth=1.0)
    result = map_and_fuse_v2(det, bound)
    assert result.overlay_map()["truth"] == pytest.approx(_delta("fabricated_authority", "high", "truth"))
    assert len(result.provenance.findings_consumed) == 1
    assert result.provenance.findings_consumed[0].confidence_bin == "high"
    assert result.provenance.findings_consumed[0].finding_id == "f-2"
    assert len(result.provenance.findings_suppressed) == 1
    assert result.provenance.findings_suppressed[0].finding_id == "f-1"
    assert result.provenance.findings_suppressed[0].suppressed is True

    twins = _bind(
        [
            _finding(
                finding_id="twin-a",
                class_id="fabricated_authority",
                confidence_bin="medium",
                start=SPAN_B[0],
                end=SPAN_B[1],
                observation_code="ungrounded_authority_cue",
            ),
            _finding(
                finding_id="twin-b",
                class_id="fabricated_authority",
                confidence_bin="medium",
                start=SPAN_B[0],
                end=SPAN_B[1],
                observation_code="invented_citation_cue",
            ),
        ]
    )
    twin_result = map_and_fuse_v2(det, twins)
    assert twin_result.overlay_map()["truth"] == pytest.approx(
        _delta("fabricated_authority", "medium", "truth")
    )
    assert twin_result.provenance.findings_consumed[0].finding_id == "twin-a"


def test_same_class_different_fingerprint_is_not_duplicate():
    bound = _bind(
        [
            _finding(
                finding_id="span-a",
                class_id="fabricated_authority",
                confidence_bin="medium",
                start=SPAN_A[0],
                end=SPAN_A[1],
                observation_code="ungrounded_authority_cue",
            ),
            _finding(
                finding_id="span-b",
                class_id="fabricated_authority",
                confidence_bin="medium",
                start=SPAN_B[0],
                end=SPAN_B[1],
                observation_code="ungrounded_authority_cue",
            ),
        ]
    )
    assert bound.findings[0].claim_fingerprint != bound.findings[1].claim_fingerprint
    det = _det(truth=1.0)
    result = map_and_fuse_v2(det, bound)
    assert result.overlay_map()["truth"] == pytest.approx(
        2 * _delta("fabricated_authority", "medium", "truth")
    )


# --- examiner cannot choose routing or magnitude ----------------------------


def test_examiner_cannot_choose_shard_routing_or_penalty_magnitude():
    bound = _bind(
        [
            _finding(
                finding_id="f-auth",
                class_id="fabricated_authority",
                confidence_bin="high",
                start=SPAN_A[0],
                end=SPAN_A[1],
                observation_code="ungrounded_authority_cue",
            )
        ]
    )
    det = _det()
    result = map_and_fuse_v2(det, bound)
    assert result.overlay_map()["truth"] == pytest.approx(0.3)
    assert result.overlay_map()["autonomy"] == 0.0
    assert result.provenance.findings_consumed[0].mapped_shards == ("truth",)

    with pytest.raises(SemanticFuseError, match="policy/control field"):
        map_and_fuse_v2(det, bound, overlay={"truth": 0.01})  # type: ignore[call-arg]
    with pytest.raises(SemanticFuseError, match="policy/control field"):
        map_and_fuse_v2(det, bound, shard_ids=["autonomy"])  # type: ignore[call-arg]
    with pytest.raises(SemanticFuseError, match="policy/control field"):
        map_and_fuse_v2(det, bound, weights={"truth": 2.0})  # type: ignore[call-arg]
    with pytest.raises(SemanticFuseError, match="policy/control field"):
        packaged_fuse_v2(det, result.overlay_map(), thresholds={"truth": 0.5})
    with pytest.raises(SemanticFuseError, match="raw mapping"):
        map_and_fuse_v2(
            det,
            [
                {
                    "class_id": "fabricated_authority",
                    "claim_fingerprint": "ab" * 32,
                    "shard_ids": ["autonomy"],
                    "score": 0.9,
                }
            ],
        )

    raw_payload = _payload(
        [
            _finding(
                finding_id="smuggle",
                class_id="fabricated_authority",
                confidence_bin="high",
                start=SPAN_A[0],
                end=SPAN_A[1],
                observation_code="ungrounded_authority_cue",
            )
        ]
    )
    raw_payload["findings"][0]["shard_ids"] = ["autonomy"]
    with pytest.raises(SemanticFindingsError, match="policy/control field|Unknown findings"):
        bind_semantic_findings(raw_payload, candidate=CANDIDATE)


def test_governance_class_routes_only_through_packaged_map():
    bound = _bind(
        [
            _finding(
                finding_id="f-gov",
                class_id="governance_manipulation_claim",
                confidence_bin="low",
                start=SPAN_A[0],
                end=SPAN_A[1],
                observation_code="governance_override_cue",
            )
        ]
    )
    result = map_and_fuse_v2(_det(truth=1.0, autonomy=1.0), bound)
    assert result.overlay_map()["autonomy"] == pytest.approx(0.05)
    assert result.overlay_map()["truth"] == pytest.approx(0.05)
    assert result.overlay_map()["privacy"] == 0.0
    assert result.provenance.findings_consumed[0].mapped_shards == ("autonomy", "truth")


# --- fail closed ------------------------------------------------------------


def test_unknown_class_fails_closed():
    finding = _hand_finding(
        finding_id="invented",
        class_id="examiner_invented_class",
        confidence_bin="high",
        claim_fingerprint="cd" * 32,
    )
    with pytest.raises(SemanticFuseError, match="Unknown class_id"):
        map_and_fuse_v2(_det(), [finding])


def test_invalid_shard_in_packaged_policy_fails_closed():
    base = load_finding_policy_map_v1()
    bad_mapping = FindingClassMapping(
        class_id="fabricated_authority",
        shards=("loyalty",),
        overlay_deltas=(
            ("low", (("loyalty", 0.05),)),
            ("medium", (("loyalty", 0.10),)),
            ("high", (("loyalty", 0.15),)),
        ),
    )
    others = tuple(item for item in base.mappings if item.class_id != "fabricated_authority")
    bad_map = replace(base, mappings=(bad_mapping,) + others)
    with pytest.raises(SemanticFuseError, match="extra shard name"):
        _map_and_fuse_v2_for_tests(_det(), (), policy_map=bad_map)


def test_negative_and_nonfinite_overlay_fail_closed():
    base = load_finding_policy_map_v1()
    source = next(item for item in base.mappings if item.class_id == "fabricated_authority")
    negative = replace(
        source,
        overlay_deltas=(
            ("low", (("truth", -0.05),)),
            ("medium", (("truth", 0.15),)),
            ("high", (("truth", 0.30),)),
        ),
    )
    others = tuple(item for item in base.mappings if item.class_id != "fabricated_authority")
    with pytest.raises(SemanticFuseError, match="must be nonnegative"):
        _map_and_fuse_v2_for_tests(
            _det(), (), policy_map=replace(base, mappings=(negative,) + others)
        )

    nonfinite = replace(
        source,
        overlay_deltas=(
            ("low", (("truth", 0.05),)),
            ("medium", (("truth", math.nan),)),
            ("high", (("truth", 0.30),)),
        ),
    )
    with pytest.raises(SemanticFuseError, match="finite"):
        _map_and_fuse_v2_for_tests(
            _det(), (), policy_map=replace(base, mappings=(nonfinite,) + others)
        )

    overlay = {shard_id: 0.0 for shard_id in REQUIRED_IDS}
    overlay["truth"] = math.inf
    with pytest.raises(SemanticFuseError, match="finite"):
        packaged_fuse_v2(_det(), overlay)
    overlay["truth"] = -0.2
    with pytest.raises(SemanticFuseError, match="nonnegative"):
        packaged_fuse_v2(_det(), overlay)


def test_malformed_packaged_policy_fails_closed():
    raw = json.loads(packaged_finding_policy_map_bytes())
    del raw["mappings"]
    with pytest.raises(SemanticFindingsError, match="missing keys"):
        _map_and_fuse_v2_for_tests(_det(), (), policy_map=raw)
    raw = json.loads(packaged_finding_policy_map_bytes())
    raw["required_shards"] = list(REQUIRED_IDS) + ["loyalty"]
    with pytest.raises(SemanticFindingsError, match="extra shard name"):
        _map_and_fuse_v2_for_tests(_det(), (), policy_map=raw)
    raw = json.loads(packaged_finding_policy_map_bytes())
    raw["mappings"]["not_a_class"] = copy.deepcopy(raw["mappings"]["fabricated_authority"])
    with pytest.raises(SemanticFindingsError, match="Unknown class_id"):
        _map_and_fuse_v2_for_tests(_det(), (), policy_map=raw)


def test_invalid_det_and_duplicate_finding_id_fail_closed():
    with pytest.raises(SemanticFuseError, match="missing required shards"):
        map_and_fuse_v2({"truth": 1.0}, ())
    extra = _det()
    extra["loyalty"] = 0.1
    with pytest.raises(SemanticFuseError, match="extra shard name"):
        map_and_fuse_v2(extra, ())
    with pytest.raises(SemanticFuseError, match="finite"):
        map_and_fuse_v2(_det(truth=math.nan), ())
    with pytest.raises(SemanticFuseError, match="nonnegative"):
        map_and_fuse_v2(_det(truth=-0.01), ())
    with pytest.raises(SemanticFuseError, match="exceeds domain maximum"):
        map_and_fuse_v2(_det(truth=1.01), ())
    twins = [
        _hand_finding(
            finding_id="same-id",
            class_id="fabricated_authority",
            confidence_bin="low",
            claim_fingerprint="11" * 32,
        ),
        _hand_finding(
            finding_id="same-id",
            class_id="deceptive_claim",
            confidence_bin="low",
            claim_fingerprint="22" * 32,
        ),
    ]
    with pytest.raises(SemanticFuseError, match="Duplicate finding_id"):
        map_and_fuse_v2(_det(), twins)


# --- determinism, hashes, non-operational -----------------------------------


def test_output_and_provenance_are_deterministic():
    findings = [
        _finding(
            finding_id="z-last",
            class_id="overclaim_from_ambiguity",
            confidence_bin="low",
            start=SPAN_C[0],
            end=SPAN_C[1],
            observation_code="ambiguity_as_fact_cue",
        ),
        _finding(
            finding_id="a-first",
            class_id="fabricated_authority",
            confidence_bin="medium",
            start=SPAN_A[0],
            end=SPAN_A[1],
            observation_code="ungrounded_authority_cue",
        ),
    ]
    det_a = _det(truth=0.77, autonomy=0.66)
    det_b = {shard_id: det_a[shard_id] for shard_id in reversed(REQUIRED_IDS)}
    first = map_and_fuse_v2(det_a, _bind(findings))
    second = map_and_fuse_v2(det_b, _bind(list(reversed(findings))))
    assert first == second
    assert first.to_canonical_json() == second.to_canonical_json()
    payload = json.loads(first.to_canonical_json())
    assert payload["provenance"]["fuse_id"] == PACKAGED_FUSE_ID
    assert payload["provenance"]["policy_map_sha256"] == POLICY_MAP_SHA256
    assert payload["provenance"]["policy_map_source"] == PACKAGED_SOURCE
    assert first.provenance.policy_map_sha256 == _sha256_hex(packaged_finding_policy_map_bytes())
    assert [item[0] for item in payload["fused_scores"]] == list(REQUIRED_IDS)
    consumed = payload["provenance"]["findings_consumed"]
    assert [item["finding_id"] for item in consumed] == ["a-first", "z-last"]
    # Provenance is audit output, not an accepted policy input.
    with pytest.raises(SemanticFuseError, match="Unknown map_and_fuse_v2 argument"):
        map_and_fuse_v2(det_a, _bind(findings), provenance=first.provenance)  # type: ignore[call-arg]


def test_locked_v07_0_artifact_hashes_remain_exact():
    assert _sha256_hex(REGISTRY_PATH.read_bytes()) == REGISTRY_SHA256
    assert _sha256_hex(POLICY_MAP_PATH.read_bytes()) == POLICY_MAP_SHA256
    assert _sha256_hex(packaged_finding_registry_bytes()) == REGISTRY_SHA256
    assert _sha256_hex(packaged_finding_policy_map_bytes()) == POLICY_MAP_SHA256
    assert finding_registry_sha256() == REGISTRY_SHA256
    assert finding_policy_map_sha256() == POLICY_MAP_SHA256
    result = map_and_fuse_v2(_det(), ())
    assert result.provenance.policy_map_sha256 == POLICY_MAP_SHA256
    assert result.provenance.policy_map_sha256 == LOCKED_POLICY_MAP_SHA256
    assert result.provenance.policy_map_source == PACKAGED_SOURCE
    assert result.provenance.policy_map_sha256 == _sha256_hex(packaged_finding_policy_map_bytes())
    registry = load_finding_registry_v1()
    policy_map = load_finding_policy_map_v1(registry)
    assert registry.sha256 == REGISTRY_SHA256
    assert policy_map.sha256 == POLICY_MAP_SHA256
    assert LOCKED_REGISTRY_SHA256 == REGISTRY_SHA256
    assert LOCKED_POLICY_MAP_SHA256 == POLICY_MAP_SHA256


def test_semantic_examiner_remains_non_operational_and_unwired():
    assert SEMANTIC_EXAMINER_OPERATIONAL is False
    assert public.SEMANTIC_EXAMINER_OPERATIONAL is False
    report = evaluate(CLEAN_EVAL)
    assert report.decision == "accept"
    loop = run(CLEAN_RUN)
    assert loop.decision == "accept"
    assert "map_and_fuse_v2" not in inspect.getsource(run_fn)
    assert "packaged_fuse_v2" not in inspect.getsource(run_fn)
    assert "map_and_fuse_v2" not in inspect.getsource(evaluate_fn)
    assert "semantic_fuse" not in inspect.getsource(evaluate_fn)
    assert public.map_and_fuse_v2 is map_and_fuse_v2
    assert public.packaged_fuse_v2 is packaged_fuse_v2
    assert "map_and_fuse_v2" in public.__all__
    assert "_map_and_fuse_v2_for_tests" not in public.__all__
    assert not hasattr(public, "_map_and_fuse_v2_for_tests")
    assert "AgentIdentity" not in public.__all__


def test_governing_path_modules_do_not_import_semantic_fuse():
    forbidden = (
        Path("ai4/constrain/api.py"),
        Path("ai4/constrain/runtime.py"),
        Path("ai4/constrain/evaluator_wall.py"),
        Path("src/constraints/constraint_middleware.py"),
        Path("src/shards/arbitration.py"),
    )
    offenders: list[str] = []
    for path in forbidden:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                if "semantic_fuse" in name or "semantic_findings" in name or "semantic_taxonomy" in name:
                    offenders.append(f"{path}: {name}")
    assert offenders == []


def test_public_map_and_fuse_v2_exposes_no_policy_or_registry_override():
    for fn in (map_and_fuse_v2, public.map_and_fuse_v2):
        params = inspect.signature(fn).parameters
        assert "policy_map" not in params
        assert "registry" not in params
        assert tuple(params) == ("det_scores", "findings", "kwargs")
    bound = _bind(
        [
            _finding(
                finding_id="f-auth",
                class_id="fabricated_authority",
                confidence_bin="high",
                start=SPAN_A[0],
                end=SPAN_A[1],
                observation_code="ungrounded_authority_cue",
            )
        ]
    )
    det = _det()
    with pytest.raises(SemanticFuseError, match="policy substitution"):
        map_and_fuse_v2(det, bound, policy_map=load_finding_policy_map_v1())
    with pytest.raises(SemanticFuseError, match="policy substitution"):
        map_and_fuse_v2(det, bound, registry=load_finding_registry_v1())
    with pytest.raises(SemanticFuseError, match="policy substitution"):
        public.map_and_fuse_v2(det, bound, policy_map={"mappings": {}})


def test_public_path_always_uses_locked_packaged_hash_and_routing():
    bound = _bind(
        [
            _finding(
                finding_id="f-auth",
                class_id="fabricated_authority",
                confidence_bin="high",
                start=SPAN_A[0],
                end=SPAN_A[1],
                observation_code="ungrounded_authority_cue",
            )
        ]
    )
    result = map_and_fuse_v2(_det(), bound)
    packaged_digest = _sha256_hex(packaged_finding_policy_map_bytes())
    assert packaged_digest == POLICY_MAP_SHA256 == LOCKED_POLICY_MAP_SHA256
    assert result.provenance.policy_map_sha256 == packaged_digest
    assert result.provenance.policy_map_source == PACKAGED_SOURCE
    assert result.overlay_map()["truth"] == pytest.approx(0.3)
    assert result.overlay_map()["autonomy"] == 0.0


def test_synthetic_map_cannot_claim_locked_digest():
    base = load_finding_policy_map_v1()
    assert base.sha256 == POLICY_MAP_SHA256
    source = next(item for item in base.mappings if item.class_id == "fabricated_authority")
    zeroed = replace(
        source,
        shards=("autonomy",),
        overlay_deltas=(
            ("low", (("autonomy", 0.0),)),
            ("medium", (("autonomy", 0.0),)),
            ("high", (("autonomy", 0.0),)),
        ),
    )
    others = tuple(item for item in base.mappings if item.class_id != "fabricated_authority")
    mutated = replace(base, mappings=(zeroed,) + others)
    assert mutated.sha256 == POLICY_MAP_SHA256
    bound = _bind(
        [
            _finding(
                finding_id="f-auth",
                class_id="fabricated_authority",
                confidence_bin="high",
                start=SPAN_A[0],
                end=SPAN_A[1],
                observation_code="ungrounded_authority_cue",
            )
        ]
    )
    synthetic = _map_and_fuse_v2_for_tests(_det(), bound, policy_map=mutated)
    assert synthetic.provenance.policy_map_source == SYNTHETIC_TEST_SOURCE
    assert synthetic.provenance.policy_map_sha256 != POLICY_MAP_SHA256
    assert synthetic.overlay_map()["truth"] == 0.0
    assert synthetic.overlay_map()["autonomy"] == 0.0
    public_result = map_and_fuse_v2(_det(), bound)
    assert public_result.provenance.policy_map_sha256 == POLICY_MAP_SHA256
    assert public_result.provenance.policy_map_source == PACKAGED_SOURCE
    assert public_result.overlay_map()["truth"] == pytest.approx(0.3)
    assert public_result.overlay_map()["autonomy"] == 0.0


def test_public_path_cannot_reroute_zero_penalty_or_raise_cap():
    bound = _bind(
        [
            _finding(
                finding_id="f-auth",
                class_id="fabricated_authority",
                confidence_bin="high",
                start=SPAN_A[0],
                end=SPAN_A[1],
                observation_code="ungrounded_authority_cue",
            ),
            _finding(
                finding_id="f-deceptive",
                class_id="deceptive_claim",
                confidence_bin="high",
                start=SPAN_B[0],
                end=SPAN_B[1],
                observation_code="deceptive_framing_cue",
            ),
        ]
    )
    det = _det(truth=0.95)
    public_result = map_and_fuse_v2(det, bound)
    assert public_result.overlay_map()["truth"] == pytest.approx(0.4)

    base = load_finding_policy_map_v1()
    raised_caps = tuple(
        ShardCap(shard_id=item.shard_id, cap=1.0 if item.shard_id == "truth" else item.cap)
        for item in base.shard_caps
    )
    raised = replace(base, shard_caps=raised_caps)
    with pytest.raises(SemanticFuseError, match="policy substitution"):
        map_and_fuse_v2(det, bound, policy_map=raised)
    helper = _map_and_fuse_v2_for_tests(det, bound, policy_map=raised)
    assert helper.overlay_map()["truth"] == pytest.approx(0.55)
    assert helper.provenance.policy_map_sha256 != POLICY_MAP_SHA256
    assert helper.provenance.policy_map_source == SYNTHETIC_TEST_SOURCE
    still_public = map_and_fuse_v2(det, bound)
    assert still_public.overlay_map()["truth"] == pytest.approx(0.4)
    assert still_public.provenance.policy_map_sha256 == POLICY_MAP_SHA256


def test_fixtures_are_not_beta_paraphrases():
    texts = (
        CANDIDATE.lower(),
        OBSERVATION_PROMPT.lower(),
        Path("ai4/constrain/semantic_fuse.py").read_text(encoding="utf-8").lower(),
        REGISTRY_PATH.read_text(encoding="utf-8").lower(),
        POLICY_MAP_PATH.read_text(encoding="utf-8").lower(),
    )
    for text in texts:
        for forbidden in ("jane doe", "078-05-1120", "build a bomb", "heldout", "beta prompt"):
            assert forbidden not in text
