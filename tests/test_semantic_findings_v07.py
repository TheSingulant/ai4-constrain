"""V07-0 findings-only schema, runtime fingerprints, and packaged taxonomy.

Fresh synthetic fixtures only. Do not use frozen Beta prompts.
Semantic examiner mode stays non-operational: run()/evaluate() are unchanged.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import math
from pathlib import Path

import pytest

import ai4.constrain as public
from ai4.constrain import (
    FINDINGS_SCHEMA_VERSION,
    SEMANTIC_EXAMINER_OPERATIONAL,
    SemanticFindingsError,
    bind_semantic_findings,
    claim_fingerprint_v1,
    evaluate,
    finding_policy_map_sha256,
    finding_registry_sha256,
    load_finding_policy_map_v1,
    load_finding_registry_v1,
    parse_semantic_findings,
    run,
    validate_semantic_findings,
)
from ai4.constrain.api import evaluate as evaluate_fn
from ai4.constrain.api import run as run_fn
from ai4.constrain.semantic_findings import (
    CLAIM_FINGERPRINT_VERSION,
    POLICY_SMUGGLE_KEYS,
    findings_to_dict,
    quote_sha256_for_span,
)
from ai4.constrain.semantic_taxonomy import (
    POLICY_MAP_SCHEMA_VERSION,
    REGISTRY_SCHEMA_VERSION,
    TAXONOMY_VERSION,
    packaged_finding_policy_map_bytes,
    packaged_finding_registry_bytes,
    validate_finding_policy_map_payload,
    validate_finding_registry_payload,
)
from src.shards.shard_loader import REQUIRED_IDS

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "ai4/data/semantic_v07/finding_registry_v1.json"
POLICY_MAP_PATH = ROOT / "ai4/data/semantic_v07/finding_policy_map_v1.json"

REGISTRY_SHA256 = "e817eb246889cd19e090f96f005b577252b90b87028c50860e03cacbcee94535"
POLICY_MAP_SHA256 = "c84c613d7811fd0701ac90051d4f5b9640b90e8e978430bbd64f4cca81215a78"

OBSERVATION_PROMPT = "synthetic-v07-0-observation-prompt"
OBSERVATION_PROMPT_SHA256 = hashlib.sha256(OBSERVATION_PROMPT.encode("utf-8")).hexdigest()

CANDIDATE = "The unnamed bureau certified this exact count."
SPAN_START = 4
SPAN_END = 18  # "unnamed bureau"
QUOTE = CANDIDATE[SPAN_START:SPAN_END]
QUOTE_SHA256 = hashlib.sha256(QUOTE.encode("utf-8")).hexdigest()
FINGERPRINT_GOLDEN = "537aabcf89293ecb911a6558a7efdca4258055dd44665830e42c274ab8821fb5"

CLEAN_EVAL = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)
CLEAN_RUN = "Please give a brief, checkable outline of options and limits."

EMOJI_CANDIDATE = "ok 👍 certified"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manual_fingerprint(class_id: str, start: int, end: int, quote_sha256: str) -> str:
    material = (
        b"cf_v1"
        + b"\x1f"
        + class_id.encode("utf-8")
        + b"\x1f"
        + str(start).encode("ascii")
        + b"\x1f"
        + str(end).encode("ascii")
        + b"\x1f"
        + quote_sha256.encode("ascii")
    )
    return _sha256_hex(material)


def _finding(
    *,
    finding_id: str = "finding-1",
    class_id: str = "fabricated_authority",
    confidence_bin: str = "medium",
    start: int = SPAN_START,
    end: int = SPAN_END,
    quote_sha256: str = QUOTE_SHA256,
    observation_code: str = "ungrounded_authority_cue",
    injection_signal_codes: list[str] | None = None,
) -> dict[str, object]:
    return {
        "finding_id": finding_id,
        "class_id": class_id,
        "confidence_bin": confidence_bin,
        "span": {"start": start, "end": end},
        "quote_sha256": quote_sha256,
        "observation_code": observation_code,
        "injection_signal_codes": list(injection_signal_codes or []),
    }


def _payload(
    *,
    findings: list[dict[str, object]] | None = None,
    status: str = "ok",
    extra: dict[str, object] | None = None,
    drop: frozenset[str] = frozenset(),
) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": FINDINGS_SCHEMA_VERSION,
        "examiner_id": "synthetic-examiner",
        "examiner_version": "0.7.0-test",
        "model_id": "synthetic-model",
        "provider_id": "synthetic-provider",
        "observation_prompt_sha256": OBSERVATION_PROMPT_SHA256,
        "temperature": 0,
        "status": status,
        "findings": findings if findings is not None else [_finding()],
    }
    if extra:
        document.update(extra)
    for key in drop:
        document.pop(key, None)
    return document


def _parse_ok(document: dict[str, object]):
    return parse_semantic_findings(json.dumps(document, sort_keys=True, separators=(",", ":")))


# --- 1. valid findings parse deterministically --------------------------------


def test_valid_findings_parse_deterministically():
    document = _payload()
    first = _parse_ok(document)
    second = validate_semantic_findings(copy.deepcopy(document))
    shuffled = json.dumps(document, sort_keys=False)
    third = parse_semantic_findings(shuffled)
    assert first == second == third
    assert first.schema_version == FINDINGS_SCHEMA_VERSION
    assert first.status == "ok"
    assert len(first.findings) == 1
    finding = first.findings[0]
    assert finding.class_id == "fabricated_authority"
    assert finding.span.start == SPAN_START
    assert finding.span.end == SPAN_END
    assert finding.quote_sha256 == QUOTE_SHA256
    assert "claim_fingerprint" not in findings_to_dict(first)
    again = validate_semantic_findings(findings_to_dict(first))
    assert again == first


def test_ok_status_with_empty_findings_is_valid():
    payload = validate_semantic_findings(_payload(findings=[]))
    assert payload.findings == ()
    bound = bind_semantic_findings(payload, candidate=CANDIDATE)
    assert bound.findings == ()


def test_non_ok_status_requires_empty_findings():
    for status in ("timeout", "schema_invalid", "backend_error", "injection_suspected", "empty_parse"):
        payload = validate_semantic_findings(_payload(status=status, findings=[]))
        assert payload.status == status
        bound = bind_semantic_findings(payload, candidate=CANDIDATE)
        assert bound.findings == ()


# --- 2. unknown class_id rejects ---------------------------------------------


def test_unknown_class_id_rejects():
    document = _payload(findings=[_finding(class_id="beta_paraphrase_class")])
    with pytest.raises(SemanticFindingsError, match="Unknown class_id"):
        validate_semantic_findings(document)


def test_unknown_observation_code_rejects():
    document = _payload(findings=[_finding(observation_code="frozen_beta_tell")])
    with pytest.raises(SemanticFindingsError, match="Unknown observation_code"):
        validate_semantic_findings(document)


# --- 3. extra/unknown fields reject ------------------------------------------


def test_unknown_top_level_fields_reject():
    document = _payload(extra={"commentary": "free text"})
    with pytest.raises(SemanticFindingsError, match="Unknown semantic findings payload field"):
        validate_semantic_findings(document)


def test_unknown_finding_fields_reject():
    finding = _finding()
    finding["hint"] = "extra"
    with pytest.raises(SemanticFindingsError, match="Unknown findings\\[0\\] field"):
        validate_semantic_findings(_payload(findings=[finding]))


def test_unknown_span_fields_reject():
    finding = _finding()
    finding["span"] = {"start": SPAN_START, "end": SPAN_END, "unit": "utf16"}
    with pytest.raises(SemanticFindingsError, match="Unknown findings\\[0\\].span field"):
        validate_semantic_findings(_payload(findings=[finding]))


def test_missing_required_fields_reject():
    with pytest.raises(SemanticFindingsError, match="missing keys"):
        validate_semantic_findings(_payload(drop=frozenset({"examiner_id"})))


# --- 4/5. policy-smuggling fields and examiner claim_fingerprint reject ------


@pytest.mark.parametrize("field", sorted(POLICY_SMUGGLE_KEYS))
def test_policy_smuggling_fields_reject(field: str):
    document = _payload(extra={field: 1})
    with pytest.raises(SemanticFindingsError, match="policy/control field"):
        validate_semantic_findings(document)


def test_nested_policy_smuggling_in_finding_rejects():
    finding = _finding()
    finding["decision"] = "refuse"
    with pytest.raises(SemanticFindingsError, match="policy/control field"):
        validate_semantic_findings(_payload(findings=[finding]))


def test_examiner_supplied_claim_fingerprint_rejects():
    document = _payload(extra={"claim_fingerprint": "ab" * 32})
    with pytest.raises(SemanticFindingsError, match="claim_fingerprint"):
        validate_semantic_findings(document)
    finding = _finding()
    finding["claim_fingerprint"] = "cd" * 32
    with pytest.raises(SemanticFindingsError, match="claim_fingerprint"):
        validate_semantic_findings(_payload(findings=[finding]))


def test_examiner_shard_name_keys_reject():
    document = _payload(extra={"truth": -0.2})
    with pytest.raises(SemanticFindingsError, match="extra shard name"):
        validate_semantic_findings(document)


def test_freeform_notes_and_rationale_reject():
    with pytest.raises(SemanticFindingsError, match="policy/control field"):
        validate_semantic_findings(_payload(extra={"notes": ["looks bad"]}))
    with pytest.raises(SemanticFindingsError, match="policy/control field"):
        validate_semantic_findings(_payload(extra={"rationale": "because"}))


# --- 6/7. runtime fingerprint deterministic; candidate/span/quote alter it ---


def test_runtime_fingerprint_deterministic_for_fixed_candidate_span_class():
    assert QUOTE == "unnamed bureau"
    expected = _manual_fingerprint("fabricated_authority", SPAN_START, SPAN_END, QUOTE_SHA256)
    assert expected == FINGERPRINT_GOLDEN
    bound = bind_semantic_findings(_payload(), candidate=CANDIDATE)
    again = bind_semantic_findings(_payload(), candidate=CANDIDATE)
    assert bound.findings[0].claim_fingerprint == expected
    assert again.findings[0].claim_fingerprint == expected
    assert (
        claim_fingerprint_v1(
            class_id="fabricated_authority",
            start=SPAN_START,
            end=SPAN_END,
            quote_sha256=QUOTE_SHA256,
        )
        == expected
    )
    assert CLAIM_FINGERPRINT_VERSION == "cf_v1"


def test_candidate_span_quote_and_class_changes_alter_fingerprint():
    base = bind_semantic_findings(_payload(), candidate=CANDIDATE).findings[0].claim_fingerprint
    shifted_start, shifted_end = 19, 29  # "certified"
    shifted_quote = quote_sha256_for_span(CANDIDATE, shifted_start, shifted_end)
    shifted = bind_semantic_findings(
        _payload(findings=[_finding(start=shifted_start, end=shifted_end, quote_sha256=shifted_quote)]),
        candidate=CANDIDATE,
    ).findings[0].claim_fingerprint
    assert shifted != base

    other_class = bind_semantic_findings(
        _payload(findings=[_finding(class_id="deceptive_claim", observation_code="deceptive_framing_cue")]),
        candidate=CANDIDATE,
    ).findings[0].claim_fingerprint
    assert other_class != base

    mutated = "The unnamed bureau certified this exact count!"
    assert mutated[SPAN_START:SPAN_END] == QUOTE
    same_span_same_quote = bind_semantic_findings(_payload(), candidate=mutated)
    assert same_span_same_quote.findings[0].claim_fingerprint == base

    replaced = CANDIDATE[:SPAN_START] + "UNKNOWN OFFICE" + CANDIDATE[SPAN_END:]
    assert len(replaced) == len(CANDIDATE)
    new_quote = quote_sha256_for_span(replaced, SPAN_START, SPAN_END)
    assert new_quote != QUOTE_SHA256
    changed_quote = bind_semantic_findings(
        _payload(findings=[_finding(quote_sha256=new_quote)]),
        candidate=replaced,
    ).findings[0].claim_fingerprint
    assert changed_quote != base


def test_unicode_scalar_span_not_utf16_code_units():
    start = EMOJI_CANDIDATE.index("👍")
    end = start + 1
    assert len(EMOJI_CANDIDATE) == 14
    quote_sha = quote_sha256_for_span(EMOJI_CANDIDATE, start, end)
    document = _payload(
        findings=[_finding(start=start, end=end, quote_sha256=quote_sha, finding_id="emoji-1")]
    )
    bound = bind_semantic_findings(document, candidate=EMOJI_CANDIDATE)
    assert bound.findings[0].finding.span.start == 3
    assert bound.findings[0].finding.span.end == 4
    utf16_end = start + 2
    with pytest.raises(SemanticFindingsError, match="quote_sha256 does not match"):
        bind_semantic_findings(
            _payload(
                findings=[
                    _finding(
                        start=start,
                        end=utf16_end,
                        quote_sha256=quote_sha,
                        finding_id="utf16-wrong",
                    )
                ]
            ),
            candidate=EMOJI_CANDIDATE,
        )
    with pytest.raises(SemanticFindingsError, match="out of bounds"):
        bind_semantic_findings(
            _payload(
                findings=[
                    _finding(
                        start=start,
                        end=len(EMOJI_CANDIDATE) + 1,
                        quote_sha256=quote_sha,
                        finding_id="oob",
                    )
                ]
            ),
            candidate=EMOJI_CANDIDATE,
        )


# --- 8. malformed spans/quotes fail closed -----------------------------------


def test_malformed_spans_and_quotes_fail_closed():
    with pytest.raises(SemanticFindingsError, match="start must not exceed end"):
        validate_semantic_findings(_payload(findings=[_finding(start=10, end=4)]))
    with pytest.raises(SemanticFindingsError, match="non-empty"):
        validate_semantic_findings(_payload(findings=[_finding(start=4, end=4)]))
    with pytest.raises(SemanticFindingsError, match="must be an integer"):
        finding = _finding()
        finding["span"] = {"start": 4.5, "end": 18}
        validate_semantic_findings(_payload(findings=[finding]))
    with pytest.raises(SemanticFindingsError, match="must be an integer"):
        finding = _finding()
        finding["span"] = {"start": True, "end": 18}
        validate_semantic_findings(_payload(findings=[finding]))
    with pytest.raises(SemanticFindingsError, match="out of bounds"):
        bind_semantic_findings(
            _payload(findings=[_finding(start=0, end=len(CANDIDATE) + 1, quote_sha256="ab" * 32)]),
            candidate=CANDIDATE,
        )
    with pytest.raises(SemanticFindingsError, match="quote_sha256 does not match"):
        bind_semantic_findings(
            _payload(findings=[_finding(quote_sha256="ab" * 32)]),
            candidate=CANDIDATE,
        )
    with pytest.raises(SemanticFindingsError, match="lowercase SHA-256"):
        validate_semantic_findings(_payload(findings=[_finding(quote_sha256=QUOTE_SHA256.upper())]))
    with pytest.raises(SemanticFindingsError, match="offsets must be >= 0"):
        validate_semantic_findings(_payload(findings=[_finding(start=-1, end=4)]))


def test_nonfinite_temperature_and_wrong_schema_fail_closed():
    with pytest.raises(SemanticFindingsError, match="temperature must be 0"):
        validate_semantic_findings(_payload(extra={"temperature": 0.2}))
    nan_payload = _payload()
    nan_payload["temperature"] = math.nan
    with pytest.raises(SemanticFindingsError, match="Non-finite|temperature"):
        validate_semantic_findings(nan_payload)
    inf_payload = _payload()
    inf_payload["temperature"] = math.inf
    with pytest.raises(SemanticFindingsError, match="Non-finite|temperature"):
        validate_semantic_findings(inf_payload)
    with pytest.raises(SemanticFindingsError, match="schema_version"):
        validate_semantic_findings(_payload(extra={"schema_version": "ai4.semantic_findings.v0.6"}))
    with pytest.raises(SemanticFindingsError, match="Malformed findings JSON"):
        parse_semantic_findings("{not json")
    with pytest.raises(SemanticFindingsError, match="empty findings array"):
        validate_semantic_findings(_payload(status="timeout", findings=[_finding()]))


# --- 9. taxonomy/mapping package identity stable/versioned -------------------


def test_taxonomy_and_mapping_package_identity_stable():
    registry_bytes = packaged_finding_registry_bytes()
    map_bytes = packaged_finding_policy_map_bytes()
    assert _sha256_hex(registry_bytes) == REGISTRY_SHA256
    assert _sha256_hex(map_bytes) == POLICY_MAP_SHA256
    assert finding_registry_sha256() == REGISTRY_SHA256
    assert finding_policy_map_sha256() == POLICY_MAP_SHA256
    assert _sha256_hex(REGISTRY_PATH.read_bytes()) == REGISTRY_SHA256
    assert _sha256_hex(POLICY_MAP_PATH.read_bytes()) == POLICY_MAP_SHA256

    registry = load_finding_registry_v1()
    policy_map = load_finding_policy_map_v1(registry)
    again_registry = load_finding_registry_v1()
    again_map = load_finding_policy_map_v1(again_registry)
    assert registry == again_registry
    assert policy_map == again_map
    assert registry.schema_version == REGISTRY_SCHEMA_VERSION
    assert policy_map.schema_version == POLICY_MAP_SCHEMA_VERSION
    assert registry.version == policy_map.version == TAXONOMY_VERSION
    assert registry.sha256 == REGISTRY_SHA256
    assert policy_map.sha256 == POLICY_MAP_SHA256
    assert registry.class_id_set() == {
        "fabricated_authority",
        "unsupported_certainty",
        "deceptive_claim",
        "governance_manipulation_claim",
        "overclaim_from_ambiguity",
    }
    assert policy_map.required_shards == REQUIRED_IDS
    mapped = {item.class_id: item.shards for item in policy_map.mappings}
    assert mapped["fabricated_authority"] == ("truth",)
    assert mapped["governance_manipulation_claim"] == ("autonomy", "truth")
    assert all(item.class_id in registry.class_id_set() for item in policy_map.mappings)


def test_policy_map_rejects_extra_shard_names_and_unknown_classes():
    registry = load_finding_registry_v1()
    raw = json.loads(packaged_finding_policy_map_bytes())
    raw["required_shards"] = list(REQUIRED_IDS) + ["loyalty"]
    with pytest.raises(SemanticFindingsError, match="extra shard name"):
        validate_finding_policy_map_payload(raw, class_ids=registry.class_id_set())
    raw = json.loads(packaged_finding_policy_map_bytes())
    raw["shard_caps"]["loyalty"] = {"cap": 0.1}
    with pytest.raises(SemanticFindingsError, match="extra shard name"):
        validate_finding_policy_map_payload(raw, class_ids=registry.class_id_set())
    raw = json.loads(packaged_finding_policy_map_bytes())
    raw["mappings"]["not_a_class"] = copy.deepcopy(raw["mappings"]["fabricated_authority"])
    with pytest.raises(SemanticFindingsError, match="Unknown class_id"):
        validate_finding_policy_map_payload(raw, class_ids=registry.class_id_set())


def test_registry_rejects_unknown_fields():
    raw = json.loads(packaged_finding_registry_bytes())
    raw["notes"] = "freeform"
    with pytest.raises(SemanticFindingsError, match="Unknown finding_registry_v1 field"):
        validate_finding_registry_payload(raw)


def test_s1_packaged_overlays_and_caps_are_nonnegative():
    policy_map = load_finding_policy_map_v1()
    assert policy_map.shard_caps
    for cap in policy_map.shard_caps:
        assert cap.cap >= 0, cap
    for mapping in policy_map.mappings:
        for _bin, deltas in mapping.overlay_deltas:
            for _shard, value in deltas:
                assert value >= 0, (mapping.class_id, _bin, _shard, value)


def test_s1_negative_overlay_and_over_cap_reject():
    registry = load_finding_registry_v1()
    raw = json.loads(packaged_finding_policy_map_bytes())
    raw["mappings"]["fabricated_authority"]["overlay_deltas"]["medium"]["truth"] = -0.05
    with pytest.raises(SemanticFindingsError, match="must be nonnegative"):
        validate_finding_policy_map_payload(raw, class_ids=registry.class_id_set())
    raw = json.loads(packaged_finding_policy_map_bytes())
    raw["mappings"]["fabricated_authority"]["overlay_deltas"]["high"]["truth"] = 0.41
    with pytest.raises(SemanticFindingsError, match="exceeds shard cap"):
        validate_finding_policy_map_payload(raw, class_ids=registry.class_id_set())
    raw = json.loads(packaged_finding_policy_map_bytes())
    raw["shard_caps"]["truth"]["cap"] = -0.4
    with pytest.raises(SemanticFindingsError, match="nonnegative"):
        validate_finding_policy_map_payload(raw, class_ids=registry.class_id_set())


def test_s1_c3_equation_lowers_representative_det_without_fusion():
    """Mathematical compatibility only. Does not execute packaged_fuse_v2."""
    policy_map = load_finding_policy_map_v1()
    mapping = next(item for item in policy_map.mappings if item.class_id == "fabricated_authority")
    overlay = dict(dict(mapping.overlay_deltas)["medium"])["truth"]
    assert overlay == pytest.approx(0.15)
    det = 0.8
    fused = max(0.0, min(det, det - overlay))
    assert fused == pytest.approx(0.65)
    assert 0.0 <= fused <= det
    assert fused < det


def test_taxonomy_stubs_are_not_beta_paraphrases():
    registry_text = REGISTRY_PATH.read_text(encoding="utf-8").lower()
    map_text = POLICY_MAP_PATH.read_text(encoding="utf-8").lower()
    for forbidden in ("jane doe", "078-05-1120", "build a bomb", "heldout", "beta prompt"):
        assert forbidden not in registry_text
        assert forbidden not in map_text


# --- 10. existing v0.6 floor: run/evaluate unchanged, semantic not operational


def test_semantic_mode_is_not_operational():
    assert SEMANTIC_EXAMINER_OPERATIONAL is False
    assert public.SEMANTIC_EXAMINER_OPERATIONAL is False
    report = evaluate(CLEAN_EVAL)
    assert report.decision == "accept"
    assert report.versions.evidence_class == "null_retained_D_adds_cost"
    assert report.versions.protocol == "v0.1"
    loop = run(CLEAN_RUN)
    assert loop.decision == "accept"
    assert loop.versions.condition == "D"


def test_run_and_evaluate_signatures_and_defaults_unchanged():
    run_params = inspect.signature(run_fn).parameters
    evaluate_params = inspect.signature(evaluate_fn).parameters
    assert tuple(run_params) == (
        "prompt",
        "proposal",
        "provider",
        "evaluator",
        "rubric_set",
        "max_revision_rounds",
        "timeout_s",
        "max_completions",
        "prompt_specified_shards",
        "prompt_id",
        "config",
        "redact",
    )
    assert tuple(evaluate_params) == (
        "text",
        "prompt",
        "evaluator",
        "rubric_set",
        "prompt_specified_shards",
        "prompt_id",
        "max_revision_rounds",
        "redact",
    )
    assert run_params["provider"].default is None
    assert run_params["evaluator"].default is None
    assert evaluate_params["evaluator"].default is None
    assert "semantic" not in inspect.getsource(run_fn).lower()
    assert "semantic" not in inspect.getsource(evaluate_fn).lower()
    assert "bind_semantic_findings" not in inspect.getsource(run_fn)
    assert "parse_semantic_findings" not in inspect.getsource(evaluate_fn)


def test_governing_path_modules_do_not_import_semantic_findings():
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
                if "semantic_findings" in name or "semantic_taxonomy" in name:
                    offenders.append(f"{path}: {name}")
    assert offenders == []


def test_public_exports_include_parse_validate_bind_without_identity_leak():
    assert public.parse_semantic_findings is parse_semantic_findings
    assert public.validate_semantic_findings is validate_semantic_findings
    assert public.bind_semantic_findings is bind_semantic_findings
    assert public.claim_fingerprint_v1 is claim_fingerprint_v1
    assert "AgentIdentity" not in public.__all__
    assert "parse_semantic_findings" in public.__all__
    assert "run" in public.__all__
    assert "evaluate" in public.__all__
