import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_store import EpisodicMemoryStore


class _FakeCollection:
    def __init__(self):
        self.upserts = []

    def upsert(self, ids, documents, metadatas, embeddings):
        self.upserts.append(
            {
                "ids": ids,
                "documents": documents,
                "metadatas": metadatas,
                "embeddings": embeddings,
            }
        )


class _FakeEmbedding:
    def tolist(self):
        return [0.1, 0.2, 0.3]


class _FakeEmbedder:
    def encode(self, _texts):
        return [_FakeEmbedding()]


class EpisodicMemoryStoreTests(unittest.TestCase):
    def test_retrieve_similar_raises_when_vector_backend_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(EpisodicMemoryStore, "_init_vector_backend", lambda self: None):
                store = EpisodicMemoryStore(persist_dir=Path(tmpdir))

            with self.assertRaises(RuntimeError):
                store.log_correction(
                    {
                        "id": "a",
                        "timestamp_utc": "2026-01-01T00:00:00+00:00",
                        "correction_type": "priority_override",
                        "correction_text": "Prioritize VIP attendees first",
                    }
                )

            with self.assertRaises(RuntimeError):
                store.retrieve_similar(
                    "vip attendees",
                    correction_type="priority_override",
                    top_k=5,
                )

    def test_log_correction_upserts_all_and_scoped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(EpisodicMemoryStore, "_init_vector_backend", lambda self: None):
                store = EpisodicMemoryStore(persist_dir=Path(tmpdir))

            collections = {}

            def fake_get_or_create(name):
                collections.setdefault(name, _FakeCollection())
                return collections[name]

            store.vector_enabled = True
            store._embedder = _FakeEmbedder()
            store._get_or_create_collection = fake_get_or_create

            status = store.log_correction(
                {
                    "id": "abc-1",
                    "timestamp_utc": "2026-01-01T00:00:00+00:00",
                    "correction_type": "priority_override",
                    "correction_text": "Put VIP overlap at top",
                }
            )

            self.assertTrue(status["stored_vector"])
            self.assertEqual(status["backend"], "vector")
            self.assertIn("episodic_corrections", collections)
            self.assertIn("episodic_corrections__priority_override", collections)
            self.assertEqual(len(collections["episodic_corrections"].upserts), 1)
            self.assertEqual(len(collections["episodic_corrections__priority_override"].upserts), 1)


if __name__ == "__main__":
    unittest.main()
