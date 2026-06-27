"""User feedback agent for the workflow state graph."""

from datetime import datetime, timezone

from actions.location_action import current_location, format_location
from episodic_context import (
    extract_meeting_context_for_episode,
    extract_original_ranking_for_episode,
    extract_sender_email_for_episode,
)
from formatting import display_panel
from memory_store import EpisodicMemoryStore, infer_correction_type
from preferences import (
    apply_structured_preferences_from_feedback,
    get_user_identity,
    get_vip_emails,
    load_preferences,
    save_preferences,
    summarize_digest_preferences,
)
from workflow_state import WorkflowState


def apply_feedback(state: WorkflowState, satisfied: bool, improvement_note: str = "") -> WorkflowState:
    """Persist feedback from the web UI into preferences and episodic memory."""
    next_state: WorkflowState = dict(state)
    preferences = load_preferences()

    feedback = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "satisfied": satisfied,
        "improvement_note": improvement_note,
    }
    preferences.setdefault("digest_feedback", []).append(feedback)
    apply_structured_preferences_from_feedback(preferences, improvement_note)
    preferences["digest_preferences_summary"] = summarize_digest_preferences(preferences)
    save_preferences(preferences)

    if improvement_note:
        identity = get_user_identity(preferences)
        vip_emails = get_vip_emails(preferences)
        memory_store = EpisodicMemoryStore()
        episode = {
            "timestamp_utc": feedback["timestamp_utc"],
            "correction_text": improvement_note,
            "correction_type": infer_correction_type(improvement_note),
            "satisfied": False,
            "source": "digest_feedback",
            "location": format_location(current_location()),
            "sender_email": extract_sender_email_for_episode(improvement_note),
            "meeting_context": extract_meeting_context_for_episode(),
            "original_ranking": extract_original_ranking_for_episode(improvement_note),
            "user_reason": improvement_note,
            "user_name": identity.get("name", ""),
            "vip_email_count": len(vip_emails),
        }
        memory_store.log_correction(episode)

    next_state["user_feedback"] = feedback
    return next_state


def user_feedback_agent(state: WorkflowState) -> WorkflowState:
    """No-op feedback node — feedback is now submitted via the web UI POST /api/feedback."""
    return dict(state)
