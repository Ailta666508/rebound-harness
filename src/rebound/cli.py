"""User-facing commands; expensive model calls are always explicit."""

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from rebound.demo import DemoService
from rebound.store import Store

app = typer.Typer(no_args_is_help=True, help="Rebound — recover with evidence.")
console = Console()


def show(snapshot):
    console.print(f"[bold]{snapshot['id']}[/bold]  {snapshot['status']}")
    console.print_json(data=snapshot.get("metrics", {"operations": len(snapshot["operations"])}))


@app.command()
def demo(scenario: str = "lost_ack", policy: str = "evidence", steps: int = 8, data: Path = Path(".rebound")):
    """Run an explicitly simulated, persistent lost-receipt demonstration."""
    show(asyncio.run(DemoService(data).create_demo(scenario, policy, steps)))


@app.command()
def runs(data: Path = Path(".rebound")):
    table = Table("Run", "Status", "Title")
    for run in DemoService(data).list_runs():
        table.add_row(run["id"], run["status"], run["title"])
    console.print(table)


@app.command()
def inspect(run_id: str, data: Path = Path(".rebound")):
    """Read the full recorded trace without performing external actions."""
    console.print_json(data=DemoService(data).snapshot(run_id))


@app.command()
def resume(run_id: str, data: Path = Path(".rebound")):
    """Resume a demo. Model sessions use agent --run-id with their adapter."""
    show(asyncio.run(DemoService(data).resume(run_id)))


@app.command()
def approve(run_id: str, operation_id: str, data: Path = Path(".rebound")):
    """Approve the exact persisted tool invocation, then explicitly resume."""
    Store(data / "journal.sqlite").approve(run_id, operation_id)
    console.print("Approved. Resume with the originating runner.")


@app.command()
def resolve(run_id: str, operation_id: str, result: str, note: str, data: Path = Path(".rebound")):
    """Reconcile a demo call using a human-verified JSON result and evidence note."""
    value = json.loads(result)
    if not isinstance(value, dict):
        raise typer.BadParameter("result must be a JSON object")
    show(asyncio.run(DemoService(data).resolve(run_id, operation_id, value, note)))


@app.command()
def verify(run_id: str, data: Path = Path(".rebound")):
    from rebound.verification import verify_snapshot
    result = verify_snapshot(Store(data / "journal.sqlite").snapshot(run_id))
    console.print_json(data=result)
    if not result["valid"]:
        raise typer.Exit(1)


@app.command()
def benchmark(output: Path = Path("benchmarks/local-results"), seeds: int = 5, lengths: str = "4,12,24"):
    """Run scripted fault trials; no LLM API key or hidden model charges."""
    from rebound.benchmark import run_suite
    if not 1 <= seeds <= 100:
        raise typer.BadParameter("seeds must be in 1..100")
    horizons = [int(value) for value in lengths.split(",")]
    if not horizons or any(not 1 <= n <= 200 for n in horizons):
        raise typer.BadParameter("lengths must be comma-separated values in 1..200")
    summary = run_suite(output, seeds=seeds, lengths=horizons)
    console.print_json(data=summary)


@app.command()
def serve(data: Path = Path(".rebound"), port: int = 8787):
    """Start the trusted-workstation inspector bound to loopback."""
    import uvicorn

    from rebound.api import create_app
    uvicorn.run(create_app(data), host="127.0.0.1", port=port)


@app.command()
def agent(prompt: str = "", model: str = "", base_url: str = "https://api.openai.com/v1", data: Path = Path(".rebound"), workspace: Path = Path("workspace"), run_id: str | None = None, max_turns: int = 20):
    """Run a real model-driven file agent. Set REBOUND_API_KEY if required."""
    from rebound.agent import AgentRunner, ChatModel
    from rebound.tools import workspace_tools
    if not model:
        raise typer.BadParameter("--model is required; choose an available model at your endpoint")
    runner = AgentRunner(Store(data / "journal.sqlite"), workspace_tools(workspace), ChatModel(model, base_url), max_turns=max_turns)
    result = asyncio.run(runner.run(prompt, run_id))
    show(result)
    if result["metadata"].get("answer"):
        console.print(result["metadata"]["answer"])


if __name__ == "__main__":
    app()
