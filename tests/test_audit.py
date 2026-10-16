from rebound.audit import build_audit_report


def test_audit_report_is_redacted_and_counts_recovery_decisions():
    report = build_audit_report({
        "id": "run-1", "status": "needs_review", "title": "synthetic",
        "operations": [
            {"status": "unknown", "attempts": 2, "arguments": {"secret": "hide"}, "result": {"token": "hide"}},
            {"status": "succeeded", "attempts": 1, "arguments": {}, "result": {"ok": True}},
        ],
        "events": [
            {"kind": "run.created", "created_at": 100.0, "payload": {"steps": 2}},
            {"kind": "recovery.decision", "created_at": 100.125, "payload": {"action": "probe", "evidence": {"result": "hide"}}},
            {"kind": "recovery.decision", "created_at": 100.5, "payload": {"action": "review"}},
            {"kind": "budget.runtime_limits_call", "created_at": 100.75, "payload": {"seconds": 0.2}},
            {"kind": "run.runtime_config", "created_at": 100.01, "payload": {"policy": "evidence", "max_result_bytes": 1000}},
        ],
    })
    assert report == {
        "schema_version": 1, "run_id": "run-1", "status": "needs_review", "title": "synthetic",
        "operation_count": 2, "operation_statuses": {"succeeded": 1, "unknown": 1},
        "uncertain_operation_count": 1,
        "attempts": 3, "event_count": 4, "heartbeat_count": 0,
        "event_kinds": {"budget.runtime_limits_call": 1, "recovery.decision": 2, "run.created": 1},
        "recovery_decisions": {"probe": 1, "review": 1}, "needs_review": True,
        "budget_events": {"budget.runtime_limits_call": 1}, "budget_exhausted": True,
        "duration_seconds": 0.75,
        "runtime_config": {"policy": "evidence", "max_result_bytes": 1000},
    }
    assert "secret" not in str(report) and "token" not in str(report)
