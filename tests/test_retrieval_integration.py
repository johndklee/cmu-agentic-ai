import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from episodic_context import (
    remember_digest_observation,
    reset_digest_run_context,
    select_retrieval_correction_type,
)
from memory_store import EpisodicMemoryStore


class _FakeEmbedding:
    def tolist(self):
        return [0.1, 0.2, 0.3]


class _FakeEmbedder:
    def encode(self, _texts):
        return [_FakeEmbedding()]


class _FakeCollection:
    def upsert(self, ids, documents, metadatas, embeddings):
        return None

    def query(self, query_embeddings, n_results, include):
        return {
            "ids": [["prio-1"]],
            "documents": [["priority_override VIP overlap"]],
            "metadatas": [[{"correction_type": "priority_override", "timestamp_utc": "2026-01-01T00:00:00+00:00"}]],
            "distances": [[0.1]],
        }


class RetrievalIntegrationTests(unittest.TestCase):
    def setUp(self):
        reset_digest_run_context()

    def tearDown(self):
        reset_digest_run_context()

    def test_scope_selection_and_scoped_retrieval_flow(self):
        remember_digest_observation(
            "key_highlights",
            "VIP overlap needsaction before Calendar Test 1",
        )
        selected_type = select_retrieval_correction_type()
        self.assertEqual(selected_type, "priority_override")

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(EpisodicMemoryStore, "_init_vector_backend", lambda self: None):
                store = EpisodicMemoryStore(persist_dir=Path(tmpdir))

            store.vector_enabled = True
            store._embedder = _FakeEmbedder()
            store._get_or_create_collection = lambda _name: _FakeCollection()

            store.log_correction(
                {
                    "id": "prio-1",
                    "timestamp_utc": "2026-01-01T00:00:00+00:00",
                    "correction_type": "priority_override",
                    "correction_text": "Prioritize VIP attendee-email overlaps at the top",
                }
            )
            store.log_correction(
                {
                    "id": "fmt-1",
                    "timestamp_utc": "2026-01-01T00:00:00+00:00",
                    "correction_type": "formatting_feedback",
                    "correction_text": "Put date before time",
                }
            )

            scoped = store.retrieve_similar(
                "vip attendee overlap",
                correction_type=selected_type,
                top_k=5,
            )
            self.assertGreaterEqual(len(scoped), 1)
            self.assertTrue(all(item.get("correction_type") == "priority_override" for item in scoped))


if __name__ == "__main__":
    unittest.main()
