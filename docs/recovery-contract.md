# Recovery contract

Rebound's default `evidence` policy treats an interrupted external operation as uncertain until it can reuse a durable result, verify a committed effect, or rely on an explicitly retry-safe tool contract.

This document describes a conditional runtime guarantee. It is not a proof of global exactly-once delivery.

## Terms

- **Logical operation:** one intended use of a tool, identified by a stable operation ID. Retries keep that ID; a new intent receives a different ID.
- **Attempt:** one dispatch of the logical operation to its provider.
- **Effect:** an externally observable change, such as a created ticket.
- **Evidence:** a provider observation about an operation, with source, authority, observation time, expiry, status, and optional result.
- **Unknown outcome:** dispatch may have happened, but no durable success result is available to the runtime. A timeout or process exit does not prove that the provider rejected the request.

## Dispatch ordering

The runtime persists intent before external I/O. A successful response is recorded with the operation's result and corresponding event. Recovery reuses durable successes.

There is necessarily a window between an external write and the local result commit. Rebound cannot atomically commit a SQLite transaction and an arbitrary remote API mutation. It records that window explicitly and reconciles it using the provider contract.

| Interruption point | What the journal establishes | Default recovery |
| --- | --- | --- |
| Before persisted dispatch intent | The operation is still planned | Dispatch normally |
| After intent, before confirmed result | The attempt may have reached the provider | Treat the outcome as unknown |
| After provider effect, before local commit | The journal alone cannot prove success | Probe or use retry-safe provider semantics |
| After local result commit | A durable result exists | Reuse it and continue |

## Tool capabilities

| Kind | Required promise | Recovery action after uncertainty |
| --- | --- | --- |
| `read_only` | Repetition creates no effect that must be deduplicated | Retry within the attempt budget |
| `idempotent` | The provider deduplicates the same operation ID over the required recovery horizon | Retry with the same ID |
| `reconcilable` | A probe can return observations about the operation | Accept valid committed evidence; otherwise probe within budget and stop for review |
| `opaque` | No reliable automatic reconciliation is available | Stop for review |

The declaration belongs to the adapter. It must describe real provider semantics. Sending an `Idempotency-Key` header to an endpoint that ignores it does not establish idempotence. A provider with a short deduplication retention window may cease to satisfy the declaration for old runs.

## Accepting evidence

An observation of a committed operation is usable only when all required checks pass:

1. Its operation ID matches the uncertain logical operation.
2. Its source is declared authoritative for that confirmation.
3. Its observation and validity interval satisfy the runtime's freshness rules.
4. Its status is `committed` and it contains the usable result.

A policy records both accepted and rejected observations with the reason for its decision. A result from a different operation, stale evidence, a non-authoritative cache, or an observation without a result cannot silently certify success.

The current contract binds observations to an operation ID and time interval. It does not implement a general resource-version dependency graph. Freshness is evaluated with local time, so clock assumptions remain relevant.

## Why absence does not authorize another write

Suppose attempt A is delayed inside a provider. Probe B returns “not found.” The runtime retries as attempt C, then both A and C commit. Even a fresh read at B can be accurate at that moment and still fail to prove that A will never commit.

For this reason, the default policy does not automatically repeat uncertain non-idempotent operations on negative evidence. `absent`, `pending`, `unknown`, probe exceptions, and exhausted budgets lead to bounded waiting or `needs_review`. A stronger future adapter could expose a provider-enforced cancellation or fenced retry contract, but a boolean absence flag alone is insufficient.

## Cancellation boundary

Cancellation and new dispatch intent are arbitrated in a SQLite write transaction. Once a run is cancelled, appending steps or persisting a new dispatch is refused. A committed dispatch intent is the boundary: cancellation after that point cannot retract an in-flight external request. Its eventual result may still be recorded, while the run remains cancelled. Cancellation does not imply rollback of external effects.

## Human reconciliation

Manual resolution requires a concrete result and an explanatory note. This is an explicit external assertion by the operator and is recorded as such. The assertion event and confirmed operation result commit in one local transaction. It is not an automatic proof that the provider state is correct.

Before resolving a run, check the external system using its own operational tools. A manual decision should identify the relevant external object, describe what was checked, and preserve any useful reference. Rebound cannot validate facts that its adapters cannot observe.

## Budgets and progress

Attempt limits bound repeated dispatch. Probe budgets and delays bound reconciliation work. When the runtime cannot establish a safe next action within those limits, it preserves the uncertain operation and stops for review.

This is a deliberate availability tradeoff. The evaluation measures review and missing-effect rates alongside duplicate effects, so conservative stopping is visible rather than counted as successful completion.

## Scope of the guarantee

Under truthful adapters, valid evidence, durable local storage, and supported single-run execution ownership, the default policy:

- Reuses a recorded successful operation.
- Preserves a logical operation's identity across attempts.
- Does not treat an unknown outcome as proven failure.
- Does not automatically redispatch an uncertain non-idempotent write.
- Does not accept unrelated, non-authoritative, or expired evidence as confirmation.

It does not guarantee that an external provider executes only once, that evidence is truthful, that disk corruption is recoverable, or that every run completes automatically. It cannot make arbitrary shell commands transactional.

## Experimental policies

The CLI exposes comparison policies such as `naive`, `checkpoint`, `idempotent`, `verify`, and `no_freshness`. These intentionally differ in recovery semantics; some are expected to duplicate or miss effects under particular faults. The default safety statements above apply to `evidence`, not to every experimental policy.
