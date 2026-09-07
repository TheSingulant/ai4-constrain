"""Stage 2D metrics hooks. No production KPIs.

Primary and secondary definitions are frozen in docs/stage2d-protocol.md.
Do not retune these from held-out live outputs. There is no held-out live
run in this authoring PR.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from src.metrics import item_metrics, specified_constraint_violations, usefulness_proxy
from src.stage2d.icc import ICCResult, check_case
from src.stage2d.schema import Stage2DCase


def stage2d_item_row(case: Stage2DCase, result, *, icc: ICCResult | None = None) -> dict:
    row = item_metrics(result, case.prompt, category=case.category)
    icc_result = icc if icc is not None else check_case(case, result.text)
    terminal = row["frozen_terminal"]
    row.update(
        {
            "protocol": "stage2d-stress-v0.1",
            "specified_principles": list(case.specified_principles),
            "acceptable_terminals": list(case.acceptable_terminals),
            "terminal_acceptable": terminal in case.acceptable_terminals,
            "revised": int(result.revision_rounds_used) > 0,
            "revision_rounds_used": int(result.revision_rounds_used),
            "icc_n_failed": icc_result.n_failed,
            "icc_all_auto_passed": icc_result.all_auto_passed,
            "icc": icc_result.as_dict(),
            "favors": dict(case.favors),
            "conflict_brief": case.conflict_brief,
        }
    )
    row["usefulness_proxy"] = usefulness_proxy(case.prompt, result.text)
    row["specified_constraint_violations"] = specified_constraint_violations(
        result.evaluation, case.specified_shards
    )
    return row


def summarize_stage2d(rows: Sequence[dict]) -> dict:
    n = len(rows) or 1
    revised = sum(1 for row in rows if row.get("revised"))
    return {
        "protocol": "stage2d-stress-v0.1",
        "n": len(rows),
        "primary": {
            "specified_constraint_violation_rate": round(
                sum(1 for row in rows if row.get("specified_constraint_violations", 0) > 0) / n,
                4,
            ),
            "icc_auto_fail_rate": round(
                sum(1 for row in rows if row.get("icc_n_failed", 0) > 0) / n,
                4,
            ),
            "mean_usefulness_proxy": round(
                sum(row.get("usefulness_proxy", 0.0) for row in rows) / n,
                4,
            ),
        },
        "secondary": {
            "revision_rate": round(revised / n, 4),
            "mean_revision_rounds": round(
                sum(row.get("revision_rounds_used", 0) for row in rows) / n,
                4,
            ),
            "acceptable_terminal_rate": round(
                sum(1 for row in rows if row.get("terminal_acceptable")) / n,
                4,
            ),
            "mean_model_calls": round(sum(row.get("model_calls", 0) for row in rows) / n, 4),
            "total_model_calls": sum(row.get("model_calls", 0) for row in rows),
            "estimated_usd": round(sum(row.get("estimated_usd", 0.0) for row in rows), 6),
            "mean_latency_ms": round(sum(row.get("latency_ms", 0.0) for row in rows) / n, 4),
            "frozen_terminals": dict(Counter(row.get("frozen_terminal") for row in rows)),
            "reviewer_disagreement": None,
        },
    }


def compare_c_vs_d(results_by_condition: dict[str, dict]) -> dict:
    if "C" not in results_by_condition or "D" not in results_by_condition:
        return {"primary": "D_vs_C", "available": False}
    c_pri = results_by_condition["C"]["summary"]["primary"]
    d_pri = results_by_condition["D"]["summary"]["primary"]
    c_sec = results_by_condition["C"]["summary"]["secondary"]
    d_sec = results_by_condition["D"]["summary"]["secondary"]
    return {
        "primary": "D_vs_C",
        "available": True,
        "c_violation_rate": c_pri["specified_constraint_violation_rate"],
        "d_violation_rate": d_pri["specified_constraint_violation_rate"],
        "c_icc_auto_fail_rate": c_pri["icc_auto_fail_rate"],
        "d_icc_auto_fail_rate": d_pri["icc_auto_fail_rate"],
        "c_mean_usefulness": c_pri["mean_usefulness_proxy"],
        "d_mean_usefulness": d_pri["mean_usefulness_proxy"],
        "c_revision_rate": c_sec["revision_rate"],
        "d_revision_rate": d_sec["revision_rate"],
        "c_estimated_usd": c_sec["estimated_usd"],
        "d_estimated_usd": d_sec["estimated_usd"],
        "c_total_model_calls": c_sec["total_model_calls"],
        "d_total_model_calls": d_sec["total_model_calls"],
    }
