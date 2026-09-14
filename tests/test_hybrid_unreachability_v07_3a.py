"""V07-3A structural-unreachability proofs.

Inspect imports and call paths. Do not trust a single flag.
Synthetic fixtures only. No live/paid providers. No Beta prompts.
"""

from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path

import ai4.constrain as public
from ai4.constrain import SEMANTIC_EXAMINER_OPERATIONAL, evaluate, run
from ai4.constrain.api import evaluate as evaluate_fn
from ai4.constrain.api import run as run_fn
from ai4.constrain.runtime import RuntimeConfig
from ai4.constrain.semantic_examiner import (
    EXAMINER_PIN_KIND,
    EXAMINER_PIN_KIND_CALLER_CONFIG,
    observation_prompt_sha256,
)
from ai4.constrain.semantic_taxonomy import (
    finding_policy_map_sha256,
    finding_registry_sha256,
    packaged_finding_policy_map_bytes,
    packaged_finding_registry_bytes,
)
from src.agents.recursive_agent import ConstrainedAgent
from src.constraints.constraint_middleware import ConstraintMiddleware
from src.providers.mock import HeuristicMockProvider
from src.shards.shard_evaluator import ShardEvaluator

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "ai4/data/semantic_v07/finding_registry_v1.json"
POLICY_MAP_PATH = ROOT / "ai4/data/semantic_v07/finding_policy_map_v1.json"
PROMPT_PATH = ROOT / "ai4/data/semantic_v07/observation_prompt_v1.txt"

REGISTRY_SHA256 = "e817eb246889cd19e090f96f005b577252b90b87028c50860e03cacbcee94535"
POLICY_MAP_SHA256 = "c84c613d7811fd0701ac90051d4f5b9640b90e8e978430bbd64f4cca81215a78"
PROMPT_SHA256 = "6ec541e391f7207a1b12ee1a00c7311c8de4a50810651a0eca829a2f07dc62bf"

GOVERNING_MODULES = (
    Path("ai4/constrain/api.py"),
    Path("ai4/constrain/runtime.py"),
    Path("ai4/constrain/evaluator_wall.py"),
    Path("ai4/constrain/session.py"),
    Path("ai4/constrain/cli.py"),
    Path("ai4/constrain/ext.py"),
    Path("ai4/constrain/report.py"),
    Path("src/constraints/constraint_middleware.py"),
    Path("src/shards/arbitration.py"),
    Path("src/shards/shard_evaluator.py"),
    Path("src/agents/recursive_agent.py"),
    Path("src/agents/base_agent.py"),
)

HYBRID_NEEDLES = (
    "observe_semantic_candidate",
    "map_and_fuse_v2",
    "packaged_fuse_v2",
    "rebuild_fused_evaluation",
    "hybrid_ready",
    "install_hybrid",
    "HybridObservedEvaluator",
    "RunBudgetAuthority",
    "HybridExecutionAbort",
    "_v07_3a",
    "_v07_3b",
    "hybrid_enable",
    "HYBRID_ENABLE",
    "AI4_ENABLE_HYBRID",
    "SEMANTIC_MODE",
)

CLEAN_EVAL = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)
CLEAN_RUN = "Please give a brief, checkable outline of options and limits."


def _module_imports_and_calls(path: Path) -> tuple[list[str], list[str], str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imported: list[str] = []
    called: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.append(func.id)
            elif isinstance(func, ast.Attribute):
                called.append(func.attr)
    return imported, called, source


def test_governing_modules_have_no_hybrid_import_or_call_path():
    offenders: list[str] = []
    for path in GOVERNING_MODULES:
        imported, called, source = _module_imports_and_calls(path)
        for needle in HYBRID_NEEDLES:
            if any(needle in name for name in imported):
                offenders.append(f"{path} import: {needle}")
            if needle in called:
                offenders.append(f"{path} call: {needle}")
            if needle in source:
                offenders.append(f"{path} source: {needle}")
    assert offenders == []


def test_public_init_does_not_wire_v07_3a():
    init_src = Path("ai4/constrain/__init__.py").read_text(encoding="utf-8")
    assert "_v07_3a" not in init_src
    assert "_v07_3b" not in init_src
    assert "hybrid_ready" not in init_src
    assert "rebuild_fused_evaluation" not in init_src
    assert "RunBudgetAuthority" not in init_src
    assert "install_hybrid" not in init_src


def test_api_run_cannot_install_hybrid():
    source = inspect.getsource(run_fn)
    assert "install_hybrid" not in source
    assert "hybrid" not in source.lower()
    assert "observe_semantic_candidate" not in source
    assert "map_and_fuse_v2" not in source
    assert "rebuild_fused_evaluation" not in source
    params = tuple(inspect.signature(run_fn).parameters)
    assert "hybrid" not in "".join(params).lower()
    assert params == (
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
    )
    report = run(CLEAN_RUN)
    assert report.decision == "accept"
    assert report.versions.condition == "D"
    assert report.evaluator.evaluator_id == "v0.1-regex"


def test_api_evaluate_remains_deterministic():
    source = inspect.getsource(evaluate_fn)
    assert "semantic" not in source.lower()
    assert "observe_semantic_candidate" not in source
    assert "map_and_fuse_v2" not in source
    params = tuple(inspect.signature(evaluate_fn).parameters)
    assert params == (
        "text",
        "prompt",
        "evaluator",
        "rubric_set",
        "prompt_specified_shards",
        "prompt_id",
        "max_revision_rounds",
        "redact",
    )
    report = evaluate(CLEAN_EVAL)
    assert report.decision == "accept"
    assert report.mode == "evaluate_only"
    assert report.telemetry.calls == 0


def test_constrained_agent_and_middleware_unchanged():
    agent_src = inspect.getsource(ConstrainedAgent.run)
    decide_src = inspect.getsource(ConstraintMiddleware.decide)
    for source in (agent_src, decide_src):
        assert "observe_semantic_candidate" not in source
        assert "map_and_fuse_v2" not in source
        assert "rebuild_fused_evaluation" not in source
        assert "hybrid" not in source.lower()
        assert "semantic" not in source.lower()
    middleware = ConstraintMiddleware()
    evaluation = ShardEvaluator().evaluate(CLEAN_EVAL)
    decision = middleware.decide(evaluation, revision_round=0)
    assert decision.action == "accept"
    agent = ConstrainedAgent(HeuristicMockProvider())
    result = agent.run(CLEAN_RUN)
    assert result.state.name in {"ACCEPT", "REVISE", "REFUSE", "TIMEOUT", "REPEATED"}


def test_no_env_or_config_flag_enables_hybrid():
    fields = {item.name for item in RuntimeConfig.__dataclass_fields__.values()}
    assert "hybrid" not in "".join(fields).lower()
    assert "semantic" not in "".join(fields).lower()
    cfg_src = Path("ai4/constrain/runtime.py").read_text(encoding="utf-8")
    api_src = Path("ai4/constrain/api.py").read_text(encoding="utf-8")
    for source in (cfg_src, api_src):
        assert "AI4_ENABLE_HYBRID" not in source
        assert "HYBRID_ENABLE" not in source
        assert "hybrid_enabled" not in source
    for key in os.environ:
        if key.startswith("AI4_"):
            assert "HYBRID" not in key
    RuntimeConfig().validate()


def test_semantic_examiner_operational_and_pin_kind_unchanged():
    assert SEMANTIC_EXAMINER_OPERATIONAL is False
    assert public.SEMANTIC_EXAMINER_OPERATIONAL is False
    assert EXAMINER_PIN_KIND == EXAMINER_PIN_KIND_CALLER_CONFIG
    assert EXAMINER_PIN_KIND == "caller_config"


def test_locked_artifact_hashes_unchanged():
    import hashlib

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    assert digest(PROMPT_PATH) == PROMPT_SHA256
    assert digest(REGISTRY_PATH) == REGISTRY_SHA256
    assert digest(POLICY_MAP_PATH) == POLICY_MAP_SHA256
    assert observation_prompt_sha256() == PROMPT_SHA256
    assert finding_registry_sha256() == REGISTRY_SHA256
    assert finding_policy_map_sha256() == POLICY_MAP_SHA256
    assert hashlib.sha256(packaged_finding_registry_bytes()).hexdigest() == REGISTRY_SHA256
    assert hashlib.sha256(packaged_finding_policy_map_bytes()).hexdigest() == POLICY_MAP_SHA256


def test_no_ready_or_governing_wrapper_type_exists():
    import ai4.constrain._v07_3a as prim
    import ai4.constrain._v07_3a.context as ctx

    assert not hasattr(prim, "Ready")
    assert not hasattr(prim, "HybridObservedEvaluator")
    assert not hasattr(ctx, "Ready")
    assert hybrid_ready_name_is_stub()


def hybrid_ready_name_is_stub() -> bool:
    from ai4.constrain._v07_3a import hybrid_ready

    result = hybrid_ready()
    return result.reason == "slice_incomplete"
