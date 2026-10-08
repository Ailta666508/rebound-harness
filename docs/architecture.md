# Architecture

Rebound separates three concerns: deciding what task to perform, deciding whether a tool may be dispatched, and checking whether the intended external effects actually occurred.

![Architecture](assets/architecture.svg)

## Runtime and journal

`models.py` defines typed steps, tool kinds, and evidence. `store.py` owns the SQLite journal and exposes snapshots of runs, operations, and events. `runtime.py` executes a persisted plan and applies the selected recovery policy.

SQLite WAL provides local transactional storage without a database service. Operation updates and their events belong in the same transaction. The journal is an execution record; external providers remain responsible for their own effects. Rebound deliberately avoids a database transaction held open across a network call.

A run contains ordered steps. Each logical step maps to a stable operation. An operation can have several attempts, but a successful result belongs to that logical operation. Recovery inspects persisted state before deciding whether another dispatch is appropriate.

An event records a transition or decision. A run snapshot presents current state alongside its history. Inspecting a snapshot is read-only; resuming a run can perform I/O.

## Tool boundary

`Tool` exposes an async `execute(operation_id, arguments)` function and, where supported, an async `probe(operation_id)` function. The adapter declares whether its tool is read-only, provider-idempotent, reconcilable, or opaque.

The runtime controls operation identity and policy; the adapter controls how those guarantees map to a real service. The provider owns the authoritative effect. A timeout crosses this trust boundary as uncertainty, not a fabricated failure result.

The contract makes adapters small enough to test independently. Test whether the same ID is truly deduplicated, whether probes distinguish pending from completed operations, how long confirmations remain valid, and what happens when the provider loses its own state.

## Planning and model calls

The model adapter accepts a compatible chat/tool-call endpoint. The model proposes actions through exposed tools; the runtime governs execution and records results. Deterministic workflow execution remains usable without model calls, which allows recovery experiments to isolate runtime behavior from planning variance.

Model tool plans and final answers are persisted before continuing. An optional Pydantic `output_model` validates the final JSON, and resuming requires the same output schema. Context trimming retains complete assistant/tool groups; if the newest group cannot fit, the session enters `needs_review` rather than discarding its newest observations.

The model is not the authority on whether an external write committed. Recovery rules use structured tool observations. A model explanation can help a human understand a run, but cannot turn missing evidence into a successful operation.

## Failure boundaries

The runtime exposes hooks at `before_dispatch`, `after_effect`, and `after_commit`. These support targeted tests at the boundary between local state and external I/O. Python exceptions and actual process termination cover different failure modes and should be reported separately.

The standalone demo stores simulated provider state in a separate SQLite database. The benchmark evaluator may inspect that state to compute outcomes. Recovery policies may only call the provider's public execution and probe interfaces.

This separation prevents the policy from using injected fault labels or hidden effect counts to decide how to recover. It also makes duplicate writes detectable even when a policy reports task completion.

## Recovery decisions

![Recovery decisions](assets/recovery.svg)

A valid durable result is reused. Otherwise the runtime assesses tool capabilities and available evidence. Safe-to-repeat tools may be retried within limits. Reconcilable effects require usable committed evidence; insufficient information eventually produces a review state.

See [recovery-contract.md](recovery-contract.md) for the exact assumptions and the check-then-act race that prevents negative queries from authorizing arbitrary retries.

## Local inspector

FastAPI exposes run lists, snapshots, demo creation, resume operations, and event records. The React/TypeScript interface presents the same persisted information as the CLI. The event endpoint is a finite snapshot stream; clients refresh to obtain later records rather than assuming an indefinitely connected subscription.

From a source checkout, build the inspector with Node.js 24 and pnpm 11.25.0 before starting the API. Release wheels include the built static assets:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
rebound serve --data .rebound --port 8787
```

To develop the frontend separately, use the scripts in `frontend/package.json`:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

The inspector is intended for trusted local use. It is not a multi-user control plane and does not provide deployment-grade authentication or tenant isolation. Keep the server bound to the local interface unless adding an appropriate access-control layer.

## Evaluation boundary

The evaluation package generates shared workloads and fault schedules, instantiates each policy, records its observations, and separately judges effect history. A real LangGraph comparator uses the framework's persistence interface and implements the same conservative policy, testing portability rather than claiming a framework advantage.

Outputs include trial data and summaries. The important comparison is multi-dimensional: completion, duplicates, missing effects, review, and cost. A conservative policy that stops every run must be distinguishable from one that actually recovers.

See [experiments.md](experiments.md) for scenarios, aggregation, uncertainty, and interpretation limits.

## Design decisions

| Decision | Reason | Cost |
| --- | --- | --- |
| SQLite first | Reproduce a full run on one machine with few dependencies | No distributed scheduling or database failover |
| Stable operation IDs | Preserve identity across uncertain attempts | Application and provider must agree on what counts as one intent |
| Structured evidence | Validate recovery rules deterministically | Evidence adapters require provider-specific work |
| Conservative non-idempotent retries | Avoid a check-then-act race | Some runs need review even when a retry might succeed |
| Separate effect oracle | Catch duplicate and missing writes independently | Synthetic providers do not establish production generality |
| Optional model access | Isolate execution semantics and avoid mandatory API costs | Scripted results do not measure reasoning quality |

## Extensions

The next useful extensions are provider-specific evidence adapters, tested idempotency retention contracts, model-driven recovery tasks, and richer workload dependencies. Distributed leases and fencing require a separate ownership design; they should precede multi-worker execution.
