"""Committed tree must not contain credential material."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def test_secret_scan_clean():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "secret_scan.py"
    spec = importlib.util.spec_from_file_location("ai4_secret_scan", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hits = module.scan(root)
    assert hits == []
