# Rebound v0.1 implementation contract

This document fixes the interfaces used by the implementation. Public scope: a
single-machine Python agent harness with a durable SQLite journal and explicit
external-effect uncertainty. It is not a distributed scheduler or a universal
exactly-once guarantee.

## Modules and interfaces

- `rebound.models`: Pydantic `Step(tool: str, arguments: dict, key: str)`;
  `Evidence(operation_id: str, status: committed|absent|pending|unknown,
  result: dict|None, authoritative: bool=False, observed_at: float,
  valid_until: float, source: str, final: bool=False)`;
  `ToolKind`: read_only, idempotent, reconcilable, opaque.
- `rebound.tools`: `Tool(name, kind, execute, probe=None, description='',
  parameters=None)`. Async execute signature `(operation_id: str, arguments:
  dict) -> dict`. Async probe signature `(operation_id: str) -> Evidence`.
  Provider adapters must not overstate idempotency, final absence or freshness.
- `rebound.store`: `Store(path)`, `create_run(steps, title='...') -> str`,
  `list_runs() -> list[dict]`, `snapshot(run_id) -> dict` with fields
  `id,title,status,created_at,updated_at,steps,operations,events`.
  Operations include `id,step_key,tool,arguments,status,result,attempts`.
  Events include `seq,kind,operation_id,payload,created_at`.
- `rebound.runtime`: `Runtime(store, tools: list[Tool], policy='evidence',
  max_attempts=3, probe_budget=3, probe_delay=0.01, tool_timeout=10,
  evidence_ttl=30, fault_hook=None)`;
  `await run(run_id) -> dict` (snapshot). `fault_hook(point, operation_id)`
  is synchronous, called at before_dispatch / after_effect / after_commit.
  Policies: evidence, naive, checkpoint, idempotent, verify, no_freshness.
  `await resolve(run_id, operation_id, result: dict, note: str) -> dict`
  records manual reconciliation; never invents confirmation automatically.
- `rebound.demo`: `DemoService(data_dir)`; synchronous `list_runs()`,
  `snapshot(run_id)`; async `create_demo(scenario='lost_ack', policy='evidence',
  steps=8) -> dict`, `resume(run_id) -> dict`, `resolve(...) -> dict`.
  Scenarios: clean, lost_ack, delayed_visibility, unavailable, stale_evidence.
  A demo uses a separate provider SQLite database and is explicitly simulated.
- `rebound.benchmark`: CLI calls `run_suite(output: Path, seeds: int=5,
  lengths: list[int]|None=None) -> dict`. Output summary.json/results.jsonl and
  reports, including effect counts, review rates, and configuration metadata.
- `rebound.api`: `create_app(data_dir: Path) -> FastAPI`. API under `/api`:
  GET /health, GET /runs, GET /runs/{id}, POST /demo
  `{scenario,policy,steps}`, POST /runs/{id}/resume,
  GET /runs/{id}/events (SSE finite snapshot stream or documented polling).
  Optional POST manual-resolution with explicit result and note.
- `rebound.cli`: `rebound demo`, `runs`, `inspect ID`, `resume ID`,
  `benchmark`, `serve`, `agent`, `verify ID`. Exact flags in README after CLI.

## Recovery invariants

Persist dispatch intent before external I/O. A process interrupted while an
operation is dispatched leaves UNKNOWN, not proven failure. Reuse durable
success. Stable logical ID across retries, distinct ID for a new user intent.
Accept committed evidence only if it matches operation ID, is authoritative,
fresh and contains a result. Negative evidence from an eventually consistent
read never justifies repeating a non-idempotent write. V0.1 only automatically
retries read-only/provider-idempotent tools; non-idempotent missing evidence
waits within probe budget then needs_review. This avoids the check-then-act race.
Probe failures and budget exhaustion are recorded. Recovery decisions carry
evidence and reasons. Tool/model credentials are never stored in the journal.

## Evaluation discipline

Use separate provider effect state as oracle. Policies see only execute/probe,
never hidden oracle tables or injected fault labels. Compare common tool
capabilities, same workload and fault schedule. Report completion and duplicate
and missing effects plus review rate and probe cost. Count triggered faults.
Synthetic scripted experiments are not LLM performance claims. Add an actual
LangGraph persistent baseline adapter, and label omissions/limits honestly.
Separate recorded replay from live resume. Keep raw results, seed, version and
environment metadata. Compare evidence freshness ablation explicitly.

## Attribution

Maintainer: Ailta666508. Related work credits upstream projects and the ideas
they informed. Rebound is an independent implementation under Apache-2.0.
