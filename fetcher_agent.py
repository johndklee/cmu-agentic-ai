"""Fetcher agent for populating workflow raw data from external APIs."""

from datetime import datetime, timezone
from typing import Any

from actions.calendar_action import fetch_upcoming_events
from actions.email_action import fetch_recent_emails
from actions.key_highlights_action import run_key_highlights_action
from actions.location_action import current_location, format_location
from actions.news_action import fetch_news_items
from actions.tasks_action import fetch_open_tasks
from actions.weather_action import fetch_weather_snapshot, resolve_location_details
from workflow_state import WorkflowState


def _resolve_query_from_state(state: WorkflowState) -> str:
    """Resolve location query from state fallback or session location."""
    existing = state.get("raw_fetched_data", {}) if isinstance(state, dict) else {}
    location_data = existing.get("location", {}) if isinstance(existing, dict) else {}
    query = ""
    if isinstance(location_data, dict):
        query = str(location_data.get("query") or "").strip()
    if query:
        return query

    session_location = current_location()
    return format_location(session_location).strip()


def fetcher_agent(state: WorkflowState) -> WorkflowState:
    """Fetch raw Gmail/Calendar/Weather/News/Tasks data into workflow state."""
    next_state: WorkflowState = dict(state)
    raw_fetched_data: dict[str, Any] = {}
    fetch_errors: dict[str, str] = {}

    location_query = _resolve_query_from_state(state)
    location_details = None
    if location_query:
        try:
            location_details = resolve_location_details(location_query)
            raw_fetched_data["location"] = {
                "query": location_query,
                "resolved_name": location_details.get("name", ""),
                "latitude": location_details.get("latitude"),
                "longitude": location_details.get("longitude"),
                "timezone": location_details.get("timezone") or "UTC",
            }
        except Exception as exc:
            fetch_errors["location"] = str(exc)
            raw_fetched_data["location"] = {
                "query": location_query,
                "resolved_name": "",
                "latitude": None,
                "longitude": None,
                "timezone": "UTC",
            }
    else:
        fetch_errors["location"] = "Missing location query."
        raw_fetched_data["location"] = {
            "query": "",
            "resolved_name": "",
            "latitude": None,
            "longitude": None,
            "timezone": "UTC",
        }

    try:
        weather = fetch_weather_snapshot(location_query)
        raw_fetched_data["weather"] = {
            "description": weather.get("description", ""),
            "temperature_c": weather.get("temperature_c"),
            "apparent_temperature_c": weather.get("apparent_temperature_c"),
            "high_c": weather.get("high_c"),
            "low_c": weather.get("low_c"),
            "wind_kmh": weather.get("wind_kmh"),
            "weather_code": weather.get("weather_code"),
        }
    except Exception as exc:
        fetch_errors["weather"] = str(exc)
        raw_fetched_data["weather"] = {
            "description": "",
            "temperature_c": None,
            "apparent_temperature_c": None,
            "high_c": None,
            "low_c": None,
            "wind_kmh": None,
            "weather_code": None,
        }

    try:
        raw_fetched_data["news"] = fetch_news_items(location_query)
    except Exception as exc:
        fetch_errors["news"] = str(exc)
        raw_fetched_data["news"] = []

    try:
        raw_fetched_data["calendar_events"] = fetch_upcoming_events(max_items=5)
    except Exception as exc:
        fetch_errors["calendar_events"] = str(exc)
        raw_fetched_data["calendar_events"] = []

    try:
        raw_fetched_data["emails"] = fetch_recent_emails(max_items=5)
    except Exception as exc:
        fetch_errors["emails"] = str(exc)
        raw_fetched_data["emails"] = []

    try:
        _tasklist_id, _list_title, tasks = fetch_open_tasks(max_items=5)
        raw_fetched_data["tasks"] = tasks
    except Exception as exc:
        fetch_errors["tasks"] = str(exc)
        raw_fetched_data["tasks"] = []

    try:
        raw_fetched_data["vip_followup_result"] = run_key_highlights_action()
    except Exception as exc:
        fetch_errors["vip_followup"] = str(exc)
        raw_fetched_data["vip_followup_result"] = None

    if location_details and "location" in raw_fetched_data:
        raw_fetched_data["location"].setdefault("resolved_name", location_details.get("name", ""))

    raw_fetched_data["fetch_errors"] = fetch_errors
    raw_fetched_data["fetched_at_utc"] = datetime.now(timezone.utc).isoformat()
    next_state["raw_fetched_data"] = raw_fetched_data
    return next_state
