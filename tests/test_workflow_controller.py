import unittest
from importlib.util import find_spec
from unittest.mock import patch

from workflow_controller import (
    critic_node,
    fetcher_node,
    feedback_node,
    retrieval_node,
    route_after_critic,
    run_workflow_fetch_phase,
    run_workflow_digest,
    strategist_node,
    synthesize_node,
)

HAS_LANGGRAPH = find_spec("langgraph") is not None


class WorkflowControllerTests(unittest.TestCase):
    def test_fetcher_node_delegates_to_fetcher_agent(self):
        sentinel = {"raw_fetched_data": {"ok": True}}
        with patch("workflow_controller.fetcher_agent", return_value=sentinel) as mocked:
            result = fetcher_node({})

        mocked.assert_called_once_with({})
        self.assertEqual(result, sentinel)

    def test_retrieval_node_delegates_to_memory_store(self):
        sentinel = [{"id": "corr-1", "correction_text": "Prefer VIP items"}]
        mock_store = patch("workflow_controller.EpisodicMemoryStore").start()
        self.addCleanup(patch.stopall)
        mock_store.return_value.retrieve_similar.return_value = sentinel

        state = {
            "raw_fetched_data": {
                "location": {"resolved_name": "Pittsburgh, PA, US"},
                "calendar_events": [{"summary": "Meeting"}],
                "emails": [{"subject": "Ping"}],
                "tasks": [{"title": "Todo"}],
            }
        }

        result = retrieval_node(state)

        mock_store.return_value.retrieve_similar.assert_called_once()
        self.assertEqual(result["retrieved_corrections"], sentinel)

    def test_strategist_node_delegates_to_ranking_strategist(self):
        sentinel = {"candidate_rankings": [{"candidate_id": "candidate_1"}]}
        with patch("workflow_controller.ranking_strategist", return_value=sentinel) as mocked:
            result = strategist_node({})

        mocked.assert_called_once_with({})
        self.assertEqual(result, sentinel)

    def test_critic_node_delegates_to_ranking_critic(self):
        sentinel = {"scores": [{"candidate_id": "candidate_1", "total": 0.9}]}
        with patch("workflow_controller.ranking_critic", return_value=sentinel) as mocked:
            result = critic_node({})

        mocked.assert_called_once_with({})
        self.assertEqual(result, sentinel)

    def test_synthesize_node_delegates_to_synthesize_digest(self):
        sentinel = {"digest_output": {"title": "Daily Digest"}}
        with patch("workflow_controller.synthesize_digest", return_value=sentinel) as mocked:
            result = synthesize_node({})

        mocked.assert_called_once_with({})
        self.assertEqual(result, sentinel)

    def test_feedback_node_delegates_to_user_feedback_agent(self):
        sentinel = {"user_feedback": {"satisfied": True}}
        with patch("workflow_controller.user_feedback_agent", return_value=sentinel) as mocked:
            result = feedback_node({})

        mocked.assert_called_once_with({})
        self.assertEqual(result, sentinel)

    def test_route_after_critic_returns_strategist_on_refine(self):
        state = {
            "pruning_decisions": [
                {"candidate_id": "__controller__", "decision": "refine", "refinement_round": 1}
            ]
        }
        self.assertEqual(route_after_critic(state), "strategist")

    def test_route_after_critic_returns_synthesize_on_proceed(self):
        state = {
            "pruning_decisions": [
                {"candidate_id": "__controller__", "decision": "proceed", "refinement_round": 2}
            ]
        }
        self.assertEqual(route_after_critic(state), "synthesize")

    @unittest.skipUnless(HAS_LANGGRAPH, "langgraph not installed in test environment")
    def test_run_workflow_fetch_phase_invokes_fetcher_node(self):
        fetched = {
            "raw_fetched_data": {
                "source": "fetcher",
                "location": {"resolved_name": "Pittsburgh, PA, US"},
                "calendar_events": [{"summary": "Meeting"}],
                "emails": [{"subject": "Ping"}],
                "tasks": [{"title": "Todo"}],
            }
        }
        retrieved = {
            "raw_fetched_data": {
                "source": "fetcher",
                "location": {"resolved_name": "Pittsburgh, PA, US"},
                "calendar_events": [{"summary": "Meeting"}],
                "emails": [{"subject": "Ping"}],
                "tasks": [{"title": "Todo"}],
            },
            "retrieved_corrections": [{"id": "corr-1"}],
        }
        ranked = {
            "raw_fetched_data": {"source": "fetcher"},
            "retrieved_corrections": [{"id": "corr-1"}],
            "candidate_rankings": [],
        }
        critiqued = {
            "raw_fetched_data": {"source": "fetcher"},
            "retrieved_corrections": [{"id": "corr-1"}],
            "candidate_rankings": [],
            "scores": [],
            "pruning_decisions": [{"candidate_id": "__controller__", "decision": "proceed"}],
        }
        synthesized = {
            "raw_fetched_data": {"source": "fetcher"},
            "retrieved_corrections": [{"id": "corr-1"}],
            "candidate_rankings": [],
            "scores": [],
            "pruning_decisions": [{"candidate_id": "__controller__", "decision": "proceed"}],
            "digest_output": {"title": "Daily Digest"},
        }
        final_state = {
            **synthesized,
            "user_feedback": {"satisfied": True, "improvement_note": ""},
        }

        with patch("workflow_controller.fetcher_agent", return_value=fetched) as fetch_mock, patch(
            "workflow_controller.EpisodicMemoryStore"
        ) as store_mock, patch("workflow_controller.ranking_strategist", return_value=ranked) as strategist_mock, patch(
            "workflow_controller.ranking_critic", return_value=critiqued
        ) as critic_mock, patch("workflow_controller.synthesize_digest", return_value=synthesized) as synthesize_mock:
            store_mock.return_value.vector_enabled = True
            store_mock.return_value.retrieve_similar.return_value = [{"id": "corr-1"}]
            with patch("workflow_controller.user_feedback_agent", return_value=final_state) as feedback_mock:
                result = run_workflow_digest({})

        fetch_mock.assert_called_once()
        store_mock.return_value.retrieve_similar.assert_called_once()
        strategist_mock.assert_called_once_with(retrieved)
        critic_mock.assert_called_once_with(ranked)
        synthesize_mock.assert_called_once_with(critiqued)
        feedback_mock.assert_called_once_with(synthesized)
        self.assertEqual(result, final_state)


if __name__ == "__main__":
    unittest.main()
