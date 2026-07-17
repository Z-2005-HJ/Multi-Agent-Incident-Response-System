import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Database,
  FileText,
  Gauge,
  GitBranch,
  Lock,
  Play,
  RefreshCw,
  Route,
  Search,
  ShieldCheck,
  Terminal,
  XCircle,
  Zap,
} from "lucide-react";
import "./styles.css";

type TabKey = "report" | "evidence" | "trace" | "eval" | "llm";

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
  llm_provider?: string | null;
  llm_model?: string | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
  llm_latency_ms?: number | null;
  llm_error_type?: string | null;
  prompt_version?: string | null;
  privacy_mode?: string | null;
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
  evidence_context?: {
    metric_findings: Array<{
      metric_name: string;
      query: string;
      value?: number | null;
      baseline?: number | null;
      severity: string;
      summary: string;
    }>;
    log_evidence_hits: Array<{
      timestamp?: string | null;
      source: string;
      level: string;
      message: string;
      matched_terms: string[];
    }>;
    deployment_events: Array<{
      service_name: string;
      version: string;
      commit_sha: string;
      author: string;
      deployed_at: string;
      environment: string;
      summary: string;
      risk_flags: string[];
    }>;
    evidence_sources: Record<string, string>;
    evidence_errors: string[];
  } | null;
  metadata: {
    agent_execution?: Record<string, { execution_mode?: string; fallback_reason?: string | null }>;
    standardized_evidence?: Record<string, unknown>;
  };
};

type LLMStatus = {
  mode: string;
  enabled: boolean;
  model?: string | null;
  privacy_mode: string;
  base_url_configured: boolean;
  api_key_configured: boolean;
};

type IncidentSummary = {
  incident_id: string;
  trace_id: string;
  status: string;
  service_name: string;
  severity: string;
  human_approval_required: boolean;
  approval_status: string;
  created_at?: string | null;
};

type FeedbackResult = {
  feedback_id: string;
  feedback_type: string;
  title: string;
  summary: string;
  key_signals: string[];
  doc_path: string;
  knowledge_source_id: string;
};

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";
const STATIC_API_TOKEN = (import.meta.env.VITE_API_TOKEN ?? import.meta.env.VITE_DEMO_API_TOKEN)?.trim();
const RELEASE_APPROVAL_ID = import.meta.env.VITE_RELEASE_APPROVAL_ID?.trim();
const AUTH_STORAGE_KEY = "incident-response-access-token";

type AuthContext = {
  actor_type: "tenant_key" | "admin" | "demo" | "user";
  actor_id: string;
  tenant_id?: string | null;
  tenant_name?: string | null;
  email?: string | null;
  full_name?: string | null;
  role?: "viewer" | "operator" | "approver" | "admin" | null;
  scopes: string[];
  operations_mode: string;
};

function getStoredToken() {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(AUTH_STORAGE_KEY)?.trim() ?? "";
}

function setStoredToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) {
    window.localStorage.setItem(AUTH_STORAGE_KEY, token);
  } else {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
  }
}

function getActiveToken() {
  return STATIC_API_TOKEN || getStoredToken();
}

async function apiFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers ?? {});
  const token = getActiveToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (RELEASE_APPROVAL_ID && (path === "/incidents/run" || path === "/incidents/submit")) {
    headers.set("X-Release-Approval", RELEASE_APPROVAL_ID);
  }
  return fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });
}

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

const sampleChange = `Deployment completed for checkout-api shortly before the alert.
Commit touched database connection pool configuration.
Rollback candidate: previous stable release.`;

function App() {
  const [serviceName, setServiceName] = useState("checkout-api");
  const [alertDescription, setAlertDescription] = useState(
    "Service checkout-api error rate increased from 0.5% to 12% after deployment.",
  );
  const [timeWindow, setTimeWindow] = useState("2026-06-18T10:20:00Z/2026-06-18T10:30:00Z");
  const [rawLogs, setRawLogs] = useState(sampleLogs);
  const [metricsJson, setMetricsJson] = useState(sampleMetrics);
  const [changeDescription, setChangeDescription] = useState(sampleChange);
  const [investigationNotes, setInvestigationNotes] = useState(
    "On-call noted database wait time increased after the latest release.",
  );
  const [activeTab, setActiveTab] = useState<TabKey>("report");
  const [result, setResult] = useState<IncidentResult | null>(null);
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [history, setHistory] = useState<IncidentSummary[]>([]);
  const [approvalNote, setApprovalNote] = useState("");
  const [feedbackContent, setFeedbackContent] = useState("");
  const [feedbackResult, setFeedbackResult] = useState<FeedbackResult | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isSavingFeedback, setIsSavingFeedback] = useState(false);
  const [authLoading, setAuthLoading] = useState(true);
  const [authContext, setAuthContext] = useState<AuthContext | null>(null);
  const [tenantIdInput, setTenantIdInput] = useState("");
  const [emailInput, setEmailInput] = useState("");
  const [passwordInput, setPasswordInput] = useState("");
  const [isSigningIn, setIsSigningIn] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nodeEnds = useMemo(
    () => result?.trace_events.filter((event) => event.event_type === "node_end") ?? [],
    [result],
  );

  useEffect(() => {
    apiFetch("/llm/status")
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: LLMStatus | null) => setLlmStatus(payload))
      .catch(() => setLlmStatus(null));
    void bootstrapAuth();
  }, []);

  async function bootstrapAuth() {
    try {
      const response = await apiFetch("/auth/me");
      if (!response.ok) {
        if (!STATIC_API_TOKEN) {
          setStoredToken(null);
        }
        setAuthContext(null);
        return;
      }
      const payload = (await response.json()) as AuthContext;
      setAuthContext(payload);
      await loadHistory();
    } catch {
      setAuthContext(null);
    } finally {
      setAuthLoading(false);
    }
  }

  async function loadHistory() {
    const response = await apiFetch("/incidents");
    if (response.ok) {
      setHistory((await response.json()) as IncidentSummary[]);
    }
  }

  async function login() {
    setIsSigningIn(true);
    setError(null);
    try {
      const response = await apiFetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantIdInput,
          email: emailInput,
          password: passwordInput,
        }),
      });
      if (!response.ok) {
        const body = await response.text();
        throw new Error(`HTTP ${response.status}: ${body.slice(0, 240)}`);
      }
      const payload = (await response.json()) as { access_token: string; auth_context: AuthContext };
      if (!STATIC_API_TOKEN) {
        setStoredToken(payload.access_token);
      }
      setAuthContext(payload.auth_context);
      setPasswordInput("");
      await loadHistory();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Unable to sign in");
    } finally {
      setIsSigningIn(false);
      setAuthLoading(false);
    }
  }

  async function logout() {
    if (!STATIC_API_TOKEN) {
      await apiFetch("/auth/logout", { method: "POST" }).catch(() => null);
      setStoredToken(null);
    }
    setAuthContext(null);
    setHistory([]);
    setResult(null);
  }

  if (authLoading) {
    return (
      <main className="auth-shell">
        <section className="auth-card">
          <RefreshCw className="spin" size={20} />
          <strong>Loading workspace</strong>
        </section>
      </main>
    );
  }

  if (!authContext) {
    return (
      <main className="auth-shell">
        <section className="auth-card">
          <div className="panel-heading">
            <ShieldCheck size={18} />
            <h2>Tenant Sign In</h2>
          </div>
          <label>
            <span>Tenant ID</span>
            <input value={tenantIdInput} onChange={(event) => setTenantIdInput(event.target.value)} />
          </label>
          <label>
            <span>Email</span>
            <input value={emailInput} onChange={(event) => setEmailInput(event.target.value)} />
          </label>
          <label>
            <span>Password</span>
            <input
              type="password"
              value={passwordInput}
              onChange={(event) => setPasswordInput(event.target.value)}
            />
          </label>
          <button className="primary-button auth-button" onClick={login} disabled={isSigningIn} type="button">
            {isSigningIn ? <RefreshCw className="spin" size={18} /> : <Lock size={18} />}
            <span>{isSigningIn ? "Signing In" : "Sign In"}</span>
          </button>
          {error ? <div className="error-strip">{error}</div> : null}
        </section>
      </main>
    );
  }

  async function runAnalysis() {
    setIsRunning(true);
    setError(null);
    try {
      const metrics = metricsJson.trim() ? JSON.parse(metricsJson) : {};
      const hasIncidentEvidence = [
        alertDescription,
        rawLogs,
        changeDescription,
        investigationNotes,
      ].some((value) => value.trim().length > 0) || Object.keys(metrics).length > 0;
      if (!hasIncidentEvidence) {
        throw new Error("Fill at least one incident evidence window before running analysis.");
      }
      const response = await apiFetch("/incidents/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          service_name: serviceName,
          alert_description: alertDescription,
          raw_logs: rawLogs,
          metrics,
          change_description: changeDescription,
          investigation_notes: investigationNotes,
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
      await loadHistory();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Request failed");
    } finally {
      setIsRunning(false);
    }
  }

  async function loadIncident(incidentId: string) {
    const response = await apiFetch(`/incidents/${incidentId}`);
    if (!response.ok) {
      setError(`Unable to load incident ${incidentId}`);
      return;
    }
    setResult((await response.json()) as IncidentResult);
    setActiveTab("report");
  }

  async function submitApproval(action: "approve" | "reject") {
    if (!result) return;
    const response = await apiFetch(`/incidents/${result.incident_id}/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved_by: "local-user", note: approvalNote }),
    });
    if (!response.ok) {
      setError(`Unable to ${action} incident`);
      return;
    }
    await loadHistory();
    setApprovalNote("");
  }

  async function ingestFeedback() {
    if (!feedbackContent.trim()) {
      setError("Manual feedback is empty");
      return;
    }
    setIsSavingFeedback(true);
    setError(null);
    try {
      const response = await apiFetch("/feedback/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_name: "frontend-manual-feedback",
          raw_content: feedbackContent,
          note: `Related service: ${serviceName}`,
        }),
      });
      if (!response.ok) {
        const body = await response.text();
        throw new Error(`HTTP ${response.status}: ${body.slice(0, 240)}`);
      }
      setFeedbackResult((await response.json()) as FeedbackResult);
      setFeedbackContent("");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Unable to save feedback");
    } finally {
      setIsSavingFeedback(false);
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
            <span>{authContext.tenant_name ?? authContext.tenant_id ?? authContext.actor_type}</span>
            <span>{authContext.email ?? authContext.actor_id}</span>
          </div>
        </div>
        <div className="topbar-actions">
          <StatusPill label={result?.workflow_status ?? "idle"} tone={result ? "ok" : "muted"} />
          {!STATIC_API_TOKEN ? (
            <button className="secondary-button" onClick={logout} type="button" title="Sign out">
              <Lock size={16} />
              <span>Sign Out</span>
            </button>
          ) : null}
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
          <label>
            <span>Change / Deployment</span>
            <textarea
              value={changeDescription}
              onChange={(event) => setChangeDescription(event.target.value)}
            />
          </label>
          <label>
            <span>Investigation Notes</span>
            <textarea
              value={investigationNotes}
              onChange={(event) => setInvestigationNotes(event.target.value)}
            />
          </label>
          <section className="feedback-panel">
            <div className="panel-heading">
              <FileText size={18} />
              <h2>Manual Feedback</h2>
            </div>
            <textarea
              className="feedback-input"
              value={feedbackContent}
              onChange={(event) => setFeedbackContent(event.target.value)}
              placeholder="Paste sanitized system feedback, error output, or investigation notes"
            />
            <button className="secondary-button" onClick={ingestFeedback} disabled={isSavingFeedback} type="button">
              {isSavingFeedback ? <RefreshCw className="spin" size={16} /> : <FileText size={16} />}
              <span>{isSavingFeedback ? "Saving" : "Save Feedback"}</span>
            </button>
            {feedbackResult ? (
              <div className="feedback-result">
                <strong>{feedbackResult.feedback_type}</strong>
                <span>{feedbackResult.knowledge_source_id}</span>
              </div>
            ) : null}
          </section>
          {error ? <div className="error-strip">{error}</div> : null}
          <HistoryPanel items={history} selectedId={result?.incident_id} onSelect={loadIncident} />
        </form>

        <section className="output-panel">
          <SummaryBand result={result} nodeEnds={nodeEnds} />
          <nav className="tabs">
            <TabButton active={activeTab === "report"} onClick={() => setActiveTab("report")} icon={<FileText size={16} />} label="Report" />
            <TabButton active={activeTab === "evidence"} onClick={() => setActiveTab("evidence")} icon={<Gauge size={16} />} label="Evidence" />
            <TabButton active={activeTab === "trace"} onClick={() => setActiveTab("trace")} icon={<Route size={16} />} label="Trace" />
            <TabButton active={activeTab === "eval"} onClick={() => setActiveTab("eval")} icon={<Activity size={16} />} label="Eval" />
            <TabButton active={activeTab === "llm"} onClick={() => setActiveTab("llm")} icon={<Zap size={16} />} label="LLM" />
          </nav>

          <div className="tab-body">
            {!result ? <EmptyState /> : null}
            {result && activeTab === "report" ? (
              <ReportView
                result={result}
                approvalNote={approvalNote}
                setApprovalNote={setApprovalNote}
                onApproval={submitApproval}
              />
            ) : null}
            {result && activeTab === "evidence" ? <EvidenceView result={result} /> : null}
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
      <MetricTile icon={<CheckCircle2 size={18} />} label="Nodes" value={`${nodeEnds.length}/10`} tone="green" />
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

function HistoryPanel({
  items,
  selectedId,
  onSelect,
}: {
  items: IncidentSummary[];
  selectedId?: string;
  onSelect: (incidentId: string) => void;
}) {
  return (
    <section className="history-panel">
      <div className="panel-heading">
        <Database size={18} />
        <h2>Run History</h2>
      </div>
      <div className="history-list">
        {items.length ? (
          items.map((item) => (
            <button
              className={item.incident_id === selectedId ? "history-item active" : "history-item"}
              key={item.incident_id}
              onClick={() => onSelect(item.incident_id)}
              type="button"
            >
              <strong>{item.service_name}</strong>
              <span>{item.severity} · {item.approval_status}</span>
            </button>
          ))
        ) : (
          <span className="history-empty">No saved runs</span>
        )}
      </div>
    </section>
  );
}

function ReportView({
  result,
  approvalNote,
  setApprovalNote,
  onApproval,
}: {
  result: IncidentResult;
  approvalNote: string;
  setApprovalNote: (value: string) => void;
  onApproval: (action: "approve" | "reject") => void;
}) {
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
      {report.human_approval_required ? (
        <section className="section-block wide">
          <h3>Human Approval</h3>
          <textarea
            className="approval-note"
            value={approvalNote}
            onChange={(event) => setApprovalNote(event.target.value)}
            placeholder="Approval note"
          />
          <div className="approval-actions">
            <button className="approve-button" onClick={() => onApproval("approve")} title="Approve high-risk plan">
              <CheckCircle2 size={16} />
              <span>Approve</span>
            </button>
            <button className="reject-button" onClick={() => onApproval("reject")} title="Reject high-risk plan">
              <XCircle size={16} />
              <span>Reject</span>
            </button>
          </div>
        </section>
      ) : null}
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
          <span className="duration">{event.llm_latency_ms ?? event.duration_ms} ms</span>
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
              <span>{String(score.llm_latency_ms ?? score.duration_ms ?? 0)} ms</span>
              <span>{String(score.total_tokens ?? "-")} tok</span>
              <span>{String(score.retrieval_mode ?? (score.schema_valid === false ? "invalid" : "valid"))}</span>
            </div>
          ))}
        </div>
      </section>
      <ListBlock title="Risks" items={result.eval_report.risks} />
      <ListBlock title="Recommendations" items={result.eval_report.recommendations} />
    </div>
  );
}

function EvidenceView({ result }: { result: IncidentResult }) {
  const evidence = result.evidence_context;
  return (
    <div className="evidence-layout">
      <section className="section-block wide">
        <h3>Metric Evidence</h3>
        <EvidenceSource value={evidence?.evidence_sources.metrics} />
        <div className="evidence-list">
          {(evidence?.metric_findings.length ? evidence.metric_findings : []).map((item) => (
            <article className="evidence-item" key={item.metric_name}>
              <div className="evidence-head">
                <strong><Gauge size={15} /> {item.metric_name}</strong>
                <StatusPill label={item.severity} tone={item.severity === "high" ? "warn" : "muted"} />
              </div>
              <p>{item.summary}</p>
              <code>{item.query}</code>
            </article>
          ))}
          {!evidence?.metric_findings.length ? <span className="history-empty">No metric evidence</span> : null}
        </div>
      </section>
      <section className="section-block">
        <h3>Log Evidence</h3>
        <EvidenceSource value={evidence?.evidence_sources.logs} />
        <div className="evidence-list">
          {(evidence?.log_evidence_hits.length ? evidence.log_evidence_hits : []).map((item) => (
            <article className="evidence-item compact" key={`${item.timestamp}-${item.message}`}>
              <strong><Search size={15} /> {item.level}</strong>
              <p>{item.message}</p>
              <span>{item.source} · {item.matched_terms.join(", ") || "no matched term"}</span>
            </article>
          ))}
          {!evidence?.log_evidence_hits.length ? <span className="history-empty">No log evidence hits</span> : null}
        </div>
      </section>
      <section className="section-block">
        <h3>Deployment Clues</h3>
        <EvidenceSource value={evidence?.evidence_sources.deployment} />
        <div className="evidence-list">
          {(evidence?.deployment_events.length ? evidence.deployment_events : []).map((item) => (
            <article className="evidence-item compact" key={item.commit_sha}>
              <strong><GitBranch size={15} /> {item.version}</strong>
              <p>{item.summary}</p>
              <span>{item.deployed_at} · {item.risk_flags.join(", ") || "no risk flag"}</span>
            </article>
          ))}
          {!evidence?.deployment_events.length ? <span className="history-empty">No deployment events</span> : null}
        </div>
      </section>
      {evidence?.evidence_errors.length ? <ListBlock title="Evidence Errors" items={evidence.evidence_errors} /> : null}
    </div>
  );
}

function EvidenceSource({ value }: { value?: string }) {
  return <span className="evidence-source">source: {value ?? "unknown"}</span>;
}

function LLMView({ result, status }: { result: IncidentResult | null; status: LLMStatus | null }) {
  const execution = result?.metadata.agent_execution ?? {};
  return (
    <div className="llm-grid">
      <article className="llm-row">
        <div>
          <strong>{status?.mode ?? "unknown"}</strong>
          <p>{status?.model ?? "model unavailable"}</p>
          <p><Lock size={12} /> privacy: {status?.privacy_mode ?? "unknown"}</p>
        </div>
        <StatusPill label={status?.enabled ? "enabled" : "mock"} tone={status?.enabled ? "ok" : "muted"} />
      </article>
      {Object.entries(execution).map(([agent, info]) => (
        <article className="llm-row" key={agent}>
          <div>
            <strong>{agent}</strong>
            {info.fallback_reason ? <p>{info.fallback_reason}</p> : null}
            <p>
              model: {String((info as Record<string, unknown>).llm_model ?? "-")} · tokens:{" "}
              {String((info as Record<string, unknown>).total_tokens ?? "-")} · latency:{" "}
              {String((info as Record<string, unknown>).llm_latency_ms ?? "-")} ms
            </p>
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
