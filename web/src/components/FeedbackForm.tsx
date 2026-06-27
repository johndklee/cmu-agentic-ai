import { useState } from "react";
import { submitFeedback } from "../api";

interface Props {
  onDone: () => void;
}

export function FeedbackForm({ onDone }: Props) {
  const [satisfied, setSatisfied] = useState<boolean | null>(null);
  const [note, setNote] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit() {
    if (satisfied === null) return;
    try {
      await submitFeedback(satisfied, note);
      setSubmitted(true);
      onDone();
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  if (submitted) return <p className="feedback-done">Thanks for your feedback!</p>;

  return (
    <div className="feedback-form">
      <p>Are you satisfied with today's digest?</p>
      <div className="feedback-buttons">
        <button
          className={satisfied === true ? "active" : ""}
          onClick={() => setSatisfied(true)}
        >
          👍 Yes
        </button>
        <button
          className={satisfied === false ? "active" : ""}
          onClick={() => setSatisfied(false)}
        >
          👎 No
        </button>
      </div>
      {satisfied === false && (
        <textarea
          placeholder="How can we improve the digest?"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
        />
      )}
      {satisfied !== null && (
        <button className="submit-btn" onClick={handleSubmit}>
          Submit
        </button>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
