from pathlib import Path

import pytest

from src.shards.shard_loader import REQUIRED_IDS, RubricLoadError, load_rubrics


def test_loads_five_versioned_rubrics():
    rubrics = load_rubrics()
    assert tuple(item.id for item in rubrics) == (
        "harm_aversion",
        "privacy",
        "truth",
        "autonomy",
        "compassion",
    )
    assert all(item.version == "0.1.0" for item in rubrics)
    assert {item.id for item in rubrics} == set(REQUIRED_IDS)


def test_missing_directory_raises(tmp_path: Path):
    with pytest.raises(RubricLoadError):
        load_rubrics(tmp_path / "missing")


def test_missing_required_rubric_raises(tmp_path: Path):
    sample = Path("rubrics/v0.1/truth.yaml").read_text(encoding="utf-8")
    (tmp_path / "truth.yaml").write_text(sample, encoding="utf-8")
    with pytest.raises(RubricLoadError, match="Missing required"):
        load_rubrics(tmp_path)
