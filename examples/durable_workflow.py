"""Run a durable read-only workflow, optionally interrupt it at an explicit boundary.

    python examples/durable_workflow.py
    python examples/durable_workflow.py --crash-after 2
    python examples/durable_workflow.py --resume RUN_ID

The crash option exits with code 73 after a tool returns but before its result
commits. Copy the printed run ID and resume with the same data directory.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

from rebound import Runtime, Step, Store, Tool, ToolKind
from rebound.verification import verify_snapshot


async def calculate(_operation_id: str, arguments: dict) -> dict:
    values = arguments["values"]
    return {"count": len(values), "sum": sum(values)}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(".rebound/durable-example"))
    parser.add_argument("--resume", metavar="RUN_ID")
    parser.add_argument("--crash-after", type=int, default=0, metavar="N")
    args = parser.parse_args()
    if args.crash_after < 0:
        parser.error("--crash-after must be nonnegative")

    store = Store(args.data / "journal.sqlite")
    run_id = args.resume or store.create_run(
        [
            Step(key=f"batch-{index}", tool="calculate", arguments={"values": list(range(index, index + 4))})
            for index in range(4)
        ],
        title="Read-only batch calculation",
    )
    print(f"Run ID: {run_id}", flush=True)
    print(f"Resume: python examples/durable_workflow.py --data {args.data} --resume {run_id}", flush=True)
    returned = 0

    def interrupt(point: str, _operation_id: str) -> None:
        nonlocal returned
        if point == "after_effect":
            returned += 1
            if args.crash_after and returned == args.crash_after:
                print("Explicit crash requested: result not yet committed (exit 73).", flush=True)
                os._exit(73)

    runtime = Runtime(
        store,
        [Tool("calculate", ToolKind.READ_ONLY, calculate)],
        fault_hook=interrupt,
    )
    snapshot = await runtime.run(run_id)
    print(json.dumps({
        "run_id": run_id,
        "status": snapshot["status"],
        "results": [operation["result"] for operation in snapshot["operations"]],
        "verification": verify_snapshot(snapshot),
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
