import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  FileText,
  Play,
  RefreshCw,
  Route,
  ShieldCheck,
  Terminal,
  Zap,
} from "lucide-react";
import "./styles.css";

type TabKey = "report" | "trace" | "eval" | "llm";

type RootCause = {
  cause: string;
  status: string;
  confidence: number;
  evidence: string[];
};

type TraceEvent = {
  span_id: string;
  node_name: string;
  agent_name: string;
  event_type: string;
  duration_ms: number;
  execution_mode?: "rule" | "llm" | "rule_fallback" | "system" | null;
  fallback_reason?: string | null;
  error?: string | null;
};

type IncidentResult = {
  incident_id: string;
  trace_id: string;
  workflow_status: string;
  report: {
    service_name: string;
    severity: string;
    summary: string;
    timeline: string[];
    signals: string[];
    root_causes: RootCause[];
    recommended_actions: string[];
    rollback_plan: string[];
    verification_steps: string[];
    confidence: number;
    review_notes: string[];
    sources: string[];
    human_approval_required: boolean;
  };
  markdown_report: string;
  eval_report: {
    trace_id: string;
    workflow_status: string;
    total_duration_ms: number;
    agent_scores: Record<string, Record<string, unknown>>;
    risks: string[];
    recommendations: string[];
  };
  trace_events: TraceEvent[];
  metadata: {
    agent_execution?: Record<string, { execution_mode?: string; fallback_reason?: string | null }>;
  };
};

type LLMStatus = {
  mode: string;
  enabled: boolean;
  model?: string | null;
  base_url_configured: boolean;
  api_key_configured: boolean;
};

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const sampleLogs = `2026-06-18T10:21:03Z ERROR checkout-api DatabaseConnectionTimeout while acquiring database connection
2026-06-18T10:21:04Z ERROR checkout-api failed to acquire connection from pool
2026-06-18T10:21:05Z WARN checkout-api retrying payment transaction
2026-06-18T10:21:12Z ERROR checkout-api DatabaseConnectionTimeout after 3000ms`;

const sampleMetrics = `{
  "error_rate": {
    "before": 0.005,
    "after": 0.12
  },
  "p95_latency_ms": {
    "before": 230,
    "after": 2400
  },
  "db_connection_pool_usage": {
    "before": 0.45,
    "after": 0.98
  }
}`;

function App() {
  const [serviceName, setServiceName] = useState("checkout-api");
  const [alertDescription, setAlertDescription] = useState(
    "Service checkout-api error rate increased from 0.5% to 12% after deployment.",
  );
  const [timeWindow, setTimeWindow] = useState("2026-06-18T10:20:00Z/2026-06-18T10:30:00Z");
  const [rawLogs, setRawLogs] = useState(sampleLogs);
  const [metricsJson, setMetricsJson] = useState(sampleMetrics);
  const [activeTab, setActiveTab] = useState<TabKey>("report");
  const [result, setResult] = useState<IncidentResult | null>(null);
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nodeEnds = useMemo(
    () => result?.trace_events.filter((event) => event.event_type === "node_end") ?? [],
    [result],
  );

  useEffect(() => {
    fetch(`${API_BASE}/llm/status`)
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: LLMStatus | null) => setLlmStatus(payload))
      .catch(() => setLlmStatus(null));
  }, []);

  async function runAnalysis() {
    setIsRunning(true);
    setError(null);
    try {
      const metrics = JSON.parse(metricsJson);
      const response = await fetch(`${API_BASE}/incidents/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          service_name: serviceName,
          alert_description: alertDescription,
          raw_logs: rawLogs,
          metrics,
          time_window: timeWindow,
        }),
      });
      if (!response.ok) {
        const body = await response.text();
        throw new Error(`HTTP ${response.status}: ${body.slice(0, 240)}`);
      }
      const payload = (await response.json()) as IncidentResult;
      setResult(payload);
      setActiveTab("report");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Request failed");
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Incident Response Console</h1>
          <div className="subline">
            <span>{result?.incident_id ?? "No incident run"}</span>
            <span>{result?.trace_id ?? "trace pending"}</span>
          </div>
        </div>
        <div className="topbar-actions">
          <StatusPill label={result?.workflow_status ?? "idle"} tone={result ? "ok" : "muted"} />
          <button className="primary-button" onClick={runAnalysis} disabled={isRunning} title="Run analysis">
            {isRunning ? <RefreshCw className="spin" size={18} /> : <Play size={18} />}
            <span>{isRunning ? "Running" : "Run"}</span>
          </button>
        </div>
      </header>

      <section className="workspace">
        <form className="input-panel" onSubmit={(event) => event.preventDefault()}>
          <div className="panel-heading">
            <Terminal size={18} />
            <h2>Incident Input</h2>
          </div>
          <label>
            <span>Service</span>
            <input value={serviceName} onChange={(event) => setServiceName(event.target.value)} />
          </label>
          <label>
            <span>Time Window</span>
            <input value={timeWindow} onChange={(event) => setTimeWindow(event.target.value)} />
          </label>
          <label>
            <span>Alert</span>
            <textarea
              className="alert-input"
              value={alertDescription}
              onChange={(event) => setAlertDescription(event.target.value)}
            />
          </label>
          <label>
            <span>Logs</span>
            <textarea value={rawLogs} onChange={(event) => setRawLogs(event.target.value)} />
          </label>
          <label>
            <span>Metrics JSON</span>
            <textarea value={metricsJson} onChange={(event) => setMetricsJson(event.target.value)} />
          </label>
          {error ? <div className="error-strip">{error}</div> : null}
        </form>

        <section className="output-panel">
          <SummaryBand result={result} nodeEnds={nodeEnds} />
          <nav className="tabs">
            <TabButton active={activeTab === "report"} onClick={() => setActiveTab("report")} icon={<FileText size={16} />} label="Report" />
            <TabButton active={activeTab === "trace"} onClick={() => setActiveTab("trace")} icon={<Route size={16} />} label="Trace" />
            <TabButton active={activeTab === "eval"} onClick={() => setActiveTab("eval")} icon={<Activity size={16} />} label="Eval" />
            <TabButton active={activeTab === "llm"} onClick={() => setActiveTab("llm")} icon={<Zap size={16} />} label="LLM" />
          </nav>

          <div className="tab-body">
            {!result ? <EmptyState /> : null}
            {result && activeTab === "report" ? <ReportView result={result} /> : null}
            {result && activeTab === "trace" ? <TraceView events={nodeEnds} /> : null}
            {result && activeTab === "eval" ? <EvalView result={result} /> : null}
            {activeTab === "llm" ? <LLMView result={result} status={llmStatus} /> : null}
          </div>
        </section>
      </section>
    </main>
  );
}

function SummaryBand({ result, nodeEnds }: { result: IncidentResult | null; nodeEnds: TraceEvent[] }) {
  const duration = result?.eval_report.total_duration_ms ?? 0;
  return (
    <section className="summary-grid">
      <MetricTile icon={<ShieldCheck size={18} />} label="Severity" value={result?.report.severity ?? "-"} tone="red" />
      <MetricTile icon={<AlertTriangle size={18} />} label="Approval" value={result?.report.human_approval_required ? "required" : "clear"} tone="amber" />
      <MetricTile icon={<Clock3 size={18} />} label="Duration" value={`${duration} ms`} tone="blue" />
      <MetricTile icon={<CheckCircle2 size={18} />} label="Nodes" value={`${nodeEnds.length}/9`} tone="green" />
    </section>
  );
}

function MetricTile({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: string; tone: string }) {
  return (
    <div className={`metric-tile ${tone}`}>
      <div className="metric-icon">{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function TabButton({ active, icon, label, onClick }: { active: boolean; icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button className={active ? "tab active" : "tab"} onClick={onClick} title={label}>
      {icon}
      <span>{label}</span>
    </button>
  );
}

function ReportView({ result }: { result: IncidentResult }) {
  const report = result.report;
  return (
    <div className="report-grid">
      <section className="section-block wide">
        <h3>Summary</h3>
        <p>{report.summary}</p>
      </section>
      <ListBlock title="Signals" items={report.signals} />
      <ListBlock title="Timeline" items={report.timeline} />
      <section className="section-block wide">
        <h3>Root Causes</h3>
        <div className="cause-list">
          {report.root_causes.map((cause) => (
            <article className="cause-item" key={cause.cause}>
              <div className="cause-head">
                <strong>{cause.cause}</strong>
                <StatusPill label={`${cause.status} ${(cause.confidence * 100).toFixed(0)}%`} tone="ok" />
              </div>
              <ul>
                {cause.evidence.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </section>
      <ListBlock title="Actions" items={report.recommended_actions} />
      <ListBlock title="Rollback" items={report.rollback_plan} />
      <ListBlock title="Verification" items={report.verification_steps} />
      <ListBlock title="Review" items={report.review_notes} />
    </div>
  );
}

function TraceView({ events }: { events: TraceEvent[] }) {
  return (
    <div className="trace-list">
      {events.map((event, index) => (
        <article className="trace-row" key={`${event.node_name}-${event.span_id}`}>
          <div className="trace-index">{index + 1}</div>
          <div className="trace-main">
            <div className="trace-title">
              <strong>{event.node_name}</strong>
              <span>{event.agent_name}</span>
            </div>
            {event.fallback_reason ? <p>{event.fallback_reason}</p> : null}
          </div>
          <StatusPill label={event.execution_mode ?? "system"} tone={event.execution_mode === "llm" ? "ok" : event.execution_mode === "rule_fallback" ? "warn" : "muted"} />
          <span className="duration">{event.duration_ms} ms</span>
        </article>
      ))}
    </div>
  );
}

function EvalView({ result }: { result: IncidentResult }) {
  const scores = Object.entries(result.eval_report.agent_scores);
  return (
    <div className="eval-layout">
      <section className="section-block wide">
        <h3>Agent Scores</h3>
        <div className="score-table">
          {scores.map(([agent, score]) => (
            <div className="score-row" key={agent}>
              <strong>{agent}</strong>
              <span>{String(score.execution_mode ?? "system")}</span>
              <span>{String(score.duration_ms ?? 0)} ms</span>
              <span>{score.schema_valid === false ? "invalid" : "valid"}</span>
            </div>
          ))}
        </div>
      </section>
      <ListBlock title="Risks" items={result.eval_report.risks} />
      <ListBlock title="Recommendations" items={result.eval_report.recommendations} />
    </div>
  );
}

function LLMView({ result, status }: { result: IncidentResult | null; status: LLMStatus | null }) {
  const execution = result?.metadata.agent_execution ?? {};
  return (
    <div className="llm-grid">
      <article className="llm-row">
        <div>
          <strong>{status?.mode ?? "unknown"}</strong>
          <p>{status?.model ?? "model unavailable"}</p>
        </div>
        <StatusPill label={status?.enabled ? "enabled" : "mock"} tone={status?.enabled ? "ok" : "muted"} />
      </article>
      {Object.entries(execution).map(([agent, info]) => (
        <article className="llm-row" key={agent}>
          <div>
            <strong>{agent}</strong>
            {info.fallback_reason ? <p>{info.fallback_reason}</p> : null}
          </div>
          <StatusPill label={info.execution_mode ?? "unknown"} tone={info.execution_mode === "llm" ? "ok" : "warn"} />
        </article>
      ))}
      {!Object.keys(execution).length ? (
        <article className="llm-row">
          <div>
            <strong>agent_execution</strong>
            <p>No incident run yet</p>
          </div>
          <StatusPill label="pending" tone="muted" />
        </article>
      ) : null}
    </div>
  );
}

function ListBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="section-block">
      <h3>{title}</h3>
      <ul>
        {(items.length ? items : ["-"]).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function StatusPill({ label, tone }: { label: string; tone: "ok" | "warn" | "muted" }) {
  return <span className={`status-pill ${tone}`}>{label}</span>;
}

function EmptyState() {
  return (
    <div className="empty-state">
      <Activity size={28} />
      <span>Awaiting incident run</span>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
