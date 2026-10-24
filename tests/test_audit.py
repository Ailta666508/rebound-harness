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
        "attempts": 3, "event_count": 5, "heartbeat_count": 0, "last_heartbeat": None, "heartbeat_runner_count": 0, "heartbeat_statuses": {}, "heartbeat_operations": {}, "heartbeat_missing_operations": [], "heartbeat_status_mismatches": [], "heartbeat_attempt_mismatches": [], "heartbeat_health": {"coverage": 1.0, "status_mismatch_count": 0, "attempt_mismatch_count": 0, "healthy": True},
        "event_kinds": {"budget.runtime_limits_call": 1, "recovery.decision": 2, "run.created": 1, "run.runtime_config": 1},
        "recovery_decisions": {"probe": 1, "review": 1}, "needs_review": True,
        "budget_events": {"budget.runtime_limits_call": 1}, "budget_exhausted": True,
        "duration_seconds": 0.75,
        "runtime_config": {"policy": "evidence", "max_result_bytes": 1000},
        "runner_identity_consistent": True,
        "journal_sequence": None,
    }
    assert "secret" not in str(report) and "token" not in str(report)


def test_audit_reports_only_redacted_last_heartbeat_identity():
    report = build_audit_report({"id": "run-1", "events": [
        {"kind": "run.heartbeat", "operation_id": "op-1", "created_at": 10.0, "payload": {"secret": "hidden"}},
        {"kind": "run.heartbeat", "operation_id": "op-2", "created_at": 12.0, "payload": {"status": "planned"}},
    ]})
    assert report["heartbeat_count"] == 2
    assert report["heartbeat_runner_count"] == 0
    assert report["heartbeat_statuses"] == {"unknown": 1, "planned": 1}
    assert report["heartbeat_operations"] == {
        "op-1": {"status": "unknown", "attempts": 0, "runner_id": None, "created_at": 10.0},
        "op-2": {"status": "planned", "attempts": 0, "runner_id": None, "created_at": 12.0},
    }
    assert report["heartbeat_missing_operations"] == []
    assert report["runner_identity_consistent"] is True
    assert report["last_heartbeat"] == {"operation_id": "op-2", "created_at": 12.0, "runner_id": None}
    assert "secret" not in str(report)


def test_audit_detects_event_sequence_gaps_and_reordering():
    report = build_audit_report({"events": [
        {"seq": 4, "kind": "run.created", "created_at": 1.0, "payload": {}},
        {"seq": 6, "kind": "run.heartbeat", "created_at": 2.0, "payload": {}},
        {"seq": 5, "kind": "run.completed", "created_at": 3.0, "payload": {}},
    ]})
    assert report["journal_sequence"] == {
        "first": 4, "last": 5, "monotonic": False,
        "contiguous": False, "missing_count": 0,
    }


def test_audit_lists_operations_without_a_heartbeat():
    report = build_audit_report({
        "operations": [{"id": "op-seen"}, {"id": "op-missing"}],
        "events": [{"kind": "run.heartbeat", "operation_id": "op-seen", "created_at": 1.0, "payload": {}}],
    })
    assert report["heartbeat_missing_operations"] == ["op-missing"]
    assert report["heartbeat_health"] == {
        "coverage": 0.5, "status_mismatch_count": 0,
        "attempt_mismatch_count": 0, "healthy": False,
    }


def test_audit_flags_heartbeat_status_drift():
    report = build_audit_report({
        "operations": [{"id": "op-1", "status": "succeeded"}],
        "events": [{"kind": "run.heartbeat", "operation_id": "op-1", "created_at": 1.0, "payload": {"status": "unknown"}}],
    })
    assert report["heartbeat_status_mismatches"] == [{
        "operation_id": "op-1", "operation_status": "succeeded", "heartbeat_status": "unknown",
    }]


def test_audit_flags_heartbeat_attempt_drift():
    report = build_audit_report({
        "operations": [{"id": "op-1", "status": "succeeded", "attempts": 3}],
        "events": [{"kind": "run.heartbeat", "operation_id": "op-1", "created_at": 1.0,
                    "payload": {"status": "succeeded", "attempts": 2}}],
    })
    assert report["heartbeat_attempt_mismatches"] == [{
        "operation_id": "op-1", "operation_attempts": 3, "heartbeat_attempts": 2,
    }]
