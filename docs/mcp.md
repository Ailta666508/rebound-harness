# Trusted local MCP tools

The optional adapter connects to a local stdio server using the official
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), pinned to
`mcp==2.3.0` in the `mcp` extra. It discovers tools and converts their descriptions
and JSON input schemas into Rebound `Tool` objects.

```sh
pip install -e '.[mcp]'
```

This adapter is an embedding API. The `rebound agent` command does not
implicitly discover installed servers. Remote HTTP transport, OAuth, prompts,
resources, sampling, elicitation, and MCP continuation flows are outside this
first adapter's scope.

## Minimal example

Save a trusted server as `server.py`:

```python
from mcp.server import MCPServer

server = MCPServer("Arithmetic")

@server.tool()
def double(value: int) -> dict[str, int]:
    return {"value": value * 2}

if __name__ == "__main__":
    server.run(transport="stdio")
```

Then connect, execute, and close its subprocess:

```python
import asyncio
import sys
from pathlib import Path

from rebound.mcp import MCPToolContract, stdio_tools
from rebound.models import Step, ToolKind
from rebound.runtime import Runtime
from rebound.store import Store

async def main():
    async with stdio_tools(
        sys.executable,
        ["server.py"],
        namespace="arithmetic",
        allowlist=["double"],
        # This declaration comes from our knowledge of our server implementation.
        contracts={"double": MCPToolContract(kind=ToolKind.READ_ONLY)},
    ) as tools:
        store = Store(Path(".rebound/mcp.sqlite"))
        run_id = store.create_run([
            Step(key="double-7", tool="arithmetic__double", arguments={"value": 7})
        ])
        snapshot = await Runtime(store, tools).run(run_id)
        print(snapshot["operations"][0]["result"]["structuredContent"])

asyncio.run(main())
```

Keep `Runtime.run()` and any resumed work inside the `async with` block. Tools
retained after the connection has closed reject calls before contacting a server.
To resume in a new process, reconnect to the same trusted server implementation
and pass the resulting tools to a runtime using the existing journal.

## Recovery contracts

Every discovered tool defaults to `ToolKind.OPAQUE`, regardless of advertised
`readOnlyHint` or `idempotentHint`. Those are server-supplied hints, not proof of
a provider's behavior. Explicit `MCPToolContract` configuration can declare a
known read-only or idempotent operation and set `permission="ask"` or `"deny"`.
There is no generic evidence probe, so this adapter does not accept the
`RECONCILABLE` kind.

If an audited provider deduplicates by a string argument, reserve that field
for the harness:

```python
contracts = {
    "create_ticket": MCPToolContract(
        kind=ToolKind.IDEMPOTENT,
        operation_id_argument="idempotency_key",
        permission="ask",
    )
}
```

The field must exist as a string property in the provider's tool schema. Rebound
removes it from the model-visible schema and injects the stable operation ID on
every execution attempt. Caller-supplied overrides are rejected before I/O.
**The remote tool must actually provide durable deduplication** for the relevant
retention window and arguments. Adding an ID field alone does not make a write
idempotent. Intrinsically idempotent tools may use an explicit contract without
an ID field.

An MCP `isError` response can arrive after a side effect. The adapter raises an
ordinary `MCPToolError`, so the runtime treats the outcome as uncertain. It does
not label the error as proof of no effect. The session API performs one tool
request per execution attempt; high-level SDK redispatch for continuation or
schema negotiation is not used. Unsupported continuation results remain
uncertain rather than being counted as success.

## Process and data boundaries

Only launch a server command you trust. It is started without a shell but has
the caller's OS permissions; stdio is not an execution sandbox. Pass credentials
through `env` rather than command-line arguments. The adapter does not journal
server environment variables or process arguments. Normal tool arguments and
returned content are journaled, so keep credentials out of those values.

Tool names use `<namespace>__<server-tool-name>`. Discovery follows pagination
with cycle and page-count checks. An explicit allowlist restricts exposed tools;
unknown configured names fail discovery. Server descriptions and returned text
remain untrusted tool data for the model.

## Verified behavior

`tests/test_mcp.py` launches actual local MCP server subprocesses. It checks
schema discovery, ignoring server hints, successful structured output, an error
after a physical file write, explicit approval, and durable deduplication after
restarting the server. No loopback port is needed.
