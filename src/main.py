import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import get_settings
from dependencies import ESService
from services.elasticsearch import ElasticsearchService
from services.migrations import log_migration_results, run_migrations

# Configure logging to work with uvicorn
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s:     %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    settings = get_settings()
    es_service = ElasticsearchService()

    # Store in app state for dependency injection
    app.state.es_service = es_service

    logger.info("Starting up...")

    health = await es_service.health_check()
    if health.get("status") == "unavailable":
        logger.warning("Elasticsearch unavailable: %s", health.get("error"))
    else:
        logger.info(
            "Elasticsearch connected: %s (%s)",
            health["cluster_name"],
            health["status"],
        )

        logger.info("Running migrations...")
        results = await run_migrations(es_service, Path(settings.data_path))
        log_migration_results(results)

        stats = await es_service.get_index_stats()
        if stats and not stats.get("error"):
            for idx, s in stats.items():
                logger.info(
                    "Index %s: %d docs, %.2f MB",
                    idx,
                    s["doc_count"],
                    s["size_bytes"] / 1024 / 1024,
                )

    yield

    logger.info("Shutting down...")
    await es_service.close()


app = FastAPI(
    title="Product Search Engine",
    description="Elasticsearch-powered product search API",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
async def root():
    """Serve the search UI."""
    return FileResponse(static_dir / "index.html")


@app.get("/health")
async def health_check(es: ESService):
    """Check API and Elasticsearch health."""
    return {"api": "healthy", "elasticsearch": await es.health_check()}


@app.get("/stats")
async def index_stats(es: ESService):
    """Get all index statistics."""
    return await es.get_index_stats()


@app.get("/stats/{index_name}")
async def single_index_stats(index_name: str, es: ESService):
    """Get statistics for a specific index."""
    if index_name not in [es.PRODUCTS_INDEX, es.ORDERS_INDEX]:
        raise HTTPException(status_code=404, detail=f"Index '{index_name}' not found")
    return await es.get_index_stats(index_name)


@app.get("/users")
async def get_users(es: ESService):
    """Get all users with their order counts."""
    order_counts = await es.get_user_order_counts()
    # Sort by order count (descending) and return as list
    users = [
        {"user_id": user_id, "order_count": count}
        for user_id, count in sorted(
            order_counts.items(), key=lambda x: x[1], reverse=True
        )
    ]
    return {"users": users, "total": len(users)}


@app.get("/mappings/{index_name}")
async def get_mapping(index_name: str, es: ESService):
    """Get the index mapping."""
    if index_name == es.PRODUCTS_INDEX:
        return es.get_products_mapping()
    elif index_name == es.ORDERS_INDEX:
        return es.get_orders_mapping()
    raise HTTPException(status_code=404, detail=f"Index '{index_name}' not found")


@app.get("/search")
async def search_products(
    es: ESService,
    q: str = Query(..., description="Search query", min_length=1),
    size: int = Query(10, ge=1, le=100, description="Number of results"),
    start: int = Query(0, ge=0, description="Offset for pagination"),
    user_id: str | None = Query(None, description="User ID for personalized boosting"),
):
    """
    Search products across title, description, vendor, and attributes.

    Parameters:
    - q: Search query
    - size: Number of results
    - start: Offset for pagination
    - user_id: Optional user ID for personalized ranking based on purchase history
    """
    return await es.search_products(query=q, size=size, start=start, user_id=user_id)
