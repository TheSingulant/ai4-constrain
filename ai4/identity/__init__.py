"""``ai4.identity`` — offline identity and provenance kernel.

A signed AI⁴ identity record binds claims and provenance to an agent identity; it does not prove the agent is aligned, safe, or correctly governed.

Identity is not trust. Identity makes trust systems possible.

This module is a sibling of ``ai4.constrain``. It is not imported by
``run()``, ``evaluate()``, session walls, the provider wall, or the
evaluator wall. It does not write signature fields onto DecisionReport,
does not bind sessions to ``.ai4`` names, controller keys, manifest
hashes, or manifest versions, and never feeds policy back into
RuntimeConfig, SessionPolicyIdentity, rubrics, thresholds, arbitration,
the D controller, refusal semantics, or ``EVIDENCE_CLASS``.

Verification is fully offline. There is no default network access, no
Unstoppable SDK, no on-chain write, no wallet-as-identity, no tokenomics,
no TEE, and no HTTP service. Crypto is standard Ed25519 and SHA-256 only.
Canonicalization is RFC 8785 JCS.

Live ``.ai4`` lookup lives in ``ai4.identity.resolve``. That adapter is
a discovery sibling, not this kernel. This preamble does not import or
export resolver types. Resolution is not verification.
"""

from __future__ import annotations

from ai4.identity.attestation import (
    sign_attestation,
    sign_rotation,
    verify_attestation,
    verify_attestation_signature,
)
from ai4.identity.binding import (
    BINDING_VERDICTS,
    BindingResult,
    ReportBinding,
    bind_report,
    report_digest,
    verify_report_binding,
)
from ai4.identity.canonical import (
    CANONICALIZATION_PROFILE,
    RFC8785_PACKAGE_VERSION,
    canonicalize,
)
from ai4.identity.crypto import (
    SIGNATURE_ALGORITHM,
    LocalEd25519,
    generate_ed25519_keypair,
)
from ai4.identity.digest import digest_canonical, sha256_hex
from ai4.identity.errors import IdentityError
from ai4.identity.schemas import (
    ATTESTATION_SCHEMA_ID,
    IDENTITY_SCHEMA_ID,
    MANIFEST_VERSION_MAX,
    MANIFEST_VERSION_MIN,
    AgentAttestation,
    AgentIdentity,
    ClaimedProfile,
    NameRecordSnapshot,
    RotationAttestation,
)
from ai4.identity.timeutil import FixedClock, SystemClock
from ai4.identity.trust import TrustContext, verify_rotation

GOVERNING_PRINCIPLE = (
    "A signed AI⁴ identity record binds claims and provenance to an agent "
    "identity; it does not prove the agent is aligned, safe, or correctly "
    "governed."
)

__all__ = [
    "ATTESTATION_SCHEMA_ID",
    "BINDING_VERDICTS",
    "CANONICALIZATION_PROFILE",
    "GOVERNING_PRINCIPLE",
    "IDENTITY_SCHEMA_ID",
    "MANIFEST_VERSION_MAX",
    "MANIFEST_VERSION_MIN",
    "RFC8785_PACKAGE_VERSION",
    "SIGNATURE_ALGORITHM",
    "AgentAttestation",
    "AgentIdentity",
    "BindingResult",
    "ClaimedProfile",
    "FixedClock",
    "IdentityError",
    "LocalEd25519",
    "NameRecordSnapshot",
    "ReportBinding",
    "RotationAttestation",
    "SystemClock",
    "TrustContext",
    "bind_report",
    "canonicalize",
    "digest_canonical",
    "generate_ed25519_keypair",
    "report_digest",
    "sha256_hex",
    "sign_attestation",
    "sign_rotation",
    "verify_attestation",
    "verify_attestation_signature",
    "verify_report_binding",
    "verify_rotation",
]
