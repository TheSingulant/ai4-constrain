"""V07-3B non-governing infrastructure primitives.

Synthetic fixtures only. No frozen Beta prompts. No live/paid providers.
These tests import the private ``ai4.constrain._v07_3b`` package directly.
They do not activate hybrid on ``run()`` / ``evaluate()``.
"""

from __future__ import annotations

import inspect
import math
import time
from types import SimpleNamespace

import pytest

from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.budget import STATE_EXECUTING, STATE_RESERVED, RunBudgetAuthority
from ai4.constrain._v07_3a.context import ContinuitySnapshot, NotReady, TrustedProductConfig
from ai4.constrain._v07_3b.budget import BudgetAwareProviderAdapter, reserve_examiner_lane
from ai4.constrain._v07_3b.context import (
    HybridConfiguration,
    HybridContext,
    HybridContextBuilder,
    HybridContextValidator,
)
from ai4.constrain._v07_3b.feedback import (
    FEEDBACK_TEMPLATE_REGISTRY_VERSION,
    format_hybrid_revision_feedback,
    lookup_feedback_template,
    reject_injected_feedback_payload,
)
from ai4.constrain._v07_3b.origin import (
    REDIRECT_POLICY_EXPLICIT_ALLOWLIST,
    REDIRECT_POLICY_NONE,
    allowlist_origin,
    bind_transport,
    canonicalize_origin,
)
from ai4.constrain._v07_3b.provenance import (
    CLAIM_CONFIGURED,
    CLAIM_SERVED_MODEL_OBSERVED,
    MINT_CALLER_POPULATED,
    MINT_SERVED_MODEL,
    PROVENANCE_CLAIMS,
    ProvenanceClaim,
    bundle_claims,
    collect_account_observed,
    collect_configured,
    collect_origin_allowlisted,
    collect_provider_session_bound,
    collect_served_model_observed,
    collect_transport_bound,
    evidence_is_attested,
    evidence_is_authenticated,
)
from ai4.constrain._v07_3b.readiness import (
    REASON_DEFERRED_TO_3C,
    ReadinessFacts,
    compute_readiness_facts,
    hybrid_ready,
    observed_provenance_required_satisfied,
)
from ai4.constrain._v07_3b.separation import (
    CREDENTIAL_COMPARE_ALGORITHM,
    GRADE_BEST_EFFORT,
    GRADE_HARD_DISQUALIFIER,
    GRADE_MINIMUM_OPERATIONAL,
    assess_operational_separation,
    credential_compare_token,
    credentials_equal,
)
from ai4.constrain._v07_3b.snapshot import (
    ArtifactContinuitySnapshot,
    assert_locked_artifact_hashes,
    detect_identity_drift,
)
from ai4.constrain.semantic_examiner import EXAMINER_PIN_KIND, EXAMINER_PIN_KIND_CALLER_CONFIG
from ai4.constrain.semantic_findings import FINDINGS_SCHEMA_VERSION, SEMANTIC_EXAMINER_OPERATIONAL
from ai4.constrain.semantic_fuse import LOCKED_POLICY_MAP_SHA256, LOCKED_REGISTRY_SHA256, PACKAGED_FUSE_ID
from src.providers.mock import HeuristicMockProvider

REGISTRY_SHA256 = "e817eb246889cd19e090f96f005b577252b90b87028c50860e03cacbcee94535"
POLICY_MAP_SHA256 = "c84c613d7811fd0701ac90051d4f5b9640b90e8e978430bbd64f4cca81215a78"
PROMPT_SHA256 = "6ec541e391f7207a1b12ee1a00c7311c8de4a50810651a0eca829a2f07dc62bf"

PROPOSER_ORIGIN = "https://proposer.test"
EXAMINER_ORIGIN = "https://examiner.test"


def _trusted_config() -> TrustedProductConfig:
    return TrustedProductConfig(
        proposer_provider_id="synthetic-proposer",
        proposer_model_id="synthetic-proposer-model",
        examiner_provider_id="synthetic-examiner",
        examiner_model_id="synthetic-examiner-model",
        examiner_id="synthetic-examiner-id",
        examiner_version="0.7.3b-test",
        observation_prompt_sha256=PROMPT_SHA256,
    )


def _configuration(**overrides: object) -> HybridConfiguration:
    values: dict[str, object] = {
        "trusted": _trusted_config(),
        "origin_allowlist": (PROPOSER_ORIGIN, EXAMINER_ORIGIN),
        "proposer_requested_origin": PROPOSER_ORIGIN,
        "examiner_requested_origin": EXAMINER_ORIGIN,
        "max_usd": 1.0,
        "deadline_monotonic": time.monotonic() + 30.0,
        "max_proposal_completions": 2,
        "max_examiner_calls": 1,
    }
    values.update(overrides)
    return HybridConfiguration(**values)  # type: ignore[arg-type]


def _off_continuity() -> ContinuitySnapshot:
    return ContinuitySnapshot(
        ever_on=False,
        ever_required=False,
        persisted_report_schema_0_2_0=False,
        persisted_semantic=False,
    )


def _snapshot(**overrides: object) -> ArtifactContinuitySnapshot:
    values: dict[str, object] = {
        "observation_prompt_sha256": PROMPT_SHA256,
        "registry_sha256": REGISTRY_SHA256,
        "policy_map_sha256": POLICY_MAP_SHA256,
        "fuse_id": PACKAGED_FUSE_ID,
        "examiner_config_identity": "synthetic-examiner-id:0.7.3b-test:synthetic-examiner/synthetic-examiner-model",
        "examiner_provenance_identity": "configured=configured",
        "proposer_identity": "synthetic-proposer/synthetic-proposer-model",
        "evaluator_identity": "v0.1-regex",
        "evaluator_fingerprint": "frozen:v0.1-regex",
        "semantic_schema_version": FINDINGS_SCHEMA_VERSION,
        "examiner_call_cap": 1,
        "semantic_config_version": "v07.3b.0",
    }
    values.update(overrides)
    return ArtifactContinuitySnapshot(**values)  # type: ignore[arg-type]


# --- §1 provenance ----------------------------------------------------------


def test_provenance_vocabulary_and_configured_is_not_observed():
    assert PROVENANCE_CLAIMS == (
        "configured",
        "transport_bound",
        "origin_allowlisted",
        "provider_session_bound",
        "served_model_observed",
        "account_observed",
    )
    configured = collect_configured("synthetic-examiner/synthetic-examiner-model")
    assert configured.claim == CLAIM_CONFIGURED
    assert configured.is_runtime_observed() is False
    assert configured.is_attested() is False
    observed = collect_served_model_observed("synthetic-served-model")
    assert observed.claim == CLAIM_SERVED_MODEL_OBSERVED
    assert observed.is_runtime_observed() is True
    assert observed.is_attested() is False
    bundle = bundle_claims((configured, observed))
    assert evidence_is_attested(bundle) is False
    assert evidence_is_authenticated(bundle) is False
    assert evidence_is_attested(configured) is False


def test_caller_populated_labels_cannot_mint_observed_provenance():
    with pytest.raises(HybridExecutionAbort) as exc:
        ProvenanceClaim(
            claim=CLAIM_SERVED_MODEL_OBSERVED,
            value="spoofed-model",
            minted_by=MINT_CALLER_POPULATED,
        )
    assert exc.value.abort_class == "caller_config_pin_forbidden"
    with pytest.raises(HybridExecutionAbort) as spoofed:
        ProvenanceClaim(
            claim=CLAIM_SERVED_MODEL_OBSERVED,
            value="spoofed-model",
            minted_by=MINT_SERVED_MODEL,
        )
    assert spoofed.value.abort_class == "caller_config_pin_forbidden"
    with pytest.raises(HybridExecutionAbort):
        ProvenanceClaim(
            claim=CLAIM_SERVED_MODEL_OBSERVED,
            value="spoofed-model",
            minted_by="authenticated",
        )


def test_collectors_cover_all_slots():
    claims = (
        collect_configured("cfg"),
        collect_transport_bound("https://examiner.test"),
        collect_origin_allowlisted("https://examiner.test"),
        collect_provider_session_bound("obj:1"),
        collect_served_model_observed("served"),
        collect_account_observed("acct-1"),
    )
    bundle = bundle_claims(claims)
    assert bundle.kind == "runtime_observed"
    assert bundle.observed_value("served_model_observed") == "served"
    assert bundle.observed_value("configured") is None


# --- §2 origin --------------------------------------------------------------


def test_canonical_origin_normalization():
    assert canonicalize_origin("HTTPS://EXAMPLE.com:443/path?q=1#frag") == "https://example.com"
    assert canonicalize_origin("http://EXAMPLE.com.:80") == "http://example.com"
    assert canonicalize_origin("https://example.com:8443/x") == "https://example.com:8443"
    puny = canonicalize_origin("https://exämple.test")
    assert puny.startswith("https://xn--")
    assert "/" not in puny[len("https://") :]
    with pytest.raises(HybridExecutionAbort) as exc:
        canonicalize_origin("ftp://example.com")
    assert exc.value.abort_class == "origin_allowlist_failure"
    with pytest.raises(HybridExecutionAbort):
        canonicalize_origin("https://user:pass@example.com")


def test_origin_allowlist_and_honest_redirect_policy():
    allowed = allowlist_origin("https://EXAMINER.test/ignored", (EXAMINER_ORIGIN, PROPOSER_ORIGIN))
    assert allowed == EXAMINER_ORIGIN
    with pytest.raises(HybridExecutionAbort) as exc:
        allowlist_origin("https://other.test", (EXAMINER_ORIGIN,))
    assert exc.value.abort_class == "origin_allowlist_failure"

    bound = bind_transport(
        requested_origin=EXAMINER_ORIGIN,
        peer_origin="https://examiner.test:443",
        redirect_policy=REDIRECT_POLICY_NONE,
    )
    assert bound.peer_is_proxy is False
    with pytest.raises(HybridExecutionAbort):
        bind_transport(
            requested_origin=EXAMINER_ORIGIN,
            peer_origin="https://proxy.test",
            redirect_policy=REDIRECT_POLICY_NONE,
        )
    with pytest.raises(HybridExecutionAbort):
        bind_transport(
            requested_origin=EXAMINER_ORIGIN,
            peer_origin=EXAMINER_ORIGIN,
            followed_redirects=("https://other.test",),
            redirect_policy=REDIRECT_POLICY_NONE,
        )
    proxy = bind_transport(
        requested_origin=EXAMINER_ORIGIN,
        peer_origin="https://proxy.test",
        followed_redirects=(EXAMINER_ORIGIN,),
        redirect_policy=REDIRECT_POLICY_EXPLICIT_ALLOWLIST,
        allowlist=(EXAMINER_ORIGIN, "https://proxy.test"),
    )
    assert proxy.peer_is_proxy is True
    assert proxy.peer_origin == "https://proxy.test"


# --- §3 operational separation ----------------------------------------------


def test_operational_separation_grades_and_credential_hmac():
    assert CREDENTIAL_COMPARE_ALGORITHM == "hmac-sha256-ephemeral-process-local"
    config = _trusted_config()
    from ai4.constrain._v07_3a.context import bind_roles

    proposer, examiner = bind_roles(config)
    minimum = assess_operational_separation(proposer=proposer, examiner=examiner)
    assert minimum.grade == GRADE_MINIMUM_OPERATIONAL
    assert minimum.minimum_satisfied is True
    assert "independence" not in minimum.grade
    assert "legal_entity_independence" in minimum.not_proven

    same_pin = assess_operational_separation(proposer=proposer, examiner=proposer)
    assert same_pin.grade == GRADE_HARD_DISQUALIFIER
    assert "same_provider_and_model_pin" in same_pin.hard_disqualifiers

    token_a = credential_compare_token("synthetic-secret-a")
    token_b = credential_compare_token("synthetic-secret-b")
    assert credentials_equal(token_a, token_a) is True
    assert credentials_equal(token_a, token_b) is False
    shared = assess_operational_separation(
        proposer=proposer,
        examiner=examiner,
        proposer_credential="shared-secret",
        examiner_credential="shared-secret",
    )
    assert shared.grade == GRADE_HARD_DISQUALIFIER
    assert "shared_credential" in shared.hard_disqualifiers

    client = object()
    shared_obj = assess_operational_separation(
        proposer=proposer,
        examiner=examiner,
        proposer_session=client,
        examiner_session=client,
    )
    assert shared_obj.grade == GRADE_HARD_DISQUALIFIER

    from ai4.constrain._v07_3a.context import RoleBinding

    same_provider = RoleBinding(
        role="examiner",
        provider_id=proposer.provider_id,
        model_id="other-model",
    )
    best = assess_operational_separation(proposer=proposer, examiner=same_provider)
    assert best.grade == GRADE_BEST_EFFORT
    assert "same_provider_different_model" in best.best_effort_notes
    assert best.minimum_satisfied is False


# --- §4 / §10 context builder and readiness ---------------------------------


def test_hybrid_context_builder_and_non_installing_readiness():
    context = (
        HybridContextBuilder(_configuration())
        .with_continuity(_off_continuity())
        .with_runtime_provenance(
            bundle_claims(
                (
                    collect_configured("synthetic-examiner/synthetic-examiner-model"),
                    collect_origin_allowlisted(EXAMINER_ORIGIN),
                    collect_transport_bound(EXAMINER_ORIGIN),
                )
            )
        )
        .build()
    )
    assert isinstance(context, HybridContext)
    facts = HybridContextValidator().validate(context)
    assert facts.origin_allowlisted is True
    assert facts.locked_artifacts_ok is True
    assert facts.hard_disqualified is False
    readiness = compute_readiness_facts(context)
    assert isinstance(readiness, ReadinessFacts)
    assert readiness.ready is False
    assert readiness.installing is False
    result = hybrid_ready(context)
    assert isinstance(result, NotReady)
    assert result.reason == REASON_DEFERRED_TO_3C
    with pytest.raises(HybridExecutionAbort) as exc:
        result.install()
    assert exc.value.abort_class == "continuity_required_not_ready"
    with pytest.raises(HybridExecutionAbort):
        context.install()
    import ai4.constrain._v07_3b as prim
    import ai4.constrain._v07_3b.readiness as ready_mod

    assert not hasattr(prim, "Ready")
    assert not hasattr(ready_mod, "Ready")
    assert hybrid_ready(None).reason == REASON_DEFERRED_TO_3C


def test_context_rejects_authority_kwargs_and_same_pin():
    with pytest.raises(HybridExecutionAbort) as exc:
        HybridContextBuilder(_configuration(), install=True)  # type: ignore[call-arg]
    assert exc.value.abort_class == "caller_config_pin_forbidden"
    same = _trusted_config()
    colliding = TrustedProductConfig(
        proposer_provider_id=same.examiner_provider_id,
        proposer_model_id=same.examiner_model_id,
        examiner_provider_id=same.examiner_provider_id,
        examiner_model_id=same.examiner_model_id,
        examiner_id=same.examiner_id,
        examiner_version=same.examiner_version,
        observation_prompt_sha256=PROMPT_SHA256,
    )
    context = HybridContextBuilder(
        HybridConfiguration(
            trusted=colliding,
            origin_allowlist=(PROPOSER_ORIGIN, EXAMINER_ORIGIN),
            proposer_requested_origin=PROPOSER_ORIGIN,
            examiner_requested_origin=EXAMINER_ORIGIN,
            max_usd=1.0,
            deadline_monotonic=time.monotonic() + 10.0,
            max_proposal_completions=1,
            max_examiner_calls=1,
        )
    ).build()
    facts = HybridContextValidator().validate(context)
    assert facts.hard_disqualified is True
    assert hybrid_ready(context).reason == REASON_DEFERRED_TO_3C


def test_default_builder_does_not_mint_observed_origin_from_config():
    context = HybridContextBuilder(_configuration()).build()
    assert context.provenance.kind != "runtime_observed"
    assert context.provenance.kind == "unobserved"
    assert all(not item.is_runtime_observed() for item in context.provenance.claims)
    assert context.provenance.claim("origin_allowlisted") is None
    assert context.provenance.claim("configured") is not None
    facts = HybridContextValidator().validate(context)
    assert facts.configured_origin_allowlist_pass is True
    assert facts.origin_allowlisted is False
    assert "origin_allowlisted" not in facts.observed_claim_names
    assert facts.has_runtime_observed_provenance is False
    readiness = compute_readiness_facts(context)
    assert readiness.configured_origin_allowlist_pass is True
    assert readiness.origin_allowlisted is False
    assert "origin_allowlisted" not in readiness.observed_claim_names
    assert readiness.has_runtime_observed_provenance is False
    assert observed_provenance_required_satisfied(readiness) is False


def test_configured_origin_not_on_allowlist_fails_closed():
    with pytest.raises(HybridExecutionAbort) as exc:
        HybridContextBuilder(
            HybridConfiguration(
                trusted=_trusted_config(),
                origin_allowlist=(PROPOSER_ORIGIN,),
                proposer_requested_origin=PROPOSER_ORIGIN,
                examiner_requested_origin=EXAMINER_ORIGIN,
                max_usd=1.0,
                deadline_monotonic=time.monotonic() + 10.0,
                max_proposal_completions=1,
                max_examiner_calls=1,
            )
        )
    assert exc.value.abort_class == "origin_allowlist_failure"


def test_runtime_origin_allowlisted_still_observed():
    context = (
        HybridContextBuilder(_configuration())
        .with_runtime_provenance(
            bundle_claims(
                (
                    collect_configured("synthetic-examiner/synthetic-examiner-model"),
                    collect_origin_allowlisted(EXAMINER_ORIGIN),
                )
            )
        )
        .build()
    )
    assert context.provenance.kind == "runtime_observed"
    observed = context.provenance.claim("origin_allowlisted")
    assert observed is not None
    assert observed.is_runtime_observed() is True
    facts = HybridContextValidator().validate(context)
    assert facts.origin_allowlisted is True
    assert "origin_allowlisted" in facts.observed_claim_names
    assert facts.has_runtime_observed_provenance is True
    readiness = compute_readiness_facts(context)
    assert observed_provenance_required_satisfied(readiness) is True
    assert readiness.configured_origin_allowlist_pass is True


# --- §5 budget surface ------------------------------------------------------


def test_budget_adapter_inert_without_authority_and_honest_with_authority():
    inner = HeuristicMockProvider()
    inert = BudgetAwareProviderAdapter(inner)
    assert inert.budget_authority is None
    first = inert.complete(system="s", user="Please give a brief, checkable outline.")
    assert first.text
    clock = {"now": 0.0}
    auth = RunBudgetAuthority(
        deadline_monotonic=10.0,
        max_proposal_completions=1,
        max_examiner_calls=1,
        max_usd=1.0,
        clock=lambda: clock["now"],
    )
    wrapped = BudgetAwareProviderAdapter(inner, budget_authority=auth, reserve_usd=0.25)
    wrapped.complete(system="s", user="Please give a brief, checkable outline.")
    snap = auth.snapshot()
    assert snap["proposal_committed"] == 1
    assert snap["usd_committed"] >= 0.0
    reservation = reserve_examiner_lane(auth, usd=0.10)
    executing = auth.begin_execute(reservation)
    committed = auth.commit(executing, actual_usd=0.10)
    assert committed.state == "committed"
    assert auth.snapshot()["examiner_committed"] == 1


def test_budget_authority_still_records_actual_over_reserve():
    auth = RunBudgetAuthority(
        deadline_monotonic=time.monotonic() + 30.0,
        max_proposal_completions=1,
        max_examiner_calls=0,
        max_usd=1.0,
    )

    class _Spendy:
        name = "spendy"

        def complete(self, *, system: str, user: str):
            from src.providers.base import Completion

            return Completion(text="ok", estimated_usd=0.40)

        def revise(self, *, system: str, user: str, draft: str, feedback: str):
            from src.providers.base import Completion

            return Completion(text="ok", estimated_usd=0.40)

    wrapped = BudgetAwareProviderAdapter(_Spendy(), budget_authority=auth, reserve_usd=0.10)
    wrapped.complete(system="s", user="u")
    assert auth.snapshot()["usd_committed"] == pytest.approx(0.40)


def _bound_auth(*, max_proposal: int = 2) -> RunBudgetAuthority:
    return RunBudgetAuthority(
        deadline_monotonic=10.0,
        max_proposal_completions=max_proposal,
        max_examiner_calls=0,
        max_usd=1.0,
        clock=lambda: 0.0,
    )


def _assert_no_stranded_reservation(auth: RunBudgetAuthority) -> None:
    snap = auth.snapshot()
    assert snap["usd_reserved"] == 0
    assert snap["proposal_reserved"] == 0
    for handle in auth._reservations.values():
        assert handle.state not in {STATE_RESERVED, STATE_EXECUTING}


def test_unknown_estimated_usd_fails_closed_and_releases():
    from src.providers.base import Completion

    class _Missing:
        name = "missing"

        def complete(self, *, system: str, user: str):
            return SimpleNamespace(text="ok")

        def revise(self, *, system: str, user: str, draft: str, feedback: str):
            return SimpleNamespace(text="ok")

    class _NoneCost:
        name = "none-cost"

        def complete(self, *, system: str, user: str):
            return SimpleNamespace(text="ok", estimated_usd=None)

        def revise(self, *, system: str, user: str, draft: str, feedback: str):
            return SimpleNamespace(text="ok", estimated_usd=None)

    for inner in (_Missing(), _NoneCost()):
        auth = _bound_auth(max_proposal=1)
        wrapped = BudgetAwareProviderAdapter(inner, budget_authority=auth, reserve_usd=0.20)
        with pytest.raises(HybridExecutionAbort) as exc:
            wrapped.complete(system="s", user="u")
        assert exc.value.abort_class == "schema_invalid"
        assert auth.snapshot()["usd_committed"] == 0.0
        assert auth.snapshot()["proposal_committed"] == 0
        _assert_no_stranded_reservation(auth)
        retry = auth.reserve_proposal_completion(usd=0.10)
        assert retry.state == STATE_RESERVED
        auth.release(retry)

    class _Zero:
        name = "zero"

        def complete(self, *, system: str, user: str):
            return Completion(text="ok", estimated_usd=0.0)

        def revise(self, *, system: str, user: str, draft: str, feedback: str):
            return Completion(text="ok", estimated_usd=0.0)

    zero_auth = _bound_auth()
    BudgetAwareProviderAdapter(_Zero(), budget_authority=zero_auth, reserve_usd=0.20).complete(
        system="s", user="u"
    )
    assert zero_auth.snapshot()["usd_committed"] == pytest.approx(0.0)
    assert zero_auth.snapshot()["proposal_committed"] == 1


def test_malformed_estimated_usd_fails_closed_and_releases():
    class _Bad:
        def __init__(self, value: object) -> None:
            self._value = value
            self.name = "bad"

        def complete(self, *, system: str, user: str):
            return SimpleNamespace(text="ok", estimated_usd=self._value)

        def revise(self, *, system: str, user: str, draft: str, feedback: str):
            return SimpleNamespace(text="ok", estimated_usd=self._value)

    for value in (-0.01, math.nan, math.inf, -math.inf, "1.0", object(), True):
        auth = _bound_auth(max_proposal=1)
        wrapped = BudgetAwareProviderAdapter(_Bad(value), budget_authority=auth, reserve_usd=0.20)
        with pytest.raises(HybridExecutionAbort) as exc:
            wrapped.complete(system="s", user="u")
        assert exc.value.abort_class == "schema_invalid"
        assert auth.snapshot()["usd_committed"] == 0.0
        _assert_no_stranded_reservation(auth)
        retry = auth.reserve_proposal_completion(usd=0.10)
        auth.release(retry)


def test_provider_throw_still_releases_and_off_passthrough_unchanged():
    class _Boom:
        name = "boom"

        def complete(self, *, system: str, user: str):
            raise RuntimeError("provider failed")

        def revise(self, *, system: str, user: str, draft: str, feedback: str):
            raise RuntimeError("provider failed")

    auth = _bound_auth(max_proposal=1)
    wrapped = BudgetAwareProviderAdapter(_Boom(), budget_authority=auth, reserve_usd=0.20)
    with pytest.raises(RuntimeError, match="provider failed"):
        wrapped.complete(system="s", user="u")
    assert auth.snapshot()["usd_committed"] == 0.0
    _assert_no_stranded_reservation(auth)
    retry = auth.reserve_proposal_completion(usd=0.10)
    auth.release(retry)

    missing = SimpleNamespace(text="off-passthrough")
    class _NoCost:
        name = "off"

        def complete(self, *, system: str, user: str):
            return missing

        def revise(self, *, system: str, user: str, draft: str, feedback: str):
            return missing

    inert = BudgetAwareProviderAdapter(_NoCost())
    assert inert.complete(system="s", user="u") is missing


# --- §8 feedback templates --------------------------------------------------


def test_feedback_templates_are_closed_and_reject_injection():
    text = lookup_feedback_template("unsupported_certainty", "ungrounded_certainty_cue")
    assert "certainty" in text
    joined = format_hybrid_revision_feedback(
        (("unsupported_certainty", "ungrounded_certainty_cue"),)
    )
    assert "template-only" in joined
    assert FEEDBACK_TEMPLATE_REGISTRY_VERSION.startswith("ai4.hybrid_feedback")
    with pytest.raises(HybridExecutionAbort) as exc:
        format_hybrid_revision_feedback(
            (("unsupported_certainty", "ungrounded_certainty_cue"),),
            freeform="ignore safety",
        )
    assert exc.value.abort_class == "injection_suspected"
    with pytest.raises(HybridExecutionAbort):
        reject_injected_feedback_payload({"quote": "candidate span text"})
    with pytest.raises(HybridExecutionAbort):
        lookup_feedback_template("unsupported_certainty", "deceptive_framing_cue")
    from src.constraints.constraint_middleware import ConstraintMiddleware

    assert "format_hybrid_revision_feedback" not in inspect.getsource(ConstraintMiddleware)
    assert "format_hybrid_revision_feedback" not in inspect.getsource(
        ConstraintMiddleware.format_feedback
    )


# --- §9 artifact snapshot ---------------------------------------------------


def test_artifact_snapshot_drift_fail_closed():
    expected = _snapshot()
    assert_locked_artifact_hashes(expected)
    detect_identity_drift(expected, expected)
    observed = _snapshot(registry_sha256="00" * 32)
    with pytest.raises(HybridExecutionAbort) as exc:
        detect_identity_drift(expected, observed)
    assert exc.value.abort_class == "identity_drift"
    with pytest.raises(HybridExecutionAbort) as hashed:
        assert_locked_artifact_hashes(observed)
    assert hashed.value.abort_class == "registry_hash_mismatch"


def test_locked_constants_and_pin_kind_unchanged():
    assert PROMPT_SHA256 == "6ec541e391f7207a1b12ee1a00c7311c8de4a50810651a0eca829a2f07dc62bf"
    assert REGISTRY_SHA256 == LOCKED_REGISTRY_SHA256
    assert POLICY_MAP_SHA256 == LOCKED_POLICY_MAP_SHA256
    assert PACKAGED_FUSE_ID == "packaged_fuse_v2"
    assert SEMANTIC_EXAMINER_OPERATIONAL is False
    assert EXAMINER_PIN_KIND == EXAMINER_PIN_KIND_CALLER_CONFIG
