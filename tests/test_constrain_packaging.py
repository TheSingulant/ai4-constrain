"""Clean-install packaging oracles. Do not use the checkout as the import root."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEAN = "Here is a brief, checkable answer: I can outline options and limits."


def _build_dist(dist: Path) -> tuple[Path, Path]:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "build"],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", str(dist)],
        cwd=ROOT,
        check=True,
    )
    wheels = list(dist.glob("*.whl"))
    sdists = list(dist.glob("*.tar.gz"))
    assert wheels, "wheel was not built"
    assert sdists, "sdist was not built"
    return wheels[0], sdists[0]


def test_sdist_and_wheel_contain_frozen_rubrics(tmp_path: Path):
    import tarfile
    import zipfile

    wheel, sdist = _build_dist(tmp_path / "dist")
    with tarfile.open(sdist) as archive:
        names = archive.getnames()
    assert any(name.endswith("ai4/data/rubrics/v0.1/privacy.yaml") for name in names)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    assert any(name.endswith("ai4/data/rubrics/v0.1/privacy.yaml") for name in names)


def test_clean_target_install_import_and_cli_do_not_need_repo(tmp_path: Path):
    wheel, _sdist = _build_dist(tmp_path / "dist")
    site = tmp_path / "site"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(site), str(wheel)],
        check=True,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(site)
    env.pop("PYTHONPATH", None)
    env["PYTHONPATH"] = str(site)
    work = tmp_path / "work"
    work.mkdir()
    probe = r"""
import os, sys
from pathlib import Path
os.chdir(Path(%r))
assert not Path("ai4").exists()
from ai4.constrain import ConstrainedSession, evaluate, run
from ai4.constrain.rubrics import packaged_rubric_bytes
report = evaluate(%r)
assert report.decision == "accept", report.decision
assert packaged_rubric_bytes()
loop = run("Please give a brief, checkable outline of options and limits.")
assert loop.decision == "accept", loop.decision
session = ConstrainedSession()
turn = session.complete("Please give a brief, checkable outline of options and limits.")
assert turn.report.decision == "accept", turn.report.decision
print("installed-ok", report.versions.evaluator_id, loop.terminal, turn.turn_index)
""" % (str(work), CLEAN)
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(work),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "installed-ok" in result.stdout
    cli = r"""
from ai4.constrain.cli import main
raise SystemExit(main(["evaluate", "--text", %r]))
""" % CLEAN
    cli_result = subprocess.run(
        [sys.executable, "-c", cli],
        cwd=str(work),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert cli_result.returncode == 0, cli_result.stderr
    assert '"decision": "accept"' in cli_result.stdout


def _install_and_probe(tmp_path: Path, artifact: Path, label: str) -> None:
    site = tmp_path / f"site-{label}"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(site), str(artifact)],
        check=True,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(site)
    work = tmp_path / f"work-{label}"
    work.mkdir()
    sessions = work / "sessions"
    probe = r"""
import os
from pathlib import Path
os.chdir(Path(%r))
assert not Path("ai4").exists()
from ai4.constrain import ConstrainedSession
from ai4.constrain.session import FileSessionStore

store = FileSessionStore(Path(%r))
session = ConstrainedSession(
    session_id="pkg-1",
    store=store,
    include_history=True,
    provider="mock",
)
first = session.complete("Please give a brief, checkable outline of options and limits.")
assert first.report.decision == "accept", first.report.decision
assert session.last_output == first.trusted_output == first.report.final_output

restored = ConstrainedSession.load(
    "pkg-1",
    store=store,
    include_history=True,
    provider="mock",
)
assert restored.config.redact is True
assert len(restored.turns) == 1
second = restored.complete("Add one more checkable limit.")
assert second.report.decision == "accept", second.report.decision
assert "Turn 1 user:" in second.composed_prompt
assert first.trusted_output in second.composed_prompt
assert restored.last_output == second.trusted_output
print("snapshot-restore-ok", restored.session_id, second.turn_index)
""" % (str(work), str(sessions))
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(work),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "snapshot-restore-ok" in result.stdout


def test_clean_wheel_and_sdist_snapshot_restore_subsequent_turn(tmp_path: Path):
    wheel, sdist = _build_dist(tmp_path / "dist")
    _install_and_probe(tmp_path, wheel, "wheel")
    _install_and_probe(tmp_path, sdist, "sdist")
