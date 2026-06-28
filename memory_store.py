"""Episodic memory store with vector-only persistence and retrieval."""

import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


MEMORY_DIR = Path(__file__).with_name(".memory")
DEFAULT_COLLECTION_NAME = "episodic_corrections"

CORRECTION_TYPES = {
    "priority_override",
    "missed_item",
    "irrelevant_item",
    "formatting_feedback",
    "preference_update",
    "general_feedback",
}

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
    "you",
    "your",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def infer_correction_type(note: str) -> str:
    """Infer correction type from free-text user feedback."""
    lowered = (note or "").strip().lower()
    if not lowered:
        return "general_feedback"
    if any(token in lowered for token in ["priority", "rank", "top", "urgent", "vip", "important"]):
        return "priority_override"
    if any(token in lowered for token in ["missed", "forgot", "left out", "didn't include", "did not include"]):
        return "missed_item"
    if any(token in lowered for token in ["irrelevant", "noise", "too much", "remove", "don't show", "dont show"]):
        return "irrelevant_item"
    if any(token in lowered for token in ["format", "style", "order", "layout"]):
        return "formatting_feedback"
    if any(token in lowered for token in ["location", "weather", "temperature", "topic", "email", "name"]):
        return "preference_update"
    return "general_feedback"


def _parse_iso_datetime(value: str):
    if not value:
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_days(timestamp_utc: str) -> float:
    dt = _parse_iso_datetime(timestamp_utc)
    if dt is None:
        return math.inf
    delta = datetime.now(timezone.utc) - dt
    return max(0.0, delta.total_seconds() / 86400.0)


def _recency_weight(timestamp_utc: str) -> float:
    """Downweight older-than-30-day corrections without excluding them."""
    age = _age_days(timestamp_utc)
    if age <= 30:
        return 1.0
    if age <= 60:
        return 0.75
    return 0.55


def _is_stale(timestamp_utc: str) -> bool:
    return _age_days(timestamp_utc) > 60


def _tokenize(text: str) -> set:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {word for word in words if len(word) > 2 and word not in _STOPWORDS}


def _lexical_score(query_text: str, document: str) -> float:
    query_tokens = _tokenize(query_text)
    doc_tokens = _tokenize(document)
    if not query_tokens or not doc_tokens:
        return 0.0
    overlap = len(query_tokens & doc_tokens)
    return overlap / float(len(query_tokens))


def _record_document(record: dict) -> str:
    parts = [
        f"correction_type={record.get('correction_type', '')}",
        f"correction_text={record.get('correction_text', '')}",
        f"sender={record.get('sender_email', '')}",
        f"meeting_context={record.get('meeting_context', '')}",
        f"original_ranking={record.get('original_ranking', '')}",
        f"user_reason={record.get('user_reason', '')}",
        f"location={record.get('location', '')}",
    ]
    return " | ".join(part for part in parts if part and not part.endswith("="))


class EpisodicMemoryStore:
    """Persist correction episodes and retrieve them from vector indexes."""

    def __init__(
        self,
        persist_dir: Path = None,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    ):
        base_dir = Path(persist_dir) if persist_dir else MEMORY_DIR
        self.persist_dir = base_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.embedding_model = embedding_model

        self.vector_enabled = False
        self._chroma_client = None
        self._chroma_collections = {}
        self._embedder = None
        self._backend_error = ""

        self._init_vector_backend()

    def _init_vector_backend(self) -> None:
        try:
            import chromadb
        except Exception as err:
            self._backend_error = f"chromadb unavailable: {err}"
            return

        try:
            from sentence_transformers import SentenceTransformer
        except Exception as err:
            self._backend_error = f"sentence-transformers unavailable: {err}"
            return

        try:
            chroma_dir = self.persist_dir / "chroma"
            chroma_dir.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(chroma_dir))
            embedder = SentenceTransformer(self.embedding_model)
            self._chroma_client = client
            self._embedder = embedder
            self.vector_enabled = True
            self._backend_error = ""
            self._get_or_create_collection(self.collection_name)
        except Exception as err:
            self._backend_error = f"vector backend init failed: {err}"
            self.vector_enabled = False
            self._chroma_client = None
            self._chroma_collections = {}
            self._embedder = None

    def _get_or_create_collection(self, collection_name: str):
        if not self._chroma_client:
            return None
        if collection_name in self._chroma_collections:
            return self._chroma_collections[collection_name]
        collection = self._chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._chroma_collections[collection_name] = collection
        return collection

    def _collection_name_for_correction_type(self, correction_type: str) -> str:
        normalized = (correction_type or "").strip().lower()
        if normalized in CORRECTION_TYPES:
            return f"{self.collection_name}__{normalized}"
        return self.collection_name

    def backend_status(self) -> dict:
        return {
            "vector_enabled": self.vector_enabled,
            "backend_error": self._backend_error,
            "collection_name": self.collection_name,
            "loaded_collections": sorted(self._chroma_collections.keys()),
            "embedding_model": self.embedding_model,
        }

    def clear_all(self) -> dict:
        """Delete all records from every loaded collection."""
        if not self.vector_enabled or not self._chroma_client:
            return {"cleared": 0, "error": "vector backend unavailable"}
        cleared = 0
        for name in list(self._chroma_collections.keys()):
            try:
                self._chroma_client.delete_collection(name)
                cleared += 1
            except Exception:
                pass
        self._chroma_collections.clear()
        return {"cleared": cleared}

    def _normalize_record(self, record: dict) -> dict:
        """Normalize record shape used by both writes and reindexing."""
        normalized = dict(record or {})
        normalized.setdefault("id", str(uuid.uuid4()))
        normalized.setdefault("timestamp_utc", _utc_now_iso())
        normalized.setdefault("correction_text", "")
        normalized.setdefault("correction_type", infer_correction_type(normalized.get("correction_text", "")))
        normalized["is_stale"] = _is_stale(normalized.get("timestamp_utc", ""))
        normalized["document"] = _record_document(normalized)
        return normalized

    def _upsert_vector_record(self, normalized: dict) -> bool:
        """Upsert one normalized record into vector collections."""
        if not self.vector_enabled:
            return False

        embedding = self._embedder.encode([normalized["document"]])[0].tolist()
        metadata = {
            "timestamp_utc": normalized.get("timestamp_utc", ""),
            "correction_type": normalized.get("correction_type", ""),
            "is_stale": normalized.get("is_stale", False),
        }

        # Always upsert into all-corrections collection.
        all_collection = self._get_or_create_collection(self.collection_name)
        all_collection.upsert(
            ids=[normalized["id"]],
            documents=[normalized["document"]],
            metadatas=[metadata],
            embeddings=[embedding],
        )

        # Also upsert into a correction-type specific collection for scoped retrieval.
        scoped_collection_name = self._collection_name_for_correction_type(normalized.get("correction_type", ""))
        if scoped_collection_name != self.collection_name:
            scoped_collection = self._get_or_create_collection(scoped_collection_name)
            scoped_collection.upsert(
                ids=[normalized["id"]],
                documents=[normalized["document"]],
                metadatas=[metadata],
                embeddings=[embedding],
            )
        return True

    def log_correction(self, record: dict) -> dict:
        """Persist one episodic correction in vector indexes."""
        normalized = self._normalize_record(record)

        if not self.vector_enabled:
            raise RuntimeError(
                "Vector backend is required for episodic writes but is unavailable. "
                f"Details: {self._backend_error or 'unknown error'}"
            )

        try:
            self._upsert_vector_record(normalized)
            return {
                "id": normalized["id"],
                "stored_vector": True,
                "backend": "vector",
                "backend_error": "",
            }
        except Exception as err:
            raise RuntimeError(f"Vector write failed: {err}") from err

    def retrieve_similar(
        self,
        query_text: str,
        correction_type: str = "",
        top_k: int = 5,
    ) -> list:
        """Retrieve top similar correction records with recency-aware ranking."""
        query = (query_text or "").strip()
        if not query:
            return []
        if not self.vector_enabled:
            raise RuntimeError(
                "Vector backend is required for episodic retrieval but is unavailable. "
                f"Details: {self._backend_error or 'unknown error'}"
            )

        candidates = []
        try:
            scoped_collection_name = self._collection_name_for_correction_type(correction_type)
            query_collections = [scoped_collection_name]
            if scoped_collection_name != self.collection_name:
                # Also query all-corrections collection to include older mixed records.
                query_collections.append(self.collection_name)

            n_results = max(top_k * 3, top_k)
            query_embedding = self._embedder.encode([query])[0].tolist()
            seen_ids = set()

            for collection_name in query_collections:
                collection = self._get_or_create_collection(collection_name)
                if collection is None:
                    continue
                results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=n_results,
                    include=["documents", "metadatas", "distances"],
                )
                ids = (results.get("ids") or [[]])[0]
                docs = (results.get("documents") or [[]])[0]
                metadatas = (results.get("metadatas") or [[]])[0]
                distances = (results.get("distances") or [[]])[0]

                for idx, record_id in enumerate(ids):
                    if record_id in seen_ids:
                        continue
                    metadata = metadatas[idx] if idx < len(metadatas) and isinstance(metadatas[idx], dict) else {}
                    if correction_type and metadata.get("correction_type") != correction_type:
                        continue
                    seen_ids.add(record_id)
                    document = docs[idx] if idx < len(docs) else ""
                    distance = distances[idx] if idx < len(distances) else 1.0
                    similarity = max(0.0, 1.0 - float(distance))
                    timestamp_utc = str(metadata.get("timestamp_utc", ""))
                    recency = _recency_weight(timestamp_utc)
                    score = similarity * recency
                    candidates.append(
                        {
                            "id": record_id,
                            "document": document,
                            "correction_type": str(metadata.get("correction_type", "")),
                            "timestamp_utc": timestamp_utc,
                            "age_days": _age_days(timestamp_utc),
                            "is_stale": _is_stale(timestamp_utc),
                            "score": score,
                        }
                    )
        except Exception as exc:
            raise RuntimeError(f"Vector retrieval failed: {exc}") from exc

        candidates.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        return candidates[:top_k]

def format_retrieved_corrections(records: list) -> str:
    """Format retrieved episodic corrections for prompt context."""
    if not records:
        return ""

    lines = ["Retrieved episodic corrections (ranked):"]
    for idx, record in enumerate(records, start=1):
        correction_type = record.get("correction_type", "unknown")
        correction_text = record.get("correction_text", "").strip()
        if not correction_text:
            correction_text = record.get("document", "")
        timestamp_utc = record.get("timestamp_utc", "unknown_time")
        score = float(record.get("score", 0.0))
        stale_suffix = " [STALE>60d]" if record.get("is_stale") else ""
        lines.append(
            f"{idx}. type={correction_type}; ts={timestamp_utc}; score={score:.3f}; correction={correction_text}{stale_suffix}"
        )
    return "\n".join(lines)



# Module-level singleton — reuses the loaded SentenceTransformer across all callers.
_shared_store: "EpisodicMemoryStore | None" = None


def get_shared_store() -> "EpisodicMemoryStore":
    global _shared_store
    if _shared_store is None:
        _shared_store = EpisodicMemoryStore()
    return _shared_store
