from pathlib import Path

from src.experiment import compare_primary, run_experiment
from src.main import main


def test_all_conditions_run_offline(tmp_path: Path, capsys):
    payload = run_experiment()
    assert payload["protocol"] == "v0.1"
    assert set(payload["results"]) == {"A", "B", "C", "D"}
    comparison = payload["primary_comparison"]
    assert comparison["primary"] == "D_vs_C"
    assert comparison["available"] is True

    code = main(["experiment", "--condition", "all", "--output", str(tmp_path / "out.json")])
    assert code == 0
    captured = capsys.readouterr().out
    assert "D_vs_C" in captured
    assert (tmp_path / "out.json").is_file()


def test_mock_c_and_d_follow_intended_accept_and_revise_paths():
    payload = run_experiment(("C", "D"))
    c_items = {item["prompt_id"]: item for item in payload["results"]["C"]["items"]}
    d_items = {item["prompt_id"]: item for item in payload["results"]["D"]["items"]}
    # Clean first draft: both accept with no refine.
    assert c_items["clean-001"]["state"] == "accept"
    assert d_items["clean-001"]["state"] == "accept"
    assert c_items["clean-001"]["revision_rounds_used"] == 0
    assert d_items["clean-001"]["revision_rounds_used"] == 0
    assert c_items["clean-001"]["model_calls"] == 1
    assert d_items["clean-001"]["model_calls"] == 1
    # Dirty drafts: both enter revise, and a cooperative mock can clear them.
    assert c_items["priv-001"]["revision_rounds_used"] >= 1
    assert d_items["priv-001"]["revision_rounds_used"] >= 1
    assert c_items["priv-001"]["specified_constraint_violations"] == 0
    assert d_items["priv-001"]["specified_constraint_violations"] == 0
    assert c_items["harm-001"]["revision_rounds_used"] >= 1
    assert d_items["harm-001"]["revision_rounds_used"] >= 1
    assert c_items["harm-001"]["specified_constraint_violations"] == 0
    assert d_items["harm-001"]["specified_constraint_violations"] == 0


def test_compare_primary_requires_both():
    assert compare_primary({"A": {}})["available"] is False


def test_evaluate_cli(capsys):
    code = main(["evaluate", "--text", "Here is a brief, checkable answer about options."])
    assert code == 0
    assert "harm_aversion" in capsys.readouterr().out
