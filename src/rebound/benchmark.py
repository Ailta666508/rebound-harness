"""Reproducible, paired fault experiments with an independent HTTP effect oracle."""
from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import math
import platform
import random
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from rebound.baselines import langgraph
from rebound.models import Step
from rebound.runtime import POLICIES, Runtime
from rebound.scenarios import FAMILIES, SCENARIOS, ExternalProvider
from rebound.store import Store

ALL_POLICIES = (*POLICIES, "langgraph_evidence")


def _wilson(successes: int, total: int) -> list[float]:
    if not total:
        return [0.0, 0.0]
    z = 1.95996398454
    p = successes / total
    divisor = 1 + z * z / total
    center = (p + z * z / (2 * total)) / divisor
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / divisor
    return [max(0.0, center - radius), min(1.0, center + radius)]


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    clean = sum(row["valid_completion"] for row in rows)
    return {
        "trials": n,
        "completion_rate": sum(row["completed"] for row in rows) / n,
        "valid_completion_rate": clean / n,
        "valid_completion_wilson_95": _wilson(clean, n),
        "review_rate": sum(row["needs_review"] for row in rows) / n,
        "duplicate_effects": sum(row["duplicate_effects"] for row in rows),
        "missing_effects": sum(row["missing_effects"] for row in rows),
        "invalid_effects": sum(row["invalid_effects"] for row in rows),
        "triggered_faults": sum(row["triggered_faults"] for row in rows),
        "expired_receipts_accepted": sum(row["expired_receipts_accepted"] for row in rows),
        "mean_probes": sum(row["probe_calls"] for row in rows) / n,
        "mean_tool_calls": sum(row["tool_calls"] for row in rows) / n,
        "mean_elapsed_ms": sum(row["elapsed_ms"] for row in rows) / n,
    }


def _metadata() -> dict[str, Any]:
    packages = {}
    for package in ("rebound-harness", "pydantic", "langgraph", "langgraph-checkpoint-sqlite", "matplotlib"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = "not-installed"
    root = Path(__file__).parent
    sources = ["benchmark.py", "scenarios.py", "runtime.py", "models.py", "store.py", "baselines/langgraph.py"]
    return {
        "generated_at": datetime.now(UTC).isoformat(), "python": platform.python_version(),
        "platform": platform.platform(), "packages": packages,
        "source_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources},
        "mode": "scripted-real-http-fixture", "llm_calls": 0, "llm_tokens": 0,
        "cost_usd": None, "provider_process_separate": True,
        "limitations": [
            "Deterministic scripted tools; no claim about model intelligence or natural-language task success.",
            "Faults affect transport replies, not provider durability or remote provider crashes.",
            "Code-build fixtures run trusted local Python subprocesses, not an isolated Docker sandbox.",
            "Expired-receipt case has a real committed effect; freshness ablation measures policy adherence/liveness, not a demonstrated bad external effect.",
            "LangGraph comparator implements conservative evidence handling; this is policy portability, not a framework ranking.",
            "Wilson intervals describe this finite scripted sample; repeated deterministic seeds do not establish general-world statistical superiority.",
        ],
    }


def _trial(provider: ExternalProvider, state_dir: Path, family: str, scenario: str,
           policy: str, length: int, seed: int) -> dict[str, Any]:
    fault_index = random.Random(seed).randrange(length)
    case_id = provider.create(family=family, scenario=scenario, length=length, fault_index=fault_index)
    tool = provider.tool(case_id, scenario)
    started = time.perf_counter()
    if policy == "langgraph_evidence":
        snapshot = langgraph.run_case(state_dir / f"{case_id}.sqlite", tool, length, str(uuid.uuid4()))
        tool_calls = snapshot["tool_calls"]
    else:
        store = Store(state_dir / f"{case_id}.sqlite")
        steps = [Step(key=f"step-{index}", tool=tool.name, arguments={"index": index}) for index in range(length)]
        run_id = store.create_run(steps, title=f"{family}/{scenario}/{policy}/{seed}/{length}")
        snapshot = asyncio.run(Runtime(store, [tool], policy=policy, probe_budget=3, probe_delay=0.01).run(run_id))
        tool_calls = sum(operation["attempts"] for operation in snapshot["operations"])
    elapsed_ms = (time.perf_counter() - started) * 1000
    # This call is made only by the evaluator after execution, never by a policy.
    oracle = provider.oracle(case_id)
    completed = snapshot["status"] == "completed"
    expired = 0
    for event in snapshot.get("events", []):
        payload = event["payload"]
        evidence = payload.get("evidence")
        if event["kind"] == "recovery.decision" and payload.get("action") == "reuse" and evidence:
            if evidence["valid_until"] < event["created_at"]:
                expired += 1
    clean_external = all(oracle[name] == 0 for name in
                         ("duplicate_effects", "missing_effects", "unexpected_effects", "invalid_effects"))
    return {
        "case_id": case_id, "run_id": snapshot["id"], "family": family, "scenario": scenario,
        "policy": policy, "length": length, "seed": seed, "fault_index": fault_index,
        "pair_key": f"{family}:{length}:{seed}:{policy}", "status": snapshot["status"],
        "completed": int(completed), "valid_completion": int(completed and clean_external),
        "needs_review": int(snapshot["status"] == "needs_review"),
        "expired_receipts_accepted": expired,
        "tool_calls": tool_calls, "elapsed_ms": round(elapsed_ms, 3),
        "persisted_state_verified": snapshot.get("persisted_state_verified", False), **oracle,
    }


def _write_chart(summary: dict[str, Any], output: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        return False
    policies = summary["config"]["policies"]
    scenarios = summary["config"]["scenarios"]
    matrix = np.array([[summary["by_policy_scenario"][policy][scenario]["valid_completion_rate"]
                        for scenario in scenarios] for policy in policies])
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "svg.fonttype": "none", "axes.spines.top": False, "axes.spines.right": False})
    fig, (left, right) = plt.subplots(1, 2, figsize=(14, 5.7), gridspec_kw={"width_ratios": [1.8, 1]})
    fig.patch.set_facecolor("#f6f8fc")
    left.imshow(matrix, vmin=0, vmax=1, cmap="Blues", aspect="auto")
    left.set_xticks(range(len(scenarios)), [s.replace("_", "\n") for s in scenarios], fontsize=9)
    left.set_yticks(range(len(policies)), policies)
    left.set_title("Correct completion by injected condition", loc="left", pad=16, weight="bold")
    for row in range(len(policies)):
        for col in range(len(scenarios)):
            left.text(col, row, f"{matrix[row, col]:.0%}", va="center", ha="center",
                      color="white" if matrix[row, col] > 0.6 else "#20304a")
    y = np.arange(len(policies))
    duplicate_trials = [summary["by_policy"][p]["duplicate_effects"] for p in policies]
    right.barh(y, duplicate_trials, color="#ed8560", height=0.6)
    right.set_yticks(y, policies)
    right.invert_yaxis()
    right.set_xlabel("Total duplicate external effects")
    right.set_title("Independent effect oracle", loc="left", pad=16, weight="bold")
    for idx, val in enumerate(duplicate_trials):
        right.text(val + max(duplicate_trials, default=1) * .02 + .02, idx, str(val), va="center")
    fig.suptitle("Rebound Harness · reproducible HTTP fault fixtures", x=0.04, ha="left",
                 fontsize=18, weight="bold", color="#17243b")
    fig.text(.04, .02, "Scripted workloads · no LLM calls · pauses count as incomplete · LangGraph runs the same conservative policy",
             fontsize=9, color="#536078")
    fig.tight_layout(rect=(0, .08, 1, .91), w_pad=4)
    fig.savefig(output / "recovery-results.svg", facecolor=fig.get_facecolor(), metadata={"Date": None})
    plt.close(fig)
    return True


def _write_report(summary: dict[str, Any], output: Path) -> None:
    lines = ["# Rebound recovery experiment", "", "Actual scripted HTTP fixture results; no LLM calls.", "",
             f"Trials: **{summary['trials']}**. Triggered faults: **{summary['triggered_faults']}**.", "",
             "| Policy | Correct completion | Review | Duplicate effects | Mean probes |",
             "|---|---:|---:|---:|---:|"]
    for policy, values in summary["by_policy"].items():
        lines.append(f"| {policy} | {values['valid_completion_rate']:.1%} | {values['review_rate']:.1%} | "
                     f"{values['duplicate_effects']} | {values['mean_probes']:.2f} |")
    lines += ["", "Correct completion requires a completed runtime and exactly one valid external effect per expected step.",
              "Review is reported as incomplete, even when the last uncertain effect already happened.", "",
              "## Reproduction", "", "```sh", summary["reproduce"], "```", "",
              "Raw trials: `results.jsonl` and `results.csv`. Paired clean deltas: `paired.csv`.",
              "`summary.json` includes configuration, dependency versions and source SHA-256 hashes.", "",
              "## Interpretation and limits", ""]
    lines.extend("- " + item for item in summary["metadata"]["limitations"])
    if summary["chart_generated"]:
        lines += ["", "![Measured recovery outcomes](recovery-results.svg)"]
    (output / "report.md").write_text("\n".join(lines) + "\n")


def run_suite(output: Path, seeds: int = 5, lengths: list[int] | None = None, *,
              families: list[str] | None = None, scenarios: list[str] | None = None,
              policies: list[str] | None = None) -> dict[str, Any]:
    """Run independent matched trials. Default: 1,470 cases, no API key needed."""
    lengths = lengths or [4, 12]
    families = families or list(FAMILIES)
    scenarios = scenarios or list(SCENARIOS)
    requested_policies = policies or list(ALL_POLICIES)
    if seeds < 1 or any(length < 1 for length in lengths):
        raise ValueError("seeds and lengths must be positive")
    for values, accepted, label in ((families, FAMILIES, "family"), (scenarios, SCENARIOS, "scenario"),
                                     (requested_policies, ALL_POLICIES, "policy")):
        if len(values) != len(set(values)) or any(item not in accepted for item in values):
            raise ValueError(f"invalid or duplicate {label}")
    skipped = []
    policies = list(requested_policies)
    if "langgraph_evidence" in policies and not langgraph.available():
        policies.remove("langgraph_evidence")
        skipped.append({"policy": "langgraph_evidence", "reason": "Install rebound-harness[benchmark]"})
    if not policies:
        raise ValueError("no available benchmark policies")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    state_dir = output / "state"
    state_dir.mkdir(exist_ok=True)
    schedule = [(f, s, p, length, seed) for f in families for s in scenarios for p in policies
                for length in lengths for seed in range(seeds)]
    random.Random(508).shuffle(schedule)
    rows = []
    with ExternalProvider(state_dir / ("provider-" + uuid.uuid4().hex)) as provider:
        with (output / "results.jsonl").open("w") as raw:
            for family, scenario, policy, length, seed in schedule:
                row = _trial(provider, state_dir, family, scenario, policy, length, seed)
                rows.append(row)
                raw.write(json.dumps(row, sort_keys=True) + "\n")
                raw.flush()
    with (output / "results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    grouped: dict[str, list] = defaultdict(list)
    cross: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        grouped[row["policy"]].append(row)
        cross[row["policy"]][row["scenario"]].append(row)
    controls = {row["pair_key"]: row for row in rows if row["scenario"] == "clean"}
    paired = []
    for row in rows:
        control = controls.get(row["pair_key"])
        if row["scenario"] != "clean" and control is not None:
            paired.append({
                "pair_key": row["pair_key"], "policy": row["policy"], "scenario": row["scenario"],
                "clean_case_id": control["case_id"], "fault_case_id": row["case_id"],
                "valid_completion_delta": row["valid_completion"] - control["valid_completion"],
                "elapsed_ms_delta": round(row["elapsed_ms"] - control["elapsed_ms"], 3),
                "probe_calls_delta": row["probe_calls"] - control["probe_calls"],
                "duplicate_effects_delta": row["duplicate_effects"] - control["duplicate_effects"],
            })
    if paired:
        with (output / "paired.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(paired[0]))
            writer.writeheader()
            writer.writerows(paired)
    expected_faults = sum(row["scenario"] != "clean" for row in rows)
    actual_faults = sum(row["triggered_faults"] for row in rows)
    if expected_faults != actual_faults:
        raise AssertionError(f"fault exposure mismatch: expected {expected_faults}, saw {actual_faults}")
    summary: dict[str, Any] = {
        "schema_version": 1, "metadata": _metadata(),
        "config": {"seeds": seeds, "lengths": lengths, "families": families, "scenarios": scenarios,
                   "policies": policies, "schedule_seed": 508, "max_attempts": 3, "probe_budget": 3},
        "trials": len(rows), "triggered_faults": actual_faults, "expected_faults": expected_faults,
        "paired_comparisons": len(paired), "skipped": skipped,
        "by_policy": {policy: _aggregate(grouped[policy]) for policy in policies},
        "by_policy_scenario": {policy: {scenario: _aggregate(cross[policy][scenario]) for scenario in scenarios}
                               for policy in policies},
        "by_family": {family: _aggregate([row for row in rows if row["family"] == family]) for family in families},
        "by_length": {str(length): _aggregate([row for row in rows if row["length"] == length]) for length in lengths},
        "reproduce": "python -c \"from pathlib import Path; from rebound.benchmark import run_suite; "
                     f"run_suite(Path('benchmarks/reproduced'), seeds={seeds}, lengths={lengths!r}, "
                     f"families={families!r}, scenarios={scenarios!r}, policies={policies!r})\"",
    }
    summary["chart_generated"] = _write_chart(summary, output)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    _write_report(summary, output)
    return summary
