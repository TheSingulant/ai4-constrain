"""Optional Solana JSON-RPC helper using stdlib urllib. Fail closed."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ai4.transaction.errors import TransactionControlError

RPC_ENV_VAR = "AI4_SOLANA_RPC_URL"
DEFAULT_TIMEOUT_S = 10.0

RpcPost = Callable[[str, str, list[Any], float], dict[str, Any]]


def resolve_rpc_url(explicit: str | None = None) -> str | None:
    """Return an RPC URL from an explicit argument or the documented env var.

    Empty values mean "no RPC". There is no hardcoded public endpoint.
    """

    if explicit is not None:
        text = str(explicit).strip()
        return text or None
    env = os.environ.get(RPC_ENV_VAR, "")
    text = str(env).strip()
    return text or None


def validate_rpc_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise TransactionControlError(
            "RPC URL must be http or https",
            reasons=("RPC URL scheme is not http or https",),
        )
    if not parsed.netloc:
        raise TransactionControlError(
            "RPC URL is missing a host",
            reasons=("RPC URL is missing a host",),
        )
    if parsed.username or parsed.password:
        raise TransactionControlError(
            "RPC URL must not embed credentials",
            reasons=("RPC URL embeds credentials; refuse",),
        )
    return url


def json_rpc_post(
    url: str,
    method: str,
    params: list[Any],
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """POST a JSON-RPC request. Fail closed on transport or shape errors."""

    safe_url = validate_rpc_url(url)
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        safe_url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            status = int(getattr(response, "status", 0) or response.getcode() or 0)
            raw = response.read()
    except HTTPError as exc:
        raise TransactionControlError(
            "Solana RPC HTTP error; fail closed",
            reasons=(f"RPC HTTP {exc.code}",),
        ) from exc
    except URLError as exc:
        raise TransactionControlError(
            "Solana RPC unreachable; fail closed",
            reasons=(f"RPC unreachable: {exc.reason}",),
        ) from exc
    except TimeoutError as exc:
        raise TransactionControlError(
            "Solana RPC timed out; fail closed",
            reasons=("RPC timed out",),
        ) from exc
    except OSError as exc:
        raise TransactionControlError(
            "Solana RPC transport failed; fail closed",
            reasons=(f"RPC transport failed: {exc}",),
        ) from exc

    if status and status != 200:
        raise TransactionControlError(
            "Solana RPC returned a non-200 status; fail closed",
            reasons=(f"RPC HTTP {status}",),
        )
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransactionControlError(
            "Solana RPC response is not JSON; fail closed",
            reasons=("RPC response is not JSON",),
        ) from exc
    if not isinstance(body, dict):
        raise TransactionControlError(
            "Solana RPC response is not an object; fail closed",
            reasons=("RPC response is not a JSON object",),
        )
    if body.get("error"):
        raise TransactionControlError(
            "Solana RPC returned an error; fail closed",
            reasons=(f"RPC error: {body.get('error')}",),
        )
    if "result" not in body:
        raise TransactionControlError(
            "Solana RPC response is missing result; fail closed",
            reasons=("RPC response is missing result",),
        )
    return body
