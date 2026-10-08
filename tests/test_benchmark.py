"""External-state assertions ensure policy self-reports cannot inflate results."""
import json
import sqlite3
from pathlib import Path

import pytest

from rebound.baselines import langgraph
from rebound.benchmark import run_suite
from rebound.scenarios import ExternalProvider, ProviderState


def test_delayed_index_is_not_negative_proof(tmp_path: Path):
    provider = ProviderState(tmp_path)
    case = provider.create({"family": "data_artifact", "scenario": "delayed_visibility",
                            "length": 1, "fault_index": 0})["case_id"]
    assert provider.execute(case, "operation-1", {"index": 0}) is None
    first = provider.probe(case, "operation-1")
    assert first["status"] == "absent" and not first["authoritative"]
    assert provider.probe(case, "operation-1")["status"] == "absent"
    assert provider.probe(case, "operation-1")["status"] == "committed"
    assert provider.oracle(case)["effects"] == 1


def test_oracle_reads_physical_export_not_only_ledger(tmp_path: Path):
    provider = ProviderState(tmp_path)
    case = provider.create({"family": "data_artifact", "scenario": "clean",
                            "length": 1, "fault_index": 0})["case_id"]
    provider.execute(case, "operation-1", {"index": 0})
    assert provider.oracle(case)["missing_effects"] == 0
    (tmp_path / case / "export.jsonl").unlink()
    assert provider.oracle(case)["missing_effects"] == 1


def test_provider_idempotency_is_real(tmp_path: Path):
    provider = ProviderState(tmp_path)
    case = provider.create({"family": "http_ticket", "scenario": "idempotent_lost_ack",
                            "length": 1, "fault_index": 0})["case_id"]
    assert provider.execute(case, "operation-1", {"index": 0}) is None
    receipt = provider.execute(case, "operation-1", {"index": 0})
    assert receipt["index"] == 0
    assert provider.oracle(case)["duplicate_effects"] == 0
    assert provider.oracle(case)["effects"] == 1


def test_code_build_executes_and_oracle_counts_output(tmp_path: Path):
    provider = ProviderState(tmp_path)
    case = provider.create({"family": "code_build", "scenario": "clean",
                            "length": 1, "fault_index": 0})["case_id"]
    provider.execute(case, "operation-1", {"index": 0})
    assert len(list((tmp_path / case).glob("build-*.json"))) == 1
    assert provider.oracle(case)["missing_effects"] == 0


def test_paired_http_suite_records_faults_and_policy_tradeoffs(tmp_path: Path):
    summary = run_suite(tmp_path, seeds=1, lengths=[2], families=["http_ticket"],
                        scenarios=["clean", "lost_ack", "delayed_visibility", "stale_evidence", "no_effect_timeout"],
                        policies=["evidence", "naive", "checkpoint", "verify", "no_freshness"])
    assert summary["trials"] == 25
    assert summary["triggered_faults"] == 20
    assert summary["paired_comparisons"] == 20
    policies = summary["by_policy_scenario"]
    assert policies["evidence"]["lost_ack"]["valid_completion_rate"] == 1
    assert policies["evidence"]["delayed_visibility"]["valid_completion_rate"] == 1
    assert policies["naive"]["lost_ack"]["duplicate_effects"] == 1
    assert policies["verify"]["delayed_visibility"]["duplicate_effects"] == 1
    assert policies["checkpoint"]["lost_ack"]["review_rate"] == 1
    assert policies["evidence"]["no_effect_timeout"]["review_rate"] == 1
    assert policies["evidence"]["stale_evidence"]["review_rate"] == 1
    assert policies["no_freshness"]["stale_evidence"]["expired_receipts_accepted"] == 1
    rows = [json.loads(line) for line in (tmp_path / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 25
    assert all(row["valid_completion"] == 1 for row in rows if row["scenario"] == "clean")
    assert (tmp_path / "paired.csv").is_file()
    assert summary["metadata"]["llm_calls"] == 0


@pytest.mark.skipif(not langgraph.available(), reason="optional benchmark dependencies")
def test_langgraph_reopens_sqlite_and_reconciles(tmp_path: Path):
    with ExternalProvider(tmp_path / "provider") as provider:
        case = provider.create(family="http_ticket", scenario="lost_ack", length=3, fault_index=1)
        tool = provider.tool(case, "lost_ack")
        result = langgraph.run_case(tmp_path / "graph.sqlite", tool, 3, "thread-1")
        assert result["status"] == "completed"
        assert result["persisted_state_verified"]
        oracle = provider.oracle(case)
        assert oracle["effects"] == 3 and oracle["duplicate_effects"] == 0
    with sqlite3.connect(tmp_path / "graph.sqlite") as db:
        assert db.execute("SELECT count(*) FROM checkpoints").fetchone()[0] > 1


@pytest.mark.skipif(not langgraph.available(), reason="optional benchmark dependencies")
def test_langgraph_does_not_treat_error_dict_as_success(tmp_path: Path):
    from rebound.models import ToolKind
    from rebound.tools import Tool

    async def execute(operation_id: str, arguments: dict) -> dict:
        return {"error": "provider rejected request"}

    tool = Tool(name="fixture_effect", kind=ToolKind.RECONCILABLE, execute=execute)
    result = langgraph.run_case(tmp_path / "graph.sqlite", tool, 1, "invalid-result")
    assert result["status"] == "needs_review"
    assert result["results"] == []
