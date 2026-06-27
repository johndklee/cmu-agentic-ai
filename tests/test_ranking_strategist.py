import json
import unittest
from unittest.mock import patch

from ranking_strategist import ranking_strategist


class RankingStrategistTests(unittest.TestCase):
    @patch("ranking_strategist.run_crewai_ranking_strategist")
    @patch("ranking_strategist._generate_with_ollama")
    def test_ranking_strategist_uses_crewai_candidate_rankings_when_available(self, mock_generate, mock_crewai):
        mock_crewai.return_value = [
            {
                "candidate_id": f"candidate_{idx}",
                "strategy": "crewai",
                "ranking": [],
            }
            for idx in range(1, 6)
        ]

        state = {"raw_fetched_data": {}, "retrieved_corrections": []}

        updated = ranking_strategist(state)

        self.assertEqual(len(updated["candidate_rankings"]), 5)
        self.assertEqual(updated["candidate_rankings"][0]["strategy"], "crewai")
        mock_crewai.assert_called_once_with(state)
        mock_generate.assert_not_called()

    @patch("ranking_strategist._generate_with_ollama")
    def test_ranking_strategist_writes_five_candidates_from_ollama_output(self, mock_generate):
        llm_output = [
            {
                "candidate_id": f"candidate_{idx}",
                "strategy": "tot_variant",
                "ranking": [
                    {
                        "item_id": "tasks:task-1",
                        "source": "tasks",
                        "priority": "high",
                        "reason": "Due task first",
                    }
                ],
            }
            for idx in range(1, 6)
        ]
        mock_generate.return_value = json.dumps(llm_output)

        state = {
            "raw_fetched_data": {
                "tasks": [{"id": "task-1", "title": "Finish report", "due": "2026-06-14"}],
                "emails": [],
                "calendar_events": [],
                "news": [],
                "weather": {"description": "Clear"},
            },
            "retrieved_corrections": [{"correction_text": "Boost due tasks"}],
        }

        updated = ranking_strategist(state)

        self.assertIn("candidate_rankings", updated)
        self.assertEqual(len(updated["candidate_rankings"]), 5)
        self.assertEqual(updated["candidate_rankings"][0]["ranking"][0]["item_id"], "tasks:task-1")
        self.assertTrue(mock_generate.called)

    @patch("ranking_strategist._generate_with_ollama")
    def test_ranking_strategist_uses_fallback_when_llm_output_invalid(self, mock_generate):
        mock_generate.return_value = "not valid json"

        state = {
            "raw_fetched_data": {
                "tasks": [{"id": "task-1", "title": "Finish report", "due": "2026-06-14"}],
                "emails": [{"id": "msg-1", "subject": "Ping", "is_unread": True}],
                "calendar_events": [{"id": "evt-1", "summary": "Sync"}],
                "news": [{"title": "Headline"}],
                "weather": {"description": "Clear"},
            },
            "retrieved_corrections": [],
        }

        updated = ranking_strategist(state)

        self.assertEqual(len(updated["candidate_rankings"]), 5)
        self.assertEqual(updated["candidate_rankings"][0]["strategy"], "fallback_rotation")

    @patch("ranking_strategist._generate_with_ollama")
    def test_ranking_strategist_prompt_includes_retrieved_corrections(self, mock_generate):
        mock_generate.return_value = json.dumps([
            {"candidate_id": f"candidate_{idx}", "strategy": "ok", "ranking": []}
            for idx in range(1, 6)
        ])

        state = {
            "raw_fetched_data": {},
            "retrieved_corrections": [{"correction_text": "Prioritize VIP"}],
        }

        ranking_strategist(state)

        args, _kwargs = mock_generate.call_args
        self.assertIn("Prioritize VIP", args[0])


if __name__ == "__main__":
    unittest.main()
