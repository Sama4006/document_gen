"""RAG Service - Handles ChromaDB vector storage and retrieval"""

import chromadb
from chromadb.config import Settings as ChromaSettings
from backend.config import settings
from backend.services.llm_service import llm_service
from typing import List, Tuple


class RAGService:
    def __init__(self):
        """Initialize ChromaDB client and collection"""
        # Create persistent ChromaDB client
        chroma_settings = ChromaSettings(
            chroma_db_impl="duckdb+parquet",
            persist_directory=settings.chroma_db_path,
            anonymized_telemetry=False
        )
        
        self.client = chromadb.Client(chroma_settings)
        self.collection = self.client.get_or_create_collection(
            name=settings.collection_name,
            metadata={"hnsw:space": "cosine"}
        )
    
    def ingest_document(
        self,
        document_id: str,
        content: str,
        document_name: str = "document",
        metadata: dict = None
    ) -> dict:
        """
        Ingest a document into the vector store
        
        Args:
            document_id: Unique identifier for document
            content: Document content
            document_name: Name of document
            metadata: Additional metadata
            
        Returns:
            Ingestion status
        """
        if metadata is None:
            metadata = {}
        
        # Add document metadata
        metadata.update({
            "document_name": document_name,
            "doc_id": document_id
        })
        
        # Add to collection
        self.collection.add(
            ids=[document_id],
            documents=[content],
            metadatas=[metadata]
        )
        
        return {
            "status": "success",
            "document_id": document_id,
            "document_name": document_name
        }
    
    def retrieve_context(
        self,
        query: str,
        k: int = 3
    ) -> Tuple[List[str], List[dict]]:
        """
        Retrieve relevant context from stored documents
        
        Args:
            query: Query string
            k: Number of results to retrieve
            
        Returns:
            Tuple of (documents, metadatas)
        """
        results = self.collection.query(
            query_texts=[query],
            n_results=k
        )
        
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        
        return documents, metadatas
    
    def format_context(
        self,
        documents: List[str],
        metadatas: List[dict]
    ) -> str:
        """
        Format retrieved documents into readable context
        
        Args:
            documents: Retrieved document snippets
            metadatas: Document metadata
            
        Returns:
            Formatted context string
        """
        if not documents:
            return ""
        
        context_parts = []
        for doc, meta in zip(documents, metadatas):
            doc_name = meta.get("document_name", "Unknown")
            context_parts.append(f"From {doc_name}:\n{doc}")
        
        return "\n\n---\n\n".join(context_parts)
    
    def get_collection_stats(self) -> dict:
        """Get statistics about the collection"""
        count = self.collection.count()
        return {
            "collection_name": settings.collection_name,
            "document_count": count
        }


# Singleton instance
rag_service = RAGService()
