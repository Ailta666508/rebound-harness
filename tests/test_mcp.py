"""Integration with a real stdio MCP subprocess, without a network listener."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="optional MCP extra")

from rebound.mcp import MCPToolContract, MCPToolError, stdio_tools
from rebound.models import Step, ToolKind
from rebound.runtime import Runtime
from rebound.store import Store
from rebound.tools import ToolRejected


@pytest.fixture
def mcp_server(tmp_path: Path) -> Path:
    script = tmp_path / "server.py"
    script.write_text('''
from pathlib import Path
import sqlite3
import sys
from mcp.server import MCPServer
from mcp_types import CallToolResult, TextContent, ToolAnnotations

server = MCPServer("Rebound fixture")
root = Path(sys.argv[1])

@server.tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
def calculate(value: int) -> dict[str, int]:
    return {"value": value * 2}

@server.tool()
def append_then_error(value: str) -> CallToolResult:
    with (root / "effects.txt").open("a") as handle:
        handle.write(value + "\\n")
    return CallToolResult(content=[TextContent(type="text", text="reply failed after write")], is_error=True)

@server.tool()
def deduplicated(value: str, operation_id: str) -> dict[str, str | int]:
    with sqlite3.connect(root / "effects.sqlite") as db:
        db.execute("CREATE TABLE IF NOT EXISTS effects (id TEXT PRIMARY KEY, value TEXT)")
        db.execute("INSERT OR IGNORE INTO effects VALUES(?,?)", (operation_id, value))
        stored = db.execute("SELECT value FROM effects WHERE id=?", (operation_id,)).fetchone()[0]
        count = db.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
    return {"value": stored, "count": count, "operation_id": operation_id}

server.run(transport="stdio")
''')
    return script


async def test_real_stdio_discovery_does_not_trust_hints(mcp_server: Path, tmp_path: Path):
    async with stdio_tools(sys.executable, [str(mcp_server), str(tmp_path)], namespace="fixture") as tools:
        table = {tool.name: tool for tool in tools}
        assert table["fixture__calculate"].kind == ToolKind.OPAQUE
        assert table["fixture__calculate"].parameters["properties"]["value"]["type"] == "integer"
        result = await table["fixture__calculate"].execute("op-test", {"value": 7})
        assert result["structuredContent"] == {"value": 14}
        assert result["isError"] is False
    with pytest.raises(ToolRejected, match="closed"):
        await table["fixture__calculate"].execute("late", {"value": 7})


async def test_stdio_error_after_effect_is_uncertain_and_not_retried(mcp_server: Path, tmp_path: Path):
    async with stdio_tools(sys.executable, [str(mcp_server), str(tmp_path)],
                           allowlist=["append_then_error"]) as tools:
        store = Store(tmp_path / "run.sqlite")
        run = store.create_run([Step(key="write", tool=tools[0].name, arguments={"value": "once"})])
        result = await Runtime(store, tools).run(run)
        assert result["status"] == "needs_review"
        assert result["operations"][0]["status"] == "unknown"
        assert result["operations"][0]["attempts"] == 1
        assert (tmp_path / "effects.txt").read_text() == "once\n"
        with pytest.raises(MCPToolError):
            await tools[0].execute("second", {"value": "explicit"})


async def test_trusted_idempotency_injects_stable_identity(mcp_server: Path, tmp_path: Path):
    config = {"deduplicated": MCPToolContract(kind=ToolKind.IDEMPOTENT, operation_id_argument="operation_id")}
    async with stdio_tools(sys.executable, [str(mcp_server), str(tmp_path)],
                           allowlist=["deduplicated"], contracts=config) as tools:
        tool = tools[0]
        assert tool.kind == ToolKind.IDEMPOTENT
        assert "operation_id" not in tool.parameters["properties"]
        assert "operation_id" not in tool.parameters["required"]
        first = await tool.execute("same-intent", {"value": "one"})
        repeated = await tool.execute("same-intent", {"value": "one"})
        assert first["structuredContent"]["count"] == repeated["structuredContent"]["count"] == 1
        with pytest.raises(ToolRejected, match="owned"):
            await tool.execute("same-intent", {"value": "bad", "operation_id": "override"})
    # Provider fixture persists deduplication across a fresh server process.
    async with stdio_tools(sys.executable, [str(mcp_server), str(tmp_path)],
                           allowlist=["deduplicated"], contracts=config) as tools:
        result = await tools[0].execute("same-intent", {"value": "one"})
        assert result["structuredContent"]["count"] == 1


async def test_explicit_read_only_and_approval_contract(mcp_server: Path, tmp_path: Path):
    async with stdio_tools(sys.executable, [str(mcp_server), str(tmp_path)],
                           allowlist=["calculate"],
                           contracts={"calculate": MCPToolContract(kind=ToolKind.READ_ONLY, permission="ask")}) as tools:
        assert len(tools) == 1
        assert tools[0].kind == ToolKind.READ_ONLY
        store = Store(tmp_path / "approval.sqlite")
        run = store.create_run([Step(key="read", tool=tools[0].name, arguments={"value": 5})])
        paused = await Runtime(store, tools).run(run)
        assert paused["status"] == "awaiting_approval"
        assert paused["operations"][0]["attempts"] == 0
        store.approve(run, paused["operations"][0]["id"])
        completed = await Runtime(store, tools).run(run)
        assert completed["status"] == "completed"
        assert completed["operations"][0]["result"]["structuredContent"] == {"value": 10}
