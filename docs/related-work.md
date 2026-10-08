# Related work and positioning

First research pass: **2026-10-08**. Sources below are upstream repositories and official documentation. Star counts are rounded GitHub page snapshots from that date, included to describe project reach rather than technical merit. This is a focused design survey, not an exhaustive literature review or an audit of every upstream implementation.

Rebound's subject is recovery when a tool's external effect is uncertain. Several projects already address parts of this problem. The project does not claim to invent checkpoints, tool ledgers, idempotency, fault injection, or verification before retry.

## Widely used foundations

| Project | Stars at review | Relevant design | What Rebound takes from the comparison |
| --- | ---: | --- | --- |
| [Pi](https://github.com/earendil-works/pi) | 113.3k | Extensible agent harness, separate model API and execution packages, durable runtime components | Keep the execution surface small and model adapters replaceable |
| [OpenHands](https://github.com/OpenHands/OpenHands) | 90.2k | Developer control interface for agents across local, remote, and cloud environments | Present actionable execution state and inspectable task history |
| [LangGraph](https://github.com/langchain-ai/langgraph) | 42.9k | Persistent graph execution and interrupt/resume mechanisms | Compare against a real persisted graph baseline; distinguish graph state from external-effect certainty |
| [Deep Agents](https://github.com/langchain-ai/deepagents) | 30.0k | Long-task harness with filesystem tools, context management, subagents, and human approval | Treat task context and execution governance as explicit harness responsibilities |
| [Temporal](https://github.com/temporalio/temporal) | 23.5k | Durable workflow execution and retry infrastructure | Preserve intent identity and reason carefully about retry-safe external actions |
| [Pydantic AI](https://github.com/pydantic/pydantic-ai) | 20.5k | Typed model/tool interfaces and structured outputs | Use typed contracts at the runtime boundary; Rebound's core does not require this framework |
| [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) | 8.3k | A compact coding-agent implementation organized for accessible experimentation | Keep the main loop readable and experiments independently reproducible |

These systems operate at different layers. Their star counts are not comparable measures of recovery correctness, and this table does not assert that a listed project lacks recovery capabilities.

## Initial architectural reference

[Agent Foundation](https://github.com/converge-ai-labs/agent-foundation) (153 stars at review) combines an agent library with a self-hosted platform, execution environments, and durable service operation. Its broad product architecture motivated a more narrowly scoped implementation here: a local recovery runtime paired with an explicit experiment protocol. Rebound is independently implemented rather than a fork of Agent Foundation.

## Closest reliability and evaluation projects

These projects are relevant regardless of popularity. Small repositories can contain directly overlapping ideas.

| Project | Existing work relevant to Rebound | Consequence for our claims |
| --- | --- | --- |
| [UndoBench](https://github.com/tradertanmay/undobench) | Recovery and side-effect safety evaluation, paired controls, effect-history oracles, and several retry/reconciliation baselines | Fault injection, duplicate-effect measurement, and verify-before-retry are prior art; cite this work explicitly |
| [Agent Reliability Lab](https://github.com/karthikrshet/agent-reliability) | Stateful tool-call evaluation and deterministic failure injection, including timeout after an effect | Losing a successful response is an established reliability test, not a new fault class |
| [CONTINUUM](https://github.com/Cyrax321/CONTINUUM) | Semantic checkpoints, environment revalidation, provenance, an action ledger, and explicit unknown-effect review | Evidence-aware recovery and uncertain action state already have close implementations |
| [AgentLedger](https://github.com/yaogdu/AgentLedger) | A reliability runtime with durable execution, tool ledger, evidence, recovery, and inspection | A ledger and trace viewer alone do not establish novelty; focus on a precisely specified observation experiment |

This survey is based on the linked upstream descriptions and documentation. It does not adopt upstream performance claims or establish the completeness of their guarantees.

## A narrower contribution

Rebound's engineering contribution is a small, runnable implementation of an evidence-validity recovery contract together with controlled observations, a separate effect oracle, and inspectable decisions.

The experimental question is:

> With the same tool capabilities and observation budget, how do identity, authority, and freshness checks change completion, duplicate effects, missing effects, and review under degraded observations?

The unit of analysis is a recovery decision under a specified tool contract. The freshness ablation removes one condition so its effect can be measured. The experiment must show the full tradeoff, including conservative stops, rather than claiming an advantage from duplicate counts alone.

This is an engineering and experimental hypothesis. Establishing a new research result would require a broader literature review, stronger workloads, additional evidence models, and experiments beyond the initial synthetic suite.

## Two important sources on semantics

[LangGraph's persistence documentation](https://docs.langchain.com/oss/python/langgraph/persistence) explains how checkpointed state supports execution continuity. In a comparison, a baseline must use the framework's persistence correctly. Application-level evidence checks can also be built on LangGraph; this repository evaluates its documented adapter configuration rather than asserting a framework-wide limitation.

[Temporal's discussion of idempotency](https://temporal.io/blog/idempotency-and-durable-execution) highlights why stable identity and provider-side behavior matter for durable effects. Rebound follows the same underlying constraint: a local record does not make a remote write transactional, and a check followed by a write can race with an earlier in-flight request.

## Attribution and reuse

The implementation and SVG illustrations in this repository are authored for Rebound Harness. References inform design and evaluation; links do not imply endorsement or affiliation. Original project authorship is attributed to [Ailta666508](https://github.com/Ailta666508).

Rebound uses third-party dependencies under their respective licenses. Any future source or dataset reuse must preserve the source project's required notices and artifact-specific license terms. In particular, code and benchmark data can have different licenses; a repository's top-level software license should not be assumed to cover every artifact.
