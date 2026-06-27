import { type DigestResponse, type DigestItem } from "../api";

function LinkedItem({ item }: { item: DigestItem }) {
  if (!item.url) return <>{item.text}</>;
  const label = item.label ?? item.text;
  const detail = item.label ? item.text.slice(item.label.length).trimStart() : "";
  return (
    <>
      <a href={item.url} target="_blank" rel="noopener noreferrer">{label}</a>
      {detail && <span> {detail}</span>}
    </>
  );
}

const SECTION_LABELS: Record<string, string> = {
  weather: "Weather",
  key_highlights: "Key Highlights",
  tasks: "Tasks",
  calendar: "Calendar",
  emails: "Emails",
  news: "News",
};

const SECTION_ORDER = ["key_highlights", "tasks", "calendar", "emails", "news"];

interface Props {
  digest: DigestResponse;
}

export function DigestPanel({ digest }: Props) {
  return (
    <div className="digest-panel">
      <h1>{digest.title}</h1>
      {SECTION_ORDER.map((key) => {
        const items = digest.sections[key as keyof typeof digest.sections] ?? [];
        return (
          <section key={key} className="digest-section">
            <h2>{SECTION_LABELS[key]}</h2>
            {items.length === 0 ? (
              <p className="empty">No data</p>
            ) : (
              <ul>
                {items.map((item, i) => (
                  <li key={i}><LinkedItem item={item} /></li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
