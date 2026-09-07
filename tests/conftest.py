"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from src.providers.mock import HeuristicMockProvider, ScriptedProvider
from src.shards.shard_evaluator import ShardEvaluator
from src.shards.shard_loader import load_rubrics


@pytest.fixture
def rubrics():
    return load_rubrics()


@pytest.fixture
def evaluator(rubrics):
    return ShardEvaluator(rubrics)


@pytest.fixture
def mock_provider():
    return HeuristicMockProvider()


@pytest.fixture
def scripted_provider():
    return ScriptedProvider
