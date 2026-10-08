# Rebound recovery experiment

Actual scripted HTTP fixture results; no LLM calls.

Trials: **882**. Triggered faults: **756**.

| Policy | Correct completion | Review | Duplicate effects | Mean probes |
|---|---:|---:|---:|---:|
| evidence | 57.1% | 42.9% | 0 | 2.00 |
| naive | 42.9% | 0.0% | 72 | 0.00 |
| checkpoint | 14.3% | 85.7% | 0 | 0.00 |
| idempotent | 28.6% | 71.4% | 0 | 0.00 |
| verify | 57.1% | 28.6% | 18 | 1.43 |
| no_freshness | 71.4% | 28.6% | 0 | 1.71 |
| langgraph_evidence | 57.1% | 42.9% | 0 | 2.00 |

Correct completion requires a completed runtime and exactly one valid external effect per expected step.
Review is reported as incomplete, even when the last uncertain effect already happened.

## Reproduction

```sh
python -c "from pathlib import Path; from rebound.benchmark import run_suite; run_suite(Path('benchmarks/reproduced'), seeds=2, lengths=[4, 16, 32], families=['data_artifact', 'http_ticket', 'code_build'], scenarios=['clean', 'lost_ack', 'delayed_visibility', 'unavailable', 'stale_evidence', 'no_effect_timeout', 'idempotent_lost_ack'], policies=['evidence', 'naive', 'checkpoint', 'idempotent', 'verify', 'no_freshness', 'langgraph_evidence'])"
```

Raw trials: `results.jsonl` and `results.csv`. Paired clean deltas: `paired.csv`.
`summary.json` includes configuration, dependency versions and source SHA-256 hashes.

## Interpretation and limits

- Deterministic scripted tools; no claim about model intelligence or natural-language task success.
- Faults affect transport replies, not provider durability or remote provider crashes.
- Code-build fixtures run trusted local Python subprocesses, not an isolated Docker sandbox.
- Expired-receipt case has a real committed effect; freshness ablation measures policy adherence/liveness, not a demonstrated bad external effect.
- LangGraph comparator implements conservative evidence handling; this is policy portability, not a framework ranking.
- Wilson intervals describe this finite scripted sample; repeated deterministic seeds do not establish general-world statistical superiority.

![Measured recovery outcomes](recovery-results.svg)
