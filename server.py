"""FastAPI backend for the daily digest web app."""

import importlib.util
import json
import os
import warnings
warnings.filterwarnings("ignore", message="resource_tracker: There appear to be", category=UserWarning)
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path

import json as _json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from diagnostics import check_ollama_reachable, check_anthropic_reachable, check_google_diagnostics, is_truthy_env
from digest_rendering import render_json_digest
from actions.email_action import send_email_action
from feedback_agent import apply_feedback
from llm_client import ANTHROPIC_DEFAULT_MODEL, OLLAMA_DEFAULT_MODEL
from memory_store import EpisodicMemoryStore, get_shared_store
from preferences import load_preferences, save_preferences, get_user_identity, get_vip_emails, reset_all_preferences, reset_digest_preferences
from workflow_controller import run_workflow_digest, build_workflow_graph

# Hard-fail if CrewAI is not installed — it is required for the ToT ranking pipeline.
if importlib.util.find_spec("crewai") is None:
    raise RuntimeError(
        "CrewAI is required but not installed. Install with: pip install crewai"
    )
print("✅ CrewAI available")

# Initialize shared memory store once at module load so the SentenceTransformer is not reloaded on every request.
_memory_store = get_shared_store()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start MCP branch-state server — hard requirement. Failure aborts startup.
    import mcp_branch_state as _mcp_mod
    import asyncio as _asyncio
    _mcp_port_val = _mcp_mod._find_free_port(8001)
    _mcp_mod.start_mcp_server_background(port=_mcp_port_val)
    await _asyncio.sleep(0.5)  # allow SSE server to bind before first health/digest call
    try:
        await _mcp_mod._async_mcp_call("get_branch_state", {})
        print(f"✅ MCP branch-state server started and verified on port {_mcp_port_val}")
    except Exception as _e:
        raise RuntimeError(f"MCP server started on port {_mcp_port_val} but is not reachable: {_e}") from _e

    # Initialize Galileo observability.
    try:
        from galileo import galileo_context as _galileo_context
        _project = os.getenv("GALILEO_PROJECT", "Daily Digest Agent")
        _log_stream = os.getenv("GALILEO_LOG_STREAM", "default")
        _galileo_context.init(project=_project, log_stream=_log_stream)
        print(f"✅ Galileo session started (project={_project}, log_stream={_log_stream})")
    except Exception as _e:
        print(f"⚠️  Galileo init skipped: {_e}")

    yield


app = FastAPI(title="Daily Digest", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIST = Path(__file__).with_name("web") / "dist"
LAST_DIGEST_PATH = Path(__file__).parent / ".memory" / "last_digest.json"


def _save_last_digest(digest: dict) -> None:
    LAST_DIGEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {**digest, "generated_at": datetime.utcnow().isoformat() + "Z"}
    LAST_DIGEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def _maybe_email_digest(digest_output: dict) -> None:
    """Send the digest by email if the user has enabled email delivery in preferences."""
    from digest_rendering import render_email_digest_markup
    prefs = load_preferences()
    if prefs.get("email_daily_digest") is not True:
        return
    identity = get_user_identity(prefs)
    user_email = (identity.get("email") or "").strip().lower()
    if not user_email:
        print("⚠️  email_daily_digest is enabled but no user email is configured — skipping send.")
        return
    subject = str(digest_output.get("title") or "Daily Digest")
    body = render_email_digest_markup(digest_output)
    result = send_email_action(to_email=user_email, subject=subject, body=body)
    print(f"📧 Digest email: {result}")


def _load_last_digest() -> dict | None:
    if not LAST_DIGEST_PATH.exists():
        return None
    try:
        return json.loads(LAST_DIGEST_PATH.read_text())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    satisfied: bool
    improvement_note: str = ""


class PreferencesUpdate(BaseModel):
    user_name: str | None = None
    user_email: str | None = None
    user_email_aliases: list[str] | None = None
    vip_email_addresses: list[str] | None = None
    email_daily_digest: bool | None = None
    temperature_unit: str | None = None
    preferred_location_text: str | None = None
    preferred_highlight_count: int | None = Field(default=None, ge=1, le=8)


# ---------------------------------------------------------------------------
# Health / diagnostics
# ---------------------------------------------------------------------------

def _check_galileo() -> dict:
    import importlib.util
    sdk_available = importlib.util.find_spec("galileo") is not None
    console_url = os.getenv("GALILEO_CONSOLE_URL", "").strip()
    api_key_set = bool(os.getenv("GALILEO_API_KEY", "").strip())
    enabled = is_truthy_env(os.getenv("GALILEO_OBSERVABILITY_ENABLED"))

    configured = sdk_available and bool(console_url) and api_key_set
    reachable = False
    detail = ""

    if configured:
        try:
            import urllib.request as _ur
            with _ur.urlopen(console_url.rstrip("/"), timeout=3) as r:
                reachable = r.status < 500
                detail = f"HTTP {r.status}"
        except Exception as exc:
            detail = str(exc)
    else:
        missing = []
        if not sdk_available: missing.append("SDK not installed")
        if not console_url: missing.append("GALILEO_CONSOLE_URL not set")
        if not api_key_set: missing.append("GALILEO_API_KEY not set")
        detail = "; ".join(missing) if missing else "not configured"

    return {
        "sdk_available": sdk_available,
        "console_url": console_url or None,
        "api_key_set": api_key_set,
        "enabled": enabled,
        "configured": configured,
        "reachable": reachable,
        "detail": detail,
    }


def _check_langgraph() -> dict:
    import importlib.util
    available = importlib.util.find_spec("langgraph") is not None
    if available:
        try:
            from importlib.metadata import version
            from workflow_controller import describe_workflow_graph
            ver = version("langgraph")
            return {"available": True, "version": ver, "detail": f"v{ver}", "graph": describe_workflow_graph()}
        except Exception as exc:
            return {"available": False, "version": None, "detail": str(exc), "graph": None}
    return {"available": False, "version": None, "detail": "not installed", "graph": None}


def _check_mcp() -> dict:
    import mcp_branch_state as _mcp_mod
    port = _mcp_mod._mcp_port
    if port is None:
        return {"available": False, "port": None, "detail": "MCP server not started"}
    try:
        result = _mcp_mod.mcp_call("get_branch_state", {})
        if result is not None:
            return {"available": True, "port": port, "detail": f"reachable on port {port}"}
        return {"available": False, "port": port, "detail": "no response from MCP server"}
    except Exception as exc:
        return {"available": False, "port": port, "detail": str(exc)}


def _check_crewai() -> dict:
    import importlib.util
    available = importlib.util.find_spec("crewai") is not None
    if available:
        try:
            from importlib.metadata import version
            from crewai_agents import list_agents
            ver = version("crewai")
            return {"available": True, "version": ver, "detail": f"v{ver}", "agents": list_agents()}
        except Exception as exc:
            return {"available": False, "version": None, "detail": str(exc), "agents": []}
    return {"available": False, "version": None, "detail": "not installed", "agents": []}


def _check_langchain() -> dict:
    import importlib.util
    available = importlib.util.find_spec("langchain_core") is not None
    if available:
        try:
            from importlib.metadata import version
            ver = version("langchain-core")
            return {"available": True, "version": ver, "detail": f"v{ver}"}
        except Exception as exc:
            return {"available": False, "version": None, "detail": str(exc)}
    return {"available": False, "version": None, "detail": "not installed"}


def _check_fastmcp() -> dict:
    import importlib.util
    available = importlib.util.find_spec("fastmcp") is not None
    if available:
        try:
            from importlib.metadata import version
            ver = version("fastmcp")
            return {"available": True, "version": ver, "detail": f"v{ver}"}
        except Exception as exc:
            return {"available": False, "version": None, "detail": str(exc)}
    return {"available": False, "version": None, "detail": "not installed"}


def _check_weather() -> dict:
    """Probe the open-meteo geocoding endpoint used by weather_action."""
    import urllib.request as _ur
    url = "https://geocoding-api.open-meteo.com/v1/search?name=London&count=1&format=json"
    try:
        with _ur.urlopen(url, timeout=4) as resp:
            reachable = resp.status < 400
            return {"available": reachable, "detail": "open-meteo reachable" if reachable else f"HTTP {resp.status}"}
    except Exception as exc:
        return {"available": False, "detail": str(exc)}


def _check_news() -> dict:
    """Probe the Google News RSS feed used by news_action."""
    import urllib.request as _ur
    url = "https://news.google.com/rss/search?q=news&hl=en-US&gl=US&ceid=US:en"
    try:
        with _ur.urlopen(url, timeout=4) as resp:
            reachable = resp.status < 400
            return {"available": reachable, "detail": "Google News RSS reachable" if reachable else f"HTTP {resp.status}"}
    except Exception as exc:
        return {"available": False, "detail": str(exc)}


def _check_ollama_model(base_url: str) -> dict:
    """Check whether the configured Ollama model is actually pulled and available."""
    from llm_client import OLLAMA_DEFAULT_MODEL, _fetch_ollama_model_context_window
    import urllib.request as _ur
    import json as _json
    model = (os.getenv("OLLAMA_MODEL", "").strip() or OLLAMA_DEFAULT_MODEL)
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        with _ur.urlopen(url, timeout=3) as resp:
            data = _json.loads(resp.read().decode())
        models = [m.get("name", "") for m in (data.get("models") or [])]
        # Ollama model names may include ':latest' suffix
        match = any(m == model or m.startswith(f"{model}:") or model.startswith(m.split(":")[0]) for m in models)
        if match:
            ctx = _fetch_ollama_model_context_window(base_url, model)
            ctx_str = f"{ctx // 1024}K" if ctx >= 1024 else (str(ctx) if ctx else "unknown")
            return {"available": True, "model": model, "detail": f"{model} is pulled", "context_window": ctx_str, "think_disabled": True}
        return {"available": False, "model": model, "detail": f"{model} not found; run: ollama pull {model}", "context_window": None}
    except Exception as exc:
        return {"available": False, "model": model, "detail": str(exc), "context_window": None}


def _check_huggingface() -> dict:
    """Check HuggingFace token validity and embedding model cache status."""
    import urllib.request as _ur
    import json as _json
    import os as _os

    token = _os.getenv("HF_TOKEN", "").strip()
    embedding_model = _memory_store.embedding_model

    # Check local cache
    cache_dir = _os.path.expanduser("~/.cache/huggingface/hub")
    slug = "models--" + embedding_model.replace("/", "--")
    cached_locally = _os.path.isdir(_os.path.join(cache_dir, slug))

    return {
        "token_configured": bool(token),
        "embedding_model": embedding_model,
        "model_cached": cached_locally,
        "cache_path": _os.path.join(cache_dir, slug) if cached_locally else None,
    }


_ANTHROPIC_CONTEXT_WINDOWS: dict[str, str] = {
    "claude-opus-4-8": "200K",
    "claude-opus-4-6": "200K",
    "claude-sonnet-4-6": "200K",
    "claude-haiku-4-5": "200K",
    "claude-3-5-sonnet-20241022": "200K",
    "claude-3-5-haiku-20241022": "200K",
    "claude-3-opus-20240229": "200K",
}


@app.get("/api/context")
def get_context():
    """Return current location, local time, and weather for immediate display."""
    from actions.location_action import current_location, format_location
    from actions.weather_action import fetch_weather_snapshot
    from preferences import load_preferences
    from datetime import datetime
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    loc = current_location()
    location_text = format_location(loc)
    timezone_name = loc.get("timezone") or ""
    try:
        tz = ZoneInfo(timezone_name) if timezone_name else datetime.now().astimezone().tzinfo
    except ZoneInfoNotFoundError:
        tz = datetime.now().astimezone().tzinfo
    now = datetime.now(tz)
    date_text = now.strftime("%A, %B %d, %Y")
    time_text = now.strftime("%I:%M %p %Z").strip()

    weather_text = None
    try:
        prefs = load_preferences()
        snapshot = fetch_weather_snapshot(location_text)
        temp_c = snapshot.get("temperature_c")
        description = snapshot.get("description") or ""
        if temp_c is not None:
            use_f = (prefs.get("temperature_unit") or "C").upper() == "F"
            temp_val = (temp_c * 9 / 5) + 32 if use_f else temp_c
            unit = "F" if use_f else "C"
            weather_text = f"{description}, {temp_val:.1f}{unit}"
        else:
            weather_text = description or None
    except Exception:
        pass

    return {
        "location": location_text,
        "date": date_text,
        "time": time_text,
        "weather": weather_text,
    }


@app.get("/api/health")
def health():
    memory_status = _memory_store.backend_status()
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip().rstrip("/")
    ollama_reachable, ollama_detail = check_ollama_reachable(ollama_base_url)
    critic_model = os.getenv("ANTHROPIC_MODEL", "").strip() or ANTHROPIC_DEFAULT_MODEL
    anthropic_reachable, anthropic_detail, _, _ = check_anthropic_reachable(critic_model)
    google_status = check_google_diagnostics(live_probe=True)

    return {
        "ollama": {"reachable": ollama_reachable, "detail": ollama_detail, "url": ollama_base_url},
        "ollama_model": _check_ollama_model(ollama_base_url),
        "anthropic": {"reachable": anthropic_reachable, "detail": anthropic_detail, "context_window": _ANTHROPIC_CONTEXT_WINDOWS.get(critic_model, "200K")},
        "google": google_status,
        "memory": memory_status,
        "huggingface": _check_huggingface(),
        "galileo": _check_galileo(),
        "crewai": _check_crewai(),
        "langchain": _check_langchain(),
        "langgraph": _check_langgraph(),
        "fastmcp": _check_fastmcp(),
        "mcp": _check_mcp(),
        "weather": _check_weather(),
        "news": _check_news(),
    }


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

@app.post("/api/digest")
def generate_digest():
    memory_status = _memory_store.backend_status()
    if not memory_status.get("vector_enabled"):
        raise HTTPException(status_code=503, detail="Vector backend unavailable")
    try:
        state = run_workflow_digest({})
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"LangGraph unavailable: {exc}")

    digest_output = state.get("digest_output") if isinstance(state, dict) else {}
    if not isinstance(digest_output, dict) or not digest_output:
        raise HTTPException(status_code=500, detail="Workflow completed without digest output")

    return render_json_digest(digest_output)


@app.get("/api/mcp/state")
def get_mcp_state():
    """Return current MCP branch state for diagnostics."""
    try:
        from mcp_branch_state import mcp_call
        raw = mcp_call("get_branch_state", {})
        return json.loads(raw)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/digest/last")
def get_last_digest():
    digest = _load_last_digest()
    if digest is None:
        raise HTTPException(status_code=404, detail="No digest saved yet")
    return digest


@app.get("/api/digest/stream")
def stream_digest():
    memory_status = _memory_store.backend_status()
    if not memory_status.get("vector_enabled"):
        raise HTTPException(status_code=503, detail="Vector backend unavailable")

    def _safe(obj):
        """Make a workflow state value JSON-serialisable."""
        try:
            _json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return str(obj)

    def event_stream():
        try:
            graph = build_workflow_graph()
            final_state = {}
            for step in graph.stream({}, stream_mode="updates"):
                for node_name, node_state in step.items():
                    safe_state = {k: _safe(v) for k, v in (node_state or {}).items()}
                    payload = _json.dumps({"node": node_name, "state": safe_state})
                    yield f"data: {payload}\n\n"
                    final_state.update(node_state or {})

            digest_output = final_state.get("digest_output") or {}
            if isinstance(digest_output, dict) and digest_output:
                rendered = render_json_digest(digest_output)
                _save_last_digest(rendered)
                stamped = _load_last_digest() or rendered
                digest_payload = _json.dumps({"node": "__digest__", "digest": stamped})
                yield f"data: {digest_payload}\n\n"
                _maybe_email_digest(digest_output)
        except Exception as exc:
            yield f"data: {_json.dumps({'node': '__error__', 'error': str(exc)})}\n\n"
        yield "data: {\"node\": \"__done__\"}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

@app.delete("/api/memory")
def clear_memory():
    result = _memory_store.clear_all()
    prefs = load_preferences()
    prefs["digest_feedback"] = []
    prefs["digest_preferences_summary"] = ""
    save_preferences(prefs)
    return result


@app.post("/api/preferences/reset-all")
def reset_preferences_all():
    reset_all_preferences()
    return {"status": "ok"}


@app.post("/api/preferences/reset-digest")
def reset_preferences_digest():
    reset_digest_preferences()
    return {"status": "ok"}


@app.post("/api/feedback")
def submit_feedback(body: FeedbackRequest):
    apply_feedback({}, satisfied=body.satisfied, improvement_note=body.improvement_note)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

@app.get("/api/preferences")
def get_preferences():
    prefs = load_preferences()
    identity = get_user_identity(prefs)
    return {
        "user_name": prefs.get("user_name", ""),
        "user_email": prefs.get("user_email", ""),
        "user_email_aliases": prefs.get("user_email_aliases", []),
        "vip_email_addresses": get_vip_emails(prefs),
        "email_daily_digest": prefs.get("email_daily_digest"),
        "temperature_unit": prefs.get("temperature_unit", "C"),
        "preferred_location_text": prefs.get("preferred_location_text", ""),
        "digest_preferences_summary": prefs.get("digest_preferences_summary", ""),
        "preferred_highlight_count": int(prefs.get("preferred_highlight_count") or 5),
    }


@app.post("/api/preferences")
def update_preferences(body: PreferencesUpdate):
    import actions.location_action as _loc_mod
    prefs = load_preferences()
    updates = body.model_dump(exclude_none=True)
    old_location_text = (prefs.get("preferred_location_text") or "").strip()
    prefs.update(updates)
    new_location_text = (prefs.get("preferred_location_text") or "").strip()
    if new_location_text != old_location_text:
        prefs["preferred_location"] = None
        _loc_mod.SESSION_LOCATION = None
        if new_location_text:
            try:
                from preferences import resolve_preferred_location
                prefs["preferred_location"] = resolve_preferred_location(new_location_text)
                _loc_mod.SESSION_LOCATION = prefs["preferred_location"]
            except Exception:
                pass
    save_preferences(prefs)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Serve React build (production)
# ---------------------------------------------------------------------------

if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        index = WEB_DIST / "index.html"
        return FileResponse(str(index))
