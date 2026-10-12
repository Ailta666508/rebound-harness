from rebound.audit import build_audit_report


def test_audit_report_is_redacted_and_counts_recovery_decisions():
    report = build_audit_report({
        "id": "run-1", "status": "needs_review", "title": "synthetic",
        "operations": [
            {"status": "unknown", "attempts": 2, "arguments": {"secret": "hide"}, "result": {"token": "hide"}},
            {"status": "succeeded", "attempts": 1, "arguments": {}, "result": {"ok": True}},
        ],
        "events": [
            {"kind": "run.created", "payload": {"steps": 2}},
            {"kind": "recovery.decision", "payload": {"action": "probe", "evidence": {"result": "hide"}}},
            {"kind": "recovery.decision", "payload": {"action": "review"}},
            {"kind": "budget.runtime_limits_call", "payload": {"seconds": 0.2}},
        ],
    })
    assert report == {
        "schema_version": 1, "run_id": "run-1", "status": "needs_review", "title": "synthetic",
        "operation_count": 2, "operation_statuses": {"succeeded": 1, "unknown": 1},
        "attempts": 3, "event_count": 4,
        "event_kinds": {"budget.runtime_limits_call": 1, "recovery.decision": 2, "run.created": 1},
        "recovery_decisions": {"probe": 1, "review": 1}, "needs_review": True,
        "budget_events": {"budget.runtime_limits_call": 1}, "budget_exhausted": True,
    }
    assert "secret" not in str(report) and "token" not in str(report)
