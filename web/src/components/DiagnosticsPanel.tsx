import { useEffect, useState } from "react";
import { fetchHealth, type HealthResponse } from "../api";

interface Props {
  refresh?: number;
}

type RowStatus = "ok" | "warn" | "err";

function Row({ label, status, detail }: { label: string; status: RowStatus; detail: string }) {
  const icon = status === "ok" ? "●" : status === "warn" ? "◐" : "●";
  const cls = status === "ok" ? "diag-ok" : status === "warn" ? "diag-warn" : "diag-err";
  return (
    <tr>
      <td className="diag-label">{label}</td>
      <td className={`diag-icon ${cls}`}>{icon}</td>
      <td className="diag-detail">{detail}</td>
    </tr>
  );
}

function SectionHeader({ title, badge }: { title: string; badge: React.ReactNode }) {
  return (
    <tr className="diag-section-header">
      <td colSpan={2}><strong>{title}</strong></td>
      <td>{badge}</td>
    </tr>
  );
}

function modelsOk(health: HealthResponse): boolean {
  // Anthropic unavailability is not fatal — critic falls back to Ollama automatically
  return (
    health.ollama.reachable === true &&
    health.ollama_model.available === true
  );
}

function frameworksOk(health: HealthResponse): boolean {
  return (
    health.memory["vector_enabled"] === true &&
    health.crewai.available === true &&
    health.langchain.available === true &&
    health.langgraph.available === true &&
    health.fastmcp.available === true &&
    health.mcp.available === true
  );
}


function toolsOk(health: HealthResponse): boolean {
  const google = health.google as Record<string, unknown>;
  const googleCalendar = google["calendar_probe"] === "ok";
  const googleGmail = google["gmail_probe"] === "ok";
  const googleTasks = google["tasks_probe"] === "ok";
  return googleCalendar || googleGmail || googleTasks || health.weather.available || health.news.available;
}

export function DiagnosticsPanel({ refresh = 0 }: Props) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetchHealth()
      .then(setHealth)
      .finally(() => setLoading(false));
  }, [refresh]);

  const google = health?.google as Record<string, unknown> | undefined;
  const mOk = health ? modelsOk(health) : null;
  const frOk = health ? frameworksOk(health) : null;
  const tOk = health ? toolsOk(health) : null;
  const allOk = mOk === true && frOk === true && tOk === true;

  return (
    <div className="diagnostics">
      <div className="diagnostics-header">
        <h2>Diagnostics</h2>
        {!loading && health !== null && (
          <span className={allOk ? "status-badge status-ok" : "status-badge status-err"}>
            {allOk ? "● All systems go" : "● Issues detected"}
          </span>
        )}
      </div>
      {loading && <p className="loading">Loading diagnostics…</p>}
      {!loading && health && (
        <table className="diag-table">
          <tbody>
            <SectionHeader
              title="Models"
              badge={
                <span className={mOk ? "diag-badge diag-ok" : "diag-badge diag-err"}>
                  {mOk ? "all green" : "action required"}
                </span>
              }
            />
            <Row
              label="Ollama"
              status={health.ollama.reachable ? "ok" : "err"}
              detail={health.ollama.detail}
            />
            <Row
              label="Ollama Model"
              status={health.ollama_model.available ? "ok" : "err"}
              detail={health.ollama_model.available && health.ollama_model.context_window
                ? `${health.ollama_model.detail} · ${health.ollama_model.context_window} context`
                : health.ollama_model.detail}
            />
            <Row
              label="Anthropic (optional)"
              status={health.anthropic.reachable ? "ok" : "warn"}
              detail={health.anthropic.reachable
                ? `${health.anthropic.detail} · ${health.anthropic.context_window ?? "200K"} context`
                : `${health.anthropic.detail} — critic will use Ollama`}
            />

            <SectionHeader
              title="Frameworks"
              badge={
                <span className={frOk ? "diag-badge diag-ok" : "diag-badge diag-err"}>
                  {frOk ? "all green" : "action required"}
                </span>
              }
            />
            <Row
              label="Vector Memory"
              status={health.memory["vector_enabled"] ? "ok" : "err"}
              detail={health.memory["vector_enabled"] ? "enabled" : String(health.memory["backend_error"] || "unavailable")}
            />
            <Row
              label="Embedding Model"
              status={health.memory["vector_enabled"] ? "ok" : "warn"}
              detail={String(health.memory["embedding_model"] || "unknown")}
            />
            <Row
              label="HF Token"
              status={health.huggingface.token_configured ? "ok" : "warn"}
              detail={health.huggingface.token_configured ? "configured" : "not set — unauthenticated (rate limited)"}
            />
            <Row
              label="HF Model Cache"
              status={health.huggingface.model_cached ? "ok" : "warn"}
              detail={
                health.huggingface.model_cached
                  ? `cached locally · ${health.huggingface.embedding_model}`
                  : `not cached · will download on first use`
              }
            />
            <Row
              label="CrewAI"
              status={health.crewai.available ? "ok" : "err"}
              detail={health.crewai.detail}
            />
            {health.crewai.agents.map((agent) => (
              <tr key={agent.role} className="diag-agent-row">
                <td className="diag-label diag-agent-label">↳ {agent.role}</td>
                <td className="diag-icon diag-ok">●</td>
                <td className="diag-detail">
                  <span className="diag-agent-model">{agent.provider}/{agent.model}</span>
                  <span className="diag-agent-purpose"> — {agent.purpose}</span>
                </td>
              </tr>
            ))}
            <Row
              label="LangChain Core"
              status={health.langchain.available ? "ok" : "err"}
              detail={health.langchain.detail}
            />
            <Row
              label="LangGraph"
              status={health.langgraph.available ? "ok" : "err"}
              detail={health.langgraph.detail}
            />
            {health.langgraph.graph && (
              <>
                {health.langgraph.graph.nodes.map((node) => (
                  <tr key={node.id} className="diag-agent-row">
                    <td className="diag-label diag-agent-label">↳ {node.label}</td>
                    <td className="diag-icon diag-ok">●</td>
                    <td className="diag-detail diag-agent-purpose">{node.description}</td>
                  </tr>
                ))}
                <tr className="diag-agent-row">
                  <td className="diag-label diag-agent-label" style={{ paddingTop: "0.4rem" }}>Edges</td>
                  <td />
                  <td className="diag-detail" style={{ paddingTop: "0.4rem" }}>
                    {health.langgraph.graph.edges.map((e, i) => (
                      <span key={i} style={{ display: "block", fontSize: "0.78rem", color: e.type === "conditional" ? "#d97706" : "#6b7280" }}>
                        {e.from} → {e.to}{e.condition ? ` (${e.condition})` : ""}
                      </span>
                    ))}
                  </td>
                </tr>
              </>
            )}
            <Row
              label="FastMCP"
              status={health.fastmcp.available ? "ok" : "err"}
              detail={health.fastmcp.detail}
            />
            <Row
              label="MCP Branch State"
              status={health.mcp.available ? "ok" : "err"}
              detail={health.mcp.detail}
            />

            <SectionHeader
              title="Observability"
              badge={<span className="diag-badge diag-optional">optional</span>}
            />
            <tr>
              <td className="diag-label">Galileo</td>
              <td className={`diag-icon ${health.galileo.configured && health.galileo.reachable ? "diag-ok" : health.galileo.sdk_available ? "diag-warn" : "diag-err"}`}>
                {health.galileo.configured && health.galileo.reachable ? "●" : health.galileo.sdk_available ? "◐" : "●"}
              </td>
              <td className="diag-detail">
                {health.galileo.configured && health.galileo.console_url
                  ? <><a href={health.galileo.console_url} target="_blank" rel="noopener noreferrer">monitor</a></>
                  : health.galileo.detail}
              </td>
            </tr>

            <SectionHeader
              title="Tools"
              badge={
                <span className={tOk ? "diag-badge diag-ok" : "diag-badge diag-err"}>
                  {tOk ? "at least one green" : "all unavailable"}
                </span>
              }
            />
            <Row
              label="Google Calendar"
              status={google?.["calendar_read"] === "ok" ? "ok" : "err"}
              detail={google?.["calendar_read"] === "ok" ? "read" : `read: ${String(google?.["calendar_read"] ?? "—")}`}
            />
            <Row
              label="Google Gmail"
              status={google?.["gmail_read"] === "ok" ? "ok" : "err"}
              detail={google?.["gmail_read"] === "ok" ? "read" : `read: ${String(google?.["gmail_read"] ?? "—")}`}
            />
            <Row
              label="Google Tasks"
              status={google?.["tasks_read"] === "ok" && google?.["tasks_write"] === "ok" ? "ok" : google?.["tasks_read"] === "ok" ? "warn" : "err"}
              detail={(() => {
                const r = google?.["tasks_read"] === "ok";
                const w = google?.["tasks_write"] === "ok";
                if (r && w) return "read · write";
                if (r) return `read · write: ${String(google?.["tasks_write"] ?? "—")}`;
                return `read: ${String(google?.["tasks_read"] ?? "—")}`;
              })()}
            />
            <Row
              label="Weather"
              status={health.weather.available ? "ok" : "err"}
              detail={health.weather.detail}
            />
            <Row
              label="News"
              status={health.news.available ? "ok" : "err"}
              detail={health.news.detail}
            />
          </tbody>
        </table>
      )}
    </div>
  );
}
