import { useEffect, useRef, useState } from "react";
import { fetchLastDigest, fetchDigestStatus, streamDigest, NODE_LABELS, type DigestResponse, type DigestStep } from "../api";
import { ContextBar } from "../components/ContextBar";
import { DigestPanel } from "../components/DigestPanel";
import { FeedbackForm } from "../components/FeedbackForm";
import { DiagnosticsPanel } from "../components/DiagnosticsPanel";
import { PreferencesPanel } from "../components/PreferencesPanel";

type State = "idle" | "loading" | "done" | "error";

interface Props {
  onEditSettings: () => void;
  contextRefresh?: number;
}

export function DigestPage({ onEditSettings, contextRefresh = 0 }: Props) {
  const [status, setStatus] = useState<State>("idle");
  const [steps, setSteps] = useState<DigestStep[]>([]);
  const [digest, setDigest] = useState<DigestResponse | null>(null);
  const [error, setError] = useState("");
  const [feedbackDone, setFeedbackDone] = useState(false);
  const [diagnosticsRefresh, setDiagnosticsRefresh] = useState(0);
  const [prefsRefresh, setPrefsRefresh] = useState(0);
  const cancelRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    fetchDigestStatus().then((s) => {
      if (s.running) {
        // A run is in progress — show accumulated steps and connect to the stream
        const prior = s.steps.map(({ node }) => ({
          label: NODE_LABELS[node] ?? `Running ${node}…`,
        }));
        setSteps(prior);
        setStatus("loading");
        cancelRef.current = streamDigest(
          (step) => setSteps((prev) => [...prev, step]),
          (d) => { setDigest(d); setStatus("done"); },
          (msg) => { setError(msg); setStatus("error"); },
        );
      } else {
        fetchLastDigest()
          .then((d) => { if (d) { setDigest(d); setStatus("done"); } })
          .catch(() => {});
      }
    }).catch(() => {
      fetchLastDigest()
        .then((d) => { if (d) { setDigest(d); setStatus("done"); } })
        .catch(() => {});
    });
    return () => cancelRef.current?.();
  }, []);

  function runDigest() {
    cancelRef.current?.();
    setStatus("loading");
    setSteps([]);
    setFeedbackDone(false);
    setDiagnosticsRefresh((n) => n + 1);

    cancelRef.current = streamDigest(
      (step) => setSteps((prev) => [...prev, step]),
      (d) => { setDigest(d); setStatus("done"); },
      (msg) => { setError(msg); setStatus("error"); },
    );
  }

  return (
    <div className="page">
      <ContextBar refresh={contextRefresh} />
      <div className="digest-controls">
        <button className="run-digest-btn" onClick={runDigest} disabled={status === "loading"}>
          {status === "loading" ? "Generating…" : "Generate Digest"}
        </button>
        {digest?.generated_at && (
          <p className="last-refreshed">
            Last refreshed: {new Date(digest.generated_at).toLocaleString()}
          </p>
        )}
      </div>

      {status === "loading" && (
        <div className="progress-log">
          {steps.length === 0
            ? <p className="progress-step">Starting…</p>
            : steps.map((s, i) => (
                <p key={i} className={`progress-step${i === steps.length - 1 ? " progress-step--active" : ""}`}>
                  {i === steps.length - 1 ? "⏳ " : "✓ "}{s.label}
                  {s.llm && <span className="progress-step-llm"> · {s.llm}</span>}
                </p>
              ))
          }
        </div>
      )}

      {status === "error" && <p className="error">Failed to load digest: {error}</p>}
      {status === "done" && digest && (
        <>
          <DigestPanel digest={digest} />
          {!feedbackDone && <FeedbackForm onDone={() => { setFeedbackDone(true); setPrefsRefresh((n) => n + 1); }} />}
          {feedbackDone && <p className="feedback-done">Feedback saved.</p>}
        </>
      )}
      <PreferencesPanel onEdit={onEditSettings} refresh={prefsRefresh} />
      <DiagnosticsPanel refresh={diagnosticsRefresh} />
    </div>
  );
}
