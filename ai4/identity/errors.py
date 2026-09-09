"""Fail-closed errors for the identity/provenance kernel.

These are not constraint decisions. They never become accept/revise/refuse.
"""

from __future__ import annotations


class IdentityError(ValueError):
    """A required identity, attestation, or binding step could not complete.

    Callers must treat this as a hard failure. The kernel does not skip
    unknown fields, unknown algorithms, or unverified signatures.
    """
