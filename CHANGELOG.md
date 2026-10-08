# Changelog

## 0.1.0 — 2026-10-08

First public release of Rebound Harness.

- SQLite WAL journal with stable operation identity, persisted dispatch intent,
  crash recovery, budgets, permissions, and explicit manual reconciliation.
- Evidence contracts checking operation identity, authority, validity, and
  recorded results before accepting confirmation of uncertain effects.
- Model-driven tool loop with durable plans, context limits, and optional typed
  final output; conservative stdio MCP adapter and Docker execution tool.
- React inspector for persisted operations, recovery evidence, and JSON export.
- Seven-policy fault laboratory with paired controls, an independent effect
  oracle, a persistent LangGraph comparator, and raw results from 882 trials.
- Python 3.12/3.13, real Docker, and desktop/mobile Chromium checks in CI.
- English/Chinese guides, authored architecture diagrams, actual UI screenshots,
  runnable examples, and a related-work survey.

The reference experiments use scripted providers and make no model-quality or
production reliability claims. Recovery remains conditional on tool contracts;
the prototype does not guarantee global exactly-once effects.
