import { useCallback, useEffect, useState } from "react";
import Card from "../components/Card";
import MonoValue from "../components/MonoValue";
import Panel from "../components/Panel";
import StatusPill from "../components/StatusPill";
import logoMark from "../assets/ringback-mark.png";

const INTENT_LABELS = {
  proof_of_registration: "Proof of registration",
  subject_cancellation: "Subject cancellation",
  other: "General query",
};

function elapsed(createdAt) {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(`${createdAt}Z`)) / 60000));
  return `${minutes}m`;
}

function isToday(createdAt) {
  const created = new Date(`${createdAt}Z`);
  const now = new Date();
  return (
    created.getFullYear() === now.getFullYear() &&
    created.getMonth() === now.getMonth() &&
    created.getDate() === now.getDate()
  );
}

function displayName(item) {
  return item.student_name || item.caller_name || item.student_number || item.phone;
}

function BoolValue({ value }) {
  return <span className={`bool-value bool-value--${value}`}>{value ? "Yes" : "No"}</span>;
}

export default function DashboardPage() {
  const [cases, setCases] = useState([]);
  const [selectedId, setSelectedId] = useState(null);

  const refresh = useCallback(async () => {
    const res = await fetch("/api/cases");
    if (!res.ok) return;
    const data = await res.json();
    setCases(data);
    setSelectedId((current) => current ?? data[0]?.id ?? null);
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 2000);
    return () => clearInterval(id);
  }, [refresh]);

  const selected = cases.find((c) => c.id === selectedId) || null;
  const todayCount = cases.filter((c) => isToday(c.created_at)).length;
  const resolvedCount = cases.filter((c) => c.status === "resolved").length;

  return (
    <div className="page page--dashboard">
      <div className="top-bar">
        <div className="brand-row" style={{ marginBottom: 0 }}>
          <img src={logoMark} alt="" className="brand-mark" />
          <span className="brand-name">Ringback</span>
        </div>
        <span className="top-bar__meta">NUST · Registrar's office</span>
      </div>

      <div className="dashboard-layout">
        <Panel title="Queue" right={<span className="tag">{cases.length}</span>} className="queue-panel">
          {cases.length === 0 ? (
            <div className="empty-state">
              <p className="empty-state__title">No open queries</p>
              <p className="empty-state__body">New ones appear here as students submit them.</p>
            </div>
          ) : (
            <>
              <div className="queue-list">
                {cases.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    className={`queue-row ${c.id === selectedId ? "queue-row--selected" : ""}`}
                    onClick={() => setSelectedId(c.id)}
                  >
                    <div className="queue-row__top">
                      <StatusPill status={c.status} />
                      <MonoValue className="queue-row__time">{elapsed(c.created_at)}</MonoValue>
                    </div>
                    <div className="queue-row__name">{displayName(c)}</div>
                  </button>
                ))}
              </div>
              <div className="queue-footer-divider" />
              <p className="queue-footer-stats">
                {todayCount} today · {resolvedCount} resolved
              </p>
            </>
          )}
        </Panel>

        <div className="detail-column">
          {selected ? (
            <CaseDetail key={selected.id} item={selected} />
          ) : (
            <Panel title="Case detail">
              <p className="empty-state__body">Select a case from the queue.</p>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

function CaseDetail({ item }) {
  const result = item.structured_result;
  const name = displayName(item);
  const breadcrumbSource = item.student_name || item.caller_name;
  const breadcrumbName = breadcrumbSource ? breadcrumbSource.split(" ")[0] : item.phone;

  return (
    <div className="detail-fade">
      <div className="breadcrumb">
        Queue / {INTENT_LABELS[item.intent] || "Unclassified"} / {breadcrumbName}
      </div>
      <h1 className="page-heading">{name}</h1>
      {(item.student_number || item.phone) && (
        <p className="mono detail-subline">
          {[item.student_number, item.phone].filter(Boolean).join(" · ")}
        </p>
      )}

      <div className="summary-cards">
        <Card>
          <div className="tag-row">
            <span className="tag">Attempt {item.call_attempts} of 3</span>
            <StatusPill status={item.status} />
            {item.preparer_used === "deterministic" && (
              <span className="tag">Fallback: keyword + TF-IDF</span>
            )}
          </div>
          <div className="card-title">{INTENT_LABELS[item.intent] || "Unclassified"}</div>
          <MonoValue className="card-sub">
            {item.completion_confidence != null
              ? `Confidence ${item.completion_confidence.toFixed(2)}`
              : "In progress"}
          </MonoValue>
        </Card>
        <Card>
          <div className="tag-row">
            <span className="tag">
              {item.routed_office ? "Routed" : item.status === "resolved" ? "Resolved" : "Pending"}
            </span>
          </div>
          <div className="card-title">
            {item.routed_office || (item.status === "resolved" ? "Resolved on the call" : "Awaiting outcome")}
          </div>
          {item.routed_contact && <MonoValue className="card-sub">{item.routed_contact}</MonoValue>}
        </Card>
      </div>

      <Panel title="Call detail">
        <div className="inset-box">
          <p className="field-label">They asked</p>
          <p className="inset-box__query">{item.original_query}</p>
        </div>

        {item.reasoning && (
          <div className="inset-box">
            <p className="field-label">Reasoning</p>
            <p className="inset-box__query">{item.reasoning}</p>
          </div>
        )}

        {result && (
          <div className="result-grid">
            {Object.entries(result).map(([key, value]) => (
              <div key={key} className="result-field">
                <p className="field-label">{key.replace(/_/g, " ")}</p>
                <p className="mono">
                  {typeof value === "boolean" ? <BoolValue value={value} /> : String(value)}
                </p>
              </div>
            ))}
          </div>
        )}

        {item.retrieved_sources && item.retrieved_sources.length > 0 && (
          <div className="inset-box">
            <p className="field-label">Sources used</p>
            <div className="sources-list">
              {item.retrieved_sources.map((s) => (
                <div key={s.chunk_id} className="sources-list__row">
                  <span>{s.heading}</span>
                  <MonoValue className="sources-list__score">{s.score.toFixed(2)}</MonoValue>
                </div>
              ))}
            </div>
          </div>
        )}

        {item.no_kb_coverage && (
          <div className="inset-box">
            <p className="field-label">Sources used</p>
            <p className="inset-box__query">
              No reference material matched this question — the agent was told to say so
              rather than guess.
            </p>
          </div>
        )}

        {item.transcript && (
          <div className="inset-box">
            <p className="field-label">Transcript</p>
            <p className="transcript-text">{item.transcript}</p>
          </div>
        )}

        {item.routed_reason && (
          <div className="routed-box">
            <p className="field-label">Routed to</p>
            <p>{item.routed_office}</p>
            <p className="mono">{item.routed_contact}</p>
            <div className="routed-box__reason">
              <p>{item.routed_reason}</p>
            </div>
          </div>
        )}

        {item.status === "failed" && (
          <div className="failed-box">
            <p className="card-title">No answer after {item.call_attempts} attempts</p>
            <p>This student will need a manual callback.</p>
          </div>
        )}
      </Panel>
    </div>
  );
}
