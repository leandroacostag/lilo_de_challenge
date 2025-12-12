"""FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from services.elasticsearch import ElasticsearchService


def get_es_service(request: Request) -> ElasticsearchService:
    """Get Elasticsearch service from app state."""
    es_service = getattr(request.app.state, "es_service", None)
    if es_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return es_service


# Type alias for cleaner endpoint signatures
ESService = Annotated[ElasticsearchService, Depends(get_es_service)]
