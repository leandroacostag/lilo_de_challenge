from pydantic import BaseModel, Field


class TextField(BaseModel):
    """Field with both raw (original) and normalized/cleaned value."""

    raw: str | None = None
    value: str | None = None


class Product(BaseModel):
    """Raw product model as received from JSON data."""

    id: str = Field(alias="_id")
    vendor: str | None = None
    sku: str | None = None
    title: str
    description: str | None = None
    unit_of_measure: str | None = None
    category: str | None = None
    attributes: dict | None = None
    region_availability: list[str] = []
    supplier_rating: float | None = None
    inventory_status: str | None = None
    bulk_pack_size: str | None = None

    class Config:
        populate_by_name = True


class AttributeValue(BaseModel):
    raw: str | None = None
    value: str | None = None


class NormalizedProduct(BaseModel):
    """Product model after normalization, ready for Elasticsearch indexing."""

    id: str
    sku: str | None = None
    embedding: list[float] | None = None  # Dense vector for semantic search (384 dims)

    # Text fields with raw + normalized value
    vendor: TextField = TextField()
    title: TextField = TextField()
    description: TextField = TextField()

    # Unit normalization
    unit_of_measure: str | None = None  # Normalized to standard (kg, g, lb, oz, L, gal)

    # Weight in multiple units (for user preference filtering)
    weight_kg: float | None = None
    weight_g: float | None = None
    weight_lb: float | None = None
    weight_oz: float | None = None

    # Category hierarchy
    category: str | None = None  # Cleaned category path
    category_level1: str | None = None
    category_level2: str | None = None
    category_level3: str | None = None

    # Raw attributes (stored, not indexed)
    attributes: dict | None = None

    # Synthetic searchable field: normalized attribute keys + values as string
    # Used in embeddings for semantic search (title + description + attributes)
    attributes_search: str | None = None

    # Arrays and numerics
    region_availability: list[str] = []
    supplier_rating: float | None = None
    inventory_status: str | None = None
    bulk_pack_quantity: int | None = None  # Parsed from bulk_pack_size
