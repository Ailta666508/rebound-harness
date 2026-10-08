"""Optional, conservative adapter for explicitly trusted stdio MCP servers.

Server tool annotations never establish replay safety. Only the embedding
application can opt into a stronger contract after auditing its provider.
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from rebound.models import ToolKind
from rebound.tools import Tool, ToolRejected


class MCPToolError(RuntimeError):
    """An MCP error result does not establish that no external effect occurred."""


@dataclass(frozen=True)
class MCPToolContract:
    """Trusted application configuration, never inferred from server hints."""

    kind: ToolKind = ToolKind.OPAQUE
    permission: Literal["allow", "ask", "deny"] = "allow"
    operation_id_argument: str | None = None

    def __post_init__(self) -> None:
        kind = ToolKind(self.kind)
        if kind not in {ToolKind.OPAQUE, ToolKind.READ_ONLY, ToolKind.IDEMPOTENT}:
            raise ValueError("stdio adapter has no evidence probe; use opaque, read_only, or idempotent")
        if self.permission not in {"allow", "ask", "deny"}:
            raise ValueError("invalid MCP tool permission")
        if self.operation_id_argument is not None and not self.operation_id_argument:
            raise ValueError("operation ID argument must be nonempty")
        object.__setattr__(self, "kind", kind)


@asynccontextmanager
async def stdio_tools(
    command: str,
    args: Sequence[str] = (),
    *,
    namespace: str = "mcp",
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    allowlist: Sequence[str] | None = None,
    contracts: Mapping[str, MCPToolContract] | None = None,
    timeout: float = 30,
) -> AsyncIterator[list[Tool]]:
    """Launch one trusted local server and expose its tools for this context.

    No shell is used. This is not process isolation: the configured server runs
    with the caller's OS permissions. ``env`` and process arguments are not
    journaled. Resources, prompts, sampling, elicitation, and remote transports
    are outside this adapter's scope.
    """
    if not command or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", namespace) or timeout <= 0:
        raise ValueError("require a command, a short safe namespace, and a positive timeout")
    try:
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        from mcp_types import CallToolResult
    except ImportError as error:
        raise ImportError("Install the optional adapter with pip install 'rebound-harness[mcp]'") from error

    trusted = dict(contracts or {})
    allowed = set(allowlist) if allowlist is not None else None
    parameters = StdioServerParameters(command=command, args=list(args),
                                        env=dict(env) if env is not None else None, cwd=cwd)
    active = False
    async with Client(parameters, cache=None, read_timeout_seconds=timeout) as client:
        specs: dict[str, Any] = {}
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(100):
            page = await client.list_tools(cursor=cursor)
            for spec in page.tools:
                if spec.name in specs:
                    raise ValueError("MCP discovery returned a duplicate tool name")
                specs[spec.name] = spec
            cursor = page.next_cursor
            if cursor is None:
                break
            if cursor in seen_cursors:
                raise ValueError("MCP discovery repeated a pagination cursor")
            seen_cursors.add(cursor)
        else:
            raise ValueError("MCP tool discovery exceeded 100 pages")
        unknown = (set(trusted) | (allowed or set())) - set(specs)
        if unknown:
            raise ValueError(f"Configured MCP tool names were not discovered: {sorted(unknown)}")

        def adapt(spec: Any) -> Tool:
            contract = trusted.get(spec.name, MCPToolContract())
            name = f"{namespace}__{spec.name}"
            if len(name) > 128:
                raise ValueError("Namespaced MCP tool name exceeds harness limit")
            schema = deepcopy(spec.input_schema)
            reserved = contract.operation_id_argument
            if reserved is not None:
                properties = schema.get("properties", {})
                if reserved not in properties or properties[reserved].get("type") != "string":
                    raise ValueError("Configured operation ID argument must be a declared string property")
                del properties[reserved]
                schema["required"] = [field for field in schema.get("required", []) if field != reserved]

            async def execute(operation_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
                if not active:
                    raise ToolRejected("MCP connection context has closed")
                supplied = dict(arguments)
                if reserved:
                    if reserved in supplied:
                        raise ToolRejected("Operation ID field is owned by the harness")
                    supplied[reserved] = operation_id
                # Use the session API once, avoiding high-level automatic re-dispatch
                # for input-required/schema negotiation. Runtime owns recovery decisions.
                result = await client.session.call_tool(spec.name, supplied, allow_input_required=True)
                if not isinstance(result, CallToolResult):
                    raise MCPToolError("MCP tool requires unsupported continuation input")
                if result.is_error:
                    raise MCPToolError("MCP server returned an error; external outcome is uncertain")
                return result.model_dump(mode="json", by_alias=True, exclude_none=True)

            return Tool(name=name, kind=contract.kind, execute=execute,
                        description=spec.description or "MCP tool", parameters=schema,
                        permission=contract.permission)

        tools = [adapt(spec) for name, spec in specs.items() if allowed is None or name in allowed]
        active = True
        try:
            yield tools
        finally:
            active = False
