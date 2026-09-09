"""Deterministic JSON canonicalization for identity and report digests.

Profile: RFC 8785 JSON Canonicalization Scheme (JCS), implemented by the
``rfc8785`` library (Trail of Bits). Identity records additionally reject
types that must never appear in this kernel (floats, bytes, non-string
keys, sets). Report binding uses the same RFC 8785 bytes over the report
JSON object, including the finite floats already present on DecisionReport.

Pinned implementation: ``rfc8785==0.1.4``. That release follows RFC 8785
ES6 number serialization, including collapsing IEEE ``+0.0`` and ``-0.0``
to JSON ``0``. Report digests are therefore this locked profile, not an
unbounded “any rfc8785” portable hash.

This module never touches the network.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import rfc8785

from ai4.identity.errors import IdentityError

CANONICALIZATION_PROFILE = "rfc8785-jcs"
RFC8785_PACKAGE_VERSION = "0.1.4"
IDENTITY_VALUE_TYPES = (type(None), bool, int, str, list, tuple, dict)


def _reject_identity_types(value: object, *, path: str = "$") -> None:
    """Fail closed on types that identity records must not carry."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, str):
        return
    if isinstance(value, float):
        raise IdentityError(
            f"{path}: identity canonicalization forbids floats; "
            "use RFC 8785 report binding for DecisionReport numbers"
        )
    if isinstance(value, bytes):
        raise IdentityError(f"{path}: identity canonicalization forbids bytes")
    if isinstance(value, (set, frozenset)):
        raise IdentityError(f"{path}: identity canonicalization forbids sets")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise IdentityError(f"{path}: object keys must be strings")
            _reject_identity_types(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            _reject_identity_types(item, path=f"{path}[{index}]")
        return
    raise IdentityError(f"{path}: unsupported identity type {type(value).__name__}")


def canonicalize(value: object, *, identity_record: bool = False) -> bytes:
    """Return RFC 8785 JCS UTF-8 bytes.

    ``identity_record=True`` applies the closed identity type profile
    before JCS. Report binding leaves this false so finite floats in
    DecisionReport remain representable.
    """
    if identity_record:
        _reject_identity_types(value)
    try:
        return rfc8785.dumps(value)
    except rfc8785.CanonicalizationError as exc:
        raise IdentityError(f"RFC 8785 canonicalization failed: {exc}") from exc


def canonicalize_utf8(value: object, *, identity_record: bool = False) -> str:
    return canonicalize(value, identity_record=identity_record).decode("utf-8")
