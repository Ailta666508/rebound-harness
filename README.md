<p align="center">
  <img src="docs/assets/banner.svg" alt="Rebound Harness — Recover with evidence" width="100%" />
</p>

<p align="center">
  <strong>A durable agent harness for the moment a tool times out and nobody knows what happened.</strong>
</p>
<p align="center">
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="docs/recovery-contract.md">Recovery contract</a> ·
  <a href="docs/experiments.md">Experiments</a> ·
  <a href="docs/related-work.md">Related work</a>
</p>
<p align="center">
  <a href="https://github.com/Ailta666508/rebound-harness/actions/workflows/ci.yml"><img alt="Verification workflow" src="https://github.com/Ailta666508/rebound-harness/actions/workflows/ci.yml/badge.svg" /></a>
  <img alt="Python 3.12+" src="https://img.shields.io/badge/Python-3.12%2B-356b99" />
  <img alt="Apache 2.0 license" src="https://img.shields.io/badge/license-Apache_2.0-5c6ac4" />
  <img alt="Local first" src="https://img.shields.io/badge/runtime-local_first-168978" />
</p>

## Why Rebound?

A ticket was created. The response was lost. Your agent restarts.

A checkpoint can tell it which result it recorded. It cannot, by itself, tell it whether the remote ticket exists. Retrying may create a duplicate; assuming success may silently skip work.

**Rebound makes that uncertainty an explicit state.** It journals the intent before dispatch, preserves the logical operation ID, checks evidence from the tool, and records why execution may continue, retry, or require review. A small fault-injection suite tests those decisions against a separate effect history.

Use it to study long-task recovery, build inspectable local agents, and test tool adapters before trusting their retry behavior.

## What is inside

| Component | What it does |
| --- | --- |
| **Durable harness** | Typed tools, persisted runs, operation journal, execution budgets, and recovery after interruption |
| **Evidence policy** | Checks operation identity, authority, freshness, and a usable result before accepting external confirmation |
| **Fault laboratory** | Lost acknowledgments, delayed visibility, unavailable probes, and stale evidence under shared workloads |
| **Inspector** | A local web interface for runs, operations, recovery decisions, and event history |
| **Evaluation artifacts** | Raw trial records and machine-readable summaries, including completion, duplicated effects, missing effects, and review cost |

This is a **single-machine research and engineering prototype**. It does not promise global exactly-once execution. Its safety depends on truthful tool contracts, durable storage, and the semantics of the external provider. See [limitations](docs/limitations.md).

## Quick start

Requires Python 3.12 or newer. The demo and scripted benchmark require no model key.

```bash
git clone https://github.com/Ailta666508/rebound-harness.git
cd rebound-harness
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,benchmark]'

rebound demo --scenario lost_ack --policy evidence --steps 8 --data .rebound
rebound runs --data .rebound
```

The demo executes a simulated external operation, loses its acknowledgment, and recovers using the provider's evidence. The simulated provider stores effects separately from the harness journal. This is an execution-recovery demonstration, not an LLM benchmark.

Use the run ID printed by the command:

```bash
rebound inspect RUN_ID --data .rebound
rebound verify RUN_ID --data .rebound
rebound resume RUN_ID --data .rebound
```

`inspect` reads the recorded run. `verify` checks the recorded trace. **`resume` is live execution and can invoke tools.** Inspecting or verifying a trace never replays external writes.

Build the inspector once when installing from a source checkout. Use Node.js 24 and pnpm 11.25.0:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
rebound serve --data .rebound --port 8787
```

Release wheels bundle the built inspector. The CLI and Python runtime do not require Node.js.

Open [localhost:8787](http://localhost:8787). For frontend development, see [architecture](docs/architecture.md#local-inspector).

## Inspect recovery decisions

![The running local inspector showing a recovered 12-step task, three evidence probes, and zero duplicate effects](docs/assets/inspector.png)

Actual Chromium screenshot from the end-to-end test: the simulated provider hides a committed operation for two reads before exposing its receipt. The inspector reads persisted data. [Mobile screenshot](docs/assets/inspector-mobile.png) · [Browser test](frontend/e2e/smoke.mjs).

## The recovery boundary

![Rebound architecture: agent or workflow, durable runtime, journal, tools, evidence, and independent evaluator](docs/assets/architecture.svg)

Every logical operation keeps its identity across retries. The runtime records dispatch intent before calling a tool, then commits the result with an event. A crash between the remote effect and that local commit leaves an uncertain operation.

| Tool contract | After an uncertain attempt |
| --- | --- |
| `read_only` | May retry within the attempt budget |
| `idempotent` | May retry with the same operation ID, relying on provider-side deduplication |
| `reconcilable` | Probe for valid committed evidence; otherwise wait within the probe budget, then request review |
| `opaque` | Cannot prove the outcome automatically; request review |

**A negative query is not a retry permit.** The original write may still be in flight, or the query may lag behind it. The default policy does not automatically repeat an uncertain non-idempotent write—even if a probe says “absent.”

![Recovery decisions: reuse a result, validate evidence, retry by contract, or request review](docs/assets/recovery.svg)

See the [recovery contract](docs/recovery-contract.md) for the assumptions and [architecture](docs/architecture.md) for the implementation boundaries.

## Use the Python runtime

```python
import asyncio
from pathlib import Path

from rebound.models import Step, ToolKind
from rebound.runtime import Runtime
from rebound.store import Store
from rebound.tools import Tool

async def count_words(operation_id: str, arguments: dict) -> dict:
    return {"words": len(arguments["text"].split())}

async def main() -> None:
    store = Store(Path("example.sqlite"))
    run_id = store.create_run(
        [Step(key="count", tool="count_words", arguments={"text": "recover with evidence"})],
        title="A small durable workflow",
    )
    runtime = Runtime(store, [Tool("count_words", ToolKind.READ_ONLY, count_words)])
    print(await runtime.run(run_id))

asyncio.run(main())
```

Runnable examples: [`durable_workflow.py`](examples/durable_workflow.py) demonstrates explicit process interruption and resume; [`typed_agent.py`](examples/typed_agent.py) demonstrates a Pydantic final answer with a default offline fixture.

```bash
python examples/durable_workflow.py
python examples/typed_agent.py
```

For effectful integrations, implement the provider's `execute` and optional `probe` contract. Setting `idempotent` is a claim about the provider; merely generating an ID does not make a tool idempotent.

## Connect a model

The model adapter accepts an OpenAI-compatible chat endpoint. Tool plans and final answers are persisted across restarts; an optional Pydantic `output_model` validates the final JSON. Context trimming preserves complete assistant/tool groups, and an oversized latest group pauses for review rather than silently discarding the newest result. Configure a key in your shell or secret manager; keep it out of committed files.

```bash
export REBOUND_API_KEY='your-provider-key'
rebound agent 'Write a short note explaining safe retries' \
  --model YOUR_MODEL \
  --base-url https://YOUR_PROVIDER/v1
```

Use `rebound agent --help` for execution limits and options. Provider support depends on the endpoint implementing the required tool-call format. Model-driven runs and deterministic recovery experiments are separate: the benchmark does not establish a model's planning quality.

## Reproduce the experiments

```bash
rebound benchmark --output benchmarks/results --seeds 5
```

The suite compares basic retry, persisted checkpoints, provider-idempotent retry, verify-before-retry, the evidence policy, and a freshness ablation. A real LangGraph adapter implements the same conservative evidence policy on persistent `StateGraph` nodes as a portability comparator. Matching outcomes are expected; this is not a claim of superiority over LangGraph.

Read [the experiment protocol](docs/experiments.md) before interpreting results. A useful recovery policy must balance **task completion, duplicate effects, missing effects, review rate, and probe cost**. Stopping every task is not a successful recovery strategy.

The committed [benchmark artifacts](benchmarks/) contain actual measured results and their provenance. The reference matrix uses 2 seeds and 4, 16, and 32 effects per task; CLI defaults use 4, 12, and 24. The provider runs in a separate process behind loopback HTTP; its tasks remain controlled fixtures. An expired receipt tests policy compliance and liveness cost, not proof of better external safety. These experiments cover a bounded set of execution failures; these results are not production availability estimates or a real-model leaderboard.

### Measured reference results

The committed run contains **882 scripted trials and 756 triggered faults**, with 126 trials per policy: 3 workload families × 7 conditions × 3 horizons × 2 seeds. It makes **zero LLM calls**. These are controlled HTTP fixture results, not production reliability estimates.

| Policy | Correct completion | Needs review | Duplicate effects | Expired receipts accepted |
| --- | ---: | ---: | ---: | ---: |
| Rebound `evidence` | 57.1% | 42.9% | 0 | 0 |
| `langgraph_evidence` | 57.1% | 42.9% | 0 | 0 |
| `naive` | 42.9% | 0.0% | 72 | 0 |
| `no_freshness` | 71.4% | 28.6% | 0 | 18 |

“Correct completion” requires every expected effect exactly once, as checked by the independent oracle. Naive retry **reported 100% completion**, but only 42.9% passed that check. Rebound and the equivalent LangGraph policy matched; their review outcomes remain incomplete work.

The freshness ablation completed more tasks by accepting 18 expired receipts. Those fixtures retained the committed effects, so the result shows a **policy-compliance/liveness tradeoff, not an external-correctness benefit from enforcing freshness**. Read the [full report](benchmarks/reference/report.md), [raw trials](benchmarks/reference/results.jsonl), and [configuration and provenance](benchmarks/reference/summary.json) for all seven policies.

![Measured correct completion, review, and duplicate effects in the scripted reference suite](benchmarks/reference/recovery-results.svg)

## What this project contributes

Rebound combines three inspectable pieces:

1. **An explicit evidence contract.** Recovery depends on the operation being confirmed, the source's authority, and the evidence's validity interval.
2. **An evidence-quality experiment.** Workloads change what the policy can observe while the evaluator retains a separate ground truth.
3. **A recovery trace.** Decisions preserve their reason and observed evidence so they can be reviewed without invoking tools again.

Durable execution, tool ledgers, verification before retry, and fault injection have substantial prior art. The research hypothesis is that explicitly validating evidence can improve the safety/completion tradeoff under degraded observations. It is a hypothesis tested in this implementation, not a claim that these ideas are new. [Related work](docs/related-work.md) discusses the closest projects.

## Project map

```text
src/rebound/          runtime, journal, tools, CLI, API, model adapter
src/rebound/baselines/ framework baseline adapters
frontend/            React + TypeScript local inspector
tests/               recovery, storage, API, and evaluation checks
benchmarks/          experiment outputs and provenance
docs/                contracts, design, protocol, related work, limitations
```

## Development

```bash
pip install -e '.[dev,benchmark]'
pytest
ruff check .
```

Tests include cases where the tool's external effect and the runtime's recorded result disagree. The critical assertions concern observable outcomes, state transitions, and decision evidence.

Useful reading:

- [Architecture and design choices](docs/architecture.md)
- [Recovery semantics and invariants](docs/recovery-contract.md)
- [Experiment protocol](docs/experiments.md)
- [Related work and research positioning](docs/related-work.md)
- [Limitations and extension roadmap](docs/limitations.md)
- [Optional MCP tool adapter](docs/mcp.md)
- [Project walkthrough and discussion guide](docs/interview-guide.md)

## License and author

Apache-2.0. Created and maintained by [Ailta666508](https://github.com/Ailta666508). Upstream projects are credited in [related work](docs/related-work.md). Bundled frontend dependencies retain their [third-party license notices](THIRD_PARTY_NOTICES.md).
