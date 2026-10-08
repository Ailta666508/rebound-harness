# Limitations and roadmap

Rebound is a single-machine reference implementation and experiment platform. Its strongest claims concern the recovery decisions it makes under declared contracts and injected failures.

## External effects are not atomic with the journal

SQLite cannot participate in a transaction with every tool provider. A process can exit after a provider commits an effect but before the runtime records success. Rebound represents and reconciles that uncertainty; it cannot remove the distributed-systems boundary.

The default policy's refusal to blindly repeat uncertain non-idempotent writes reduces one cause of duplicate effects. It cannot prevent a provider from duplicating a request internally or returning false evidence.

## Tool declarations are trusted contracts

An adapter that incorrectly marks a tool idempotent can make retries unsafe. Evidence authority is an adapter claim, not a cryptographic proof of a remote service's truthfulness. Deduplication expiration, service resets, permissions, and cache semantics must be tested for each integration.

Evidence is associated with an operation and a time interval. General dependency invalidation and resource-version reconciliation are not implemented by that schema. Clock discontinuities can affect freshness checks.

## Conservative recovery can reduce completion

An unavailable probe or an opaque operation can require manual review. A clean safety metric with a high review or missing-effect rate is not evidence of useful autonomous recovery. Reports should show the entire tradeoff.

Manual reconciliation accepts an operator's explicit assertion. It records provenance but cannot independently prove an inaccessible remote state.

## Persistence has a deployment boundary

Local SQLite survives supported process restarts. It is not replicated storage and does not promise recovery from disk loss, corruption, or arbitrary schema changes. Backups, migration discipline, and operational monitoring remain the deployer's responsibility.

The prototype is not a distributed scheduler. Do not infer multi-host leadership, lease fencing, worker failover, or tenant isolation from the presence of a durable journal.

## Evaluation is bounded

Scripted trials use controlled tasks and simulated provider behavior. They isolate recovery decisions and make failures reproducible, but they do not measure open-ended task quality, realistic production fault frequency, provider availability, or an LLM's general reasoning ability.

Repeated seeds in a synthetic suite may differ only in a small number of dimensions. Trial count is not the same as independent real-world coverage. Results apply to the committed workload generator and scenario definitions.

Framework comparisons measure the specific documented adapter configuration. LangGraph and other systems allow application authors to add tool-specific reconciliation; a baseline without such a policy is not an upper bound on that framework's capabilities.

## Security and execution

The local inspector assumes a trusted operator and is not a public service. Tool inputs, outputs, and operator notes can contain sensitive information. API credentials are read from configuration rather than intentionally written to the run journal, but an arbitrary tool can still return secrets in its result; adapters must avoid doing so.

A path restriction is not an operating-system sandbox. A Docker container is only as isolated as its mounts, privileges, network access, and runtime configuration. Shell execution cannot gain transactional semantics from journaling alone.

## Roadmap

| Direction | Evidence needed before calling it complete |
| --- | --- |
| Production provider adapters | Contract tests against actual idempotency and query semantics |
| Fenced retry protocol | Provider-enforced cancellation or version checks preventing races |
| Model-driven recovery study | Declared models, prompts, token budgets, repeated runs, and raw traces |
| Long-horizon task suite | Workload dependencies and fault schedules beyond repeated independent operations |
| Distributed workers | Ownership, leases, fencing, and overlapping-worker tests |
| Rich dependency evidence | Resource versions, invalidation rules, and cross-operation dependency tests |
| Public deployment | Authentication, authorization, secret handling, and operational hardening |
