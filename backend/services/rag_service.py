"""RAG service: chunking, ChromaDB storage and retrieval.

Embeddings are computed with the OpenAI embedding model (via `llm_service`)
and passed to Chroma explicitly, so Chroma never downloads its own model.
"""

import re
from collections import OrderedDict
from typing import Callable, List, Optional, Tuple

import chromadb
from chromadb.config import Settings as ChromaSettings

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


class RAGService:
    def __init__(
        self,
        client: Optional["chromadb.api.ClientAPI"] = None,
        embed_fn: Optional[EmbedFn] = None,
        collection_name: Optional[str] = None,
    ):
        self._client = client
        self._embed = embed_fn or llm_service.get_embeddings
        self._collection_name = collection_name or settings.collection_name
        self._collection = None

    @property
    def collection(self):
        if self._collection is None:
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

        # Chroma metadata values must be scalars.
        base = {
            k: v
            for k, v in (metadata or {}).items()
            if isinstance(v, (str, int, float, bool))
        }
        base.update({"document_name": document_name, "doc_id": document_id})

        self.collection.add(
            ids=[f"{document_id}:{i}" for i in range(len(chunks))],
            documents=chunks,
            embeddings=self._embed(chunks),
            metadatas=[{**base, "chunk_index": i} for i in range(len(chunks))],
        )
        return {
            "document_id": document_id,
            "document_name": document_name,
            "chunks": len(chunks),
            "characters": len(content),
        }

    # ------------------------------------------------------------ retrieve
    def retrieve_context(self, query: str, k: int = 3) -> Tuple[List[str], List[dict]]:
        total = self.collection.count()
        if k <= 0 or total == 0:
            return [], []
        results = self.collection.query(
            query_embeddings=self._embed([query]),
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
    def list_documents(self) -> List[dict]:
        docs: "OrderedDict[str, dict]" = OrderedDict()
        for meta in self.collection.get(include=["metadatas"]).get("metadatas") or []:
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
        found = self.collection.get(where={"doc_id": document_id}, include=[])
        ids = found.get("ids") or []
        if ids:
            self.collection.delete(ids=ids)
        return len(ids)

    def get_collection_stats(self) -> dict:
        return {
            "collection_name": self._collection_name,
            "document_count": len(self.list_documents()),
            "chunk_count": self.collection.count(),
        }


rag_service = RAGService()
