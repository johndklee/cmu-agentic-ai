"""LLM client setup and provider transport helpers."""

import importlib
import json
import os
import socket
import time
import urllib.error
import urllib.request
from dotenv import load_dotenv

load_dotenv()

OLLAMA_DEFAULT_MODEL = "llama3.1:8b"
ANTHROPIC_DEFAULT_MODEL = "claude-opus-4-6"


def _is_truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _galileo_observability_enabled() -> bool:
    return _is_truthy_env(os.getenv("GALILEO_OBSERVABILITY_ENABLED", "1"))


def _galileo_include_content() -> bool:
    return _is_truthy_env(os.getenv("GALILEO_INCLUDE_CONTENT", "1"))


def _log_llm_span(
    *,
    provider: str,
    model: str,
    prompt: str,
    response_text: str = "",
    latency_ms: int,
    status: str,
    error: Exception | None = None,
) -> None:
    """Log an LLM call as a Galileo trace with a single LLM span."""
    if not _galileo_observability_enabled():
        return
    try:
        import galileo

        include_content = _galileo_include_content()
        input_text = prompt if include_content else f"[{len(prompt)} chars]"
        output_text = response_text if include_content else f"[{len(response_text)} chars]"
        if error is not None:
            output_text = f"ERROR: {type(error).__name__}: {error}"

        logger = galileo.galileo_context.get_logger_instance()
        logger.add_trace(input=input_text, name=f"{provider}.llm_call")
        logger.add_llm_span(
            input=input_text,
            output=output_text,
            model=model,
            duration_ns=latency_ms * 1_000_000,
            metadata={"provider": provider, "status": status, "latency_ms": str(latency_ms)},
        )
        logger.conclude(output=output_text)
        galileo.galileo_context.flush()
    except Exception:
        pass


def _resolve_ollama_num_ctx() -> int:
    """Resolve optional Ollama context window override from environment."""
    raw = os.getenv("OLLAMA_NUM_CTX", "").strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        return 0
    return value if value > 0 else 0


def _extract_positive_int(value) -> int:
    """Best-effort parse for positive integer values."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _fetch_ollama_model_context_window(base_url: str, model: str) -> int:
    """Fetch model context window size from Ollama show API when available."""
    payload = json.dumps({"model": model}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/show",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read().decode("utf-8")
    except Exception:
        return 0

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    details = parsed.get("details") or {}
    model_info = parsed.get("model_info") or {}

    for candidate in (
        details.get("context_length"),
        model_info.get("llama.context_length"),
        model_info.get("general.context_length"),
    ):
        value = _extract_positive_int(candidate)
        if value:
            return value
    return 0


def _generate_with_anthropic(user_prompt: str, model: str) -> str:
    """Send prompt via Anthropic Messages API."""
    started = time.perf_counter()
    try:
        import anthropic
    except Exception as err:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _log_llm_span(provider="anthropic", model=model, prompt=user_prompt,
                      latency_ms=latency_ms, status="error", error=err)
        raise RuntimeError(
            "Anthropic provider selected but package is unavailable. "
            "Install with: pip install anthropic"
        ) from err

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=10000,
            messages=[
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
        )
        output = response.content[0].text
    except Exception as err:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _log_llm_span(provider="anthropic", model=model, prompt=user_prompt,
                      latency_ms=latency_ms, status="error", error=err)
        raise

    latency_ms = int((time.perf_counter() - started) * 1000)
    _log_llm_span(provider="anthropic", model=model, prompt=user_prompt,
                  response_text=output, latency_ms=latency_ms, status="success")
    return output


def _generate_with_ollama(user_prompt: str, model: str) -> str:
    """Send prompt via local Ollama chat API."""
    started = time.perf_counter()
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip().rstrip("/")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": user_prompt,
            }
        ],
        "stream": False,
    }
    num_ctx = _resolve_ollama_num_ctx()
    if num_ctx:
        payload["options"] = {"num_ctx": num_ctx}
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
        },
    )
    timeout_seconds = 120
    try:
        timeout_seconds = int(os.getenv("OLLAMA_REQUEST_TIMEOUT_SECONDS", "120").strip())
    except ValueError:
        timeout_seconds = 120
    if timeout_seconds <= 0:
        timeout_seconds = 120
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="ignore")
        runtime_err = RuntimeError(f"Ollama request failed ({err.code}): {detail}")
        latency_ms = int((time.perf_counter() - started) * 1000)
        _log_llm_span(provider="ollama", model=model, prompt=user_prompt,
                      latency_ms=latency_ms, status="error", error=runtime_err)
        raise runtime_err from err
    except (TimeoutError, socket.timeout) as err:
        runtime_err = RuntimeError(
            f"Ollama request timed out after {timeout_seconds}s. "
            "Increase OLLAMA_REQUEST_TIMEOUT_SECONDS or reduce prompt size."
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        _log_llm_span(provider="ollama", model=model, prompt=user_prompt,
                      latency_ms=latency_ms, status="error", error=runtime_err)
        raise runtime_err from err
    except urllib.error.URLError as err:
        runtime_err = RuntimeError(
            "Ollama request failed. Ensure Ollama is running and reachable at "
            f"{base_url}: {err}"
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        _log_llm_span(provider="ollama", model=model, prompt=user_prompt,
                      latency_ms=latency_ms, status="error", error=runtime_err)
        raise runtime_err from err

    parsed = json.loads(raw)
    message = parsed.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        latency_ms = int((time.perf_counter() - started) * 1000)
        _log_llm_span(provider="ollama", model=model, prompt=user_prompt,
                      response_text=content, latency_ms=latency_ms, status="success")
        return content

    runtime_err = RuntimeError("Ollama response did not include text content.")
    latency_ms = int((time.perf_counter() - started) * 1000)
    _log_llm_span(provider="ollama", model=model, prompt=user_prompt,
                  latency_ms=latency_ms, status="error", error=runtime_err)
    raise runtime_err


