"""Build a redacted, deterministic operational report from a persisted run."""

from __future__ import annotations

from collections import Counter
from typing import Any


def build_audit_report(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Summarize recovery behavior without exposing tool arguments or results."""
    operations = snapshot.get("operations", [])
    events = snapshot.get("events", [])
    statuses = Counter(str(operation.get("status", "unknown")) for operation in operations)
    decisions = [
        event["payload"]
        for event in events
        if event.get("kind") == "recovery.decision" and isinstance(event.get("payload"), dict)
    ]
    decision_counts = Counter(str(item.get("action", "unknown")) for item in decisions)
    budget_events = Counter(
        str(event.get("kind")) for event in events
        if str(event.get("kind", "")).startswith("budget.")
    )
    timeout_events = [
        event for event in events
        if event.get("kind") == "tool.timeout" and isinstance(event.get("operation_id"), str)
    ]
    timeout_operations = Counter(event["operation_id"] for event in timeout_events)
    heartbeat_count = sum(1 for event in events if event.get("kind") == "run.heartbeat")
    heartbeats = [event for event in events if event.get("kind") == "run.heartbeat"]
    last_heartbeat = heartbeats[-1] if heartbeats else None
    runner_ids = sorted({
        event.get("payload", {}).get("runner_id")
        for event in heartbeats
        if isinstance(event.get("payload"), dict) and isinstance(event["payload"].get("runner_id"), str)
    })
    heartbeat_statuses = Counter(
        str(event.get("payload", {}).get("status", "unknown"))
        for event in heartbeats
        if isinstance(event.get("payload"), dict)
    )
    heartbeat_operations: dict[str, dict[str, Any]] = {}
    for event in heartbeats:
        operation_id = event.get("operation_id")
        payload = event.get("payload")
        if isinstance(operation_id, str) and isinstance(payload, dict):
            heartbeat_operations[operation_id] = {
                "status": str(payload.get("status", "unknown")),
                "attempts": payload.get("attempts", 0),
                "runner_id": payload.get("runner_id"),
                "created_at": event.get("created_at"),
            }
    heartbeat_duplicate_operations = sorted(
        operation_id for operation_id in {
            event.get("operation_id") for event in heartbeats
            if isinstance(event.get("operation_id"), str)
        }
        if sum(1 for event in heartbeats if event.get("operation_id") == operation_id) > 1
    )
    heartbeat_duplicate_counts = {
        operation_id: sum(1 for event in heartbeats if event.get("operation_id") == operation_id)
        for operation_id in heartbeat_duplicate_operations
    }
    heartbeat_missing_operations = sorted(
        operation.get("id") for operation in operations
        if isinstance(operation.get("id"), str) and operation["id"] not in heartbeat_operations
    )
    heartbeat_status_mismatches = sorted([
        {
            "operation_id": operation["id"],
            "operation_status": str(operation.get("status", "unknown")),
            "heartbeat_status": heartbeat_operations[operation["id"]]["status"],
        }
        for operation in operations
        if isinstance(operation.get("id"), str)
        and operation["id"] in heartbeat_operations
        and str(operation.get("status", "unknown")) != heartbeat_operations[operation["id"]]["status"]
    ], key=lambda item: item["operation_id"])
    heartbeat_attempt_mismatches = sorted([
        {
            "operation_id": operation["id"],
            "operation_attempts": int(operation.get("attempts", 0)),
            "heartbeat_attempts": int(heartbeat_operations[operation["id"]].get("attempts", 0)),
        }
        for operation in operations
        if isinstance(operation.get("id"), str)
        and operation["id"] in heartbeat_operations
        and int(operation.get("attempts", 0)) != int(heartbeat_operations[operation["id"]].get("attempts", 0))
    ], key=lambda item: item["operation_id"])
    identified_operation_count = sum(
        1 for operation in operations if isinstance(operation.get("id"), str)
    )
    heartbeat_health = {
        "coverage": round(
            (identified_operation_count - len(heartbeat_missing_operations)) / identified_operation_count,
            6,
        ) if identified_operation_count else 1.0,
        "status_mismatch_count": len(heartbeat_status_mismatches),
        "attempt_mismatch_count": len(heartbeat_attempt_mismatches),
        "healthy": not (
            heartbeat_missing_operations or heartbeat_status_mismatches or heartbeat_attempt_mismatches
        ),
    }
    timestamps = [
        float(event["created_at"])
        for event in events
        if isinstance(event.get("created_at"), (int, float))
        and not isinstance(event.get("created_at"), bool)
    ]
    duration_seconds = max(timestamps) - min(timestamps) if len(timestamps) >= 2 else 0.0
    runtime_events = [
        event.get("payload") for event in events
        if event.get("kind") == "run.runtime_config" and isinstance(event.get("payload"), dict)
    ]
    runtime_config = runtime_events[-1] if runtime_events else None
    configured_runner = runtime_config.get("runner_id") if isinstance(runtime_config, dict) else None
    heartbeat_runner_mismatches = sorted({
        str(event.get("payload", {}).get("runner_id"))
        for event in heartbeats
        if configured_runner is not None
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("runner_id") != configured_runner
    })
    uncertain_count = statuses.get("unknown", 0) + statuses.get("dispatched", 0)
    sequences = [event.get("seq") for event in events if isinstance(event.get("seq"), int) and not isinstance(event.get("seq"), bool)]
    sequence_check = None
    if sequences:
        first, last = min(sequences), max(sequences)
        expected = list(range(first, last + 1))
        missing = sorted(set(expected) - set(sequences))
        sequence_check = {
            "first": first,
            "last": last,
            "monotonic": all(left < right for left, right in zip(sequences, sequences[1:])),
            "contiguous": sequences == expected,
            "missing_count": len(missing),
            "duplicate_count": len(sequences) - len(set(sequences)),
            "missing": missing,
        }
    return {
        "schema_version": 1,
        "run_id": snapshot.get("id"),
        "status": snapshot.get("status"),
        "title": snapshot.get("title"),
        "operation_count": len(operations),
        "operation_statuses": dict(sorted(statuses.items())),
        "uncertain_operation_count": uncertain_count,
        "attempts": sum(int(operation.get("attempts", 0)) for operation in operations),
        "event_count": len(events),
        "heartbeat_count": heartbeat_count,
        "last_heartbeat": ({
            "operation_id": last_heartbeat.get("operation_id"),
            "created_at": last_heartbeat.get("created_at"),
            "runner_id": last_heartbeat.get("payload", {}).get("runner_id") if isinstance(last_heartbeat.get("payload"), dict) else None,
        } if last_heartbeat else None),
        "heartbeat_runner_count": len(runner_ids),
        "heartbeat_statuses": dict(sorted(heartbeat_statuses.items())),
        "heartbeat_operations": dict(sorted(heartbeat_operations.items())),
        "heartbeat_duplicate_operations": heartbeat_duplicate_operations,
        "heartbeat_duplicate_counts": heartbeat_duplicate_counts,
        "heartbeat_missing_operations": heartbeat_missing_operations,
        "heartbeat_status_mismatches": heartbeat_status_mismatches,
        "heartbeat_attempt_mismatches": heartbeat_attempt_mismatches,
        "heartbeat_health": heartbeat_health,
        "heartbeat_runner_mismatches": heartbeat_runner_mismatches,
        "runner_identity_consistent": (
            not heartbeat_runner_mismatches
        ),
        "event_kinds": dict(sorted(Counter(str(event.get("kind", "unknown")) for event in events).items())),
        "recovery_decisions": dict(sorted(decision_counts.items())),
        "budget_events": dict(sorted(budget_events.items())),
        "budget_exhausted": sum(budget_events.values()) > 0,
        "tool_timeout_count": len(timeout_events),
        "tool_timeout_operations": dict(sorted(timeout_operations.items())),
        "duration_seconds": round(max(0.0, duration_seconds), 6),
        "runtime_config": runtime_config,
        "journal_sequence": sequence_check,
        "needs_review": snapshot.get("status") == "needs_review",
    }
