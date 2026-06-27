import unittest

from key_highlights_agent import (
    run_key_highlights_shadow,
    should_promote_shadow_result,
    validate_agent_b_output,
)


class KeyHighlightsAgentTests(unittest.TestCase):
    def test_shadow_output_is_schema_valid_for_basic_payload(self):
        payload = {
            "title": "Daily Digest",
            "date": "Monday, June 01, 2026",
            "time": "9:00 PM PDT",
            "location": "San Francisco, California, US",
            "sections": {
                "key_highlights": "overdue task: A | due soon task: B",
                "weather": "Clear sky",
                "news": "Headline 1 | Headline 2",
                "calendar": "Meeting 1",
                "tasks": "Task 1",
                "emails": "Email 1",
            },
        }

        result = run_key_highlights_shadow(payload)

        self.assertTrue(result.get("schema_valid"))
        self.assertGreaterEqual(result.get("highlights_count", 0), 1)
        self.assertEqual(result.get("confidence"), "medium")

    def test_invalid_output_reports_schema_errors_for_fallback(self):
        invalid_output = {
            "highlights": [
                {"rank": 2, "text": "", "category": "invalid", "evidence": "not-a-list"}
            ],
            "confidence": "maybe",
        }
        constraints = {"max_highlights": 5, "max_chars_each": 180}

        is_valid, errors = validate_agent_b_output(invalid_output, constraints)

        self.assertFalse(is_valid)
        self.assertGreaterEqual(len(errors), 1)

    def test_guarded_promotion_passes_when_thresholds_are_met(self):
        result = {
            "schema_valid": True,
            "confidence": "medium",
            "timed_out": False,
            "overlap_ratio": 0.8,
            "ordering_changes": 1,
            "empty_result": False,
            "highlights_count": 3,
        }

        promoted, failures = should_promote_shadow_result(result)

        self.assertTrue(promoted)
        self.assertEqual(failures, [])

    def test_guarded_promotion_fails_when_gates_are_violated(self):
        result = {
            "schema_valid": False,
            "confidence": "low",
            "timed_out": True,
            "overlap_ratio": 0.1,
            "ordering_changes": 9,
            "empty_result": True,
            "highlights_count": 0,
        }

        promoted, failures = should_promote_shadow_result(result)

        self.assertFalse(promoted)
        self.assertIn("schema_invalid", failures)
        self.assertIn("confidence_too_low", failures)
        self.assertIn("timed_out", failures)


if __name__ == "__main__":
    unittest.main()
