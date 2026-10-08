import asyncio
import os
import sqlite3
import subprocess
import sys
import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rebound import Evidence, Runtime, Step, Store, Tool, ToolKind
from rebound.demo import DemoService
from rebound.verification import verify_snapshot


@pytest.mark.parametrize("scenario", ["lost_ack", "delayed_visibility"])
async def test_reconciles_committed_effect_without_repeating(tmp_path, scenario):
    service = DemoService(tmp_path)
    result = await service.create_demo(scenario, steps=8)
    assert result["status"] == "completed"
    assert result["metrics"]["effects"] == 8
    assert result["metrics"]["duplicate_effects"] == 0
    assert verify_snapshot(result)["valid"]
    result = await DemoService(tmp_path).resume(result["id"])
    assert result["metrics"]["effects"] == 8


async def test_naive_baseline_exposes_real_duplicate(tmp_path):
    result = await DemoService(tmp_path).create_demo("lost_ack", policy="naive", steps=4)
    assert result["status"] == "completed"
    assert result["metrics"]["duplicate_effects"] == 1


@pytest.mark.parametrize("scenario", ["unavailable", "stale_evidence"])
async def test_uncertain_or_expired_evidence_needs_review(tmp_path, scenario):
    result = await DemoService(tmp_path).create_demo(scenario, steps=4)
    assert result["status"] == "needs_review"
    assert result["metrics"]["duplicate_effects"] == 0
    assert result["metrics"]["completed_steps"] < 4


async def test_permission_exact_operation_and_distinct_intents(tmp_path):
    calls = []
    async def execute(op, args):
        calls.append(op)
        return args
    store = Store(tmp_path / "runs.sqlite")
    tool = Tool("write", ToolKind.OPAQUE, execute, permission="ask")
    ids = [store.create_run([Step(key="same", tool="write", arguments={"x": 1})]) for _ in range(2)]
    for run_id in ids:
        snap = await Runtime(store, [tool]).run(run_id)
        assert snap["status"] == "awaiting_approval"
        assert not any(e["kind"] == "operation.dispatched" for e in snap["events"])
        store.approve(run_id, snap["operations"][0]["id"])
        assert (await Runtime(store, [tool]).run(run_id))["status"] == "completed"
    assert len(set(calls)) == 2


@given(st.floats(min_value=1, max_value=10000, allow_nan=False, allow_infinity=False))
def test_expired_receipts_never_authorize_reuse(age):
    now = time.time()
    tool = Tool("write", ToolKind.RECONCILABLE, None)
    runtime = Runtime.__new__(Runtime)
    runtime.policy, runtime.evidence_ttl = "evidence", 30
    evidence = Evidence(operation_id="op", status="committed", result={"ok": True}, authoritative=True,
                        observed_at=now-age-1, valid_until=now-age, source="receipt")
    assert runtime.decide(tool, {"id": "op"}, evidence).action == "probe"


def test_mismatched_receipt_and_negative_read_are_not_permission(tmp_path):
    runtime = Runtime(Store(tmp_path / "state.sqlite"), [])
    tool = Tool("write", ToolKind.RECONCILABLE, None)
    now = time.time()
    wrong = Evidence(operation_id="other", status="committed", result={}, authoritative=True,
                     observed_at=now, valid_until=now+30, source="receipt")
    assert runtime.decide(tool, {"id": "op"}, wrong).action == "probe"
    absent = wrong.model_copy(update={"operation_id": "op", "status": "absent", "final": True})
    assert runtime.decide(tool, {"id": "op"}, absent).action == "probe"


async def test_retry_budget_and_stable_identity(tmp_path):
    attempts = []
    async def execute(op, _args):
        attempts.append(op)
        raise TimeoutError()
    store = Store(tmp_path / "state.sqlite")
    run = store.create_run([Step(key="x", tool="read")])
    snap = await Runtime(store, [Tool("read", ToolKind.READ_ONLY, execute)], max_attempts=2).run(run)
    assert snap["status"] == "needs_review"
    assert len(attempts) == 2 and len(set(attempts)) == 1
    assert verify_snapshot(snap)["valid"]


async def test_cancel_during_effect_does_not_report_completed(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    run = store.create_run([Step(key="x", tool="write"), Step(key="y", tool="write")])
    async def execute(_op, _args):
        store.set_status(run, "cancelled")
        return {"committed": True}
    snap = await Runtime(store, [Tool("write", ToolKind.OPAQUE, execute)]).run(run)
    assert snap["status"] == "cancelled"
    assert snap["operations"][0]["status"] == "succeeded"
    assert snap["operations"][1]["status"] == "planned"


CRASH_WORKER = r'''
import asyncio, os, sqlite3, sys, time
from rebound import Store, Runtime, Tool, ToolKind, Evidence
state, provider, run_id, point = sys.argv[1:]
async def execute(op, args):
    with sqlite3.connect(provider) as db:
        db.execute("INSERT INTO effects VALUES(?)", (op,))
    return {"receipt": op}
async def probe(op):
    with sqlite3.connect(provider) as db:
        count = db.execute("SELECT count(*) FROM effects WHERE id=?", (op,)).fetchone()[0]
    now = time.time()
    return Evidence(operation_id=op, status="committed" if count else "absent",
      result={"receipt":op} if count else None, authoritative=True,
      observed_at=now, valid_until=now+60, source="separate provider database")
def hook(at, op):
    if at == point: os._exit(73)
result = asyncio.run(Runtime(Store(state), [Tool("write", ToolKind.RECONCILABLE, execute, probe)], fault_hook=hook).run(run_id))
print(result["status"])
'''


@pytest.mark.parametrize("point,expected", [("after_effect", "completed"), ("after_commit", "completed"), ("before_dispatch", "needs_review")])
def test_actual_process_death_and_fresh_process_recovery(tmp_path, point, expected):
    state, provider = tmp_path / "journal.sqlite", tmp_path / "provider.sqlite"
    with sqlite3.connect(provider) as db:
        db.execute("CREATE TABLE effects(id TEXT)")
    store = Store(state)
    run = store.create_run([Step(key="one", tool="write")])
    args = [sys.executable, "-c", CRASH_WORKER, str(state), str(provider), run]
    crashed = subprocess.run([*args, point], capture_output=True, text=True, timeout=20)
    assert crashed.returncode == 73, crashed.stderr
    recovered = subprocess.run([*args, "never"], capture_output=True, text=True, timeout=20)
    assert recovered.returncode == 0, recovered.stderr
    assert recovered.stdout.strip() == expected
    with sqlite3.connect(provider) as db:
        count = db.execute("SELECT count(*) FROM effects").fetchone()[0]
    assert count == (0 if point == "before_dispatch" else 1)
    assert verify_snapshot(store.snapshot(run))["valid"]


async def test_two_runners_cannot_enter_same_run(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    run = store.create_run([Step(key="one", tool="slow")])
    entered, release = asyncio.Event(), asyncio.Event()
    async def execute(_op, _args):
        entered.set()
        await release.wait()
        return {}
    tools = [Tool("slow", ToolKind.READ_ONLY, execute)]
    first = asyncio.create_task(Runtime(store, tools).run(run))
    await entered.wait()
    try:
        with pytest.raises(RuntimeError, match="active runner"):
            await Runtime(Store(store.path), tools).run(run)
    finally:
        release.set()
        await first


async def test_manual_resolution_is_explicit_and_durable(tmp_path):
    service = DemoService(tmp_path)
    snap = await service.create_demo("unavailable", steps=4)
    uncertain = next(o for o in snap["operations"] if o["status"] == "unknown")
    with pytest.raises(ValueError, match="evidence note"):
        await service.resolve(snap["id"], uncertain["id"], {}, "")
    result = await service.resolve(snap["id"], uncertain["id"], {"ticket_id": "human-verified"}, "Operator checked provider receipt")
    assert result["status"] == "completed"
    assert result["metrics"]["effects"] == 4


@pytest.mark.skipif(os.getenv("REBOUND_TEST_DOCKER") != "1", reason="enable Docker integration explicitly")
async def test_real_docker_sandbox():
    from rebound.tools import docker_tool
    tool = docker_tool()
    result = await tool.execute("sandbox-test", {"code": "import os; print(sum(range(10))); print(os.getuid())"})
    assert result["exit_code"] == 0
    assert "45" in result["stdout"] and "65534" in result["stdout"]
