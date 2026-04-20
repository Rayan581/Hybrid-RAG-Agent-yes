import os
import logging
from functools import lru_cache
from typing import List, Optional
from chromadb import PersistentClient
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

# Configuration
CHROMA_PATH = os.getenv("CHROMA_PATH", "/app/chroma_db")
COLLECTION_NAME = "daraz_kb"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"

logger = logging.getLogger(__name__)

class Retriever:
    def __init__(self):
        # Disable telemetry to fix capture() error and save resources
        self.client = PersistentClient(
            path=CHROMA_PATH,
            settings=Settings(anonymized_telemetry=False)
        )
        self._model = None  # Model loaded lazily
        self.collection = self.client.get_or_create_collection(name=COLLECTION_NAME)
        logger.info(f"Retriever initialized (Lazy Loading enabled) for: {COLLECTION_NAME}")

    def _get_model(self) -> SentenceTransformer:
        """Loads the embedding model into RAM only when first needed."""
        if self._model is None:
            logger.info(f"Loading embedding model into RAM: {EMBED_MODEL_NAME}...")
            self._model = SentenceTransformer(EMBED_MODEL_NAME)
        return self._model

    @lru_cache(maxsize=128)
    def _get_query_embedding(self, query: str) -> List[float]:
        """Encodes query text with LRU caching to save CPU."""
        model = self._get_model()
        logger.debug(f"Computing embedding for query: {query[:50]}...")
        return model.encode(query).tolist()

    def search(self, query: str, top_k: int = 4) -> List[str]:
        """Retrieves top_k relevant documents from the vector store."""
        try:
            query_embedding = self._get_query_embedding(query)
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k
            )
            
            if results and results["documents"]:
                return results["documents"][0]
            return []
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def get_relevant_context(self, query: str, top_k: int = 4) -> str:
        """Formats top results into a single string for prompt injection."""
        docs = self.search(query, top_k)
        if not docs:
            return ""
            
        context_header = "\n[Retrieved Knowledge Context]\n"
        context_body = "\n".join([f"- {doc}" for doc in docs])
        return context_header + context_body + "\n"

# Singleton instance
retriever = Retriever()

