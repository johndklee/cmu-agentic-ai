import json
import os
import types
import unittest
from unittest.mock import patch

import llm_client


class _FakeHTTPResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeGalileoModule:
    def __init__(self):
        self.events = []

    def log_event(self, event_name, payload):
        self.events.append((event_name, payload))


class LlmClientObservabilityTests(unittest.TestCase):
    def test_build_observability_payload_excludes_content_by_default(self):
        with patch.dict(os.environ, {"GALILEO_INCLUDE_CONTENT": "0"}, clear=False):
            payload = llm_client._build_observability_payload(
                provider="anthropic",
                model="claude-opus-4-6",
                status="success",
                latency_ms=12,
                prompt="email user@example.com",
                response_text="result",
            )

        self.assertIn("prompt_sha256", payload)
        self.assertIn("response_sha256", payload)
        self.assertNotIn("prompt", payload)
        self.assertNotIn("response", payload)

    def test_build_observability_payload_includes_content_when_enabled(self):
        with patch.dict(os.environ, {"GALILEO_INCLUDE_CONTENT": "true"}, clear=False):
            payload = llm_client._build_observability_payload(
                provider="anthropic",
                model="claude-opus-4-6",
                status="success",
                latency_ms=12,
                prompt="prompt text",
                response_text="response text",
            )

        self.assertEqual(payload.get("prompt"), "prompt text")
        self.assertEqual(payload.get("response"), "response text")
        self.assertNotIn("prompt_sha256", payload)

    def test_maybe_emit_galileo_event_noop_when_disabled(self):
        with patch.dict(os.environ, {"GALILEO_OBSERVABILITY_ENABLED": "0"}, clear=False):
            with patch("llm_client._emit_galileo_event") as mock_emit:
                llm_client._maybe_emit_galileo_event("llm.request", {"k": "v"})

        mock_emit.assert_not_called()

    def test_maybe_emit_galileo_event_emits_when_enabled(self):
        with patch.dict(os.environ, {"GALILEO_OBSERVABILITY_ENABLED": "1"}, clear=False):
            with patch("llm_client._emit_galileo_event") as mock_emit:
                llm_client._maybe_emit_galileo_event("llm.request", {"k": "v"})

        mock_emit.assert_called_once_with("llm.request", {"k": "v"})

    def test_generate_with_ollama_emits_safe_event(self):
        fake_galileo = _FakeGalileoModule()
        response_body = json.dumps({"message": {"content": "ok"}})

        with patch.dict(
            os.environ,
            {
                "GALILEO_OBSERVABILITY_ENABLED": "1",
                "GALILEO_INCLUDE_CONTENT": "0",
                "OLLAMA_BASE_URL": "http://localhost:11434",
            },
            clear=False,
        ):
            with patch("llm_client._import_galileo_module", return_value=fake_galileo):
                with patch("llm_client.urllib.request.urlopen", return_value=_FakeHTTPResponse(response_body)):
                    output = llm_client._generate_with_ollama(
                        "Email from john.doe@example.com about account 12345678",
                        "llama3.1:8b",
                    )

        self.assertEqual(output, "ok")
        self.assertEqual(len(fake_galileo.events), 1)
        _event_name, payload = fake_galileo.events[0]
        self.assertEqual(payload.get("provider"), "ollama")
        self.assertEqual(payload.get("status"), "success")
        self.assertNotIn("prompt", payload)
        self.assertNotIn("response", payload)
        self.assertIn("prompt_sha256", payload)

    def test_generate_with_anthropic_emits_safe_event(self):
        fake_galileo = _FakeGalileoModule()

        class _FakeMessages:
            @staticmethod
            def create(model, max_tokens, messages):
                del model, max_tokens, messages
                return types.SimpleNamespace(
                    content=[types.SimpleNamespace(text="ok")]
                )

        class _FakeAnthropicClient:
            def __init__(self):
                self.messages = _FakeMessages()

        fake_anthropic_module = types.SimpleNamespace(Anthropic=_FakeAnthropicClient)

        with patch.dict(
            os.environ,
            {
                "GALILEO_OBSERVABILITY_ENABLED": "1",
                "GALILEO_INCLUDE_CONTENT": "0",
            },
            clear=False,
        ):
            with patch.dict("sys.modules", {"anthropic": fake_anthropic_module}):
                with patch("llm_client._import_galileo_module", return_value=fake_galileo):
                    output = llm_client._generate_with_anthropic(
                        "Email from john.doe@example.com about account 12345678",
                        "claude-opus-4-6",
                    )

        self.assertEqual(output, "ok")
        self.assertEqual(len(fake_galileo.events), 1)
        _event_name, payload = fake_galileo.events[0]
        self.assertEqual(payload.get("provider"), "anthropic")
        self.assertEqual(payload.get("status"), "success")
        self.assertNotIn("prompt", payload)
        self.assertNotIn("response", payload)
        self.assertIn("prompt_sha256", payload)


if __name__ == "__main__":
    unittest.main()
