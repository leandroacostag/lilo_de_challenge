import asyncio
import json
import logging
import re
from pathlib import Path

from elasticsearch import AsyncElasticsearch
from rapidfuzz import process

from config import get_settings
from models.product import Product
from services.embeddings import EmbeddingService
from services.normalizer import ProductNormalizer

logger = logging.getLogger(__name__)


class ElasticsearchService:
    """
    Elasticsearch service for index management and document operations.
    Handles both products and orders indexes.
    """

    PRODUCTS_INDEX = "products"
    ORDERS_INDEX = "orders"

    def __init__(self):
        settings = get_settings()
        self.client = AsyncElasticsearch(
            hosts=[settings.elasticsearch_url],
            basic_auth=(settings.elasticsearch_user, settings.elasticsearch_password),
        )
        self.normalizer = ProductNormalizer()
        self.embedding_service = EmbeddingService()
        self._data_path = Path(settings.data_path)
        self._mappings_path = (
            Path(__file__).parent.parent.parent / "infra" / "elasticsearch" / "mappings"
        )
        self._synonyms = self._load_synonyms(self._data_path / "synonyms.json")
        self._cached_vendors: list[str] | None = None

    def _load_synonyms(self, path: Path) -> list[str]:
        """Load synonyms in Elasticsearch format."""
        synonyms = []
        if path.exists():
            with open(path) as f:
                pairs = json.load(f)
                for pair in pairs:
                    if len(pair) == 2:
                        synonyms.append(f"{pair[0]}, {pair[1]}")
        return synonyms

    def _load_mapping(self, mapping_name: str, inject_synonyms: bool = False) -> dict:
        """Load index mapping from JSON file."""
        mapping_path = self._mappings_path / f"{mapping_name}.json"
        with open(mapping_path) as f:
            mapping = json.load(f)

        mapping.pop("$schema", None)
        mapping.pop("$comment", None)

        # Inject synonyms only for products mapping
        if inject_synonyms and "analysis" in mapping.get("settings", {}):
            filters = mapping["settings"]["analysis"].get("filter", {})
            if "product_synonyms" in filters:
                filters["product_synonyms"]["synonyms"] = self._synonyms

        return mapping

    async def close(self):
        """Close the Elasticsearch client connection."""
        await self.client.close()

    async def index_exists(self, index_name: str) -> bool:
        """Check if an index exists."""
        return await self.client.indices.exists(index=index_name)

    async def ensure_index(
        self, index_name: str, mapping_name: str, inject_synonyms: bool = False
    ) -> bool:
        """
        Create index only if it doesn't exist.
        Returns True if index was created, False if it already existed.
        """
        if await self.index_exists(index_name):
            return False

        mapping = self._load_mapping(mapping_name, inject_synonyms=inject_synonyms)
        await self.client.indices.create(index=index_name, body=mapping)
        return True

    async def ensure_products_index(self) -> bool:
        """Create products index if it doesn't exist."""
        return await self.ensure_index(
            self.PRODUCTS_INDEX, "products", inject_synonyms=True
        )

    async def ensure_orders_index(self) -> bool:
        """Create orders index if it doesn't exist."""
        return await self.ensure_index(
            self.ORDERS_INDEX, "orders", inject_synonyms=False
        )

    async def index_products(self, products_path: Path) -> int:
        """
        Load, normalize, generate embeddings, and bulk index products.
        Uses chunked batches to avoid overwhelming ES with large payloads.
        Returns the number of indexed documents.
        """
        BATCH_SIZE = 500  # Smaller batches due to embedding size

        with open(products_path) as f:
            raw_products = json.load(f)

        # Step 1: Normalize all products
        logger.info(f"Normalizing {len(raw_products)} products...")
        normalized_products = []
        for raw in raw_products:
            product = Product(**raw)
            normalized = self.normalizer.normalize(product)
            normalized_products.append(normalized)

        # Step 2: Generate embeddings in batch
        logger.info("Generating embeddings for products...")
        product_texts = [
            (
                p.title.value or p.title.raw or "",
                p.description.value,
                p.attributes_search,
            )
            for p in normalized_products
        ]
        embeddings = self.embedding_service.embed_products_batch(product_texts)
        logger.info(f"Generated {len(embeddings)} embeddings")

        # Step 3: Assign embeddings to products
        for normalized, embedding in zip(normalized_products, embeddings, strict=True):
            normalized.embedding = embedding

        # Step 4: Bulk index in chunks
        total_indexed = 0
        total_batches = (len(normalized_products) + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_num in range(total_batches):
            start_idx = batch_num * BATCH_SIZE
            end_idx = min(start_idx + BATCH_SIZE, len(normalized_products))
            batch = normalized_products[start_idx:end_idx]

            operations = []
            for normalized in batch:
                operations.append(
                    {"index": {"_index": self.PRODUCTS_INDEX, "_id": normalized.id}}
                )
                operations.append(normalized.model_dump(exclude_none=True))

            logger.info(
                f"Indexing batch {batch_num + 1}/{total_batches} ({len(batch)} docs)..."
            )

            response = await self.client.bulk(operations=operations, refresh=False)
            if response.get("errors"):
                errors = [
                    item
                    for item in response["items"]
                    if "error" in item.get("index", {})
                ]
                logger.error("Bulk indexing errors (products): %s", errors[:5])

            total_indexed += len(batch)

            # Small delay between batches to let ES breathe
            if batch_num < total_batches - 1:
                await asyncio.sleep(0.5)

        # Final refresh after all batches
        await self.client.indices.refresh(index=self.PRODUCTS_INDEX)
        logger.info(f"Indexed {total_indexed} products total")

        return total_indexed

    async def index_orders(self, orders_path: Path) -> int:
        """
        Load and bulk index orders with computed fields.
        Returns the number of indexed documents.
        """
        with open(orders_path) as f:
            raw_orders = json.load(f)

        operations = []
        for order in raw_orders:
            # Compute total_items and total_amount
            items = order.get("cart", {}).get("items", [])
            total_items = sum(item.get("quantity", 0) for item in items)
            total_amount = sum(
                item.get("price", 0) * item.get("quantity", 0) for item in items
            )

            doc = {
                **order,
                "total_items": total_items,
                "total_amount": round(total_amount, 2),
            }

            operations.append(
                {"index": {"_index": self.ORDERS_INDEX, "_id": order["order_id"]}}
            )
            operations.append(doc)

        if operations:
            response = await self.client.bulk(operations=operations, refresh=True)
            if response.get("errors"):
                errors = [
                    item
                    for item in response["items"]
                    if "error" in item.get("index", {})
                ]
                logger.error("Bulk indexing errors (orders): %s", errors[:5])

            return len(raw_orders)

        return 0

    async def get_index_stats(self, index_name: str | None = None) -> dict:
        """Get statistics about an index or all indexes."""
        try:
            if index_name:
                stats = await self.client.indices.stats(index=index_name)
                count = await self.client.count(index=index_name)
                size = stats["_all"]["primaries"]["store"]["size_in_bytes"]
                return {
                    "index": index_name,
                    "doc_count": count["count"],
                    "size_bytes": size,
                }
            else:
                # Return stats for all managed indexes
                result = {}
                for idx in [self.PRODUCTS_INDEX, self.ORDERS_INDEX]:
                    if await self.index_exists(idx):
                        stats = await self.client.indices.stats(index=idx)
                        count = await self.client.count(index=idx)
                        size = stats["_all"]["primaries"]["store"]["size_in_bytes"]
                        result[idx] = {
                            "doc_count": count["count"],
                            "size_bytes": size,
                        }
                return result
        except Exception as e:
            return {"error": str(e)}

    async def health_check(self) -> dict:
        """Check Elasticsearch cluster health."""
        try:
            health = await self.client.cluster.health()
            return {
                "status": health["status"],
                "cluster_name": health["cluster_name"],
                "number_of_nodes": health["number_of_nodes"],
            }
        except Exception as e:
            return {"status": "unavailable", "error": str(e)}

    def get_products_mapping(self) -> dict:
        """Get the products index mapping."""
        return self._load_mapping("products", inject_synonyms=True)

    def get_orders_mapping(self) -> dict:
        """Get the orders index mapping."""
        return self._load_mapping("orders", inject_synonyms=False)

    async def get_user_purchase_history(self, user_id: str) -> dict[str, int]:
        """
        Get user's purchase history from orders index.

        Returns a dict mapping product_id -> total_quantity_ordered.
        This is used for personalized boosting in search results.
        """
        if not user_id:
            return {}

        try:
            # Query orders for this user and aggregate product quantities
            response = await self.client.search(
                index=self.ORDERS_INDEX,
                body={
                    "size": 0,  # We only want aggregations
                    "query": {"term": {"user_id": user_id}},
                    "aggs": {
                        "products": {
                            "nested": {"path": "cart.items"},
                            "aggs": {
                                "by_product": {
                                    "terms": {
                                        "field": "cart.items.product_id",
                                        "size": 1000,  # Get up to 1000 unique products
                                    },
                                    "aggs": {
                                        "total_quantity": {
                                            "sum": {"field": "cart.items.quantity"}
                                        }
                                    },
                                }
                            },
                        }
                    },
                },
            )

            # Extract product_id -> quantity mapping
            purchase_history = {}
            buckets = (
                response.get("aggregations", {})
                .get("products", {})
                .get("by_product", {})
                .get("buckets", [])
            )

            for bucket in buckets:
                product_id = bucket["key"]
                quantity = int(bucket["total_quantity"]["value"])
                purchase_history[product_id] = quantity

            logger.debug(
                f"User {user_id} has {len(purchase_history)} products in purchase history"
            )
            return purchase_history

        except Exception as e:
            logger.error(f"Error fetching purchase history for user {user_id}: {e}")
            return {}

    async def get_user_order_counts(self) -> dict[str, int]:
        """
        Get order counts for all users.
        Returns a dictionary mapping user_id -> order_count.
        """
        try:
            response = await self.client.search(
                index=self.ORDERS_INDEX,
                size=0,  # We only want aggregations
                aggs={
                    "users": {
                        "terms": {
                            "field": "user_id",
                            "size": 10000,  # Get all users
                        }
                    }
                },
            )

            user_counts = {}
            buckets = (
                response.get("aggregations", {}).get("users", {}).get("buckets", [])
            )

            for bucket in buckets:
                user_id = bucket["key"]
                count = bucket["doc_count"]
                user_counts[user_id] = count

            logger.debug(f"Found order counts for {len(user_counts)} users")
            return user_counts

        except Exception as e:
            logger.error(f"Error fetching user order counts: {e}")
            return {}

    async def search_products(
        self,
        query: str,
        size: int = 10,
        start: int = 0,
        user_id: str | None = None,
    ) -> dict:
        """
        Hybrid search combining BM25 (keyword) and kNN (semantic) with manual RRF.

        Since ES basic license doesn't support built-in RRF, we implement it manually:
        1. Run BM25 text search
        2. Run kNN vector search
        3. Combine results using RRF formula: score = sum(1 / (k + rank_i))
        4. Apply user-level boosting based on purchase history (if user_id provided)

        This naturally combines rankings without needing to normalize scores.
        """
        logger.debug(f"Query: {query}, User: {user_id}")

        # Generate query embedding for semantic search
        query_embedding = self.embedding_service.embed_text(query)

        # Fetch vendors and build BM25 query
        bm25_query = await self._build_bm25_query(query)

        # Fetch more candidates for RRF fusion
        fetch_size = min(size * 5, 200)

        # Fetch user purchase history if user_id provided
        user_history = {}
        if user_id:
            user_history = await self.get_user_purchase_history(user_id)

        # Run both searches in parallel
        bm25_response, knn_response = await asyncio.gather(
            self.client.search(
                index=self.PRODUCTS_INDEX,
                body={"query": bm25_query, "size": fetch_size},
            ),
            self.client.search(
                index=self.PRODUCTS_INDEX,
                body={
                    "knn": {
                        "field": "embedding",
                        "query_vector": query_embedding,
                        "k": fetch_size,
                        "num_candidates": fetch_size * 2,
                    },
                    "size": fetch_size,
                },
            ),
        )

        # Apply manual RRF fusion with user-level boosting
        fused_results, total = self._apply_rrf(
            bm25_response,
            knn_response,
            k=60,
            size=size,
            start=start,
            user_purchase_history=user_history,
        )

        return self._format_rrf_response(fused_results, total, query, user_id)

    def _apply_rrf(
        self,
        bm25_response: dict,
        knn_response: dict,
        k: int = 60,
        size: int = 10,
        start: int = 0,
        user_purchase_history: dict[str, int] | None = None,
    ) -> tuple[list[dict], int]:
        """
        Apply Reciprocal Rank Fusion to combine BM25 and kNN results.

        RRF score = sum(1 / (k + rank)) for each ranking method
        k is a constant (typically 60) that smooths the ranking contribution.

        If user_purchase_history is provided, applies additional boost based on
        how many times the user has ordered each product:
        - 1-5 orders: 1.2x boost
        - 6-20 orders: 1.5x boost
        - 21-50 orders: 2.0x boost
        - 50+ orders: 2.5x boost
        """
        user_history = user_purchase_history or {}

        # Build rank maps: doc_id -> rank (1-indexed)
        bm25_ranks = {}
        for rank, hit in enumerate(bm25_response["hits"]["hits"], 1):
            bm25_ranks[hit["_id"]] = rank

        knn_ranks = {}
        for rank, hit in enumerate(knn_response["hits"]["hits"], 1):
            knn_ranks[hit["_id"]] = rank

        # Collect all unique documents
        all_docs = {}
        for hit in bm25_response["hits"]["hits"]:
            all_docs[hit["_id"]] = hit
        for hit in knn_response["hits"]["hits"]:
            if hit["_id"] not in all_docs:
                all_docs[hit["_id"]] = hit

        # Calculate RRF scores with user-level boosting
        rrf_scores = []
        for doc_id, hit in all_docs.items():
            score = 0.0
            # BM25 contribution
            if doc_id in bm25_ranks:
                score += 1.0 / (k + bm25_ranks[doc_id])
            # kNN contribution
            if doc_id in knn_ranks:
                score += 1.0 / (k + knn_ranks[doc_id])

            # Apply user purchase history boost
            user_boost = 1.0
            user_orders = 0
            product_id = hit["_source"].get("id")
            if product_id and product_id in user_history:
                user_orders = user_history[product_id]
                if user_orders >= 50:
                    user_boost = 2.5
                elif user_orders >= 21:
                    user_boost = 2.0
                elif user_orders >= 6:
                    user_boost = 1.5
                elif user_orders >= 1:
                    user_boost = 1.2

            final_score = score * user_boost

            rrf_scores.append(
                {
                    "doc_id": doc_id,
                    "rrf_score": final_score,
                    "base_rrf_score": score,
                    "user_boost": user_boost,
                    "user_orders": user_orders,
                    "bm25_rank": bm25_ranks.get(doc_id),
                    "knn_rank": knn_ranks.get(doc_id),
                    "hit": hit,
                }
            )

        # Sort by RRF score descending
        rrf_scores.sort(key=lambda x: x["rrf_score"], reverse=True)

        total_fused = len(rrf_scores)

        # Apply pagination
        return rrf_scores[start : start + size], total_fused

    def _format_rrf_response(
        self,
        rrf_results: list[dict],
        total: int,
        query: str,
        user_id: str | None = None,
    ) -> dict:
        """Format RRF results into API response."""
        results = []
        for item in rrf_results:
            hit = item["hit"]
            source = hit["_source"]
            result = {
                "id": source.get("id"),
                "score": item["rrf_score"],
                "bm25_rank": item["bm25_rank"],
                "knn_rank": item["knn_rank"],
                "title": source.get("title", {}).get("raw"),
                "description": source.get("description", {}).get("raw"),
                "vendor": source.get("vendor", {}).get("raw"),
                "category": source.get("category"),
                "sku": source.get("sku"),
                "supplier_rating": source.get("supplier_rating"),
                "inventory_status": source.get("inventory_status"),
                "attributes": source.get("attributes", {}),
            }

            # Include user boosting info if available
            if user_id and item.get("user_orders", 0) > 0:
                result["user_boost"] = item["user_boost"]
                result["user_orders"] = item["user_orders"]
                result["base_score"] = item["base_rrf_score"]

            results.append(result)

        response = {
            "query": query,
            "total": total,
            "returned": len(results),
            "results": results,
        }

        if user_id:
            response["user_id"] = user_id

        return response

    async def _get_vendors_from_index(self) -> list[str]:
        """
        Fetch unique vendors from Elasticsearch products index.
        Returns a list of normalized vendor names (lowercase).
        """
        try:
            response = await self.client.search(
                index=self.PRODUCTS_INDEX,
                size=0,  # We only want aggregations
                aggs={
                    "vendors": {
                        "terms": {
                            "field": "vendor.value",
                            "size": 10000,  # Get all vendors
                        }
                    }
                },
            )

            vendors = []
            buckets = (
                response.get("aggregations", {}).get("vendors", {}).get("buckets", [])
            )

            for bucket in buckets:
                vendor = bucket["key"]
                if vendor:  # Skip None/empty values
                    vendors.append(vendor.lower())

            logger.debug(f"Loaded {len(vendors)} vendors from index")
            return vendors

        except Exception as e:
            logger.warning(
                f"Failed to fetch vendors from index: {e}. Using empty list."
            )
            return []

    async def _get_cached_vendors(self) -> list[str]:
        """
        Get cached vendor list, fetching from ES if not cached.
        This is async because we need to query Elasticsearch.
        """
        if self._cached_vendors is None:
            self._cached_vendors = await self._get_vendors_from_index()
        return self._cached_vendors

    def _extract_numbers(self, query: str) -> list[float]:
        """Extract numeric values from query (e.g., '50mm' -> 50.0)."""
        numbers: list[float] = []
        for match in re.finditer(r"(\d+(?:\.\d+)?)", query):
            try:
                num = float(match.group(1))
                numbers.append(num)
            except ValueError:
                continue
        return numbers

    def _detect_vendor_in_query(
        self, query: str, known_vendors: list[str]
    ) -> str | None:
        """
        Detect known vendor names in query using fuzzy matching.
        Returns the vendor name if found with sufficient similarity, None otherwise.

        Uses rapidfuzz to handle typos and variations (e.g., "weir" matches "wier", "weer").
        Uses the fuzzy_match_threshold from normalizer config (default: 80%).

        Args:
            query: Search query string
            known_vendors: List of vendor names to check

        Returns:
            Matched vendor name (lowercase) if similarity >= threshold, None otherwise
        """
        if not known_vendors:
            logger.warning("_detect_vendor_in_query called without vendors list")
            return None

        query_lower = query.lower()

        # First, try exact substring match (fast path)
        for vendor in known_vendors:
            if vendor in query_lower:
                return vendor

        # If no exact match, try fuzzy matching
        query_words = query_lower.split()
        for word in query_words:
            result = process.extractOne(
                word,
                known_vendors,
                score_cutoff=self.normalizer.fuzzy_threshold,
            )

            if result:
                matched_vendor, score, _ = result
                logger.debug(
                    f"Fuzzy matched vendor '{matched_vendor}' (score: {score:.1f}%) "
                    f"from query word '{word}'"
                )
                return matched_vendor

        return None

    async def _build_bm25_query(self, query: str) -> dict:
        """
        Build BM25 query with intelligent boosting.

        Strategy:
        - Vendor detection: Strong boost for vendor matches
        - Combined boost: Vendor + attribute match together
        - Category matching: Handled naturally by BM25 and semantic search

        Args:
            query: Search query string
        """
        known_vendors = await self._get_cached_vendors()

        # Extract features from query
        detected_vendor = self._detect_vendor_in_query(query, known_vendors)
        numeric_values = self._extract_numbers(query)

        bool_query = {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query,
                            "fields": [
                                "title.value^5",
                                "category^3",
                                "vendor.value.text^4",  # Increased vendor weight
                                "description.value",
                                "attributes_search^2",  # Attributes in searchable format
                            ],
                            "type": "best_fields",
                            "tie_breaker": 0.3,
                        }
                    }
                ],
                "should": [
                    # Phrase boost for title
                    {"match_phrase": {"title.value": {"query": query, "boost": 10}}},
                    # Category match boost
                    {"match": {"category": {"query": query, "boost": 3}}},
                ],
            }
        }

        # Vendor boost - moderate, but combined with attributes gets super boost
        if detected_vendor:
            bool_query["bool"]["should"].append(
                {
                    "match": {
                        "vendor.value.text": {"query": detected_vendor, "boost": 30}
                    }
                }
            )
            bool_query["bool"]["should"].append(
                {
                    "wildcard": {
                        "vendor.value": {"value": f"*{detected_vendor}*", "boost": 20}
                    }
                }
            )
        else:
            # General vendor match
            bool_query["bool"]["should"].append(
                {"match": {"vendor.value.text": {"query": query, "boost": 3}}}
            )

        # Numeric value boosts (keyless): boost products mentioning the numbers
        for num in numeric_values:
            # Boost when the number appears in attributes_search text
            bool_query["bool"]["should"].append(
                {
                    "match_phrase": {
                        "attributes_search": {
                            "query": str(num),
                            "boost": 40,
                        }
                    }
                }
            )
            # Light boost if number appears in title
            bool_query["bool"]["should"].append(
                {
                    "match_phrase": {
                        "title.value": {
                            "query": str(int(num)) if num.is_integer() else str(num),
                            "boost": 10,
                        }
                    }
                }
            )

        return bool_query
