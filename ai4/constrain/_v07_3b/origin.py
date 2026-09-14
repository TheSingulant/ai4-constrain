"""Canonical origin normalization and allowlist (V07-3B §2).

Deterministic origin identity:

- scheme is ``http`` or ``https`` only, lowercased
- host is lowercased, IDNA-encoded, trailing dots stripped
- default ports (80 / 443) are omitted
- path, query, and fragment are never part of the canonical origin
- userinfo is rejected

Redirect / proxy honesty
------------------------
If the TLS/TCP peer is a proxy, the bound origin is the proxy peer, not
the caller-intended origin. This module does not silently accept
arbitrary redirects. The default redirect policy is ``none``: the peer
must equal the requested origin. ``explicit_allowlist`` requires every
recorded hop and the final peer to be allowlisted after normalization.

TLS wording
-----------
``transport_bound`` records the peer we were told we connected to. It is
not a certificate-pin, CT-log, or cryptographic endpoint attestation.
"""

from __future__ import annotations

import encodings.idna
import ipaddress
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlsplit

from ai4.constrain._v07_3a._common import reject_authority_kwargs, require_str
from ai4.constrain._v07_3a.abort import HybridExecutionAbort

REDIRECT_POLICY_NONE = "none"
REDIRECT_POLICY_EXPLICIT_ALLOWLIST = "explicit_allowlist"
_REDIRECT_POLICIES = frozenset({REDIRECT_POLICY_NONE, REDIRECT_POLICY_EXPLICIT_ALLOWLIST})
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _idna_host(host: str) -> str:
    trimmed = host.rstrip(".").lower()
    if not trimmed:
        raise HybridExecutionAbort("schema_invalid", "origin missing host")
    if trimmed.startswith("[") and trimmed.endswith("]"):
        trimmed = trimmed[1:-1]
    try:
        ip = ipaddress.ip_address(trimmed)
    except ValueError:
        ip = None
    if ip is not None:
        if isinstance(ip, ipaddress.IPv6Address):
            return f"[{ip.compressed}]"
        return ip.compressed
    try:
        return encodings.idna.ToASCII(trimmed).decode("ascii")
    except (UnicodeError, UnicodeDecodeError) as exc:
        raise HybridExecutionAbort(
            "schema_invalid",
            f"host is not IDNA-encodable: {trimmed!r}",
        ) from exc


def canonicalize_origin(raw: str, **kwargs: Any) -> str:
    """Return ``scheme://host[:port]`` with no path/query/fragment."""
    reject_authority_kwargs(kwargs, label="canonicalize_origin")
    text = require_str(raw, field="origin")
    parts = urlsplit(text.strip())
    scheme = (parts.scheme or "").lower()
    if scheme not in _DEFAULT_PORTS:
        raise HybridExecutionAbort(
            "origin_allowlist_failure",
            f"unsupported origin scheme {scheme!r}",
        )
    if parts.username is not None or parts.password is not None:
        raise HybridExecutionAbort("schema_invalid", "origin must not include userinfo")
    host = parts.hostname
    if not host:
        raise HybridExecutionAbort("schema_invalid", "origin missing host")
    host = _idna_host(host)
    try:
        port = parts.port
    except ValueError as exc:
        raise HybridExecutionAbort("schema_invalid", "origin port is invalid") from exc
    if port is not None and port == _DEFAULT_PORTS[scheme]:
        port = None
    netloc = host if port is None else f"{host}:{port}"
    return f"{scheme}://{netloc}"


def normalize_allowlist(origins: Iterable[str], **kwargs: Any) -> tuple[str, ...]:
    reject_authority_kwargs(kwargs, label="normalize_allowlist")
    seen: set[str] = set()
    out: list[str] = []
    for item in origins:
        canonical = canonicalize_origin(item)
        if canonical not in seen:
            seen.add(canonical)
            out.append(canonical)
    return tuple(out)


def allowlist_origin(
    origin: str,
    allowlist: Iterable[str],
    **kwargs: Any,
) -> str:
    """Return the canonical origin if it is on the product allowlist."""
    reject_authority_kwargs(kwargs, label="allowlist_origin")
    canonical = canonicalize_origin(origin)
    allowed = set(normalize_allowlist(allowlist))
    if canonical not in allowed:
        raise HybridExecutionAbort(
            "origin_allowlist_failure",
            f"origin {canonical!r} is not on the product allowlist",
        )
    return canonical


@dataclass(frozen=True)
class TransportBinding:
    """Honest peer binding. Not a TLS attestation.

    ``peer_origin`` is the origin of the socket/TLS peer that was actually
    used. If that peer is a proxy, this field is the proxy origin.
    """

    requested_origin: str
    peer_origin: str
    followed_redirects: tuple[str, ...]
    redirect_policy: str
    peer_is_proxy: bool

    def __post_init__(self) -> None:
        if self.redirect_policy not in _REDIRECT_POLICIES:
            raise HybridExecutionAbort(
                "schema_invalid",
                f"unknown redirect policy {self.redirect_policy!r}",
            )
        if not isinstance(self.peer_is_proxy, bool):
            raise HybridExecutionAbort("schema_invalid", "peer_is_proxy must be a bool")
        if not isinstance(self.followed_redirects, tuple):
            raise HybridExecutionAbort("schema_invalid", "followed_redirects must be a tuple")


def bind_transport(
    *,
    requested_origin: str,
    peer_origin: str,
    followed_redirects: Iterable[str] = (),
    redirect_policy: str = REDIRECT_POLICY_NONE,
    allowlist: Iterable[str] = (),
    **kwargs: Any,
) -> TransportBinding:
    """Bind the requested origin to the observed peer.

    Hidden arbitrary redirect acceptance is rejected. When the peer
    differs from the requested origin, the peer is recorded as a proxy
    (or redirect target) rather than rewritten into the requested label.
    """
    reject_authority_kwargs(kwargs, label="bind_transport")
    if redirect_policy not in _REDIRECT_POLICIES:
        raise HybridExecutionAbort(
            "schema_invalid",
            f"unknown redirect policy {redirect_policy!r}",
        )
    requested = canonicalize_origin(requested_origin)
    peer = canonicalize_origin(peer_origin)
    hops = tuple(canonicalize_origin(item) for item in followed_redirects)
    if redirect_policy == REDIRECT_POLICY_NONE:
        if hops:
            raise HybridExecutionAbort(
                "origin_allowlist_failure",
                "redirect policy none does not accept recorded redirects",
            )
        if peer != requested:
            raise HybridExecutionAbort(
                "origin_allowlist_failure",
                f"peer {peer!r} differs from requested {requested!r}; "
                "policy none does not accept a proxy or redirect",
            )
        return TransportBinding(
            requested_origin=requested,
            peer_origin=peer,
            followed_redirects=(),
            redirect_policy=redirect_policy,
            peer_is_proxy=False,
        )
    allowed = set(normalize_allowlist(allowlist))
    for hop in (requested, *hops, peer):
        if hop not in allowed:
            raise HybridExecutionAbort(
                "origin_allowlist_failure",
                f"redirect/peer hop {hop!r} is not on the product allowlist",
            )
    return TransportBinding(
        requested_origin=requested,
        peer_origin=peer,
        followed_redirects=hops,
        redirect_policy=redirect_policy,
        peer_is_proxy=peer != requested,
    )


__all__ = [
    "REDIRECT_POLICY_EXPLICIT_ALLOWLIST",
    "REDIRECT_POLICY_NONE",
    "TransportBinding",
    "allowlist_origin",
    "bind_transport",
    "canonicalize_origin",
    "normalize_allowlist",
]
