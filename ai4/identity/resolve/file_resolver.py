"""Offline file resolver. First-slice discovery; no network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from ai4.identity.errors import IdentityError
from ai4.identity.resolve.resolver import validate_raw_records
from ai4.identity.resolve.types import MAX_RECORDS_PAYLOAD_BYTES, RESOLVER_IDS
from ai4.identity.timeutil import format_utc

_FILE_KEYS = frozenset({"records", "name", "captured_at", "freshness_kind"})
FILE_RESOLVER_FRESHNESS_KIND = "fixture"


class FileResolver:
    """Load Unstoppable-shaped records from a JSON file or directory of files.

    Default product path. Does not contact Unstoppable, HTTP, or a chain.
    Directory lookup is contained to the resolved records directory.
    Freshness is resolver-controlled fixture metadata, never live.
    """

    resolver_id = "file"
    freshness_kind = FILE_RESOLVER_FRESHNESS_KIND

    def __init__(self, records_path: str | Path, *, captured_at: str | None = None) -> None:
        if self.resolver_id not in RESOLVER_IDS:
            raise IdentityError("unknown resolver_id")
        raw_path = Path(records_path)
        if not raw_path.exists():
            raise IdentityError(f"records path does not exist: {raw_path}")
        self._directory = raw_path.is_dir()
        self.path = raw_path.resolve()
        self._override_captured_at = captured_at
        self._single: dict[str, object] | None = None
        if not self._directory:
            self._single = _load_fixture_file(self.path)
        # Local files cannot claim live/cached transport. Ignore JSON freshness_kind.
        self.freshness_kind = FILE_RESOLVER_FRESHNESS_KIND
        if self._single is not None:
            self.captured_at = self._captured_at_for(self._single)
        elif captured_at is not None:
            self.captured_at = format_utc(captured_at)
        else:
            self.captured_at = ""

    def resolve(self, name: str) -> Mapping[str, str]:
        payload = self._payload_for(name)
        payload_name = payload.get("name")
        if isinstance(payload_name, str) and payload_name and payload_name != name:
            raise IdentityError(
                f"records file name {payload_name!r} does not match queried name {name!r}"
            )
        records = payload.get("records")
        if not isinstance(records, dict):
            raise IdentityError("records file missing records object")
        validate_raw_records(records)
        return {str(key): str(value) for key, value in records.items()}

    def captured_at_for(self, name: str) -> str:
        return self._captured_at_for(self._payload_for(name))

    def freshness_kind_for(self, name: str) -> str:
        del name
        return FILE_RESOLVER_FRESHNESS_KIND

    def _payload_for(self, name: str) -> dict[str, object]:
        if self._single is not None:
            return self._single
        return _load_fixture_file(self._contained_directory_file(name))

    def _contained_directory_file(self, name: str) -> Path:
        """Resolve ``{name}.json`` only inside the canonical records directory."""
        if not isinstance(name, str) or not name:
            raise IdentityError("unresolved .ai4 name")
        filename = f"{name}.json"
        if Path(name).is_absolute() or Path(filename).is_absolute():
            raise IdentityError("records path escapes resolver directory")
        if "/" in name or "\\" in name or "/" in filename or "\\" in filename:
            raise IdentityError("records path escapes resolver directory")
        candidate = self.path / filename
        try:
            resolved = candidate.resolve()
        except OSError as exc:
            raise IdentityError("records path escapes resolver directory") from exc
        try:
            resolved.relative_to(self.path)
        except ValueError as exc:
            raise IdentityError("records path escapes resolver directory") from exc
        if not resolved.is_file():
            raise IdentityError(f"unresolved .ai4 name: {name!r}")
        return resolved

    def _captured_at_for(self, payload: dict[str, object] | None) -> str:
        if self._override_captured_at is not None:
            return format_utc(self._override_captured_at)
        if payload is None:
            raise IdentityError("captured_at is required for file resolver")
        raw = payload.get("captured_at")
        if not isinstance(raw, str) or not raw:
            raise IdentityError("records file missing captured_at")
        return format_utc(raw)


def _load_fixture_file(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if len(data) > MAX_RECORDS_PAYLOAD_BYTES:
        raise IdentityError("records file exceeds payload size cap")
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IdentityError(f"malformed records file: {exc}") from exc
    if not isinstance(raw, dict):
        raise IdentityError("records file must be a JSON object")
    extra = sorted(str(key) for key in raw if key not in _FILE_KEYS)
    if extra:
        raise IdentityError(f"Unknown records-file field(s) {extra}; failing closed")
    return raw
