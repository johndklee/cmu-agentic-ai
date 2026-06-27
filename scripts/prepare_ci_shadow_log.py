#!/usr/bin/env python3
"""Prepare CI shadow metrics log at the repository contract path."""

import argparse
import json
import sys
from pathlib import Path


DEFAULT_SOURCE = Path(__file__).resolve().parents[1] / ".memory" / "key_highlights_shadow.jsonl"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "ci" / "key_highlights_shadow.jsonl"


def _load_records(path: Path):
    records = []
    if not path.exists():
        return records

    with path.open("r", encoding="utf-8") as handle:
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
    return records


def _write_records(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=True))
            handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Prepare CI shadow metrics log")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="Source JSONL log path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output CI JSONL log path")
    parser.add_argument("--tail", type=int, default=50, help="Keep only last N source records (0 = all)")
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output)

    source_records = _load_records(source)
    if source_records:
        if args.tail > 0:
            source_records = source_records[-args.tail:]
        _write_records(output, source_records)
        print(f"prepared_from=source")
        print(f"source_path={source}")
        print(f"output_path={output}")
        print(f"records={len(source_records)}")
        return 0

    output_records = _load_records(output)
    if output_records:
        print("prepared_from=existing_output")
        print(f"source_path={source}")
        print(f"output_path={output}")
        print(f"records={len(output_records)}")
        return 0

    print("prepared_from=none")
    print(f"source_path={source}")
    print(f"output_path={output}")
    print("records=0")
    print("error=No source shadow log found and no existing CI log present")
    return 1


if __name__ == "__main__":
    sys.exit(main())
