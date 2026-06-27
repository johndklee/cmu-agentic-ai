"""Shared Google credential and service helpers.

Supports two auth modes, auto-detected from credentials.json:
  - Service account (type == "service_account"): uses domain-wide delegation to
    impersonate the user set in GOOGLE_IMPERSONATE_EMAIL. No browser needed.
  - OAuth2 desktop app: launches a local browser flow on first run, then
    persists token_google.json for silent refresh on subsequent runs.
"""

import json
import os
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

TOKEN_PATH = Path(__file__).resolve().parent.parent / "token_google.json"
CREDENTIALS_PATH = Path(__file__).resolve().parent.parent / "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks",
]


def _credentials_path() -> Path:
    """Resolve credentials file path from env or project root."""
    env_path = os.getenv("GOOGLE_OAUTH_CLIENT_FILE", "").strip()
    if env_path:
        candidate = Path(env_path).expanduser()
        if not candidate.is_absolute():
            candidate = (Path(__file__).resolve().parent.parent / candidate).resolve()
        if candidate.exists():
            return candidate

    if CREDENTIALS_PATH.exists():
        return CREDENTIALS_PATH

    project_root = Path(__file__).resolve().parent.parent
    matches = sorted(project_root.glob("client_secret*.json"))
    if matches:
        return matches[0]

    raise ValueError(
        "Google credentials not found. Provide one of: "
        "(1) project-root credentials.json (service account or OAuth desktop app), "
        "(2) project-root client_secret*.json, or "
        "(3) GOOGLE_OAUTH_CLIENT_FILE=<path>."
    )


def _is_service_account(path: Path) -> bool:
    """Return True if the credentials file is a service account key."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("type") == "service_account"
    except Exception:
        return False


def _get_service_account_credentials(path: Path):
    """Build impersonated credentials from a service account key file."""
    from google.oauth2 import service_account

    impersonate = os.getenv("GOOGLE_IMPERSONATE_EMAIL", "").strip()
    if not impersonate:
        raise ValueError(
            "Service account credentials require GOOGLE_IMPERSONATE_EMAIL in .env — "
            "set it to the Google Workspace user email to impersonate (e.g. you@yourdomain.com)."
        )

    return service_account.Credentials.from_service_account_file(
        str(path),
        scopes=SCOPES,
        subject=impersonate,
    )


def _get_oauth_credentials(path: Path) -> Credentials:
    """Load OAuth2 credentials, launching browser flow when needed."""
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return creds


# Keep old name for backward compatibility
def resolve_credentials_path() -> Path:
    return _credentials_path()


def get_google_credentials():
    """Return valid Google credentials, auto-detecting service account vs OAuth2."""
    path = _credentials_path()
    if _is_service_account(path):
        return _get_service_account_credentials(path)
    return _get_oauth_credentials(path)


def build_google_service(api_name: str, version: str):
    """Build an authorized Google API service client."""
    creds = get_google_credentials()
    return build(api_name, version, credentials=creds)


def format_google_http_error(api_label: str, err: HttpError) -> str:
    """Return a concise, user-facing message for common Google API failures."""
    status = getattr(getattr(err, "resp", None), "status", None)
    reason = ""
    message = ""

    if getattr(err, "content", None):
        try:
            payload = json.loads(err.content.decode("utf-8"))
            error_data = payload.get("error", {})
            message = str(error_data.get("message", "")).strip()
            details = error_data.get("errors") or []
            if details and isinstance(details, list):
                reason = str(details[0].get("reason", "")).strip()
        except (UnicodeDecodeError, ValueError, AttributeError, TypeError):
            pass

    lowered_message = message.lower()
    if status == 403 and (reason == "accessNotConfigured" or "has not been used in project" in lowered_message):
        url_match = re.search(r"https?://\S+", message)
        enable_url = url_match.group(0).rstrip('.,;') if url_match else "https://console.cloud.google.com/apis/library"
        return (
            f"Google {api_label} API is not enabled for your Cloud project. "
            f"Enable it here: {enable_url} Then wait a few minutes and retry."
        )

    if status == 401:
        return (
            f"Google {api_label} authorization failed. Remove token_google.json and run the action again to re-authorize."
        )

    if status == 403 and "insufficient authentication scopes" in lowered_message:
        return (
            f"Google {api_label} authorization is missing required scopes. "
            "Remove token_google.json and run the action again to re-authorize with updated permissions."
        )

    if message:
        return f"Google {api_label} API error ({status}): {message}"

    return f"Google {api_label} API request failed: {err}"
