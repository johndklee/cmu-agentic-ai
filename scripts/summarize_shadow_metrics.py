#!/usr/bin/env python3
"""Summarize key-highlights shadow/adoption metrics from JSONL logs."""

import argparse
import json
import sys
from pathlib import Path


DEFAULT_LOG_PATH = Path(__file__).resolve().parents[1] / ".memory" / "key_highlights_shadow.jsonl"


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_records(log_path: Path, tail: int = 0):
    if not log_path.exists():
        return []

    records = []
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                records.append(parsed)

    if tail > 0:
        return records[-tail:]
    return records


def summarize(records):
    total = len(records)
    if total == 0:
        return {
            "total": 0,
            "valid_rate": 0.0,
            "timeout_rate": 0.0,
            "avg_overlap": 0.0,
            "avg_ordering_changes": 0.0,
            "avg_highlights_count": 0.0,
            "promotion_pass_rate": 0.0,
        }

    valid = sum(1 for r in records if bool(r.get("schema_valid", False)))
    timed_out = sum(1 for r in records if bool(r.get("timed_out", False)))

    overlap_values = [_safe_float(r.get("overlap_ratio", 0.0), 0.0) for r in records]
    ordering_values = [_safe_int(r.get("ordering_changes", 0), 0) for r in records]
    highlight_counts = [_safe_int(r.get("highlights_count", 0), 0) for r in records]

    promoted = sum(
        1
        for r in records
        if bool(r.get("schema_valid", False))
        and str(r.get("confidence", "low")) in {"medium", "high"}
        and not bool(r.get("timed_out", False))
        and _safe_float(r.get("overlap_ratio", 0.0), 0.0) >= 0.6
        and _safe_int(r.get("ordering_changes", 0), 0) <= 2
        and _safe_int(r.get("highlights_count", 0), 0) > 0
        and not bool(r.get("empty_result", False))
    )

    return {
        "total": total,
        "valid_rate": valid / total,
        "timeout_rate": timed_out / total,
        "avg_overlap": sum(overlap_values) / total,
        "avg_ordering_changes": sum(ordering_values) / total,
        "avg_highlights_count": sum(highlight_counts) / total,
        "promotion_pass_rate": promoted / total,
    }


def evaluate_gates(stats, *, min_records, min_valid_rate, max_timeout_rate, min_promotion_pass_rate):
    failures = []

    if stats["total"] < min_records:
        failures.append(
            f"records gate failed: got {stats['total']}, required >= {min_records}"
        )
    if stats["valid_rate"] < min_valid_rate:
        failures.append(
            f"valid_rate gate failed: got {stats['valid_rate']:.3f}, required >= {min_valid_rate:.3f}"
        )
    if stats["timeout_rate"] > max_timeout_rate:
        failures.append(
            f"timeout_rate gate failed: got {stats['timeout_rate']:.3f}, required <= {max_timeout_rate:.3f}"
        )
    if stats["promotion_pass_rate"] < min_promotion_pass_rate:
        failures.append(
            "promotion_pass_rate gate failed: "
            f"got {stats['promotion_pass_rate']:.3f}, required >= {min_promotion_pass_rate:.3f}"
        )

    return failures


def main():
    parser = argparse.ArgumentParser(description="Summarize key-highlights shadow metrics")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH), help="Path to shadow JSONL log")
    parser.add_argument("--tail", type=int, default=0, help="Only summarize the last N records")
    parser.add_argument(
        "--min-records",
        type=int,
        default=1,
        help="Minimum records required for gate evaluation",
    )
    parser.add_argument(
        "--min-valid-rate",
        type=float,
        default=0.95,
        help="Minimum allowed valid_rate",
    )
    parser.add_argument(
        "--max-timeout-rate",
        type=float,
        default=0.05,
        help="Maximum allowed timeout_rate",
    )
    parser.add_argument(
        "--min-promotion-pass-rate",
        type=float,
        default=0.70,
        help="Minimum allowed promotion_pass_rate",
    )
    parser.add_argument(
        "--enforce-gates",
        action="store_true",
        help="Exit non-zero if quality gates fail",
    )
    parser.add_argument(
        "--github-annotations",
        action="store_true",
        help="Emit GitHub Actions error annotations for gate failures",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Optional path to write metrics and gate results as JSON",
    )
    args = parser.parse_args()

    log_path = Path(args.log_path)
    records = load_records(log_path, tail=max(0, args.tail))
    stats = summarize(records)

    print(f"log_path={log_path}")
    print(f"records={stats['total']}")
    print(f"valid_rate={stats['valid_rate']:.3f}")
    print(f"timeout_rate={stats['timeout_rate']:.3f}")
    print(f"avg_overlap={stats['avg_overlap']:.3f}")
    print(f"avg_ordering_changes={stats['avg_ordering_changes']:.3f}")
    print(f"avg_highlights_count={stats['avg_highlights_count']:.3f}")
    print(f"promotion_pass_rate={stats['promotion_pass_rate']:.3f}")

    failures = evaluate_gates(
        stats,
        min_records=max(0, args.min_records),
        min_valid_rate=args.min_valid_rate,
        max_timeout_rate=args.max_timeout_rate,
        min_promotion_pass_rate=args.min_promotion_pass_rate,
    )

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "log_path": str(log_path),
            "tail": max(0, args.tail),
            "thresholds": {
                "min_records": max(0, args.min_records),
                "min_valid_rate": args.min_valid_rate,
                "max_timeout_rate": args.max_timeout_rate,
                "min_promotion_pass_rate": args.min_promotion_pass_rate,
            },
            "stats": stats,
            "gate_failures": failures,
            "gates_passed": not failures,
        }
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=True, indent=2)
            handle.write("\n")
        print(f"output_json={output_path}")

    if failures:
        print("gates=FAIL")
        for failure in failures:
            print(f"gate_failure={failure}")
            if args.github_annotations:
                print(f"::error title=Shadow Metrics Gate::{failure}")
        if args.enforce_gates:
            return 1
    else:
        print("gates=PASS")

    return 0


if __name__ == "__main__":
    sys.exit(main())
