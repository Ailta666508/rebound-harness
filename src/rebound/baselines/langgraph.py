"""SQLite-persistent LangGraph comparator with conservative effect handling.

This runs the same evidence policy on a mature graph runtime. Equality is useful:
it shows recovery behavior comes from tool contracts and policy, not brand names.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict


class EffectReceipt(BaseModel):
    model_config = ConfigDict(extra="allow")
    effect_id: str
    index: int
    value: int


class GraphState(TypedDict, total=False):
    index: int
    length: int
    run_id: str
    operation_id: str
    status: str
    results: list[dict[str, Any]]
    attempts: int
    probe_calls: int
    tool_calls: int
    reason: str


def available() -> bool:
    try:
        import langgraph.checkpoint.sqlite  # noqa: F401
        import langgraph.graph  # noqa: F401
        return True
    except ImportError:
        return False


def run_case(path: Path, tool: Any, length: int, run_id: str, *, max_attempts: int = 3,
             probe_budget: int = 3, evidence_ttl: float = 30) -> dict[str, Any]:
    """Run each operation through durable intent, execution, and reconciliation."""
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import END, START, StateGraph

    def receipt(value: dict[str, Any], index: int) -> dict[str, Any]:
        checked = EffectReceipt.model_validate(value)
        if checked.index != index or checked.value != (index + 1) ** 2:
            raise ValueError("receipt does not match requested fixture operation")
        return checked.model_dump()

    def intent(state: GraphState) -> GraphState:
        return {"operation_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{state['run_id']}:{state['index']}")),
                "attempts": 0, "status": "dispatched"}

    def execute(state: GraphState) -> GraphState:
        attempts = state["attempts"] + 1
        calls = state.get("tool_calls", 0) + 1
        try:
            value = asyncio.run(tool.execute(state["operation_id"], {"index": state["index"]}))
            result = receipt(value, state["index"])
            return {"results": state["results"] + [result], "index": state["index"] + 1,
                    "attempts": attempts, "tool_calls": calls, "status": "running"}
        except Exception as error:
            return {"attempts": attempts, "tool_calls": calls, "status": "unknown",
                    "reason": type(error).__name__}

    def reconcile(state: GraphState) -> GraphState:
        calls = state.get("probe_calls", 0)
        if tool.probe:
            for _ in range(probe_budget):
                calls += 1
                try:
                    evidence = asyncio.run(tool.probe(state["operation_id"]))
                    now = time.time()
                    if (evidence.operation_id == state["operation_id"]
                            and str(evidence.status) == "committed"
                            and evidence.authoritative and evidence.result is not None
                            and evidence.observed_at <= now + 1 and now <= evidence.valid_until
                            and now - evidence.observed_at <= evidence_ttl):
                        result = receipt(evidence.result, state["index"])
                        return {"results": state["results"] + [result], "index": state["index"] + 1,
                                "status": "running", "probe_calls": calls,
                                "reason": "fresh_authoritative_receipt"}
                except Exception:
                    pass
                if str(tool.kind) in {"idempotent", "read_only"} and state["attempts"] < max_attempts:
                    return {"status": "retry", "probe_calls": calls, "reason": "provider_safe_retry"}
                time.sleep(0.01)
        if str(tool.kind) in {"idempotent", "read_only"} and state["attempts"] < max_attempts:
            return {"status": "retry", "probe_calls": calls, "reason": "provider_safe_retry"}
        return {"status": "needs_review", "probe_calls": calls, "reason": "unresolved_external_effect"}

    def finish(state: GraphState) -> GraphState:
        return {"status": "completed"}

    def route(state: GraphState) -> str:
        if state["status"] == "unknown":
            return "reconcile"
        if state["status"] == "needs_review":
            return END
        if state["status"] == "retry":
            return "execute"
        return "finish" if state["index"] >= state["length"] else "intent"

    graph = StateGraph(GraphState)
    graph.add_node("intent", intent)
    graph.add_node("execute", execute)
    graph.add_node("reconcile", reconcile)
    graph.add_node("finish", finish)
    graph.add_edge(START, "intent")
    graph.add_edge("intent", "execute")
    graph.add_conditional_edges("execute", route)
    graph.add_conditional_edges("reconcile", route)
    graph.add_edge("finish", END)
    config: RunnableConfig = {"configurable": {"thread_id": run_id}, "recursion_limit": max(50, length * 8)}
    initial: GraphState = {"index": 0, "length": length, "run_id": run_id,
                           "results": [], "tool_calls": 0, "probe_calls": 0, "status": "running"}
    path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(path)) as saver:
        compiled = graph.compile(checkpointer=saver)
        result = compiled.invoke(initial, config=config)
    # Reopen disk storage rather than claiming an in-memory saver is persistent.
    with SqliteSaver.from_conn_string(str(path)) as reopened:
        restored = graph.compile(checkpointer=reopened).get_state(config).values
    if restored != result:
        raise AssertionError("LangGraph persisted state differs after reopening SQLite")
    return {"id": run_id, "status": result["status"], "results": result["results"],
            "tool_calls": result.get("tool_calls", 0), "events": [],
            "persisted_state_verified": True, "reason": result.get("reason", "")}
