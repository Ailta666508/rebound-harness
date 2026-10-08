import json

import httpx
import pytest

from rebound import Store, Tool, ToolKind
from rebound.agent import AgentRunner, ChatModel, context_window
from rebound.tools import ToolRejected, workspace_tools


class ScriptedModel:
    model = "scripted-test-model"
    def __init__(self):
        self.calls = 0
    async def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "write", "arguments": '{"value":42}'}}]}, {"total_tokens": 12}
        assert messages[-1]["role"] == "tool"
        return {"role": "assistant", "content": "Completed with receipt."}, {"total_tokens": 8}


async def test_model_plan_is_persisted_before_effect_and_no_repeat(tmp_path):
    store = Store(tmp_path / "journal.sqlite")
    seen = []
    async def execute(op, args):
        runs = store.list_runs()
        assert runs[0]["metadata"]["pending_calls"]
        seen.append(op)
        return args
    model = ScriptedModel()
    runner = AgentRunner(store, [Tool("write", ToolKind.OPAQUE, execute)], model)
    snap = await runner.run("Write value 42")
    assert snap["status"] == "completed"
    assert snap["metadata"]["answer"] == "Completed with receipt."
    await runner.run(run_id=snap["id"])
    assert len(seen) == 1 and model.calls == 2


async def test_real_transport_contract_without_remote_api_call():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer test-only-secret"
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert body["messages"][0]["role"] == "user"
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {"total_tokens": 3}})
    model = ChatModel("test-model", "https://example.invalid/v1", "test-only-secret", httpx.MockTransport(handler))
    message, usage = await model.complete([{"role": "user", "content": "hello"}], [])
    assert message["content"] == "ok" and usage["total_tokens"] == 3


def test_context_never_orphans_tool_result():
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]
    for i in range(8):
        messages.extend([{"role": "assistant", "tool_calls": [{"id": str(i)}], "content": "x"*100}, {"role": "tool", "tool_call_id": str(i), "content": "y"*100}])
    window = context_window(messages, 1100)
    for i, message in enumerate(window):
        if message["role"] == "tool":
            assert window[i-1]["role"] == "assistant"
            assert window[i-1]["tool_calls"][0]["id"] == message["tool_call_id"]


async def test_workspace_path_escape_and_symlink_rejected(tmp_path):
    root = tmp_path / "workspace"
    tools = {t.name: t for t in workspace_tools(root)}
    with pytest.raises(ToolRejected):
        await tools["write_file"].execute("one", {"path": "../escape", "content": "no"})
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(ToolRejected):
        await tools["write_file"].execute("two", {"path": "link/escape", "content": "no"})
    assert not (outside / "escape").exists()


async def test_model_request_budget(tmp_path):
    model = ScriptedModel()
    async def execute(_op, args):
        return args
    runner = AgentRunner(Store(tmp_path / "s.sqlite"), [Tool("write", ToolKind.OPAQUE, execute)], model, max_turns=1)
    snap = await runner.run("test")
    assert snap["status"] == "needs_review"
    assert model.calls == 1


async def test_typed_final_output_is_validated(tmp_path):
    from pydantic import BaseModel, ValidationError
    class Result(BaseModel):
        count: int
    class Model:
        async def complete(self, messages, tools):
            return {"content": '{"count":4}'}, {}
    store = Store(tmp_path / "typed.sqlite")
    runner = AgentRunner(store, [], Model(), output_model=Result)
    snap = await runner.run("Return the count")
    assert snap["metadata"]["structured_output"] == {"count": 4}
    with pytest.raises(ValueError, match="original output schema"):
        await AgentRunner(store, [], Model()).run(run_id=snap["id"])
    class Bad:
        async def complete(self, messages, tools):
            return {"content": '{"count":"not an integer"}'}, {}
    with pytest.raises(ValidationError):
        await AgentRunner(store, [], Bad(), output_model=Result).run("Return count")
    assert store.list_runs()[0]["status"] == "failed"


async def test_oversized_latest_turn_pauses_instead_of_dropping_receipt(tmp_path):
    model = ScriptedModel()
    async def execute(op, args):
        return {"huge": "x" * 3000}
    runner = AgentRunner(Store(tmp_path / "context.sqlite"), [Tool("write", ToolKind.OPAQUE, execute)], model, max_context_chars=1000)
    snap = await runner.run("test")
    assert snap["status"] == "needs_review"
    assert model.calls == 1
    assert any(e["kind"] == "context.exhausted" for e in snap["events"])
