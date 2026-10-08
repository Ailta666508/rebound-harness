# Recovery experiments

Rebound's benchmark measures scripted tool execution under transport ambiguity.
It makes **zero model calls**. It is a harness evaluation, not a claim about LLM
reasoning, SWE-bench performance, or a new state-of-the-art recovery algorithm.

## Question and boundaries

Given the same workload, external tool capabilities, fault position, retry limit,
and maximum probe budget, how do policies trade off correct completion,
duplicate external effects, and requests for human review?

A provider runs in a separate OS process behind real loopback HTTP. Its state
is stored independently from the harness journal. A fault closes the TCP
connection without sending a response, either after the provider commits an
effect or before it starts. The harness sees a transport error; it cannot inspect
the injected fault label or the evaluator's effect oracle.

Only the evaluator reads the oracle **after** a run. This is separation of
interfaces and processes, not a security boundary against malicious Python code.
The fixture does not simulate provider disk loss, Byzantine evidence,
unbounded concurrency, provider process crashes, or actual network latency.

## Workload families

| Family | Real executed work | Independent result check |
|---|---|---|
| `data_artifact` | Append computed records to a JSONL export | Read physical export records, including duplicate and missing indices |
| `http_ticket` | Create ticket rows through the HTTP service | Inspect provider-owned SQLite ticket rows |
| `code_build` | Generate and execute trusted Python fixture programs in child processes | Read generated build output files and validate values |

Each expected step has an index and an independently known expected value.
Repeated effects create distinct physical outputs except where the provider
explicitly supports operation-ID deduplication. Tool interfaces are the same
across policies. Code fixtures are actual subprocesses, **not a Docker sandbox**,
and do not represent realistic repository repair tasks. Every input program is
project-owned trusted fixture code.

Python API default horizons are 4 and 12 external effects; the CLI defaults to
4, 12, and 24. Use `lengths=[4, 16, 32]` or a
larger list for horizon scaling. These are action counts, not context-window
lengths or hours of autonomous model work.

## Conditions

| Condition | Fault / observation | Expected interpretation |
|---|---|---|
| `clean` | No interruption | Matched control; all policies should complete |
| `lost_ack` | Effect commits; response connection is dropped | Reconcile from an operation-matched authoritative receipt |
| `delayed_visibility` | Effect commits; first two search reads return non-authoritative absence | Do not infer permission to repeat a write from search absence |
| `unavailable` | Effect commits; probes cannot determine its state | Preserve uncertainty and request review after budget exhaustion |
| `stale_evidence` | Effect commits; only an expired cached receipt is observable | Conservative policy pauses; freshness ablation accepts expired evidence |
| `no_effect_timeout` | Connection drops before the effect; later probe reports point-in-time absence | Safe policy still pauses because the read is not a fenced guarantee against an in-flight write |
| `idempotent_lost_ack` | Effect commits; response is lost; provider deduplicates by operation ID | Provider-guaranteed replay or a receipt can safely complete |

The stale-receipt fixture deliberately retains the original committed effect.
It tests adherence to a freshness requirement and its liveness cost. It **does
not** demonstrate that stale evidence caused a duplicate, a missing effect, or
that enforcing freshness always improves completion. Freshness is a conservative
trust rule whose usefulness depends on the actual provider's receipt semantics.
For a durable immutable receipt, a provider can legitimately offer a longer
validity window. The harness cannot prove a provider's declaration.

## Policies and comparator

| Policy | Configured behavior |
|---|---|
| `naive` | Retry an uncertain call regardless of tool contract |
| `checkpoint` | Reuse durable successes; pause an unresolved operation |
| `idempotent` | Retry only adapter-declared read-only or provider-idempotent operations |
| `verify` | Require valid positive evidence, but retry after one observed absence; intentionally weak single-read baseline |
| `no_freshness` | Rebound evidence policy with timestamp validity checks removed |
| `evidence` | Require identity-matched authoritative fresh positive evidence; otherwise respect safe replay contracts or pause |
| `langgraph_evidence` | The same conservative evidence policy implemented in real LangGraph `StateGraph` with on-disk `SqliteSaver` |

The LangGraph comparator uses separate intent, effect, and reconciliation nodes.
Successful receipts pass typed schema and expected-value validation. Error
dictionaries are not counted as successful tool results. After each run the
SQLite saver is closed, reopened, and its persisted terminal state is checked.
This benchmark does not kill the LangGraph runner halfway through a node; it
injects actual external HTTP reply loss and verifies disk persistence. Process
termination at harness execution boundaries is covered separately by core tests.

`langgraph_evidence` is a **policy portability comparator**. Matching outcomes
are expected. We do not manufacture an advantage over LangGraph by replaying
non-idempotent side effects against its recommended guidance. Frameworks do not
supply idempotency to external providers. See the primary documentation:
[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
and [Temporal idempotency](https://temporal.io/blog/idempotency-and-durable-execution).

All policies have a maximum of three execution attempts and three probe calls
per recovery episode. Policies may deliberately use fewer probes; `verify` can
retry after the first negative read. Fault position is selected by the same
integer seed for all policy/scenario pairs at a given horizon. Trial execution
order is deterministically shuffled using seed 508.

## Metrics

- **Completed**: the runtime declares completion.
- **Correct completion**: completed and the independent oracle finds exactly one
  valid effect for every expected index, with no missing or unexpected effects.
- **Duplicate effects**: extra physical outputs for an expected logical index.
- **Missing effects**: expected indices with no physical output, including later
  steps deliberately not executed after a pause.
- **Review rate**: fraction ending in `needs_review`. This is incomplete work,
  even if the uncertain final effect already happened.
- **Probe and tool calls**: external observations and execution attempts.
- **Expired receipts accepted**: recorded reuse decisions accepting a receipt
  past its validity window.
- **Elapsed time**: local end-to-end trial wall time, including journal and graph
  overhead. It is environment-dependent, not a production latency claim.
- **Triggered faults**: counted at the provider; the suite fails if a scheduled
  fault was not actually reached.

Every non-clean case is paired with a clean control for the same family,
horizon, seed, and policy. `paired.csv` reports changes in correct completion,
latency, probes, and duplicates. A pause can have a negative latency delta
because it performs less work; do not interpret that as faster recovery.
Wilson 95% intervals are included for sample proportions, but repeated seeded
scripted fixtures are not evidence of statistical superiority on real tasks.
There are no token costs: `llm_calls=0`, `llm_tokens=0`, and monetary model cost
is recorded as `null` rather than an invented dollar estimate.

## Run and inspect

```sh
pip install -e '.[benchmark]'
rebound benchmark --output benchmarks/local --seeds 2
```

For explicit horizons and a selected matrix:

```python
from pathlib import Path
from rebound.benchmark import run_suite

summary = run_suite(
    Path("benchmarks/local"),
    seeds=2,
    lengths=[4, 16, 32],
    families=["data_artifact", "http_ticket", "code_build"],
)
print(summary["by_policy"])
```

Outputs:

- `results.jsonl`, `results.csv`: one row per actual trial.
- `paired.csv`: fault/control comparisons when clean controls are included.
- `summary.json`: configuration, aggregate metrics, Python/dependency versions,
  source-file SHA-256 hashes, limitations, and an exact reproduction command.
- `report.md`, `recovery-results.svg`: readable measured results and chart.
- `state/`: provider databases, physical outputs, and per-trial harness or
  LangGraph SQLite journals. These are local debugging artifacts and ignored by
  Git to avoid committing bulky generated state.

If optional LangGraph dependencies are unavailable, the report records the
comparator as skipped. It never silently substitutes a mock implementation.
Running the HTTP fixture requires permission to bind a loopback port.

## Related evaluation work and contribution scope

[UndoBench](https://github.com/tradertanmay/undobench) already explores agent
recovery and side-effect safety. [Agent Reliability Lab](https://github.com/karthikrshet/agent-reliability)
also covers failures after side effects. Rebound's contribution is an inspectable
combination of explicit evidence validity rules, a durable operation journal,
paired independent-oracle fixtures, and a portable conservative comparator.
Checkpoints, idempotency keys, and injected failures themselves are established
techniques; this repository does not claim to have invented them.
