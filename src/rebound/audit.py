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
    heartbeat_count = sum(1 for event in events if event.get("kind") == "run.heartbeat")
    heartbeats = [event for event in events if event.get("kind") == "run.heartbeat"]
    last_heartbeat = heartbeats[-1] if heartbeats else None
    runner_ids = sorted({
        event.get("payload", {}).get("runner_id")
        for event in heartbeats
        if isinstance(event.get("payload"), dict) and isinstance(event["payload"].get("runner_id"), str)
    })
    timestamps = [float(event["created_at"]) for event in events if isinstance(event.get("created_at"), (int, float))]
    duration_seconds = max(timestamps) - min(timestamps) if len(timestamps) >= 2 else 0.0
    runtime_events = [
        event.get("payload") for event in events
        if event.get("kind") == "run.runtime_config" and isinstance(event.get("payload"), dict)
    ]
    runtime_config = runtime_events[-1] if runtime_events else None
    uncertain_count = statuses.get("unknown", 0) + statuses.get("dispatched", 0)
    sequences = [event.get("seq") for event in events if isinstance(event.get("seq"), int)]
    sequence_check = None
    if sequences:
        expected = list(range(sequences[0], sequences[-1] + 1))
        sequence_check = {
            "first": sequences[0],
            "last": sequences[-1],
            "monotonic": all(left < right for left, right in zip(sequences, sequences[1:])),
            "contiguous": sequences == expected,
            "missing_count": max(0, len(expected) - len(set(sequences))),
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
        "event_kinds": dict(sorted(Counter(str(event.get("kind", "unknown")) for event in events).items())),
        "recovery_decisions": dict(sorted(decision_counts.items())),
        "budget_events": dict(sorted(budget_events.items())),
        "budget_exhausted": sum(budget_events.values()) > 0,
        "duration_seconds": round(max(0.0, duration_seconds), 6),
        "runtime_config": runtime_config,
        "journal_sequence": sequence_check,
        "needs_review": snapshot.get("status") == "needs_review",
    }
