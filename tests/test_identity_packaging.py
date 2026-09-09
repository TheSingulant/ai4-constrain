"""Isolated install must ship ai4.identity without repo checkout imports."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _build_wheel(dist: Path) -> Path:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "build"],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist)],
        cwd=ROOT,
        check=True,
    )
    wheels = list(dist.glob("*.whl"))
    assert wheels, "wheel was not built"
    return wheels[0]


def test_clean_wheel_can_sign_and_verify_identity(tmp_path: Path):
    wheel = _build_wheel(tmp_path / "dist")
    site = tmp_path / "site"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(site), str(wheel)],
        check=True,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(site)
    work = tmp_path / "work"
    work.mkdir()
    probe = r"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
os.chdir(Path(%r))
assert not Path("ai4").exists()
from ai4.identity import (
    AgentIdentity,
    FixedClock,
    GOVERNING_PRINCIPLE,
    TrustContext,
    generate_ed25519_keypair,
    sign_attestation,
    verify_attestation,
)
assert "does not prove the agent is aligned" in GOVERNING_PRINCIPLE
seed, public = generate_ed25519_keypair()
now = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
identity = AgentIdentity.create(
    identity_id="agent-alpha",
    controller_public_key=public,
    manifest_version=1,
    issued_at=now,
    expires_at=now + timedelta(hours=1),
)
att = sign_attestation(identity, seed, issued_at=now, expires_at=now + timedelta(minutes=10))
verify_attestation(att, trust=TrustContext.from_identity(identity), clock=FixedClock(now))
print("identity-installed-ok", identity.manifest_hash())
""" % str(work)
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(work),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "identity-installed-ok" in result.stdout
