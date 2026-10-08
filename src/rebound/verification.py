"""Offline journal checks. Does not assert truth of external provider receipts."""


def verify_snapshot(snapshot: dict) -> dict:
    errors = []
    events = snapshot["events"]
    seqs = [event["seq"] for event in events]
    if seqs != sorted(set(seqs)):
        errors.append("event sequence is not strictly increasing")
    for op in snapshot["operations"]:
        history = [e for e in events if e["operation_id"] == op["id"]]
        dispatches = sum(e["kind"] == "operation.dispatched" for e in history)
        if dispatches != op["attempts"]:
            errors.append(f"{op['id']}: attempt count mismatch")
        success = [e for e in history if e["kind"] == "operation.succeeded"]
        if op["status"] == "succeeded" and (len(success) != 1 or success[0]["payload"].get("result") != op["result"]):
            errors.append(f"{op['id']}: result and journal disagree")
        if op["status"] == "succeeded" and not dispatches:
            errors.append(f"{op['id']}: success without dispatch intent")
    if snapshot["status"] == "completed" and any(op["status"] != "succeeded" for op in snapshot["operations"]):
        errors.append("completed run has unfinished operations")
    return {"valid": not errors, "errors": errors, "scope": "local journal consistency; external effects require a provider oracle"}
