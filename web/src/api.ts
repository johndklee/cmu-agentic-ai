const BASE = "/api";

export interface DigestItem {
  text: string;
  url?: string;
  label?: string;
}

export interface DigestResponse {
  title: string;
  location: string;
  date: string;
  time: string;
  generated_at?: string;
  sections: {
    weather: DigestItem[];
    news: DigestItem[];
    calendar: DigestItem[];
    tasks: DigestItem[];
    emails: DigestItem[];
    key_highlights: DigestItem[];
  };
}

export interface HealthResponse {
  ollama: { reachable: boolean; detail: string; url: string };
  ollama_model: { available: boolean; model: string; detail: string; context_window?: string | null; think_disabled?: boolean };
  anthropic: { reachable: boolean; detail: string; context_window?: string };
  google: Record<string, unknown>;
  memory: Record<string, unknown>;
  huggingface: {
    token_configured: boolean;
    embedding_model: string;
    model_cached: boolean;
    cache_path: string | null;
  };
  galileo: {
    sdk_available: boolean;
    console_url: string | null;
    api_key_set: boolean;
    enabled: boolean;
    configured: boolean;
    reachable: boolean;
    detail: string;
  };
  crewai: {
    available: boolean;
    version: string | null;
    detail: string;
    agents: { role: string; provider: string; model: string; endpoint: string; purpose: string }[];
  };
  langchain: {
    available: boolean;
    version: string | null;
    detail: string;
  };
  langgraph: {
    available: boolean;
    version: string | null;
    detail: string;
    graph: {
      nodes: { id: string; label: string; description: string }[];
      edges: { from: string; to: string; type: string; condition?: string }[];
    } | null;
  };
  fastmcp: {
    available: boolean;
    version: string | null;
    detail: string;
  };
  mcp: {
    available: boolean;
    port: number | null;
    detail: string;
  };
  weather: { available: boolean; detail: string };
  news: { available: boolean; detail: string };
}

export interface Preferences {
  user_name: string;
  user_email: string;
  user_email_aliases: string[];
  vip_email_addresses: string[];
  email_daily_digest: boolean | null;
  temperature_unit: string;
  preferred_location_text: string;
  digest_preferences_summary: string;
  preferred_highlight_count: number;
}

export async function fetchLastDigest(): Promise<DigestResponse | null> {
  const res = await fetch(`${BASE}/digest/last`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function fetchDigest(): Promise<DigestResponse> {
  const res = await fetch(`${BASE}/digest`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export const NODE_LABELS: Record<string, string> = {
  fetcher:        "Fetching calendar, email, tasks, news & weather…",
  retrieval:      "Retrieving episodic memory corrections…",
  strategist:     "Level 1 ToT: generating 5 candidate rankings…",
  critic:         "Level 1 ToT: scoring all 5, pruning to top 2…",
  strategist_l2:  "Level 2 ToT: refining top 2 candidates (2 variants each)…",
  synthesize:     "Synthesizing best digest from refined candidates…",
  feedback:       "Recording feedback context…",
};

export interface DigestStep {
  label: string;
  llm?: string;
}

export function streamDigest(
  onStep: (step: DigestStep) => void,
  onDone: (digest: DigestResponse) => void,
  onError: (msg: string) => void,
): () => void {
  const es = new EventSource(`${BASE}/digest/stream`);

  es.onmessage = (e) => {
    const data = JSON.parse(e.data) as {
      node: string;
      state?: { node_llm_info?: Record<string, string> };
      digest?: DigestResponse;
      error?: string;
    };
    if (data.node === "__error__") {
      es.close();
      onError(data.error ?? "Unknown error");
    } else if (data.node === "__digest__" && data.digest) {
      onDone(data.digest);
    } else if (data.node === "__done__") {
      es.close();
    } else {
      const label = NODE_LABELS[data.node] ?? `Running ${data.node}…`;
      const llmInfo = data.state?.node_llm_info ?? {};
      const llm = llmInfo[data.node];
      onStep({ label, llm });
    }
  };

  es.onerror = () => {
    es.close();
    onError("Connection to server lost.");
  };

  return () => es.close();
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${BASE}/health`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function submitFeedback(satisfied: boolean, improvement_note = ""): Promise<void> {
  const res = await fetch(`${BASE}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ satisfied, improvement_note }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function resetAllPreferences(): Promise<void> {
  const res = await fetch(`${BASE}/preferences/reset-all`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
}

export async function resetDigestPreferences(): Promise<void> {
  const res = await fetch(`${BASE}/preferences/reset-digest`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
}

export async function clearMemory(): Promise<{ cleared: number }> {
  const res = await fetch(`${BASE}/memory`, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export interface ContextInfo {
  location: string;
  date: string;
  time: string;
  weather: string | null;
}

export async function fetchContext(): Promise<ContextInfo> {
  const res = await fetch(`${BASE}/context`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function fetchPreferences(): Promise<Preferences> {
  const res = await fetch(`${BASE}/preferences`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function savePreferences(updates: Partial<Preferences>): Promise<void> {
  const res = await fetch(`${BASE}/preferences`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error(await res.text());
}
