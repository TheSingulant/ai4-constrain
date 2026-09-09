"""Bind attestations to DecisionReport bytes. Provenance only.

Binding verdicts are trust/provenance states:
``matched | unbound | mismatch | expired | untrusted_signer``.
They never become accept/revise/refuse and never alter scores or policy.

``matched`` requires an explicit TrustContext. Cryptographic signature
validity is not current trust.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from ai4.identity.attestation import verify_attestation, verify_attestation_signature
from ai4.identity.canonical import canonicalize
from ai4.identity.crypto import Verifier
from ai4.identity.digest import sha256_hex
from ai4.identity.errors import IdentityError
from ai4.identity.schemas import AgentAttestation, ClaimedProfile
from ai4.identity.timeutil import Clock
from ai4.identity.trust import TrustContext

BINDING_VERDICTS = ("matched", "unbound", "mismatch", "expired", "untrusted_signer")
BindingVerdict = Literal["matched", "unbound", "mismatch", "expired", "untrusted_signer"]


@dataclass(frozen=True)
class ReportBinding:
    """Canonical report digest plus VersionInfo claims captured at bind time."""

    report_hash: str
    claimed_profile: ClaimedProfile

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_hash": self.report_hash,
            "claimed_profile": self.claimed_profile.to_dict(),
        }


@dataclass(frozen=True)
class BindingResult:
    """Provenance verdict. Not a constraint decision."""

    verdict: BindingVerdict
    report_hash: str
    expected_report_hash: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "verdict": self.verdict,
            "report_hash": self.report_hash,
            "expected_report_hash": self.expected_report_hash,
            "detail": self.detail,
        }


def report_canonical_bytes(report: object) -> bytes:
    """RFC 8785 JCS of a DecisionReport-shaped object."""
    payload = _report_payload(report)
    return canonicalize(payload, identity_record=False)


def report_digest(report: object) -> str:
    return sha256_hex(report_canonical_bytes(report))


def bind_report(report: object) -> ReportBinding:
    """Hash canonical DecisionReport bytes and copy VersionInfo from that payload.

    Both the report hash and the claimed profile are derived from the
    same ``to_dict()`` / JSON object. A forged duck-typed ``.versions``
    attribute cannot influence binding.
    """
    payload = _report_payload(report)
    versions = _versions_from_payload(payload)
    return ReportBinding(
        report_hash=sha256_hex(canonicalize(payload, identity_record=False)),
        claimed_profile=ClaimedProfile.from_versions(versions),
    )


def verify_report_binding(
    attestation: AgentAttestation | object | None,
    report: object,
    *,
    trust: TrustContext | None = None,
    clock: Clock | None = None,
    verifier: Verifier | None = None,
    now: datetime | None = None,
) -> BindingResult:
    """Compare an attestation to a bound report. Returns a provenance verdict.

    ``matched`` is returned only when an explicit TrustContext accepts
    the attestation as current **and** the report hash/profile match.
    Crypto-valid historical attestations without current trust are
    ``untrusted_signer``, not ``matched``.
    """
    expected = report_digest(report)
    if attestation is None:
        return BindingResult("unbound", "", expected, "no attestation supplied")
    try:
        record = (
            attestation
            if isinstance(attestation, AgentAttestation)
            else AgentAttestation.from_dict(attestation)
        )
    except IdentityError as exc:
        raise IdentityError(f"malformed attestation fails closed: {exc}") from exc
    try:
        crypto = verify_attestation_signature(
            record, clock=clock, verifier=verifier, now=now
        )
    except IdentityError as exc:
        message = str(exc)
        if "expired" in message:
            return BindingResult("expired", record.report_hash, expected, message)
        if any(
            needle in message
            for needle in (
                "controller",
                "signature",
                "not yet valid",
                "manifest hash",
            )
        ):
            return BindingResult("untrusted_signer", record.report_hash, expected, message)
        raise
    if not crypto.report_hash:
        return BindingResult("unbound", "", expected, "attestation carries no report_hash")
    if crypto.report_hash != expected:
        return BindingResult(
            "mismatch",
            crypto.report_hash,
            expected,
            "wrong report hash",
        )
    actual_profile = ClaimedProfile.from_versions(_versions_from_payload(_report_payload(report)))
    if crypto.claimed_profile is None:
        return BindingResult("unbound", crypto.report_hash, expected, "no claimed profile")
    if crypto.claimed_profile.comparable() != actual_profile.comparable():
        return BindingResult(
            "mismatch",
            crypto.report_hash,
            expected,
            "runtime/rubric/evaluator/evidence-class claim mismatch vs bound report",
        )
    if trust is None:
        return BindingResult(
            "untrusted_signer",
            crypto.report_hash,
            expected,
            "TrustContext required for current-trust matched verdict; "
            "signature validity is not current identity",
        )
    try:
        verify_attestation(crypto, trust, clock=clock, verifier=verifier, now=now)
    except IdentityError as exc:
        message = str(exc)
        if "expired" in message:
            return BindingResult("expired", crypto.report_hash, expected, message)
        return BindingResult("untrusted_signer", crypto.report_hash, expected, message)
    return BindingResult("matched", crypto.report_hash, expected, "report binding matched under current trust")


def _report_payload(report: object) -> dict[str, Any]:
    if hasattr(report, "to_dict"):
        payload = report.to_dict()
    elif isinstance(report, dict):
        payload = dict(report)
    else:
        raise IdentityError("bind_report requires a DecisionReport or JSON object")
    if not isinstance(payload, dict):
        raise IdentityError("DecisionReport payload must be a JSON object")
    forbidden = [key for key in payload if key in ("signature", "attestation", "identity_proof")]
    if forbidden:
        raise IdentityError(
            f"report payload must not carry signature field(s) {forbidden}; "
            "report-schema signature fields are out of scope"
        )
    return payload


def _versions_from_payload(payload: dict[str, Any]) -> object:
    if "versions" not in payload:
        raise IdentityError("report is missing versions")
    versions = payload["versions"]
    if not isinstance(versions, dict):
        raise IdentityError("report.versions must be an object")
    return versions
