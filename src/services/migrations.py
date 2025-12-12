"""
Index migrations - handles creating and populating Elasticsearch indexes.
"""

import logging
from pathlib import Path

from services.elasticsearch import ElasticsearchService

logger = logging.getLogger(__name__)


async def run_migrations(es_service: ElasticsearchService, data_path: Path) -> dict:
    """
    Run all index migrations.
    Creates indexes if they don't exist and populates them with data.

    Returns a summary of what was done.
    """
    results = {
        "products": await _migrate_products(es_service, data_path),
        "orders": await _migrate_orders(es_service, data_path),
    }
    return results


async def _migrate_products(es_service: ElasticsearchService, data_path: Path) -> dict:
    """Migrate products index."""
    created = await es_service.ensure_products_index()

    if not created:
        return {"status": "skipped", "reason": "index already exists"}

    products_path = data_path / "products.json"
    if not products_path.exists():
        return {"status": "error", "reason": f"file not found: {products_path}"}

    count = await es_service.index_products(products_path)
    return {"status": "created", "indexed": count}


async def _migrate_orders(es_service: ElasticsearchService, data_path: Path) -> dict:
    """Migrate orders index."""
    created = await es_service.ensure_orders_index()

    if not created:
        return {"status": "skipped", "reason": "index already exists"}

    orders_path = data_path / "orders.json"
    if not orders_path.exists():
        return {"status": "error", "reason": f"file not found: {orders_path}"}

    count = await es_service.index_orders(orders_path)
    return {"status": "created", "indexed": count}


def log_migration_results(results: dict) -> None:
    """Log migration results."""
    for index_name, result in results.items():
        status = result["status"]
        if status == "created":
            logger.info(
                "Migration %s: created and indexed %d docs",
                index_name,
                result["indexed"],
            )
        elif status == "skipped":
            logger.info("Migration %s: skipped (%s)", index_name, result["reason"])
        elif status == "error":
            logger.error("Migration %s: %s", index_name, result["reason"])
