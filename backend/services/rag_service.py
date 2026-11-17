"""RAG service: chunking, vector storage and retrieval.

Two storage back ends:

* **ChromaDB** (default) keeps the knowledge base in a local folder. Good for
  running on your own machine.
* **Upstash Vector** keeps it in a hosted database. Used automatically when
  UPSTASH_VECTOR_REST_URL and UPSTASH_VECTOR_REST_TOKEN are set, which is what
  serverless hosts such as Vercel need (their disk is wiped between requests).

Embeddings are always computed by `llm_service` (OpenAI-compatible API).
"""

import math
import re
from collections import OrderedDict
from typing import Callable, List, Optional, Tuple

from backend.config import settings
from backend.services.llm_service import llm_service

EmbedFn = Callable[[List[str]], List[List[float]]]


def chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Split text into overlapping chunks, preferring paragraph/sentence ends."""
    text = re.sub(r"[ \t]+\n", "\n", text.replace("\r\n", "\n")).strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    overlap = max(0, min(overlap, chunk_size // 2))
    chunks, start = [], 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            window = text[start:end]
            # Break at the last paragraph, line or sentence end in the back half.
            for separator in ("\n\n", "\n", ". ", " "):
                cut = window.rfind(separator)
                if cut >= chunk_size // 2:
                    end = start + cut + len(separator)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def fit_dimensions(vectors: List[List[float]], dimensions: int) -> List[List[float]]:
    """Shorten embeddings to `dimensions` values and re-normalise them.

    Modern embedding models (OpenAI text-embedding-3, Gemini embedding) are
    trained so that a prefix of the vector is itself a usable embedding.
    """
    fitted = []
    for vector in vectors:
        if len(vector) < dimensions:
            raise ValueError(
                f"The embedding model returns {len(vector)} values but the vector "
                f"index expects {dimensions}. Recreate the index with "
                f"{len(vector)} dimensions or choose another embedding model."
            )
        vector = vector[:dimensions]
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        fitted.append([v / norm for v in vector])
    return fitted


# ---------------------------------------------------------------- Upstash
class UpstashStore:
    """Minimal Upstash Vector REST client (https://upstash.com/docs/vector)."""

    def __init__(self, url: str, token: str, http_client=None):
        import httpx

        self._url = url.rstrip("/")
        self._http = http_client or httpx.Client(timeout=30)
        self._headers = {"Authorization": f"Bearer {token}"}
        self._dimension: Optional[int] = None

    def _call(self, method: str, path: str, payload=None):
        response = self._http.request(
            method, f"{self._url}/{path}", headers=self._headers, json=payload
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or (isinstance(body, dict) and body.get("error")):
            detail = body.get("error") if isinstance(body, dict) else None
            raise RuntimeError(
                f"Upstash Vector error ({response.status_code}): "
                f"{detail or response.text[:300]}"
            )
        return body.get("result") if isinstance(body, dict) else body

    def info(self) -> dict:
        return self._call("GET", "info") or {}

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._dimension = int(self.info().get("dimension") or 0)
        return self._dimension

    def count(self) -> int:
        return int(self.info().get("vectorCount") or 0)

    def add(self, ids, documents, embeddings, metadatas) -> None:
        records = [
            {"id": i, "vector": v, "metadata": {**m, "text": d}}
            for i, d, v, m in zip(ids, documents, embeddings, metadatas)
        ]
        for start in range(0, len(records), 100):
            self._call("POST", "upsert", records[start : start + 100])

    def query(self, embedding, k: int) -> Tuple[List[str], List[dict]]:
        hits = self._call(
            "POST", "query", {"vector": embedding, "topK": k, "includeMetadata": True}
        ) or []
        documents, metadatas = [], []
        for hit in hits:
            metadata = dict(hit.get("metadata") or {})
            documents.append(metadata.pop("text", ""))
            metadatas.append(metadata)
        return documents, metadatas

    def all_records(self) -> List[Tuple[str, dict]]:
        records, cursor = [], "0"
        while True:
            page = self._call(
                "POST", "range", {"cursor": cursor, "limit": 1000, "includeMetadata": True}
            ) or {}
            for vector in page.get("vectors") or []:
                records.append((vector.get("id"), vector.get("metadata") or {}))
            cursor = page.get("nextCursor") or ""
            if not cursor:
                return records

    def delete(self, ids: List[str]) -> None:
        for start in range(0, len(ids), 1000):
            self._call("DELETE", "delete", {"ids": ids[start : start + 1000]})


# ----------------------------------------------------------------- service
class RAGService:
    def __init__(
        self,
        client=None,
        embed_fn: Optional[EmbedFn] = None,
        collection_name: Optional[str] = None,
        upstash: Optional[UpstashStore] = None,
    ):
        self._client = client
        self._embed = embed_fn or llm_service.get_embeddings
        self._collection_name = collection_name or settings.collection_name
        self._collection = None
        self._upstash = upstash

    # ---------------------------------------------------------- back ends
    @property
    def backend(self) -> str:
        if self._upstash is not None:
            return "upstash"
        return "upstash" if settings.uses_upstash else "chroma"

    @property
    def upstash(self) -> UpstashStore:
        if self._upstash is None:
            self._upstash = UpstashStore(
                settings.upstash_vector_rest_url, settings.upstash_vector_rest_token
            )
        return self._upstash

    @property
    def collection(self):
        if self._collection is None:
            import chromadb  # imported lazily: not installed on serverless hosts
            from chromadb.config import Settings as ChromaSettings

            if self._client is None:
                settings.chroma_path.mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(
                    path=str(settings.chroma_path),
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
            # embedding_function=None: we always supply vectors ourselves.
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
                embedding_function=None,
            )
        return self._collection

    def _embeddings(self, texts: List[str]) -> List[List[float]]:
        if self.backend != "upstash":
            return self._embed(texts)
        dimension = self.upstash.dimension
        if self._embed is llm_service.get_embeddings:
            vectors = llm_service.get_embeddings(texts, dimensions=dimension or None)
        else:
            vectors = self._embed(texts)
        return fit_dimensions(vectors, dimension) if dimension else vectors

    # -------------------------------------------------------------- ingest
    def ingest_document(
        self,
        document_id: str,
        content: str,
        document_name: str = "document",
        metadata: Optional[dict] = None,
    ) -> dict:
        chunks = chunk_text(content, settings.chunk_size, settings.chunk_overlap)
        if not chunks:
            raise ValueError("Document has no text content.")

        # Vector-store metadata values must be scalars.
        base = {
            k: v
            for k, v in (metadata or {}).items()
            if isinstance(v, (str, int, float, bool))
        }
        base.update({"document_name": document_name, "doc_id": document_id})

        ids = [f"{document_id}:{i}" for i in range(len(chunks))]
        metadatas = [{**base, "chunk_index": i} for i in range(len(chunks))]
        embeddings = self._embeddings(chunks)
        if self.backend == "upstash":
            self.upstash.add(ids, chunks, embeddings, metadatas)
        else:
            self.collection.add(
                ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas
            )
        return {
            "document_id": document_id,
            "document_name": document_name,
            "chunks": len(chunks),
            "characters": len(content),
        }

    # ------------------------------------------------------------ retrieve
    def retrieve_context(self, query: str, k: int = 3) -> Tuple[List[str], List[dict]]:
        if k <= 0:
            return [], []
        if self.backend == "upstash":
            if self.upstash.count() == 0:
                return [], []
            return self.upstash.query(self._embeddings([query])[0], k)

        total = self.collection.count()
        if total == 0:
            return [], []
        results = self.collection.query(
            query_embeddings=self._embeddings([query]),
            n_results=min(k, total),
            include=["documents", "metadatas"],
        )
        documents = (results.get("documents") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]
        return documents, [m or {} for m in metadatas]

    @staticmethod
    def format_context(documents: List[str], metadatas: List[dict]) -> str:
        return "\n\n---\n\n".join(
            f"From {meta.get('document_name', 'Unknown')}:\n{doc}"
            for doc, meta in zip(documents, metadatas)
        )

    @staticmethod
    def source_names(metadatas: List[dict]) -> List[str]:
        """Distinct document names, in retrieval order."""
        return list(
            OrderedDict.fromkeys(m.get("document_name", "Unknown") for m in metadatas)
        )

    # -------------------------------------------------------------- manage
    def _records(self) -> List[Tuple[str, dict]]:
        if self.backend == "upstash":
            return self.upstash.all_records()
        found = self.collection.get(include=["metadatas"])
        return list(zip(found.get("ids") or [], found.get("metadatas") or []))

    def list_documents(self) -> List[dict]:
        docs: "OrderedDict[str, dict]" = OrderedDict()
        for _, meta in self._records():
            doc_id = (meta or {}).get("doc_id")
            if not doc_id:
                continue
            entry = docs.setdefault(
                doc_id,
                {
                    "document_id": doc_id,
                    "document_name": meta.get("document_name", "document"),
                    "chunks": 0,
                },
            )
            entry["chunks"] += 1
        return list(docs.values())

    def delete_document(self, document_id: str) -> int:
        if self.backend == "upstash":
            ids = [i for i, meta in self._records() if (meta or {}).get("doc_id") == document_id]
            if ids:
                self.upstash.delete(ids)
            return len(ids)
        found = self.collection.get(where={"doc_id": document_id}, include=[])
        ids = found.get("ids") or []
        if ids:
            self.collection.delete(ids=ids)
        return len(ids)

    def get_collection_stats(self) -> dict:
        if self.backend == "upstash":
            return {
                "backend": "upstash",
                "collection_name": "upstash-vector",
                "document_count": len(self.list_documents()),
                "chunk_count": self.upstash.count(),
            }
        return {
            "backend": "chroma",
            "collection_name": self._collection_name,
            "document_count": len(self.list_documents()),
            "chunk_count": self.collection.count(),
        }


rag_service = RAGService()
