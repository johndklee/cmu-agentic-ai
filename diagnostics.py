"""Startup diagnostics helpers shared by server.py and main.py."""

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def is_truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_iso_datetime(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def check_ollama_reachable(base_url: str) -> tuple[bool, str]:
    url = f"{(base_url or 'http://localhost:11434').rstrip('/')}/api/version"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            raw = response.read().decode("utf-8", errors="replace").strip()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)

    version = ""
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            version = str(parsed.get("version") or "").strip()

    return True, f"reachable (version {version})" if version else "reachable"


def check_anthropic_reachable(model_name: str = "") -> tuple[bool, str, int, int]:
    try:
        import anthropic
    except Exception as exc:
        return False, f"SDK unavailable ({exc})", 0, 0

    api_key = (os.getenv("ANTHROPIC_API_KEY", "") or "").strip()
    if not api_key:
        return False, "ANTHROPIC_API_KEY not set", 0, 0

    try:
        client = anthropic.Anthropic()
        result = client.models.list()
    except Exception as exc:
        return False, str(exc), 0, 0

    data = getattr(result, "data", None)
    if isinstance(data, list) and data:
        selected = None
        target = (model_name or "").strip()
        matched_by = ""
        if target:
            for item in data:
                item_id = getattr(item, "id", "") or getattr(item, "name", "") or ""
                if item_id == target:
                    selected = item
                    matched_by = "exact"
                    break
            if selected is None:
                for item in data:
                    item_id = getattr(item, "id", "") or getattr(item, "name", "") or ""
                    if item_id.startswith(target):
                        selected = item
                        matched_by = "prefix"
                        break
            if selected is None:
                target_lower = target.lower()
                for item in data:
                    item_id = (getattr(item, "id", "") or getattr(item, "name", "") or "")
                    if target_lower in item_id.lower():
                        selected = item
                        matched_by = "contains"
                        break
        if selected is None:
            selected = data[0]
            matched_by = "fallback"

        model_id = getattr(selected, "id", "") or getattr(selected, "name", "") or ""
        input_limit = int(getattr(selected, "input_token_limit", 0) or 0)
        output_limit = int(getattr(selected, "output_token_limit", 0) or 0)
        if model_id:
            if target and matched_by == "fallback":
                return True, f"reachable (configured model {target} not in listed models; sample {model_id})", 0, 0
            if target and model_id != target and matched_by in {"prefix", "contains"}:
                return True, f"reachable (configured model {target}; matched {model_id})", input_limit, output_limit
            return True, f"reachable (model {model_id})", input_limit, output_limit
    return True, "reachable", 0, 0


def check_google_diagnostics(live_probe: bool = False) -> dict[str, object]:
    status: dict[str, object] = {
        "oauth_client_present": False,
        "oauth_client_path": "missing",
        "token_present": False,
        "token_path": "token_google.json",
        "token_valid": False,
        "token_expired": False,
        "token_refreshable": False,
        "scopes_configured": 0,
        "token_scopes_covered": False,
        "live_probe_enabled": bool(live_probe),
        "calendar_probe": "not run",
        "gmail_probe": "not run",
        "tasks_probe": "not run",
    }

    try:
        from actions import google_services as gs
    except Exception as exc:
        status["import_error"] = str(exc)
        return status

    scopes = list(getattr(gs, "SCOPES", []) or [])
    status["scopes_configured"] = len(scopes)

    try:
        credentials_path = gs.resolve_credentials_path()
        status["oauth_client_present"] = True
        status["oauth_client_path"] = str(credentials_path)
    except Exception:
        status["oauth_client_present"] = False

    token_path = getattr(gs, "TOKEN_PATH", Path(__file__).with_name("token_google.json"))
    status["token_path"] = str(token_path)
    token_exists = bool(getattr(token_path, "exists", lambda: False)())
    status["token_present"] = token_exists

    token_scopes: list[str] = []
    if token_exists:
        try:
            token_payload = json.loads(token_path.read_text(encoding="utf-8"))
            expiry = _parse_iso_datetime(str(token_payload.get("expiry", "")))
            now = datetime.now(timezone.utc)
            status["token_expired"] = bool(expiry and expiry <= now)
            status["token_valid"] = bool(expiry and expiry > now)
            status["token_refreshable"] = bool(token_payload.get("refresh_token"))
            token_scopes_raw = token_payload.get("scopes")
            if isinstance(token_scopes_raw, list):
                token_scopes = [str(i) for i in token_scopes_raw if isinstance(i, str)]
            elif isinstance(token_scopes_raw, str):
                token_scopes = [i for i in token_scopes_raw.split() if i]
        except Exception:
            status["token_parse_error"] = True

    if scopes:
        status["token_scopes_covered"] = set(scopes).issubset(set(token_scopes)) if token_scopes else False

    if not live_probe:
        return status

    if not token_exists:
        for key in ("calendar_probe", "gmail_probe", "tasks_probe"):
            status[key] = "skipped (token missing)"
        return status

    def _probe(service_name: str, version: str, call) -> str:
        try:
            svc = gs.build_google_service(service_name, version)
            call(svc)
            return "ok"
        except Exception as exc:
            return f"error ({exc})"

    def _probe_tasks_write() -> str:
        try:
            svc = gs.build_google_service("tasks", "v1")
            tasklists = svc.tasklists().list(maxResults=1).execute()
            list_id = tasklists["items"][0]["id"]
            task = svc.tasks().insert(tasklist=list_id, body={"title": "__diag_probe__"}).execute()
            svc.tasks().delete(tasklist=list_id, task=task["id"]).execute()
            return "ok"
        except Exception as exc:
            return f"error ({exc})"

    calendar_read = _probe("calendar", "v3", lambda s: s.calendarList().list(maxResults=1).execute())
    gmail_read = _probe("gmail", "v1", lambda s: s.users().getProfile(userId="me").execute())
    tasks_read = _probe("tasks", "v1", lambda s: s.tasklists().list(maxResults=1).execute())
    tasks_write = _probe_tasks_write()

    status["calendar_probe"] = calendar_read
    status["calendar_read"] = calendar_read
    status["gmail_probe"] = gmail_read
    status["gmail_read"] = gmail_read
    status["tasks_probe"] = tasks_read
    status["tasks_read"] = tasks_read
    status["tasks_write"] = tasks_write
    return status
