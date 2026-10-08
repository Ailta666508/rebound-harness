# Contributing

Start with the [recovery contract](docs/recovery-contract.md) and
[experiment protocol](docs/experiments.md). Changes to recovery behavior need a
failure-mode test with an independent effect oracle. Do not classify a tool as
idempotent merely because the runtime assigns an operation ID.

```sh
pip install -r requirements-dev.lock
pip install --no-deps -e '.[dev,benchmark,mcp]'
ruff check src tests examples
mypy src/rebound
pytest -q
```

Build the inspector using Node 24 and pnpm 11.25.0:

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm build
```

Use small focused changes, explain guarantees and assumptions, and attach the
relevant test output. Benchmark changes must preserve raw results and report
changed source hashes. Never compare policies using different hidden information.

The repository maintainer is **Ailta666508**.
