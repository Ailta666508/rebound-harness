"""Tools explicitly declare effect contracts, independent of model prompting."""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from rebound.models import Evidence, ToolKind


class ToolRejected(Exception):
    """Adapter guarantees this attempt caused no effect (e.g. validation refusal)."""


@dataclass(frozen=True)
class Tool:
    name: str
    kind: ToolKind
    execute: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
    probe: Callable[[str], Awaitable[Evidence]] | None = None
    description: str = ""
    parameters: dict[str, Any] | None = None
    permission: Literal["allow", "ask", "deny"] = "allow"

    def __post_init__(self):
        object.__setattr__(self, "kind", ToolKind(self.kind))
        if self.permission not in {"allow", "ask", "deny"}:
            raise ValueError("invalid tool permission")


def workspace_tools(root: Path) -> list[Tool]:
    """Trusted single-user file tools. Not an OS sandbox; reject symlink paths."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)

    def path_for(value):
        candidate = root / str(value)
        if candidate.is_symlink() or any(p.is_symlink() for p in candidate.parents if p != root.parent):
            raise ToolRejected("symlink paths are not allowed")
        path = candidate.resolve()
        if not path.is_relative_to(root) or path == root:
            raise ToolRejected("path must be a file inside the workspace")
        return path

    async def read(_id, args):
        path = path_for(args["path"])
        if not path.is_file():
            raise ToolRejected("file not found")
        if path.stat().st_size > 100_000:
            raise ToolRejected("file exceeds 100 KB read limit")
        return {"path": args["path"], "content": path.read_text()}

    async def write(_id, args):
        path = path_for(args["path"])
        content = str(args["content"])
        if len(content.encode()) > 100_000:
            raise ToolRejected("file exceeds 100 KB write limit")
        path.parent.mkdir(parents=True, exist_ok=True)
        # File overwrite is reconcilable/opaque, not globally idempotent in a shared workspace.
        path.write_text(content)
        return {"path": args["path"], "bytes": len(content.encode())}

    async def listing(_id, _args):
        return {"files": sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())[:500]}

    schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}
    return [
        Tool("read_file", ToolKind.READ_ONLY, read, description="Read a UTF-8 workspace file", parameters=schema),
        Tool("write_file", ToolKind.OPAQUE, write, description="Write a UTF-8 workspace file", parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False}),
        Tool("list_files", ToolKind.READ_ONLY, listing, description="List workspace files", parameters={"type": "object", "properties": {}, "additionalProperties": False}),
    ]


def docker_tool(image: str = "python:3.12-slim") -> Tool:
    """Disposable network-disabled container, no host mounts or Docker socket."""
    async def execute(_id, args):
        code = str(args.get("code", ""))
        if len(code) > 50_000:
            raise ToolRejected("code too large")
        container_name = "rebound-" + uuid.uuid4().hex
        proc = await asyncio.create_subprocess_exec(
            "docker", "run", "--rm", "--name", container_name, "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--pids-limit=64", "--memory=128m", "--cpus=1",
            "--user=65534:65534", "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
            image, "python", "-c", code,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        async def capped_read(stream):
            chunks, size = [], 0
            while chunk := await stream.read(32768):
                size += len(chunk)
                if size > 1_000_000:
                    raise RuntimeError("sandbox output limit exceeded")
                chunks.append(chunk)
            return b"".join(chunks)

        async def cleanup():
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            # Killing the Docker client does not kill its remote container.
            remover = await asyncio.create_subprocess_exec("docker", "rm", "-f", container_name,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            try:
                await asyncio.wait_for(remover.wait(), 5)
            except TimeoutError:
                remover.kill()
                await remover.wait()

        readers = [asyncio.create_task(capped_read(proc.stdout)), asyncio.create_task(capped_read(proc.stderr))]
        try:
            stdout, stderr, _ = await asyncio.wait_for(asyncio.gather(*readers, proc.wait()), timeout=20)
        finally:
            for reader in readers:
                if not reader.done():
                    reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            await asyncio.shield(cleanup())
        return {"exit_code": proc.returncode, "stdout": stdout.decode(errors="replace")[:16000], "stderr": stderr.decode(errors="replace")[:16000]}
    return Tool("python_sandbox", ToolKind.OPAQUE, execute, description="Run Python in a disposable Docker container", parameters=json.loads('{"type":"object","properties":{"code":{"type":"string"}},"required":["code"],"additionalProperties":false}'))
