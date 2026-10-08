import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  Code2,
  FileJson,
  FlaskConical,
  GitBranch,
  Layers3,
  LoaderCircle,
  Play,
  Plus,
  Radio,
  RefreshCw,
  RotateCcw,
  SearchCheck,
  ShieldCheck,
  Terminal,
  X,
} from "lucide-react";
import {
  displayTime,
  isAttention,
  isDone,
  label,
  request,
  type Operation,
  type Run,
  type RunSummary,
  type TraceEvent,
} from "./types";

const scenarios = [
  {
    id: "lost_ack",
    name: "Lost acknowledgment",
    description:
      "The provider commits an action, then its response disappears.",
    tag: "Start here",
  },
  {
    id: "delayed_visibility",
    name: "Delayed visibility",
    description: "The action exists before a query can see it.",
    tag: "Consistency",
  },
  {
    id: "stale_evidence",
    name: "Stale evidence",
    description: "An expired observation challenges the recovery policy.",
    tag: "Freshness",
  },
  {
    id: "unavailable",
    name: "Unavailable evidence",
    description: "Recovery cannot establish what happened.",
    tag: "Review",
  },
  {
    id: "clean",
    name: "Clean execution",
    description: "A reference run without an injected interruption.",
    tag: "Reference",
  },
];

function Badge({ status }: { status: string }) {
  return (
    <span
      className={`badge ${isDone(status) ? "success" : isAttention(status) ? "attention" : "neutral"}`}
    >
      <span className="status-dot" />
      {label(status)}
    </span>
  );
}

function Dialog({
  children,
  onClose,
  title,
}: {
  children: ReactNode;
  onClose: () => void;
  title: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = ref.current;
    node?.showModal();
    return () => node?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      aria-label={title}
    >
      <div className="modal-heading">
        <div>
          <span className="eyebrow">LOCAL LABORATORY</span>
          <h2>{title}</h2>
        </div>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Close dialog"
        >
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}

function CreateDialog({
  onClose,
  onCreate,
  busy,
  error,
}: {
  onClose: () => void;
  onCreate: (scenario: string, policy: string, steps: number) => Promise<void>;
  busy: boolean;
  error: string;
}) {
  const [scenario, setScenario] = useState("lost_ack");
  const [policy, setPolicy] = useState("evidence");
  const [steps, setSteps] = useState(8);
  return (
    <Dialog title="Put recovery to the test." onClose={onClose}>
      <p className="modal-description">
        Choose an interruption. Rebound writes a real local journal against a
        simulated provider. No model key required.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void onCreate(scenario, policy, steps);
        }}
      >
        <fieldset className="scenario-list">
          <legend>Fault scenario</legend>
          {scenarios.map((item) => (
            <label
              className={`scenario ${scenario === item.id ? "selected" : ""}`}
              key={item.id}
            >
              <input
                type="radio"
                name="scenario"
                value={item.id}
                checked={scenario === item.id}
                onChange={() => setScenario(item.id)}
              />
              <div>
                <span className="scenario-name">
                  {item.name}
                  <small>{item.tag}</small>
                </span>
                <span className="scenario-description">{item.description}</span>
              </div>
            </label>
          ))}
        </fieldset>
        <div className="form-row">
          <label>
            Recovery policy
            <select
              value={policy}
              onChange={(event) => setPolicy(event.target.value)}
            >
              <option value="evidence">Evidence constrained</option>
              <option value="naive">Naive retry</option>
              <option value="checkpoint">Checkpoint only</option>
              <option value="idempotent">Idempotent only</option>
              <option value="verify">Verify before retry</option>
              <option value="no_freshness">Freshness ablation</option>
            </select>
          </label>
          <label>
            Task length
            <input
              type="number"
              min={1}
              max={100}
              value={steps}
              onChange={(event) => setSteps(Number(event.target.value))}
              required
            />
          </label>
        </div>
        {error ? (
          <p className="inline-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="modal-footer">
          <span>
            <FlaskConical size={15} /> Synthetic experiment
          </span>
          <button className="button primary" disabled={busy}>
            {busy ? (
              <LoaderCircle size={16} className="spinning" />
            ) : (
              <Play size={16} />
            )}
            Create run
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function ResolveDialog({
  operation,
  onClose,
  onResolve,
  busy,
}: {
  operation: Operation;
  onClose: () => void;
  onResolve: (result: Record<string, unknown>, note: string) => Promise<void>;
  busy: boolean;
}) {
  const [result, setResult] = useState("{}");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      const value: unknown = JSON.parse(result);
      if (typeof value !== "object" || value === null || Array.isArray(value))
        throw new Error("Enter a JSON object.");
      setError("");
      await onResolve(value as Record<string, unknown>, note);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Invalid result.");
    }
  }
  return (
    <Dialog title="Record a human confirmation." onClose={onClose}>
      <p className="modal-description">
        Confirm only after independently checking the provider. This records the
        result for <code>{operation.step_key}</code> and may allow the run to
        continue.
      </p>
      <form
        className="resolution-form"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <label>
          Confirmed result · JSON object
          <textarea
            value={result}
            onChange={(event) => setResult(event.target.value)}
            rows={5}
            spellCheck={false}
            required
          />
        </label>
        <label>
          How was this outcome verified?
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={3}
            minLength={8}
            maxLength={2000}
            placeholder="Describe your independent confirmation and its source."
            required
          />
        </label>
        {error ? (
          <p className="inline-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="modal-footer">
          <span>Saved to the durable audit trail</span>
          <button className="button primary" disabled={busy}>
            {busy ? (
              <LoaderCircle size={16} className="spinning" />
            ) : (
              <Check size={16} />
            )}
            Confirm result
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function Metric({
  value,
  title,
  detail,
  icon,
}: {
  value: ReactNode;
  title: string;
  detail: string;
  icon: ReactNode;
}) {
  return (
    <div className="metric">
      <span className="metric-title">
        {title}
        {icon}
      </span>
      <strong>{value}</strong>
      <span className="metric-detail">{detail}</span>
    </div>
  );
}

function EventDetail({
  event,
  operation,
}: {
  event: TraceEvent | null;
  operation: Operation | undefined;
}) {
  const payload = event?.payload ?? {};
  const evidence =
    typeof payload.evidence === "object" && payload.evidence !== null
      ? (payload.evidence as Record<string, unknown>)
      : event?.kind === "recovery.probe"
        ? payload
        : null;
  const reason = payload.reason ?? payload.message ?? payload.error;
  return (
    <section className="detail-panel">
      <div className="panel-title">
        <span className="eyebrow">INSPECT THE DECISION</span>
        <SearchCheck size={20} />
      </div>
      <h3>{event ? label(event.kind) : "Evidence comes first."}</h3>
      <p className="detail-intro">
        {reason
          ? String(reason)
          : event
            ? "The journal records the inputs and outcome behind this transition."
            : "Select a trace event to inspect its recorded evidence and operation."}
      </p>
      {event ? (
        <>
          <dl className="detail-facts">
            <div>
              <dt>Event sequence</dt>
              <dd>#{String(event.seq).padStart(3, "0")}</dd>
            </div>
            <div>
              <dt>Recorded at</dt>
              <dd>{displayTime(event.created_at)}</dd>
            </div>
            <div>
              <dt>Operation</dt>
              <dd title={event.operation_id ?? undefined}>
                {operation?.step_key ??
                  event.operation_id?.slice(0, 12) ??
                  "Run lifecycle"}
              </dd>
            </div>
            {operation ? (
              <div>
                <dt>Tool</dt>
                <dd>{operation.tool}</dd>
              </div>
            ) : null}
          </dl>
          {evidence ? (
            <div className="evidence-block">
              <div className="evidence-title">
                <ShieldCheck size={17} />
                Recorded evidence
              </div>
              <dl>
                {[
                  "status",
                  "source",
                  "authoritative",
                  "final",
                  "operation_id",
                ].map((key) =>
                  evidence[key] !== undefined ? (
                    <div key={key}>
                      <dt>{label(key)}</dt>
                      <dd>{String(evidence[key])}</dd>
                    </div>
                  ) : null,
                )}
              </dl>
            </div>
          ) : null}
          <details className="json-disclosure" open>
            <summary>
              <FileJson size={15} />
              Event payload
            </summary>
            <pre>{JSON.stringify(payload, null, 2)}</pre>
          </details>
          {operation?.result ? (
            <details className="json-disclosure">
              <summary>
                <Code2 size={15} />
                Recorded result
              </summary>
              <pre>{JSON.stringify(operation.result, null, 2)}</pre>
            </details>
          ) : null}
        </>
      ) : (
        <div className="evidence-placeholder">
          <SearchCheck size={36} strokeWidth={1.2} />
          <span>Observation → decision → action</span>
        </div>
      )}
      <div className="principle">
        <GitBranch size={18} />
        <p>An interruption is an unknown outcome. Recovery needs evidence.</p>
      </div>
    </section>
  );
}

export default function App() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [eventSeq, setEventSeq] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [resolving, setResolving] = useState<Operation | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [eventFilter, setEventFilter] = useState("all");
  const [tab, setTab] = useState<"trace" | "operations">("trace");
  const requestNumber = useRef(0);

  const refreshRuns = useCallback(async () => {
    const all = await request<RunSummary[]>("/api/runs");
    setRuns(all);
    return all;
  }, []);

  useEffect(() => {
    let disposed = false;
    request<RunSummary[]>("/api/runs")
      .then((all) => {
        if (disposed) return;
        setRuns(all);
        setSelectedId(all[0]?.id ?? null);
      })
      .catch((reason) => {
        if (!disposed) setError(String(reason.message));
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setRun(null);
      return;
    }
    const controller = new AbortController();
    const number = ++requestNumber.current;
    setLoading(true);
    setRun(null);
    setEventSeq(null);
    request<Run>(`/api/runs/${selectedId}`, { signal: controller.signal })
      .then((data) => {
        if (number === requestNumber.current) {
          setRun(data);
          setError("");
        }
      })
      .catch((reason) => {
        if (reason.name !== "AbortError") setError(String(reason.message));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [selectedId]);

  const active = run?.status === "running" || run?.status === "pending";
  useEffect(() => {
    if (!active || !selectedId) return;
    let disposed = false;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      request<Run>(`/api/runs/${selectedId}`, { signal: controller.signal })
        .then((data) => {
          if (!disposed) setRun(data);
        })
        .catch((reason) => {
          if (!disposed && reason.name !== "AbortError")
            setError(reason.message);
        });
    }, 3000);
    return () => {
      disposed = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [active, selectedId]);

  async function create(scenario: string, policy: string, steps: number) {
    setBusy(true);
    setError("");
    try {
      const data = await request<Run>("/api/demo", {
        method: "POST",
        body: JSON.stringify({ scenario, policy, steps }),
      });
      await refreshRuns();
      setSelectedId(data.id);
      setCreating(false);
      setTab("trace");
      setEventFilter("all");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not create run.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function resume() {
    if (!run) return;
    setBusy(true);
    setError("");
    try {
      const data = await request<Run>(`/api/runs/${run.id}/resume`, {
        method: "POST",
        body: "{}",
      });
      setRun(data);
      await refreshRuns();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not resume run.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function resolve(result: Record<string, unknown>, note: string) {
    if (!run || !resolving) return;
    setBusy(true);
    setError("");
    try {
      const data = await request<Run>(
        `/api/runs/${run.id}/operations/${resolving.id}/resolve`,
        { method: "POST", body: JSON.stringify({ result, note }) },
      );
      setRun(data);
      setResolving(null);
      await refreshRuns();
    } catch (reason) {
      throw reason;
    } finally {
      setBusy(false);
    }
  }

  function download() {
    if (!run) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(run, null, 2)], { type: "application/json" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `rebound-${run.id}.json`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const completed =
    run?.operations.filter((operation) => isDone(operation.status)).length ?? 0;
  const probes =
    run?.events.filter((event) => /probe|evidence/.test(event.kind)).length ??
    0;
  const selectedEvent =
    run?.events.find((event) => event.seq === eventSeq) ??
    [...(run?.events ?? [])]
      .reverse()
      .find((event) => /decision|evidence|recovery|probe/.test(event.kind)) ??
    run?.events.at(-1) ??
    null;
  const selectedOperation = run?.operations.find(
    (operation) => operation.id === selectedEvent?.operation_id,
  );
  const filteredEvents = (run?.events ?? []).filter(
    (event) =>
      eventFilter === "all" ||
      /decision|evidence|recovery|probe|unknown|fault|review|interrupt/.test(
        event.kind,
      ),
  );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="Rebound home">
          <span className="brand-mark">
            <RotateCcw size={26} strokeWidth={2.7} />
          </span>
          <div>
            rebound<span>HARNESS / 0.1</span>
          </div>
        </a>
        <div className="workspace">
          <span className="workspace-icon">
            <Terminal size={17} />
          </span>
          <div>
            Local workspace<small>Durable execution lab</small>
          </div>
          <span className="live-dot" />
        </div>
        <button
          className="new-run"
          disabled={busy}
          onClick={() => setCreating(true)}
        >
          <Plus size={17} />
          New experiment
        </button>
        <div className="sidebar-section">
          <span>RECENT RUNS</span>
          <span>{runs.length.toString().padStart(2, "0")}</span>
        </div>
        <nav className="run-list" aria-label="Runs">
          {runs.map((item) => (
            <button
              key={item.id}
              className={`run-item ${selectedId === item.id ? "active" : ""}`}
              onClick={() => {
                if (!busy) setSelectedId(item.id);
              }}
              disabled={busy}
            >
              <span
                className={`run-indicator ${isDone(item.status) ? "done" : isAttention(item.status) ? "waiting" : ""}`}
              />
              <span className="run-item-text">
                <strong>{item.title}</strong>
                <small>
                  {item.id.slice(0, 8)}
                  <span>·</span>
                  {label(item.status)}
                </small>
              </span>
              {selectedId === item.id ? <ChevronRight size={14} /> : null}
            </button>
          ))}
          {runs.length === 0 ? (
            <p className="empty-runs">
              Your experiments will appear here. Create a run to begin.
            </p>
          ) : null}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card">
            <ShieldCheck size={19} />
            <div>
              Local by design<span>Journal stored on your machine.</span>
            </div>
          </div>
          <a
            href="https://github.com/Ailta666508/rebound-harness"
            target="_blank"
            rel="noreferrer"
          >
            Source & documentation
            <ArrowRight size={14} />
          </a>
          <span className="sidebar-credit">BUILT TO RECOVER.</span>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <Layers3 size={17} />
            <span>Workspace</span>
            <ChevronRight size={14} />
            <strong>Recovery inspector</strong>
          </div>
          <span className="local-badge">
            <span className="live-dot" />
            LOCAL SESSION
          </span>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">EXECUTION OBSERVATORY</span>
              <h1>
                Recovery, with receipts<span>.</span>
              </h1>
              <p>See what happened. Understand why it is safe to continue.</p>
            </div>
            <div className="simulated-badge">
              <FlaskConical size={16} />
              <span>
                {!run || run.metadata.simulated
                  ? "Simulated provider"
                  : "Live tool run"}
                <small>Real execution journal</small>
              </span>
            </div>
          </div>
          {error ? (
            <div className="error-banner" role="alert">
              <CircleHelp size={18} />
              <span>{error}</span>
              <button onClick={() => setError("")} aria-label="Dismiss error">
                <X size={17} />
              </button>
            </div>
          ) : null}
          {loading ? (
            <div className="loading-state" role="status">
              <LoaderCircle className="spinning" size={24} />
              <span>Reading the journal…</span>
            </div>
          ) : run ? (
            <>
              <section className="run-header">
                <div>
                  <div className="run-overline">
                    <span>RUN / {run.id.slice(0, 8)}</span>
                    <Badge status={run.status} />
                  </div>
                  <h2>{run.title}</h2>
                  <p>
                    Created {new Date(run.created_at * 1000).toLocaleString()}
                    <span className="separator">/</span>
                    {run.steps.length} planned operations
                    <span className="separator">/</span>
                    {label(String(run.metadata.policy ?? "custom"))} policy
                  </p>
                </div>
                <div className="run-actions">
                  <button className="button secondary" onClick={download}>
                    <ArrowDownToLine size={16} />
                    Export trace
                  </button>
                  <button
                    className="button primary"
                    onClick={() => {
                      void resume();
                    }}
                    disabled={
                      busy || isDone(run.status) || run.metadata.mode !== "demo"
                    }
                  >
                    {busy ? (
                      <LoaderCircle size={16} className="spinning" />
                    ) : (
                      <RotateCcw size={16} />
                    )}
                    {isDone(run.status)
                      ? "Run complete"
                      : run.metadata.mode !== "demo"
                        ? "Use source adapter"
                        : "Resume run"}
                  </button>
                </div>
              </section>
              <section className="metrics" aria-label="Run metrics">
                <Metric
                  title="Committed operations"
                  value={
                    <>
                      {completed}
                      <small> / {run.steps.length}</small>
                    </>
                  }
                  detail="Confirmed outcomes in the journal"
                  icon={<Check size={16} />}
                />
                <Metric
                  title="Execution attempts"
                  value={run.operations.reduce(
                    (sum, operation) => sum + operation.attempts,
                    0,
                  )}
                  detail="All recorded dispatch attempts"
                  icon={<RefreshCw size={16} />}
                />
                <Metric
                  title="Evidence probes"
                  value={probes}
                  detail="Recorded attempts to verify an outcome"
                  icon={<SearchCheck size={16} />}
                />
                <Metric
                  title="Duplicate effects"
                  value={
                    run.metadata.simulated
                      ? (run.metrics?.duplicate_effects ?? "—")
                      : "—"
                  }
                  detail="Provider oracle · simulated runs only"
                  icon={<ShieldCheck size={16} />}
                />
              </section>
              <div className="inspector-grid">
                <section className="trace-panel">
                  <div className="trace-heading">
                    <div
                      role="tablist"
                      aria-label="Inspect run"
                      onKeyDown={(event) => {
                        if (
                          event.key === "ArrowLeft" ||
                          event.key === "ArrowRight"
                        ) {
                          event.preventDefault();
                          setTab(tab === "trace" ? "operations" : "trace");
                          event.currentTarget
                            .querySelector<HTMLButtonElement>(
                              '[role="tab"][aria-selected="false"]',
                            )
                            ?.focus();
                        }
                      }}
                    >
                      <button
                        role="tab"
                        id="trace-tab"
                        aria-controls="trace-panel"
                        tabIndex={tab === "trace" ? 0 : -1}
                        aria-selected={tab === "trace"}
                        onClick={() => setTab("trace")}
                        className={tab === "trace" ? "selected" : ""}
                      >
                        <GitBranch size={16} />
                        Execution trace
                      </button>
                      <button
                        role="tab"
                        id="operations-tab"
                        aria-controls="operations-panel"
                        tabIndex={tab === "operations" ? 0 : -1}
                        aria-selected={tab === "operations"}
                        onClick={() => setTab("operations")}
                        className={tab === "operations" ? "selected" : ""}
                      >
                        <Layers3 size={16} />
                        Operations
                      </button>
                    </div>
                    <span className="trace-count">
                      {tab === "trace"
                        ? run.events.length
                        : run.operations.length}{" "}
                      recorded
                    </span>
                  </div>
                  {tab === "trace" ? (
                    <div
                      role="tabpanel"
                      id="trace-panel"
                      aria-labelledby="trace-tab"
                    >
                      <div className="trace-toolbar">
                        <span>
                          <Clock3 size={14} />
                          Ordered by journal sequence
                        </span>
                        <label className="sr-only" htmlFor="event-filter">
                          Filter events
                        </label>
                        <select
                          id="event-filter"
                          value={eventFilter}
                          onChange={(event) =>
                            setEventFilter(event.target.value)
                          }
                        >
                          <option value="all">All events</option>
                          <option value="recovery">Recovery events</option>
                        </select>
                      </div>
                      <div className="timeline">
                        {filteredEvents.map((event) => {
                          const attention =
                            /unknown|fault|review|interrupt|error/.test(
                              event.kind,
                            );
                          const recovery =
                            /decision|evidence|probe|recover/.test(event.kind);
                          const op = run.operations.find(
                            (operation) => operation.id === event.operation_id,
                          );
                          return (
                            <button
                              key={event.seq}
                              className={`trace-event ${selectedEvent?.seq === event.seq ? "selected" : ""} ${attention ? "event-attention" : recovery ? "event-recovery" : ""}`}
                              onClick={() => setEventSeq(event.seq)}
                              aria-pressed={selectedEvent?.seq === event.seq}
                            >
                              <span className="trace-rail">
                                <span className="event-symbol">
                                  {attention ? (
                                    <Radio size={14} />
                                  ) : recovery ? (
                                    <SearchCheck size={14} />
                                  ) : /commit|complete/.test(event.kind) ? (
                                    <Check size={14} />
                                  ) : (
                                    <span />
                                  )}
                                </span>
                              </span>
                              <span className="event-body">
                                <span className="event-heading">
                                  <strong>{label(event.kind)}</strong>
                                  <time>{displayTime(event.created_at)}</time>
                                </span>
                                <span className="event-subtitle">
                                  {op?.step_key ?? "run"}
                                  <span>·</span>
                                  {String(
                                    event.payload.reason ??
                                      event.payload.point ??
                                      op?.tool ??
                                      "lifecycle transition",
                                  )}
                                </span>
                              </span>
                              <span className="event-seq">
                                {String(event.seq).padStart(3, "0")}
                              </span>
                            </button>
                          );
                        })}
                        {filteredEvents.length === 0 ? (
                          <p className="panel-empty">
                            No events match this filter.
                          </p>
                        ) : null}
                      </div>
                      <div className="trace-footer">
                        <span className="live-dot" />
                        Persisted locally
                        <span>
                          Select an event to inspect its evidence
                          <ArrowRight size={13} />
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div
                      role="tabpanel"
                      id="operations-panel"
                      aria-labelledby="operations-tab"
                      className="operations"
                    >
                      <div className="operation-labels">
                        <span>Logical operation</span>
                        <span>Status / attempts</span>
                      </div>
                      {run.operations.map((operation) => (
                        <div className="operation-row" key={operation.id}>
                          <div>
                            <strong>{operation.step_key}</strong>
                            <small>
                              {operation.tool}
                              <span>·</span>
                              {operation.id.slice(0, 10)}
                            </small>
                          </div>
                          <div>
                            <Badge status={operation.status} />
                            <small>
                              {operation.attempts} attempt
                              {operation.attempts === 1 ? "" : "s"}
                            </small>
                            {["unknown", "dispatched"].includes(
                              operation.status,
                            ) && run.metadata.mode === "demo" ? (
                              <button
                                className="text-button"
                                disabled={busy}
                                onClick={() => setResolving(operation)}
                              >
                                Confirm result
                                <ArrowRight size={12} />
                              </button>
                            ) : null}
                          </div>
                        </div>
                      ))}
                      {run.operations.length === 0 ? (
                        <p className="panel-empty">
                          No operations have been dispatched.
                        </p>
                      ) : null}
                    </div>
                  )}
                </section>
                <EventDetail
                  event={selectedEvent}
                  operation={selectedOperation}
                />
              </div>
              {run.status === "needs_review" || run.status === "interrupted" ? (
                <div className="review-note">
                  <CircleHelp size={19} />
                  <p>
                    <strong>
                      {run.status === "needs_review"
                        ? "This run needs a confirmed outcome."
                        : "The interruption has been preserved."}
                    </strong>
                    {run.status === "needs_review"
                      ? "Resume to probe again, or inspect an operation and record a result you independently verified."
                      : "Resume to let the selected policy reconcile the outstanding action."}
                  </p>
                  <button
                    className="text-button"
                    onClick={() => setTab("operations")}
                  >
                    Inspect operations
                    <ArrowRight size={15} />
                  </button>
                </div>
              ) : null}
            </>
          ) : (
            <section className="empty-state">
              <div className="empty-illustration" aria-hidden="true">
                <span className="empty-node">
                  <Terminal size={27} />
                </span>
                <span className="empty-line" />
                <span className="empty-node center">
                  <RotateCcw size={39} strokeWidth={1.6} />
                </span>
                <span className="empty-line" />
                <span className="empty-node">
                  <ShieldCheck size={29} />
                </span>
              </div>
              <span className="eyebrow">
                A CONTROLLED FAILURE. A VISIBLE RECOVERY.
              </span>
              <h2>What happens after the interruption?</h2>
              <p>
                Create a local experiment. Lose an acknowledgment, delay a
                result, or withhold evidence. Then inspect how the harness
                decides what comes next.
              </p>
              <button
                className="button primary"
                onClick={() => setCreating(true)}
              >
                <FlaskConical size={17} />
                Create your first experiment
                <ArrowRight size={16} />
              </button>
              <div className="empty-benefits">
                <span>
                  <Check size={15} />
                  No API key
                </span>
                <span>
                  <Check size={15} />
                  Durable SQLite journal
                </span>
                <span>
                  <Check size={15} />
                  Inspectable decisions
                </span>
              </div>
            </section>
          )}
          <footer className="main-footer">
            <span>
              REBOUND HARNESS<span className="separator">/</span>Evidence before
              repetition.
            </span>
            <a href="/docs" target="_blank" rel="noreferrer">
              Explore the local API
              <ArrowRight size={13} />
            </a>
          </footer>
        </div>
      </main>
      {creating ? (
        <CreateDialog
          onClose={() => {
            if (!busy) setCreating(false);
          }}
          onCreate={create}
          busy={busy}
          error={error}
        />
      ) : null}
      {resolving ? (
        <ResolveDialog
          operation={resolving}
          onClose={() => {
            if (!busy) setResolving(null);
          }}
          onResolve={resolve}
          busy={busy}
        />
      ) : null}
    </div>
  );
}
