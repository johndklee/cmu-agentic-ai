# Requires: pip install python-dotenv rich (install anthropic when using Anthropic provider)
import argparse
import importlib.util
import os

from diagnostics import (
    check_ollama_reachable,
    check_anthropic_reachable,
    check_google_diagnostics,
    is_truthy_env,
)
from formatting import display_panel
from digest_rendering import render_email_digest_markup, render_terminal_digest
from llm_client import (
    ANTHROPIC_DEFAULT_MODEL,
    OLLAMA_DEFAULT_MODEL,
    _fetch_ollama_model_context_window,
    _resolve_ollama_num_ctx,
)
from memory_store import EpisodicMemoryStore
from user_interactions import maybe_send_digest_email
from workflow_controller import run_workflow_digest
from preferences import (
    backfill_structured_preferences_from_history,
    load_preferences,
    reset_all_preferences,
    reset_digest_preferences,
    save_preferences,
    summarize_digest_preferences,
)
from actions.location_action import (
    current_location,
    format_location,
    resolve_session_location_from_preferences,
)


def _append_terminal_stale_note(answer: str, has_stale_retrieval: bool) -> str:
    """Append stale-retrieval warning note to terminal digest when needed."""
    if not has_stale_retrieval:
        return answer
    note = "[bold]Note:[/bold] Retrieved corrections include items older than 60 days; verify before applying."
    lowered = (answer or "").lower()
    if "older than 60 days" in lowered and "note:" in lowered:
        return answer
    return (answer or "").rstrip() + "\n\n" + note


def _append_email_stale_note(answer: str, has_stale_retrieval: bool) -> str:
    """Append stale-retrieval warning note to email digest markup when needed."""
    if not has_stale_retrieval:
        return answer
    note = "Note: Retrieved corrections include items older than 60 days; verify before applying."
    lowered = (answer or "").lower()
    if "older than 60 days" in lowered and "note:" in lowered:
        return answer
    return (answer or "").rstrip() + "\n" + note


def _run_workflow_daily_digest() -> str:
    """Run the LangGraph workflow and render its digest output for the user."""
    try:
        state = run_workflow_digest({})
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph workflow is required but unavailable. Install langgraph to continue."
        ) from exc
    digest_output = state.get("digest_output") if isinstance(state, dict) else {}
    if not isinstance(digest_output, dict) or not digest_output:
        raise RuntimeError("LangGraph workflow completed without digest_output.")

    terminal_answer = _append_terminal_stale_note(
        render_terminal_digest(digest_output),
        False,
    )
    email_subject = digest_output.get("title", "Daily Digest")
    email_answer = _append_email_stale_note(render_email_digest_markup(digest_output), False)
    maybe_send_digest_email(
        terminal_answer,
        subject=email_subject,
        email_body=email_answer,
    )
    display_panel(
        f"[bold]Final Answer:[/bold] {terminal_answer}",
        title="Done",
        border_style="magenta",
    )
    return terminal_answer


def _parse_args() -> argparse.Namespace:
    """Parse CLI options for maintenance and runtime behaviors."""
    parser = argparse.ArgumentParser(description="Daily Digest assistant runtime")
    parser.add_argument(
        "--reset-preferences",
        choices=["all", "digest"],
        default="",
        help="Reset saved preferences and exit. Use 'all' or 'digest'.",
    )
    parser.add_argument(
        "--galileo-observability",
        action="store_true",
        help="Enable Galileo observability to emit observability events.",
    )
    parser.add_argument(
        "--galileo-include-content",
        action="store_true",
        help="Include raw prompt/response in Galileo observability events (requires --galileo-observability).",
    )
    return parser.parse_args()


def _show_startup_diagnostics(preferences: dict) -> None:
    """Display LLM + memory backend runtime status at startup."""
    memory_status = EpisodicMemoryStore().backend_status()
    _ = preferences
    galileo_enabled = is_truthy_env(os.getenv("GALILEO_OBSERVABILITY_ENABLED"))
    galileo_include_content = is_truthy_env(os.getenv("GALILEO_INCLUDE_CONTENT"))
    galileo_sdk_available = importlib.util.find_spec("galileo") is not None
    google_live_probe = is_truthy_env(os.getenv("GOOGLE_DIAGNOSTICS_LIVE"))
    google_status = check_google_diagnostics(live_probe=google_live_probe)
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip().rstrip("/")
    ollama_reachable, ollama_detail = check_ollama_reachable(ollama_base_url)

    strategist_model = (
        os.getenv("OLLAMA_MODEL", "").strip()
        or OLLAMA_DEFAULT_MODEL
    )
    critic_model = (
        os.getenv("ANTHROPIC_MODEL", "").strip()
        or ANTHROPIC_DEFAULT_MODEL
    )
    anthropic_reachable, anthropic_detail, anthropic_input_limit, anthropic_output_limit = check_anthropic_reachable(critic_model)

    model_ctx = _fetch_ollama_model_context_window(ollama_base_url, strategist_model)
    num_ctx = _resolve_ollama_num_ctx()
    effective_ctx = min(num_ctx, model_ctx) if model_ctx and num_ctx else (num_ctx or model_ctx)

    lines = [
        "Ollama:",
        f"  Strategist model: {strategist_model}",
        f"  URL: {ollama_base_url}",
        f"  Reachable: {'yes' if ollama_reachable else 'no'} ({ollama_detail})",
    ]

    if isinstance(effective_ctx, int) and effective_ctx > 0:
        lines.append(f"  Effective context window: {effective_ctx}")

    if isinstance(model_ctx, int) and model_ctx > 0:
        lines.append(f"  Model context window: {model_ctx}")

    if isinstance(num_ctx, int) and num_ctx > 0:
        lines.append(f"  num_ctx override: {num_ctx}")

    lines.extend(
        [
            "",
            "Claude:",
            f"  Critic model: {critic_model}",
            f"  Reachable: {'yes' if anthropic_reachable else 'no'} ({anthropic_detail})",
        ]
    )

    if isinstance(anthropic_input_limit, int) and anthropic_input_limit > 0:
        lines.append(f"  Input token limit: {anthropic_input_limit}")
    if isinstance(anthropic_output_limit, int) and anthropic_output_limit > 0:
        lines.append(f"  Output token limit: {anthropic_output_limit}")

    lines.extend(
        [
            "",
            "Galileo:",
            f"  Enabled: {'yes' if galileo_enabled else 'no'}",
            f"  Include raw content: {'yes' if galileo_include_content else 'no'}",
            f"  SDK available: {'yes' if galileo_sdk_available else 'no'}",
        ]
    )

    lines.extend(
        [
            "",
            "Google:",
            f"  OAuth client file present: {'yes' if google_status.get('oauth_client_present') else 'no'}",
            f"  Token file present: {'yes' if google_status.get('token_present') else 'no'}",
            f"  Token valid (not expired): {'yes' if google_status.get('token_valid') else 'no'}",
            f"  Token refreshable: {'yes' if google_status.get('token_refreshable') else 'no'}",
            f"  Required scopes configured: {google_status.get('scopes_configured')}",
            f"  Token scopes cover required: {'yes' if google_status.get('token_scopes_covered') else 'no'}",
            f"  Live probe enabled: {'yes' if google_status.get('live_probe_enabled') else 'no'}",
        ]
    )

    if google_status.get("import_error"):
        lines.append(f"  Import error: {google_status.get('import_error')}")
    if google_status.get("live_probe_enabled"):
        lines.append(f"  Calendar API probe: {google_status.get('calendar_probe')}")
        lines.append(f"  Gmail API probe: {google_status.get('gmail_probe')}")
        lines.append(f"  Tasks API probe: {google_status.get('tasks_probe')}")

    lines.extend(
        [
            "",
            "Chroma:",
            "  Vendor: Chroma",
            f"  Vector backend enabled: {memory_status.get('vector_enabled')}",
            f"  Vector backend error: {memory_status.get('backend_error') or 'none'}",
        ]
    )
    diagnostics = "\n".join(lines)
    display_panel(diagnostics, title="Startup Diagnostics", border_style="blue")


def main() -> None:
    """Initialize preferences, run the daily digest question, and capture feedback."""
    args = _parse_args()
    
    # Set Galileo observability environment variables if requested
    if args.galileo_observability:
        os.environ["GALILEO_OBSERVABILITY_ENABLED"] = "1"
    if args.galileo_include_content:
        os.environ["GALILEO_INCLUDE_CONTENT"] = "1"
    
    if args.reset_preferences == "all":
        reset_all_preferences()
        display_panel(
            "Reset all saved preferences to defaults.",
            title="Preferences Reset",
            border_style="yellow",
        )
        return
    if args.reset_preferences == "digest":
        reset_digest_preferences()
        display_panel(
            "Reset digest-only preferences (feedback, summary, digest email toggle, temperature unit).",
            title="Preferences Reset",
            border_style="yellow",
        )
        return
    # Bootstrap persisted preferences and session-level location selection.
    preferences = load_preferences()
    _show_startup_diagnostics(preferences)
    memory_status = EpisodicMemoryStore().backend_status()
    if not memory_status.get("vector_enabled"):
        raise RuntimeError(
            "Vector backend is required and is currently unavailable. "
            f"Details: {memory_status.get('backend_error') or 'unknown error'}"
        )
    previous_detected_location = preferences.get("last_detected_location")
    backfilled = backfill_structured_preferences_from_history(preferences)
    location_pref_changed = resolve_session_location_from_preferences(preferences, display_panel)
    detected_location_changed = preferences.get("last_detected_location") != previous_detected_location
    refreshed_summary = summarize_digest_preferences(preferences)
    summary_changed = refreshed_summary != preferences.get("digest_preferences_summary", "")
    preferences["digest_preferences_summary"] = refreshed_summary
    if backfilled or location_pref_changed or detected_location_changed or summary_changed:
        save_preferences(preferences)
    display_panel(
        preferences.get("digest_preferences_summary", "No saved digest preferences yet."),
        title="Saved Digest Preferences",
        border_style="blue",
    )
    display_panel(
        f"Using session location: {format_location(current_location())}",
        title="Location Preference",
        border_style="blue",
    )
    question = "Create a daily digest for me"
    print(f"\nAuto question: {question}")
    answer = _run_workflow_daily_digest()
    if answer:
        return

if __name__ == "__main__":
    main()