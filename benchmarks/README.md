# Benchmark artifacts

The reference experiment lives in [`reference/`](reference/) after the recorded
suite has run. Read [`../docs/experiments.md`](../docs/experiments.md) for the
protocol, policy definitions, and limitations before interpreting any chart.

The committed JSONL/CSV rows are observations from actual local runs. They are
scripted harness experiments, not synthetic claims about real model performance.
The provider performs real HTTP requests, SQLite writes, file output, and trusted
Python subprocess builds. There are no LLM calls or fabricated token costs.

Reproduce the reference protocol:

```python
from pathlib import Path
from rebound.benchmark import run_suite

run_suite(Path("benchmarks/reproduced"), seeds=2, lengths=[4, 16, 32])
```

Install `pip install -e '.[benchmark]'` first to include the real LangGraph
comparator and chart generation. The full matrix contains 882 cases and 756
injected connection drops. Every case has its own provider state and harness
journal. Generated `state/` directories remain local and are ignored by Git.
For a short smoke experiment, use one family, one seed, and `lengths=[2]`.

The exact configuration, installed versions, source hashes, aggregate results,
and reproduction command are recorded in each `summary.json`; a report's own
configuration is authoritative if it differs from the example above.
