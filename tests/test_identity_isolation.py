"""PR-E isolation: identity must not enter the governing constrain path."""

from __future__ import annotations

import ast
import inspect
import socket
from pathlib import Path

import pytest

from ai4.constrain import ConstraintExecutionError, RuntimeConfig, evaluate, run
from ai4.constrain.api import evaluate as evaluate_fn
from ai4.constrain.api import run as run_fn
from ai4.constrain.runtime import EVIDENCE_CLASS
from ai4.constrain.session import SessionPolicyIdentity, session_policy_identity
from ai4.identity import AgentIdentity, generate_ed25519_keypair, sign_attestation
from tests.test_identity_kernel import CLEAN_TEXT, LATER, NOW, _identity, _signed

CLEAN = "Please give a brief, checkable outline of options and limits."

IDENTITY_SMUGGLE_FIELDS = (
    "identity_id",
    "controller_public_key",
    "manifest_hash",
    "manifest_version",
    "manifest_uri",
    "attestation",
    "signature",
    "name_records",
    ".ai4",
    "ai4_name",
    "wallet",
    "token",
    "uns_domain",
    "attestation_uri",
    "attestation_sha256",
    "resolver_id",
    "discovery",
    "freshness",
)

RUNTIME_FORBIDDEN_FIELDS = (
    "token",
    "wallet",
    "name",
    "name_record",
    "uns_domain",
    "chain_id",
    "nft",
    "controller_public_key",
    "manifest_hash",
    "manifest_version",
    "identity_id",
    "attestation_uri",
    "resolver_id",
    "discovery",
)

CONSTRAIN_ROOT = Path("ai4/constrain")


def test_constrain_sources_do_not_import_identity():
    offenders = []
    for path in CONSTRAIN_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "ai4.identity" or alias.name.startswith("ai4.identity."):
                        offenders.append(f"{path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "ai4.identity" or module.startswith("ai4.identity."):
                    offenders.append(f"{path}: from {module}")
                if module == "ai4" and any(alias.name == "identity" for alias in node.names):
                    offenders.append(f"{path}: from ai4 import identity")
    assert offenders == []


def test_run_and_evaluate_signatures_unchanged():
    assert list(inspect.signature(run_fn).parameters) == [
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
    ]
    assert list(inspect.signature(evaluate_fn).parameters) == [
        "text",
        "prompt",
        "evaluator",
        "rubric_set",
        "prompt_specified_shards",
        "prompt_id",
        "max_revision_rounds",
        "redact",
    ]
    assert "attestation" not in inspect.signature(run_fn).parameters
    assert "identity" not in inspect.signature(run_fn).parameters
    assert "attestation" not in inspect.signature(evaluate_fn).parameters
    assert "identity" not in inspect.signature(evaluate_fn).parameters


def test_identity_fields_cannot_enter_session_policy_identity():
    raw = session_policy_identity(RuntimeConfig()).to_dict()
    for field in IDENTITY_SMUGGLE_FIELDS:
        smuggled = dict(raw)
        smuggled[field] = "smuggled"
        with pytest.raises(ConstraintExecutionError, match="Unknown policy_identity field"):
            SessionPolicyIdentity.from_dict(smuggled)
    assert set(raw) == {
        "runtime_version",
        "report_schema_version",
        "protocol",
        "condition",
        "evidence_class",
        "rubric_set",
        "evaluator_id",
        "arbitration",
    }
    assert raw["evidence_class"] == "null_retained_D_adds_cost"


def test_token_wallet_name_fields_cannot_enter_runtime_config():
    for field in RUNTIME_FORBIDDEN_FIELDS:
        with pytest.raises(TypeError):
            RuntimeConfig(**{field: "smuggled"})  # type: ignore[arg-type]
    cfg = RuntimeConfig().validate()
    assert not hasattr(cfg, "token")
    assert not hasattr(cfg, "wallet")
    assert not hasattr(cfg, "name_record")
    assert not hasattr(cfg, "controller_public_key")
    assert cfg.evaluator_id == "v0.1-regex"
    assert EVIDENCE_CLASS == "null_retained_D_adds_cost"


def test_identity_object_cannot_be_used_as_provider_or_evaluator():
    seed, public = generate_ed25519_keypair()
    identity = _identity(public)
    attestation = _signed(identity, seed)
    with pytest.raises(ConstraintExecutionError):
        run(CLEAN, provider=identity)  # type: ignore[arg-type]
    with pytest.raises(ConstraintExecutionError):
        run(CLEAN, evaluator=identity)  # type: ignore[arg-type]
    with pytest.raises(ConstraintExecutionError):
        run(CLEAN, provider=attestation)  # type: ignore[arg-type]
    with pytest.raises(ConstraintExecutionError):
        evaluate(CLEAN_TEXT, evaluator=identity)  # type: ignore[arg-type]
    with pytest.raises(ConstraintExecutionError):
        evaluate(CLEAN_TEXT, evaluator=attestation)  # type: ignore[arg-type]


def test_session_is_not_bound_to_identity_or_name():
    from ai4.constrain import ConstrainedSession

    session = ConstrainedSession(persist=False)
    turn = session.complete(CLEAN)
    identity_fields = set(session.snapshot().policy_identity.to_dict())
    assert "controller_public_key" not in identity_fields
    assert "manifest_hash" not in identity_fields
    assert "manifest_version" not in identity_fields
    assert ".ai4" not in identity_fields
    assert "identity_id" not in identity_fields
    assert turn.report.versions.evidence_class == "null_retained_D_adds_cost"


def test_no_network_during_sign_verify_bind(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("network must not be used by ai4.identity")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    import http.client

    monkeypatch.setattr(http.client.HTTPConnection, "connect", blocked)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", blocked)

    from ai4.identity import (
        FixedClock,
        TrustContext,
        bind_report,
        verify_attestation,
        verify_report_binding,
    )

    seed, public = generate_ed25519_keypair()
    identity = AgentIdentity.create(
        identity_id="agent-alpha",
        controller_public_key=public,
        manifest_version=1,
        issued_at=NOW,
        expires_at=LATER,
        manifest_uri="https://example.invalid/should-not-fetch",
    )
    report = evaluate(CLEAN_TEXT)
    att = sign_attestation(
        identity,
        seed,
        issued_at=NOW,
        expires_at=LATER,
        binding=bind_report(report),
    )
    verify_attestation(att, trust=TrustContext.from_identity(identity), clock=FixedClock(NOW))
    result = verify_report_binding(
        att, report, trust=TrustContext.from_identity(identity), clock=FixedClock(NOW)
    )
    assert result.verdict == "matched"


def test_public_constrain_api_does_not_export_identity():
    import ai4.constrain as public
    import ai4 as root

    assert not hasattr(public, "AgentIdentity")
    assert not hasattr(public, "sign_attestation")
    assert not hasattr(public, "verify_attestation")
    assert "AgentIdentity" not in getattr(root, "__all__", ())


def test_provider_and_evaluator_wall_files_are_unchanged():
    """PR-C / PR-D suites stay the same files; identity does not edit them."""
    provider = Path("tests/test_provider_policy_wall.py").read_text(encoding="utf-8")
    evaluator = Path("tests/test_evaluator_policy_wall.py").read_text(encoding="utf-8")
    assert "ai4.identity" not in provider
    assert "ai4.identity" not in evaluator
    assert "null_retained_D_adds_cost" in provider
    assert "null_retained_D_adds_cost" in evaluator


KERNEL_NETWORK_MODULES = ("urllib", "http", "http.client", "http.server")
KERNEL_FILES = (
    Path("ai4/identity/__init__.py"),
    Path("ai4/identity/attestation.py"),
    Path("ai4/identity/binding.py"),
    Path("ai4/identity/canonical.py"),
    Path("ai4/identity/crypto.py"),
    Path("ai4/identity/digest.py"),
    Path("ai4/identity/errors.py"),
    Path("ai4/identity/schemas.py"),
    Path("ai4/identity/timeutil.py"),
    Path("ai4/identity/trust.py"),
)


def _import_offenders(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for name in names:
            if name == "ai4.identity.resolve" or name.startswith("ai4.identity.resolve."):
                offenders.append(f"{path}: import {name}")
            if name in KERNEL_NETWORK_MODULES or name.startswith("urllib.") or name.startswith("http."):
                offenders.append(f"{path}: import {name}")
    return offenders


def test_constrain_sources_do_not_import_resolve():
    offenders = []
    for path in CONSTRAIN_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "identity.resolve" in alias.name:
                        offenders.append(f"{path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "identity.resolve" in module:
                    offenders.append(f"{path}: from {module}")
    assert offenders == []


def test_identity_kernel_modules_do_not_import_resolve_or_network():
    offenders: list[str] = []
    for path in KERNEL_FILES:
        offenders.extend(_import_offenders(path))
    assert offenders == []


def test_identity_init_does_not_export_resolver_types():
    import ai4.identity as kernel

    for name in (
        "DiscoveryRecord",
        "FileResolver",
        "MemoryResolver",
        "Resolver",
        "resolve_name",
        "Freshness",
        "LocalFileFetcher",
    ):
        assert name not in getattr(kernel, "__all__", ())
        assert not hasattr(kernel, name)


def test_python_m_ai4_run_remains_constrain():
    import subprocess
    import sys

    help_result = subprocess.run(
        [sys.executable, "-m", "ai4", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "ai4-constrain" in help_result.stdout or "constrained" in help_result.stdout.lower()
    assert "Current trust" not in help_result.stdout

    run_help = subprocess.run(
        [sys.executable, "-m", "ai4", "run", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run_help.returncode == 0, run_help.stderr
    assert "Propose" in run_help.stdout or "prompt" in run_help.stdout.lower()


def test_discovery_objects_cannot_be_used_as_provider_or_evaluator():
    from ai4.identity.resolve.types import DiscoveryRecord, Freshness

    discovery = DiscoveryRecord.from_dict(
        {
            "schema_id": "ai4.identity.discovery.v1",
            "name": "researcher.ai4",
            "identity_id": "agent-alpha",
            "controller_public_key": "ab" * 32,
            "manifest_sha256": "cd" * 32,
            "attestation_sha256": "",
            "attestation_uri": "researcher.ai4.attestation.json",
            "captured_at": "2026-09-08T12:00:00Z",
            "freshness": {"kind": "fixture", "age_s": 0, "max_age_s": None},
            "resolver_id": "file",
        }
    )
    with pytest.raises(ConstraintExecutionError):
        run(CLEAN, provider=discovery)  # type: ignore[arg-type]
    with pytest.raises(ConstraintExecutionError):
        run(CLEAN, evaluator=discovery)  # type: ignore[arg-type]
    with pytest.raises(ConstraintExecutionError):
        evaluate(CLEAN_TEXT, evaluator=Freshness(kind="fixture", age_s=0))  # type: ignore[arg-type]
