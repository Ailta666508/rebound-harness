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
    <Dialog title="New experiment" onClose={onClose}>
      <p className="modal-description">
        Run a fault scenario against a simulated provider. Results are saved to
        the local journal. No model API key is required.
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
    <Dialog title="Confirm an operation result" onClose={onClose}>
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
    <section className="detail-panel" aria-label="Event details">
      <div className="panel-heading">
        <h2>Event details</h2>
        <span className="count-label">
          {event ? `#${event.seq}` : "No selection"}
        </span>
      </div>
      <div className="detail-scroll">
        {event ? (
          <>
            <div className="detail-title">
              <h3>{event.kind}</h3>
              {payload.action ? (
                <span className="decision-action">
                  {String(payload.action)}
                </span>
              ) : null}
            </div>
            {reason ? <p className="detail-intro">{String(reason)}</p> : null}
            <dl className="detail-facts">
              <div>
                <dt>Timestamp</dt>
                <dd>{displayTime(event.created_at)}</dd>
              </div>
              <div>
                <dt>Operation</dt>
                <dd title={event.operation_id ?? undefined}>
                  {operation?.step_key ?? "Run lifecycle"}
                </dd>
              </div>
              {operation ? (
                <>
                  <div>
                    <dt>Tool</dt>
                    <dd>{operation.tool}</dd>
                  </div>
                  <div>
                    <dt>Status</dt>
                    <dd>
                      <Badge status={operation.status} />
                    </dd>
                  </div>
                </>
              ) : null}
            </dl>
            {evidence ? (
              <section className="evidence-block">
                <h3>
                  <ShieldCheck size={14} />
                  Recorded evidence
                </h3>
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
              </section>
            ) : null}
            <details className="json-disclosure" open>
              <summary>
                <FileJson size={14} />
                Event payload
              </summary>
              <pre>{JSON.stringify(payload, null, 2)}</pre>
            </details>
            {operation?.result ? (
              <details className="json-disclosure">
                <summary>
                  <Code2 size={14} />
                  Recorded result
                </summary>
                <pre>{JSON.stringify(operation.result, null, 2)}</pre>
              </details>
            ) : null}
          </>
        ) : (
          <p className="panel-empty">
            Select an event to view its payload and recovery evidence.
          </p>
        )}
      </div>
      <div className="panel-footer">
        Read-only view of the persisted journal
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
          <svg className="brand-mark" viewBox="0 0 128 128" aria-hidden="true">
            <path
              d="M43 14 13 44 43 74 54 63 43 52H75a18 18 0 0 1 0 36H45v16h30a34 34 0 0 0 0-68H43l11-11Z"
              transform="translate(6 7)"
              fill="#e8e6ff"
            />
            <path
              d="M43 14 13 44 43 74 54 63 43 52H75a18 18 0 0 1 0 36H45v16h30a34 34 0 0 0 0-68H43l11-11Z"
              fill="#635bff"
            />
          </svg>
          <strong>Rebound</strong>
          <span className="version">v0.1</span>
        </a>
        <div className="workspace">
          <Terminal size={16} />
          <span>Local workspace</span>
          <span className="live-dot" />
        </div>
        <div className="sidebar-actions">
          <button
            className="new-run"
            disabled={busy}
            onClick={() => setCreating(true)}
          >
            <Plus size={15} />
            New experiment
          </button>
        </div>
        <div className="sidebar-section">
          <span>Runs</span>
          <span>{runs.length}</span>
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
                  {item.id.slice(0, 12)}
                  <span>·</span>
                  {label(item.status)}
                </small>
              </span>
            </button>
          ))}
          {runs.length === 0 ? (
            <p className="empty-runs">No runs yet.</p>
          ) : null}
        </nav>
        <div className="sidebar-bottom">
          <a
            href="https://github.com/Ailta666508/rebound-harness"
            target="_blank"
            rel="noreferrer"
          >
            <Code2 size={14} />
            Source & documentation
            <ArrowRight size={13} />
          </a>
          <div>
            <span className="live-dot" />
            Local storage · SQLite
          </div>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div>
            <span>Workspace</span>
            <ChevronRight size={14} />
            <h1>Recovery inspector</h1>
          </div>
          <a href="/docs" target="_blank" rel="noreferrer">
            API reference
            <ArrowRight size={13} />
          </a>
        </header>
        <div className="content">
          <div className="workspace-summary">
            <p>Execution history, tool outcomes, and recovery decisions.</p>
            <span className="simulated-badge">
              <FlaskConical size={13} />
              {!run || run.metadata.simulated
                ? "Simulated provider"
                : "Live tool run"}
            </span>
          </div>
          {error ? (
            <div className="error-banner" role="alert">
              <CircleHelp size={16} />
              <span>{error}</span>
              <button onClick={() => setError("")} aria-label="Dismiss error">
                <X size={16} />
              </button>
            </div>
          ) : null}
          {loading ? (
            <div className="loading-state" role="status">
              <LoaderCircle className="spinning" size={20} />
              Reading the journal…
            </div>
          ) : run ? (
            <>
              <section className="run-header">
                <div className="run-summary">
                  <div className="run-title">
                    <h2>{run.title}</h2>
                    <Badge status={run.status} />
                  </div>
                  <p>
                    <code>{run.id.slice(0, 16)}</code>
                    <span className="separator">·</span>
                    {new Date(run.created_at * 1000).toLocaleString()}
                    <span className="separator">·</span>
                    {label(String(run.metadata.policy ?? "custom"))} policy
                  </p>
                </div>
                <div className="run-actions">
                  <button className="button secondary" onClick={download}>
                    <ArrowDownToLine size={14} />
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
                      <LoaderCircle size={14} className="spinning" />
                    ) : (
                      <RotateCcw size={14} />
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
                  detail="Confirmed outcomes"
                  icon={<Check size={14} />}
                />
                <Metric
                  title="Execution attempts"
                  value={run.operations.reduce(
                    (sum, operation) => sum + operation.attempts,
                    0,
                  )}
                  detail="Recorded dispatches"
                  icon={<RefreshCw size={14} />}
                />
                <Metric
                  title="Evidence probes"
                  value={probes}
                  detail="Outcome verification attempts"
                  icon={<SearchCheck size={14} />}
                />
                <Metric
                  title="Duplicate effects"
                  value={
                    run.metadata.simulated
                      ? (run.metrics?.duplicate_effects ?? "—")
                      : "—"
                  }
                  detail="Provider oracle · simulated runs only"
                  icon={<ShieldCheck size={14} />}
                />
              </section>
              {run.status === "needs_review" || run.status === "interrupted" ? (
                <div className="review-note">
                  <CircleHelp size={16} />
                  <p>
                    <strong>
                      {run.status === "needs_review"
                        ? "This run needs a confirmed outcome."
                        : "This run was interrupted."}
                    </strong>
                    Resume to check again, or inspect an operation and confirm
                    its result.
                  </p>
                  <button
                    className="text-button"
                    onClick={() => setTab("operations")}
                  >
                    Inspect operations
                    <ArrowRight size={13} />
                  </button>
                </div>
              ) : null}
              <div className="inspector-grid">
                <section className="trace-panel" aria-label="Run journal">
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
                        <GitBranch size={14} />
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
                        <Layers3 size={14} />
                        Operations
                      </button>
                    </div>
                    <span className="count-label">
                      {tab === "trace"
                        ? run.events.length
                        : run.operations.length}{" "}
                      records
                    </span>
                  </div>
                  {tab === "trace" ? (
                    <div
                      className="journal-tab"
                      role="tabpanel"
                      id="trace-panel"
                      aria-labelledby="trace-tab"
                    >
                      <div className="trace-toolbar">
                        <span>
                          <Clock3 size={13} />
                          Journal sequence
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
                      <div className="table-scroll">
                        <table className="event-table">
                          <caption className="sr-only">
                            Recorded execution events
                          </caption>
                          <colgroup>
                            <col className="col-sequence" />
                            <col className="col-event" />
                            <col className="col-operation" />
                            <col className="col-time" />
                            <col />
                          </colgroup>
                          <thead>
                            <tr>
                              <th scope="col">Seq</th>
                              <th scope="col">Event</th>
                              <th scope="col">Operation</th>
                              <th scope="col">Time</th>
                              <th scope="col">Details</th>
                            </tr>
                          </thead>
                          <tbody>
                            {filteredEvents.map((event) => {
                              const attention =
                                /unknown|fault|review|interrupt|error/.test(
                                  event.kind,
                                );
                              const op = run.operations.find(
                                (operation) =>
                                  operation.id === event.operation_id,
                              );
                              const reason = String(
                                event.payload.reason ??
                                  event.payload.point ??
                                  op?.tool ??
                                  "Run lifecycle",
                              );
                              return (
                                <tr
                                  key={event.seq}
                                  className={
                                    selectedEvent?.seq === event.seq
                                      ? "selected"
                                      : ""
                                  }
                                >
                                  <td className="mono secondary-text">
                                    {String(event.seq).padStart(3, "0")}
                                  </td>
                                  <td>
                                    <button
                                      className="event-select"
                                      onClick={() => setEventSeq(event.seq)}
                                      aria-pressed={
                                        selectedEvent?.seq === event.seq
                                      }
                                    >
                                      <span
                                        className={`event-dot ${attention ? "warning" : ""}`}
                                      />
                                      {label(event.kind)}
                                    </button>
                                  </td>
                                  <td className="mono">
                                    {op?.step_key ?? "—"}
                                  </td>
                                  <td className="mono secondary-text">
                                    {displayTime(event.created_at)}
                                  </td>
                                  <td className="cell-summary" title={reason}>
                                    {reason}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                        {filteredEvents.length === 0 ? (
                          <p className="panel-empty">
                            No events match this filter.
                          </p>
                        ) : null}
                      </div>
                      <div className="panel-footer">
                        <span>
                          {filteredEvents.length} of {run.events.length} events
                        </span>
                        <span>Select an event to view details</span>
                      </div>
                    </div>
                  ) : (
                    <div
                      className="journal-tab"
                      role="tabpanel"
                      id="operations-panel"
                      aria-labelledby="operations-tab"
                    >
                      <div className="trace-toolbar">
                        <span>{run.operations.length} logical operations</span>
                        <span>Stable IDs across retries</span>
                      </div>
                      <div className="table-scroll">
                        <table className="operation-table">
                          <caption className="sr-only">Tool operations</caption>
                          <thead>
                            <tr>
                              <th scope="col">Operation</th>
                              <th scope="col">Tool</th>
                              <th scope="col">Status</th>
                              <th scope="col">Attempts</th>
                              <th scope="col">Action</th>
                            </tr>
                          </thead>
                          <tbody>
                            {run.operations.map((operation) => (
                              <tr
                                key={operation.id}
                                className={
                                  selectedOperation?.id === operation.id
                                    ? "selected"
                                    : ""
                                }
                              >
                                <td>
                                  <button
                                    className="operation-select"
                                    disabled={
                                      !run.events.some(
                                        (event) =>
                                          event.operation_id === operation.id,
                                      )
                                    }
                                    onClick={() => {
                                      const last = [...run.events]
                                        .reverse()
                                        .find(
                                          (event) =>
                                            event.operation_id === operation.id,
                                        );
                                      if (last) setEventSeq(last.seq);
                                    }}
                                  >
                                    {operation.step_key}
                                  </button>
                                  <small
                                    className="operation-id"
                                    title={operation.id}
                                  >
                                    {operation.id.slice(0, 14)}
                                  </small>
                                </td>
                                <td className="mono">{operation.tool}</td>
                                <td>
                                  <Badge status={operation.status} />
                                </td>
                                <td className="mono">{operation.attempts}</td>
                                <td>
                                  {["unknown", "dispatched"].includes(
                                    operation.status,
                                  ) && run.metadata.mode === "demo" ? (
                                    <button
                                      className="text-button"
                                      disabled={busy}
                                      onClick={() => setResolving(operation)}
                                    >
                                      Confirm result
                                    </button>
                                  ) : (
                                    <span className="secondary-text">—</span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {run.operations.length === 0 ? (
                          <p className="panel-empty">
                            No operations have been dispatched.
                          </p>
                        ) : null}
                      </div>
                      <div className="panel-footer">
                        <span>
                          {completed} completed ·{" "}
                          {run.operations.length - completed} remaining
                        </span>
                        <span>Results persisted per operation</span>
                      </div>
                    </div>
                  )}
                </section>
                <EventDetail
                  event={selectedEvent}
                  operation={selectedOperation}
                />
              </div>
            </>
          ) : (
            <section className="empty-state">
              <GitBranch size={28} />
              <h2>No runs in this workspace</h2>
              <p>
                Create an experiment to inspect execution events and recovery
                decisions.
              </p>
              <button
                className="button primary"
                onClick={() => setCreating(true)}
              >
                <Plus size={14} />
                Create your first experiment
              </button>
              <small>Simulated provider · No API key required</small>
            </section>
          )}
        </div>
        <footer className="main-footer">
          <span>
            <span className="live-dot" />
            Local journal
          </span>
          <span>
            {run
              ? `${run.events.length} events · Updated ${displayTime(run.updated_at)}`
              : "Ready"}
          </span>
        </footer>
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
