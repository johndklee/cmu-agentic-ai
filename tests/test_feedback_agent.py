import unittest
from unittest.mock import patch

from feedback_agent import user_feedback_agent


class FeedbackAgentTests(unittest.TestCase):
    @patch("feedback_agent.save_preferences")
    @patch("feedback_agent.load_preferences")
    @patch("builtins.input", side_effect=["yes"])
    def test_feedback_agent_records_satisfied_feedback(self, mock_input, mock_load_preferences, mock_save_preferences):
        mock_load_preferences.return_value = {
            "digest_feedback": [],
            "digest_preferences_summary": "",
            "email_daily_digest": None,
        }

        updated = user_feedback_agent({"digest_output": {"title": "Daily Digest"}})

        self.assertIn("user_feedback", updated)
        self.assertTrue(updated["user_feedback"]["satisfied"])
        self.assertEqual(updated["user_feedback"]["improvement_note"], "")
        mock_save_preferences.assert_called_once()

    @patch("feedback_agent.display_panel")
    @patch("feedback_agent.EpisodicMemoryStore")
    @patch("feedback_agent.save_preferences")
    @patch("feedback_agent.load_preferences")
    @patch("builtins.input", side_effect=["no", "Add more task detail", "yes"])
    def test_feedback_agent_records_dissatisfied_feedback_and_logs_episode(
        self,
        mock_input,
        mock_load_preferences,
        mock_save_preferences,
        mock_store_cls,
        mock_display_panel,
    ):
        mock_load_preferences.return_value = {
            "digest_feedback": [],
            "digest_preferences_summary": "",
            "email_daily_digest": None,
        }
        mock_store_cls.return_value.log_correction.return_value = {"backend": "json", "backend_error": ""}

        updated = user_feedback_agent({"digest_output": {"title": "Daily Digest"}})

        self.assertFalse(updated["user_feedback"]["satisfied"])
        self.assertEqual(updated["user_feedback"]["improvement_note"], "Add more task detail")
        mock_store_cls.return_value.log_correction.assert_called_once()
        mock_save_preferences.assert_called_once()
        self.assertTrue(mock_display_panel.called)


if __name__ == "__main__":
    unittest.main()
