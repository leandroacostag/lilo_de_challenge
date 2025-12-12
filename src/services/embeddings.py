"""
Embedding service using sentence-transformers for semantic search.

Uses all-MiniLM-L6-v2 model:
- 384 dimensions
- Fast inference (~80MB model)
- Good semantic quality for product search
"""

import logging
from functools import lru_cache

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Model configuration
MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """
    Load and cache the embedding model.
    Uses lru_cache to ensure the model is loaded only once.
    """
    logger.info(f"Loading embedding model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)
    logger.info(f"Model loaded. Embedding dimension: {EMBEDDING_DIM}")
    return model


class EmbeddingService:
    """
    Service for generating text embeddings.
    Optimized for batch processing during indexing and single queries during search.
    """

    def __init__(self):
        self.model = get_embedding_model()
        self.dimension = EMBEDDING_DIM

    def embed_text(self, text: str) -> list[float]:
        """
        Generate embedding for a single text.
        Used during search queries.
        """
        if not text:
            return [0.0] * self.dimension

        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.
        Used during batch indexing for better performance.
        """
        if not texts:
            return []

        # Replace empty strings with placeholder
        processed_texts = [t if t else " " for t in texts]

        embeddings = self.model.encode(
            processed_texts,
            convert_to_numpy=True,
            show_progress_bar=len(texts) > 100,
            batch_size=32,
        )
        return embeddings.tolist()

    def embed_product(
        self,
        title: str,
        description: str | None = None,
        attributes_search: str | None = None,
    ) -> list[float]:
        """
        Generate embedding for a product using title + description + attributes_search.

        This approach (used by Amazon and other major marketplaces) includes
        attribute information in embeddings for better semantic understanding.

        Args:
            title: Product title
            description: Product description (optional)
            attributes_search: Normalized attributes as string "key1: value1, key2: value2" (optional)

        Returns:
            Embedding vector (384 dimensions)
        """
        # Combine title, description, and attributes for richer semantic representation
        text_parts = [title]
        if description:
            text_parts.append(description)
        if attributes_search:
            text_parts.append(attributes_search)

        combined_text = " ".join(text_parts)
        return self.embed_text(combined_text)

    def embed_products_batch(
        self, products: list[tuple[str, str | None, str | None]]
    ) -> list[list[float]]:
        """
        Generate embeddings for multiple products.

        Args:
            products: List of (title, description, attributes_search) tuples

        Returns:
            List of embedding vectors
        """
        combined_texts = []
        for title, description, attributes_search in products:
            text_parts = [title or ""]
            if description:
                text_parts.append(description)
            if attributes_search:
                text_parts.append(attributes_search)
            combined_texts.append(" ".join(text_parts))

        return self.embed_texts(combined_texts)

