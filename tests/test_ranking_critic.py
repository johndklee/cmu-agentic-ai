import unittest
from unittest.mock import patch

from crewai_agents import run_crewai_ranking_critic
from ranking_critic import ranking_critic


class RankingCriticTests(unittest.TestCase):
    @patch("ranking_critic.run_crewai_ranking_critic")
    @patch("ranking_critic._generate_with_anthropic")
    @patch("ranking_critic.EpisodicMemoryStore")
    def test_ranking_critic_uses_crewai_coherence_when_available(self, mock_store_cls, mock_claude, mock_crewai):
        mock_crewai.return_value = 0.9
        mock_store = mock_store_cls.return_value
        mock_store.retrieve_similar.return_value = []

        state = {
            "raw_fetched_data": {},
            "candidate_rankings": [
                {
                    "candidate_id": "candidate_1",
                    "ranking": [
                        {"item_id": "news:1", "source": "news", "priority": "low", "reason": "context"}
                    ],
                }
            ],
        }

        updated = ranking_critic(state)

        self.assertEqual(updated["scores"][0]["coherence"], 0.9)
        mock_crewai.assert_called_once()
        mock_claude.assert_not_called()

    @patch("ranking_critic._generate_with_anthropic")
    @patch("ranking_critic.EpisodicMemoryStore")
    def test_ranking_critic_writes_scores_and_pruning_decisions(self, mock_store_cls, mock_claude):
        mock_claude.return_value = '{"coherence": 0.8, "notes": "clear rationale"}'
        mock_store = mock_store_cls.return_value
        mock_store.retrieve_similar.return_value = [
            {"correction_type": "priority_override", "correction_text": "Prioritize VIP items"}
        ]

        state = {
            "raw_fetched_data": {
                "calendar_events": [
                    {"id": "evt-1", "summary": "Client meeting", "organizer_is_vip": True, "attendees": []}
                ],
                "emails": [{"id": "msg-1", "subject": "Urgent", "vip_matches": ["vip@example.com"]}],
                "tasks": [{"id": "task-1", "title": "Submit report", "due": "2026-06-14"}],
                "news": [],
                "weather": {"description": "Clear"},
            },
            "candidate_rankings": [
                {
                    "candidate_id": "candidate_1",
                    "ranking": [
                        {
                            "item_id": "calendar:evt-1",
                            "source": "calendar_events",
                            "priority": "high",
                            "reason": "VIP client meeting",
                        },
                        {
                            "item_id": "emails:msg-1",
                            "source": "emails",
                            "priority": "high",
                            "reason": "Urgent VIP email",
                        },
                    ],
                },
                {
                    "candidate_id": "candidate_2",
                    "ranking": [
                        {
                            "item_id": "tasks:task-1",
                            "source": "tasks",
                            "priority": "medium",
                            "reason": "Due tomorrow",
                        }
                    ],
                },
            ],
        }

        updated = ranking_critic(state)

        self.assertIn("scores", updated)
        self.assertIn("pruning_decisions", updated)
        self.assertEqual(len(updated["scores"]), 2)
        self.assertEqual(len(updated["pruning_decisions"]), 3)
        self.assertEqual(updated["pruning_decisions"][0]["decision"], "keep")
        self.assertIn(updated["pruning_decisions"][-1]["decision"], {"refine", "proceed"})

    @patch("ranking_critic._generate_with_anthropic")
    @patch("ranking_critic.EpisodicMemoryStore")
    def test_ranking_critic_uses_claude_only_for_coherence(self, mock_store_cls, mock_claude):
        mock_claude.return_value = '{"coherence": 0.7, "notes": "ok"}'
        mock_store = mock_store_cls.return_value
        mock_store.retrieve_similar.return_value = []

        state = {
            "raw_fetched_data": {},
            "candidate_rankings": [
                {
                    "candidate_id": "candidate_1",
                    "ranking": [
                        {
                            "item_id": "news:1",
                            "source": "news",
                            "priority": "low",
                            "reason": "context",
                        }
                    ],
                }
            ],
        }

        ranking_critic(state)

        self.assertEqual(mock_claude.call_count, 1)
        self.assertEqual(mock_store.retrieve_similar.call_count, 1)

    @patch("ranking_critic.run_crewai_ranking_critic")
    @patch("ranking_critic._generate_with_anthropic")
    @patch("ranking_critic.EpisodicMemoryStore")
    def test_ranking_critic_excludes_reason_from_claude_prompt(self, mock_store_cls, mock_claude, mock_crewai):
        mock_crewai.return_value = None
        mock_claude.return_value = '{"coherence": 0.7, "notes": "ok"}'
        mock_store = mock_store_cls.return_value
        mock_store.retrieve_similar.return_value = []

        state = {
            "raw_fetched_data": {},
            "candidate_rankings": [
                {
                    "candidate_id": "candidate_1",
                    "ranking": [
                        {
                            "item_id": "emails:1",
                            "source": "emails",
                            "priority": "high",
                            "reason": "Email from john.doe@example.com about account 12345678",
                        }
                    ],
                }
            ],
        }

        ranking_critic(state)

        prompt = mock_claude.call_args.args[0]
        self.assertNotIn('"reason"', prompt)
        self.assertNotIn("john.doe@example.com", prompt)
        self.assertNotIn("12345678", prompt)

    @patch("ranking_critic._generate_with_anthropic")
    @patch("ranking_critic.EpisodicMemoryStore")
    def test_ranking_critic_stops_refinement_at_max_rounds(self, mock_store_cls, mock_claude):
        mock_claude.return_value = '{"coherence": 0.7, "notes": "ok"}'
        mock_store = mock_store_cls.return_value
        mock_store.retrieve_similar.return_value = []

        state = {
            "raw_fetched_data": {},
            "candidate_rankings": [
                {
                    "candidate_id": "candidate_1",
                    "ranking": [{"item_id": "news:1", "source": "news", "priority": "low", "reason": "a"}],
                },
                {
                    "candidate_id": "candidate_2",
                    "ranking": [{"item_id": "news:2", "source": "news", "priority": "low", "reason": "b"}],
                },
            ],
            "pruning_decisions": [
                {"candidate_id": "__controller__", "decision": "refine", "refinement_round": 2}
            ],
        }

        updated = ranking_critic(state)
        controller_row = updated["pruning_decisions"][-1]
        self.assertEqual(controller_row["candidate_id"], "__controller__")
        self.assertEqual(controller_row["decision"], "proceed")
        self.assertEqual(controller_row["refinement_round"], 2)


class CrewAICriticPayloadTests(unittest.TestCase):
    @patch("crewai_agents._load_ranking_critic_helpers")
    @patch("crewai_agents._build_agents")
    @patch("crewai_agents._build_critic_crew")
    def test_crewai_critic_excludes_reason_from_payload(
        self,
        mock_build_critic_crew,
        mock_build_agents,
        mock_load_helpers,
    ):
        mock_load_helpers.return_value = None
        mock_build_agents.return_value = (object(), object(), object(), object(), object())

        captured_description = {}

        class FakeCrew:
            def kickoff(self):
                return '{"coherence": 0.8, "notes": "ok"}'

        def capture_task_description(task_description: str):
            captured_description["value"] = task_description
            return FakeCrew()

        mock_build_critic_crew.side_effect = capture_task_description

        result = run_crewai_ranking_critic(
            {
                "ranking": [
                    {
                        "item_id": "emails:1",
                        "source": "emails",
                        "priority": "high",
                        "reason": "Email from john.doe@example.com about account 12345678",
                    }
                ]
            }
        )

        self.assertEqual(result, 0.8)
        payload = captured_description["value"]
        self.assertNotIn('"reason"', payload)
        self.assertNotIn("john.doe@example.com", payload)
        self.assertNotIn("12345678", payload)



if __name__ == "__main__":
    unittest.main()
