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
            <tr className="diag-agent-row">
              <td className="diag-label diag-agent-label">↳ Model</td>
              <td className={`diag-icon ${health.ollama_model.available ? "diag-ok" : "diag-err"}`}>●</td>
              <td className="diag-detail">
                <span>{health.ollama_model.detail}</span>
                <span className="diag-agent-purpose">
                  {health.ollama_model.available && health.ollama_model.context_window && ` · ${health.ollama_model.context_window} context`}
                  {health.ollama_model.available && health.ollama_model.think_disabled && " · no_think"}
                  {health.ollama_model.available && " · Ranking Strategist"}
                </span>
              </td>
            </tr>
            <Row
              label="Anthropic (optional)"
              status={health.anthropic.reachable ? "ok" : "warn"}
              detail={health.anthropic.reachable ? health.anthropic.detail : `${health.anthropic.detail} — critic will use Ollama`}
            />
            <tr className="diag-agent-row">
              <td className="diag-label diag-agent-label">↳ Model</td>
              <td className={`diag-icon ${health.anthropic.reachable ? "diag-ok" : "diag-warn"}`}>●</td>
              <td className="diag-detail">
                <span>{health.anthropic.model}</span>
                <span className="diag-agent-purpose">
                  {health.anthropic.reachable
                    ? ` · ${health.anthropic.context_window ?? "200K"} context · Ranking Critic`
                    : " — not active"}
                </span>
              </td>
            </tr>

            <SectionHeader
              title="Frameworks"
              badge={
                <span className={frOk ? "diag-badge diag-ok" : "diag-badge diag-err"}>
                  {frOk ? "all green" : "action required"}
                </span>
              }
            />
            <Row
              label="Episodic Memory"
              status={health.memory["vector_enabled"] ? "ok" : "err"}
              detail={
                health.memory["vector_enabled"]
                  ? "ChromaDB vector store · stores user feedback as embeddings, retrieved each run to influence rankings"
                  : String(health.memory["backend_error"] || "unavailable")
              }
            />
            <tr className="diag-agent-row">
              <td className="diag-label diag-agent-label">↳ Embedding Model</td>
              <td className={`diag-icon ${health.huggingface.model_cached ? "diag-ok" : "diag-warn"}`}>●</td>
              <td className="diag-detail">
                <span>{String(health.memory["embedding_model"] || health.huggingface.embedding_model || "unknown")}</span>
                <span className="diag-agent-purpose">
                  {" · "}
                  {health.huggingface.model_cached ? "cached locally" : "not cached — will download on first use"}
                  {!health.huggingface.token_configured && " · HF token not set (rate limited)"}
                </span>
              </td>
            </tr>
            <Row
              label="CrewAI"
              status={health.crewai.available ? "ok" : "err"}
              detail={`${health.crewai.detail} · defines Ranking Strategist and Critic as structured agents with roles, goals, and tasks`}
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
              detail={`${health.langchain.detail} · @tool decorator for Critic scoring functions`}
            />
            {([
              ["meeting_proximity_tool",    "scores candidates by how close calendar events are to the top"],
              ["vip_alignment_tool",        "scores candidates by how well VIP-involved items are prioritized"],
              ["episodic_consistency_tool", "scores candidates against past episodic corrections from ChromaDB"],
            ] as [string, string][]).map(([name, purpose]) => (
              <tr key={name} className="diag-agent-row">
                <td className="diag-label diag-agent-label">↳ {name}</td>
                <td className={`diag-icon ${health.langchain.available ? "diag-ok" : "diag-err"}`}>●</td>
                <td className="diag-detail diag-agent-purpose">{purpose}</td>
              </tr>
            ))}
            <Row
              label="LangGraph"
              status={health.langgraph.available ? "ok" : "err"}
              detail={`${health.langgraph.detail} · orchestrates the digest workflow as a directed node graph`}
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
              detail={`${health.fastmcp.detail} · hosts the Tree-of-Thought branch state server on port 8001`}
            />
            <tr className="diag-agent-row">
              <td className="diag-label diag-agent-label">↳ Branch State</td>
              <td className={`diag-icon ${health.mcp.available ? "diag-ok" : "diag-err"}`}>●</td>
              <td className="diag-detail">
                <span>{health.mcp.detail}</span>
                <span className="diag-agent-purpose"> · shares candidate ranking state between LangGraph nodes</span>
              </td>
            </tr>

            <SectionHeader
              title="Shadow Mode"
              badge={
                <span className={health.shadow.gates_passed === true ? "diag-badge diag-ok" : health.shadow.gates_passed === false ? "diag-badge diag-err" : "diag-badge diag-optional"}>
                  {health.shadow.gates_passed === true ? "gates passing" : health.shadow.gates_passed === false ? "gates failing" : "no data yet"}
                </span>
              }
            />
            <Row
              label="Agent B (shadow)"
              status={health.shadow.enabled ? "ok" : "err"}
              detail="runs silently alongside every digest · read-only, never shown to user"
            />
            <tr className="diag-agent-row">
              <td className="diag-label diag-agent-label">↳ Local runs</td>
              <td className={`diag-icon ${health.shadow.run_count > 0 ? "diag-ok" : "diag-warn"}`}>●</td>
              <td className="diag-detail">
                {health.shadow.run_count > 0 ? `${health.shadow.run_count} run${health.shadow.run_count !== 1 ? "s" : ""} logged` : "no runs yet — run a digest to populate"}
              </td>
            </tr>
            {health.shadow.metrics_total > 0 && (
              <tr className="diag-agent-row">
                <td className="diag-label diag-agent-label">↳ CI metrics</td>
                <td className={`diag-icon ${health.shadow.gates_passed ? "diag-ok" : "diag-err"}`}>●</td>
                <td className="diag-detail">
                  <span>{health.shadow.metrics_total} runs</span>
                  <span className="diag-agent-purpose">
                    {health.shadow.valid_rate != null && ` · schema ${(health.shadow.valid_rate * 100).toFixed(0)}%`}
                    {health.shadow.timeout_rate != null && ` · timeout ${(health.shadow.timeout_rate * 100).toFixed(0)}%`}
                    {health.shadow.avg_overlap != null && ` · overlap ${(health.shadow.avg_overlap * 100).toFixed(0)}%`}
                    {health.shadow.promotion_pass_rate != null && ` · promotion ${(health.shadow.promotion_pass_rate * 100).toFixed(0)}%`}
                  </span>
                </td>
              </tr>
            )}

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
