"""One active runner per run, durable effect intent, conservative recovery."""

import asyncio
import time

from filelock import FileLock, Timeout

from rebound.models import Decision, Evidence, ToolKind
from rebound.store import Store, encode
from rebound.tools import Tool, ToolRejected

POLICIES = ("evidence", "naive", "checkpoint", "idempotent", "verify", "no_freshness")


class Runtime:
    def __init__(self, store: Store, tools: list[Tool], policy="evidence", max_attempts=3,
                 probe_budget=3, probe_delay=0.01, tool_timeout=10, evidence_ttl=30,
                 run_timeout: float | None = None, max_result_bytes: int = 1_000_000,
                 probe_backoff: float = 1.0, fault_hook=None):
        if policy not in POLICIES:
            raise ValueError(f"unknown policy: {policy}")
        if len({t.name for t in tools}) != len(tools):
            raise ValueError("duplicate tool names")
        if min(max_attempts, probe_budget, tool_timeout, evidence_ttl) <= 0 or probe_delay < 0 or probe_backoff < 1:
            raise ValueError("budgets/timeouts must be positive; delay must be nonnegative")
        if run_timeout is not None and run_timeout <= 0:
            raise ValueError("run_timeout must be positive when provided")
        if isinstance(max_result_bytes, bool) or not isinstance(max_result_bytes, int) or max_result_bytes <= 0:
            raise ValueError("max_result_bytes must be a positive integer")
        self.store, self.tools, self.policy = store, {t.name: t for t in tools}, policy
        self.max_attempts, self.probe_budget = max_attempts, probe_budget
        self.probe_delay, self.tool_timeout, self.evidence_ttl = probe_delay, tool_timeout, evidence_ttl
        self.probe_backoff = probe_backoff
        self.run_timeout = run_timeout
        self.max_result_bytes = max_result_bytes
        self.fault_hook = fault_hook

    def _hook(self, point, op_id):
        if self.fault_hook:
            self.fault_hook(point, op_id)

    def decide(self, tool: Tool, operation: dict, evidence: Evidence | None) -> Decision:
        retryable = tool.kind in {ToolKind.READ_ONLY, ToolKind.IDEMPOTENT}
        if self.policy == "naive":
            return Decision(action="retry", reason="Baseline: retry any uncertain call")
        if self.policy == "checkpoint":
            return Decision(action="review", reason="Checkpoint cannot determine external outcome")
        if self.policy == "idempotent":
            return Decision(action="retry" if retryable else "review", reason="Retry only adapter-declared replay-safe tools")
        if evidence is not None:
            now = time.time()
            identity_ok = evidence.operation_id == operation["id"]
            fresh = (evidence.observed_at <= now + 1 and now <= evidence.valid_until
                     and now - evidence.observed_at <= self.evidence_ttl)
            valid = identity_ok and evidence.authoritative
            if self.policy != "no_freshness":
                valid = valid and fresh
            if valid and evidence.status == "committed" and evidence.result is not None:
                return Decision(action="reuse", reason="Operation-matched authoritative receipt" + (" (freshness disabled)" if self.policy == "no_freshness" else " within validity window"), evidence=evidence)
            if self.policy == "verify" and evidence.status == "absent" and identity_ok:
                return Decision(action="retry", reason="Single-read verify baseline treats absence as retry permission", evidence=evidence)
        if retryable:
            return Decision(action="retry", reason="Stable operation ID and adapter replay contract", evidence=evidence)
        return Decision(action="probe", reason="Evidence insufficient; absence does not prove a write did not happen", evidence=evidence)

    async def _recover(self, run_id, operation, tool):
        for probe_index in range(self.probe_budget):
            evidence = None
            if tool.probe and self.policy not in {"naive", "checkpoint", "idempotent"}:
                try:
                    evidence = Evidence.model_validate(await asyncio.wait_for(tool.probe(operation["id"]), self.tool_timeout))
                    self.store.event(run_id, "recovery.probe", operation["id"], evidence.model_dump(mode="json"))
                except Exception as exc:
                    self.store.event(run_id, "recovery.probe_failed", operation["id"], {"error_type": type(exc).__name__})
            decision = self.decide(tool, operation, evidence)
            if decision.action == "probe" and probe_index + 1 == self.probe_budget:
                decision = Decision(action="review", reason="Probe budget exhausted; external effect remains uncertain", evidence=evidence)
            self.store.event(run_id, "recovery.decision", operation["id"], decision.model_dump(mode="json"))
            if decision.action == "reuse":
                assert decision.evidence is not None
                self.store.transition(operation["id"], "succeeded", result=decision.evidence.result)
                return "done"
            if decision.action in {"retry", "review", "fail"}:
                return decision.action
            await asyncio.sleep(self.probe_delay * (self.probe_backoff ** probe_index))
        return "review"

    async def run(self, run_id: str) -> dict:
        self.store.snapshot(run_id)  # Validate before constructing the lock path.
        lock = FileLock(str(self.store.path) + "." + run_id + ".lock")
        try:
            lock.acquire(timeout=0)
        except Timeout as exc:
            raise RuntimeError("run already has an active runner") from exc
        try:
            started_at = time.monotonic()
            budget_reported = False
            deadline = started_at + self.run_timeout if self.run_timeout is not None else None

            def runtime_budget_exhausted() -> bool:
                nonlocal budget_reported
                if self.run_timeout is None or time.monotonic() - started_at < self.run_timeout:
                    return False
                if not budget_reported:
                    self.store.event(run_id, "budget.runtime_exhausted", payload={"seconds": self.run_timeout})
                    budget_reported = True
                self.store.set_status(run_id, "needs_review")
                return True

            def execution_timeout(operation_id: str) -> float:
                """Never let one tool call exceed the remaining run budget."""
                if deadline is None:
                    return self.tool_timeout
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return 0.001
                timeout = min(self.tool_timeout, remaining)
                if timeout < self.tool_timeout:
                    self.store.event(run_id, "budget.runtime_limits_call", operation_id, {"seconds": timeout})
                return timeout

            if self.store.snapshot(run_id)["status"] == "cancelled":
                return self.store.snapshot(run_id)
            self.store.set_status(run_id, "running")
            self.store.event(run_id, "run.runtime_config", payload={
                "policy": self.policy,
                "max_attempts": self.max_attempts,
                "probe_budget": self.probe_budget,
                "tool_timeout": self.tool_timeout,
                "run_timeout": self.run_timeout,
                "max_result_bytes": self.max_result_bytes,
                "probe_backoff": self.probe_backoff,
            })
            for original in self.store.snapshot(run_id)["operations"]:
                if runtime_budget_exhausted():
                    return self.store.snapshot(run_id)
                if self.store.snapshot(run_id)["status"] == "cancelled":
                    return self.store.snapshot(run_id)
                op = original
                self.store.event(run_id, "run.heartbeat", op["id"], {"status": op["status"], "attempts": op["attempts"]})
                if op["status"] == "succeeded":
                    continue
                tool = self.tools.get(op["tool"])
                if tool is None or tool.permission == "deny":
                    self.store.event(run_id, "tool.denied", op["id"], {"reason": "missing or denied tool"})
                    self.store.set_status(run_id, "failed")
                    return self.store.snapshot(run_id)
                if tool.permission == "ask" and not op["approved"]:
                    self.store.set_status(run_id, "awaiting_approval")
                    return self.store.snapshot(run_id)
                if op["status"] == "failed":
                    self.store.set_status(run_id, "failed")
                    return self.store.snapshot(run_id)
                while True:
                    if runtime_budget_exhausted():
                        return self.store.snapshot(run_id)
                    if op["status"] in {"dispatched", "unknown"}:
                        if op["status"] == "dispatched":
                            self.store.transition(op["id"], "unknown", error="runner stopped before result commit")
                        action = await self._recover(run_id, op, tool)
                        if action == "done":
                            break
                        if action != "retry":
                            self.store.set_status(run_id, "needs_review")
                            return self.store.snapshot(run_id)
                    if op["attempts"] >= self.max_attempts:
                        self.store.event(run_id, "budget.exhausted", op["id"], {"max_attempts": self.max_attempts})
                        self.store.set_status(run_id, "needs_review")
                        return self.store.snapshot(run_id)
                    if self.store.snapshot(run_id)["status"] == "cancelled":
                        return self.store.snapshot(run_id)
                    try:
                        self.store.transition(op["id"], "dispatched", increment=True)
                    except ValueError:
                        if self.store.snapshot(run_id)["status"] == "cancelled":
                            return self.store.snapshot(run_id)
                        raise
                    self._hook("before_dispatch", op["id"])
                    try:
                        result = await asyncio.wait_for(
                            tool.execute(op["id"], op["arguments"]), execution_timeout(op["id"]),
                        )
                        if not isinstance(result, dict) or len(encode(result).encode("utf-8")) > self.max_result_bytes:
                            raise ValueError(f"tool result must be a JSON object under {self.max_result_bytes} bytes")
                    except ToolRejected as exc:
                        self.store.transition(op["id"], "failed", error=str(exc)[:1000])
                        self.store.set_status(run_id, "failed")
                        return self.store.snapshot(run_id)
                    except Exception as exc:
                        # Unknown is intentionally conservative. Exceptions do not prove non-execution.
                        self.store.transition(op["id"], "unknown", error=type(exc).__name__)
                        op = next(o for o in self.store.snapshot(run_id)["operations"] if o["id"] == op["id"])
                        continue
                    self._hook("after_effect", op["id"])
                    self.store.transition(op["id"], "succeeded", result=result)
                    self._hook("after_commit", op["id"])
                    break
            self.store.set_status(run_id, "completed")
            return self.store.snapshot(run_id)
        finally:
            lock.release()

    async def resolve(self, run_id, operation_id, result: dict, note: str) -> dict:
        if not note.strip():
            raise ValueError("manual reconciliation requires an evidence note")
        lock = FileLock(str(self.store.path) + "." + run_id + ".lock")
        with lock.acquire(timeout=0):
            self.store.reconcile(run_id, operation_id, result, note)
        return await self.run(run_id)
