# Project walkthrough

Use this guide to explain the implementation and its evidence. Replace broad claims with the specific behavior and measurements in the current repository.

## A two-minute explanation

> Rebound is a local agent harness focused on recovery after uncertain tool outcomes. If a remote operation commits but its acknowledgment is lost, a checkpoint cannot determine whether repeating it is safe. The runtime persists an operation ID and dispatch intent, then checks tool contracts and structured evidence before deciding to reuse a result, retry, or ask for review. A fault laboratory records external effects independently and measures both recovery success and duplicate or missing operations.

The core engineering problem is the boundary between a local transaction and a remote side effect. The research question is whether evidence-validity checks improve the safety/completion tradeoff under degraded observations.

## Demonstration sequence

1. Run `rebound demo --scenario lost_ack --policy evidence --steps 8 --data .rebound`.
2. Open the inspector with `rebound serve --data .rebound --port 8787`.
3. Find the uncertain operation, the observation used to confirm it, and the decision to continue.
4. Run the same scenario using an experimental baseline and inspect the effect metrics.
5. Show `unavailable` or `stale_evidence` to explain when automatic recovery stops.
6. Open the raw benchmark records and explain which component can read the ground truth.

The demo uses a simulated provider. Say that explicitly. A separate model run demonstrates model integration; it does not turn the scripted benchmark into an LLM evaluation.

## Questions worth being able to answer

### Why are checkpoints insufficient?

They persist the application's knowledge, not necessarily the remote world's state. The remote write and local commit cannot generally be atomic. A saved step number therefore does not prove that a write was or was not performed.

### Why not retry on “not found”?

The query may lag, or the original request may remain in flight. Both the original and retried operation can subsequently commit. Rebound requires provider idempotency for automatic repeated writes after uncertainty; negative evidence alone does not establish that guarantee.

### How is idempotency different from deduplication in your journal?

The journal prevents re-executing an operation whose success was durably recorded. Provider-side deduplication handles the gap where the provider committed but the local journal did not. A stable ID is necessary for that provider behavior but does not implement it by itself.

### What makes the evidence contract useful?

It specifies which operation is being confirmed, whether the source can authoritatively confirm it, and whether the observation is valid now. The policy can reject a stale or unrelated confirmation deterministically and record the reason.

### Why SQLite?

The initial goal is a reproducible single-machine experiment. SQLite removes service setup and gives transactional local state. Distributed ownership and remote failover are different design problems and are documented as extensions.

### How do you avoid unfair benchmark comparisons?

Give policies the same tasks, tool capabilities, fault schedule, and query budget. Let only the evaluator inspect hidden effect state. Report actual triggered faults, baseline configurations, and all outcome dimensions. A framework baseline tests a particular configuration, not every application that could be built on that framework.

### Is stopping for review a success?

It may be a safe decision, but it is not autonomous task completion. Review and missing-effect rates must be reported beside duplicate effects. Improving one metric by stopping everything is not a useful recovery system.

### What is original here?

The contribution is a concrete evidence contract, an implementation enforcing it, an evidence-quality experiment, and inspectable recovery decisions. Checkpoints, ledgers, idempotency, and fault injection are established ideas. Closely related projects are acknowledged in [related-work.md](related-work.md).

### What would you build next?

A real provider adapter with tested idempotency retention and probe semantics, then model-driven tasks with longer dependencies. Add distributed workers only after defining ownership, leases, and fencing.

## For a research statement

Describe the problem, state the hypothesis, explain the observation model, and report the current experiment's actual measurements and limitations. Distinguish runtime correctness from an agent's planning competence. Do not describe synthetic results as a deployment study or claim a novel algorithm without further related-work analysis.

A concise, defensible description is:

> Developed a durable agent harness and a controlled evaluation of recovery under uncertain external effects, using explicit evidence validity rules and independently checked effect histories.

Add numeric results only when they point to a committed artifact with the same configuration and sample size.

## For an engineering discussion

Be ready to walk through `models.py`, `store.py`, and `runtime.py`, then trace one failure test. Explain where the transaction begins and ends, how the operation ID is derived and preserved, what happens on cancellation, how review is represented, and what the API exposes.

The strongest demonstration is changing one assumption—such as fresh evidence becoming stale—and predicting the resulting state transition before running it.
