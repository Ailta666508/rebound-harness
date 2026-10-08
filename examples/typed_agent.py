"""Persist tool calls and validate a typed final answer.

No key is needed for the default deterministic fixture:
    python examples/typed_agent.py

An explicit --model enables a real endpoint and may incur provider charges:
    REBOUND_API_KEY=... python examples/typed_agent.py --model YOUR_MODEL \
        --base-url https://YOUR_PROVIDER/v1

The fixture demonstrates interface and durability mechanics, not LLM quality.
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from rebound import Store, Tool, ToolKind
from rebound.agent import AgentRunner, ChatModel


class RecoverySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["retry", "review", "reuse"]
    reason: str
    safe_to_repeat_automatically: bool


async def inspect_contract(_operation_id: str, _arguments: dict) -> dict:
    return {
        "tool_kind": "reconcilable",
        "outcome": "unknown",
        "provider_idempotency": False,
        "available_evidence": "none",
        "rule": "Do not automatically repeat an uncertain non-idempotent write.",
    }


class OfflineExampleModel:
    """A deterministic model fixture; no network or API credentials."""
    model = "offline-example-fixture"

    async def complete(self, messages, _tools):
        if messages[-1]["role"] != "tool":
            return {
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "inspect-1", "type": "function",
                    "function": {"name": "inspect_contract", "arguments": "{}"},
                }],
            }, {}
        return {"role": "assistant", "content": json.dumps({
            "action": "review",
            "reason": "The write may have committed and no valid confirmation is available.",
            "safe_to_repeat_automatically": False,
        })}, {}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(".rebound/typed-example"))
    parser.add_argument("--model", default="", help="Explicitly enable a real model endpoint")
    parser.add_argument("--base-url", default="https://api.openai.com/v1")
    parser.add_argument("--resume", metavar="RUN_ID")
    args = parser.parse_args()
    tools = [Tool(
        "inspect_contract", ToolKind.READ_ONLY, inspect_contract,
        description="Inspect the tool contract and evidence for this example operation.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    )]
    model = ChatModel(args.model, args.base_url) if args.model else OfflineExampleModel()
    runner = AgentRunner(
        Store(args.data / "journal.sqlite"), tools, model,
        max_turns=5, output_model=RecoverySummary,
    )
    snapshot = await runner.run(
        "Inspect the tool contract. The write timed out; explain the next permitted action.",
        run_id=args.resume,
    )
    print(json.dumps({
        "mode": "real model" if args.model else "offline scripted fixture",
        "run_id": snapshot["id"],
        "status": snapshot["status"],
        "validated_output": snapshot["metadata"].get("structured_output"),
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
