# Minimal Two-Agent Contract (No Behavior Change Yet)

## Purpose
Define a minimal, implementation-ready contract between:
- Agent A: Daily Digest Orchestrator
- Agent B: Key Highlights Specialist

This contract is design-only for now. Runtime behavior remains unchanged.

## Scope
In scope:
- Data contract between agents
- Invocation timing
- Output format and validation
- Failure handling

Out of scope:
- New runtime loops
- New model calls in production path
- Changes to current digest rendering behavior

## Agent Roles

### Agent A: Daily Digest Orchestrator
Responsibilities:
- Gather observations from existing actions (location, time, weather, news, calendar, tasks, emails).
- Build canonical digest payload.
- Own final terminal and email rendering.
- Provide deterministic fallback behavior.

Contract obligations:
- Must provide Agent B with a normalized, complete payload.
- Must not allow Agent B to mutate source observations.

### Agent B: Key Highlights Specialist
Responsibilities:
- Read-only summarization and prioritization from Agent A payload.
- Return ranked highlights with short rationale labels.

Contract obligations:
- Must use only fields provided by Agent A.
- Must not invent external facts.
- Must return strictly schema-compliant output.

## Handoff Moment
Agent B is called only after Agent A has complete observed data and a canonical payload.

No pre-observation or mid-tool-call handoff.

## Input Schema (Agent A -> Agent B)
JSON object:

{
  "digest_title": "string",
  "date_time": "string",
  "location": "string",
  "weather": "string",
  "news_items": [
    {"title": "string", "source": "string", "url": "string"}
  ],
  "calendar_items": [
    {"summary": "string", "start": "string", "end": "string", "attendees": ["string"]}
  ],
  "task_items": [
    {"title": "string", "status": "string", "due": "string"}
  ],
  "email_items": [
    {"subject": "string", "from": "string", "relation": "string", "vip": "string", "preview": "string"}
  ],
  "preferences": {
    "temperature_unit": "C|F",
    "digest_preferences_summary": "string"
  },
  "constraints": {
    "max_highlights": 5,
    "max_chars_each": 180
  }
}

Notes:
- Empty arrays are allowed.
- All strings should be pre-sanitized by existing redaction rules.

## Output Schema (Agent B -> Agent A)
JSON object:

{
  "highlights": [
    {
      "rank": 1,
      "text": "string",
      "category": "calendar|emails|tasks|weather|news|mixed",
      "evidence": ["short source pointers"]
    }
  ],
  "confidence": "low|medium|high"
}

Validation rules:
- 1 <= highlights.length <= max_highlights
- rank must be contiguous starting at 1
- text length <= max_chars_each
- category must be one of allowed enum values
- evidence must reference input payload fields only

## Error and Fallback Contract
If Agent B output is invalid or empty:
- Agent A logs a contract violation event.
- Agent A uses existing deterministic key-highlights behavior.
- Digest send/render continues (no hard failure).

If Agent B times out:
- Agent A uses existing deterministic key-highlights behavior.

## Determinism and Safety Constraints
- Agent B is read-only and side-effect free.
- No direct tool calls from Agent B in this minimal contract.
- No direct email/calendar/task writes from Agent B.

## Rollout Plan (No Behavior Change Yet)
Phase 0 (current request):
- Keep this contract as documentation only.

Phase 1 (shadow mode):
- Generate Agent B output in parallel and log comparison only.
- Do not use Agent B output for user-facing digest.

### Phase 1 Checklist
- Add `shadow_mode_key_highlights=true` runtime flag (default off).
- Add Agent B call wrapper that accepts only the defined input schema.
- Add JSON schema validator for Agent B output.
- Log per-run comparison fields: `run_id`, `timestamp_utc`, `schema_valid`, `confidence`, `highlights_count`.
- Log delta metrics versus current highlights: overlap ratio, ordering changes, empty-result rate.
- Add timeout guard (for example 2-3s) and route timeout to existing deterministic highlights.
- Ensure logs include no raw sensitive content beyond current redaction policy.
- Add one smoke test for valid output and one for invalid-output fallback.
- Keep terminal/email rendering path unchanged in Phase 1.

Phase 2 (guarded adoption):
- Use Agent B output only when schema-valid and confidence is medium/high.
- Automatic fallback to current logic on any validation failure.

## Acceptance Criteria for Future Implementation
- No regression in section order or formatting.
- No increase in fallback rate for digest generation.
- Key highlights remain grounded in observed payload.
- Email and terminal outputs stay consistent in location and intent.

## Operator Runbook

### Run Shadow Mode Only
- Command:
  - `python main.py --shadow-mode-key-highlights`
- Expected behavior:
  - Digest output remains unchanged.
  - Shadow diagnostics panel appears.
  - Metrics are appended to `.memory/key_highlights_shadow.jsonl`.

### Run Guarded Adoption Mode
- Command:
  - `python main.py --adopt-key-highlights-agent`
- Expected behavior:
  - Agent B highlights are adopted only if promotion gates pass.
  - Otherwise, deterministic highlights remain in use.
  - Shadow metrics are still logged.

### Summarize Shadow Metrics
- Command:
  - `python scripts/summarize_shadow_metrics.py`
- Optional recent-window command:
  - `python scripts/summarize_shadow_metrics.py --tail 50`
- Enforced gate command (non-zero exit on threshold failure):
  - `python scripts/summarize_shadow_metrics.py --enforce-gates --min-records 10 --min-valid-rate 0.95 --max-timeout-rate 0.05 --min-promotion-pass-rate 0.70`
- Reported fields:
  - `valid_rate`
  - `timeout_rate`
  - `avg_overlap`
  - `avg_ordering_changes`
  - `avg_highlights_count`
  - `promotion_pass_rate`

### CI Gate Workflow
- Workflow file:
  - `.github/workflows/shadow-metrics-gate.yml`
- Trigger modes:
  - `pull_request`: requires log file at `ci/key_highlights_shadow.jsonl`; fails if missing.
  - `workflow_dispatch`: accepts optional `log_path` and `tail` inputs.
- Standard CI log contract path:
  - `ci/key_highlights_shadow.jsonl`
- Producer command (run locally before PR checks to refresh CI contract file):
  - `python scripts/prepare_ci_shadow_log.py --source .memory/key_highlights_shadow.jsonl --output ci/key_highlights_shadow.jsonl --tail 50`
- Producer behavior:
  - Uses `.memory/key_highlights_shadow.jsonl` when available.
  - Falls back to existing `ci/key_highlights_shadow.jsonl` if source is unavailable.
  - Fails if neither source nor existing CI contract file is present.
- Default gate thresholds in CI:
  - `min_records=10`
  - `min_valid_rate=0.95`
  - `max_timeout_rate=0.05`
  - `min_promotion_pass_rate=0.70`

### Threshold Raise Policy
- Review cadence:
  - Weekly, after the `Weekly Shadow Metrics Report` workflow artifact is available.
- Raise conditions (all must hold for 2 consecutive weekly reports):
  - `valid_rate >= current threshold + 0.02`.
  - `timeout_rate <= current threshold - 0.01` (for max-based thresholds).
  - `promotion_pass_rate >= current threshold + 0.05`.
  - No observed formatting regressions in terminal/email parity tests.
- Raise method:
  - Tighten one threshold at a time in `.github/workflows/shadow-metrics-gate.yml`.
  - Keep other thresholds unchanged for at least one additional weekly cycle.
- Rollback trigger:
  - If a newly raised threshold fails in 2 consecutive PR runs without functional regressions, revert to previous value and re-evaluate after one week.

### Rollback
- Quick rollback to deterministic highlights:
  - Run without `--adopt-key-highlights-agent`.
- Full disable of shadow diagnostics:
  - Run without `--shadow-mode-key-highlights`.
