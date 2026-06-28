"""Show side-by-side comparison of Agent A vs Agent B highlights for recent runs."""

import argparse
import json
from pathlib import Path

DEFAULT_LOG = Path(__file__).parent.parent / ".memory" / "key_highlights_shadow.jsonl"


def _short(text: str, max_len: int = 80) -> str:
    text = text.strip()
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


def compare(log_path: Path, tail: int = 5) -> None:
    if not log_path.exists():
        print(f"Shadow log not found: {log_path}")
        return

    lines = [l for l in log_path.read_text().splitlines() if l.strip()]
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    recent = records[-tail:]
    if not recent:
        print("No records found.")
        return

    for rec in recent:
        ts = rec.get("timestamp_utc", "unknown")[:19].replace("T", " ")
        run_id = rec.get("run_id", "unknown")[:8]
        overlap = rec.get("overlap_ratio", 0.0)
        ordering = rec.get("ordering_changes", 0)
        confidence = rec.get("confidence", "?")
        timed_out = rec.get("timed_out", False)
        schema_valid = rec.get("schema_valid", False)

        print(f"\n{'═' * 80}")
        print(f"  Run: {run_id}  |  {ts} UTC  |  overlap={overlap:.0%}  ordering_changes={ordering}  confidence={confidence}")
        print(f"  schema_valid={schema_valid}  timed_out={timed_out}")
        print(f"{'─' * 80}")

        a_items = rec.get("agent_a_highlights") or []
        b_items = rec.get("agent_b_highlights") or []
        max_rows = max(len(a_items), len(b_items))

        if not a_items and not b_items:
            print("  (no highlight text logged — upgrade key_highlights_agent.py to capture highlights)")
        else:
            col = 38
            print(f"  {'Agent A (main pipeline)':<{col}}  {'Agent B (shadow)'}")
            print(f"  {'─' * col}  {'─' * col}")
            for i in range(max_rows):
                a = _short(a_items[i], col) if i < len(a_items) else ""
                b = _short(b_items[i], col) if i < len(b_items) else ""
                marker = "  " if i < len(a_items) and i < len(b_items) and a_items[i].strip().lower() == b_items[i].strip().lower() else "≠ "
                print(f"{marker} {a:<{col}}  {b}")

    print(f"\n{'═' * 80}")
    print(f"Showing last {len(recent)} of {len(records)} runs. Log: {log_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Agent A vs Agent B shadow highlights")
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--tail", type=int, default=5, help="Number of recent runs to show")
    args = parser.parse_args()
    compare(args.log_path, tail=args.tail)


if __name__ == "__main__":
    main()
