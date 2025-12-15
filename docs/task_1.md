# Task 1 — Index Design and Mapping

## Index & Analyzers
- **Index:** `products` (mapping in `infra/elasticsearch/mappings/products.json`)
- **Analyzers:**  
  - `product_analyzer`: standard + lowercase + product_synonyms + english_stop + english_stemmer  
  - `product_search_analyzer`: standard + lowercase + product_synonyms  
  - `keyword_normalizer`: lowercase + trim  
  - Synonyms injected from `data/synonyms.json`

## Key Fields
- `title.value`, `description.value` (text, searchable); `.raw` stored, not indexed  
- `vendor.value` keyword + `.text`; `.raw` stored  
- `category` text + `.keyword`; `category_level1/2/3` keywords  
- `attributes_search` text (searchable); raw `attributes` stored (not indexed)  
- `embedding` dense_vector (384, cosine)  
- Numerics: weight_kg/g/lb/oz, supplier_rating, bulk_pack_quantity  
- Arrays: region_availability

## Handling Messy Data
- Attribute keys normalized (lowercase/underscores); search uses `attributes_search`; raw attributes kept for UI.  
- Units normalized; weight converted to kg/g/lb/oz.  
- Multi-region stored as keyword array.  
- Junk/duplicates removed; `.raw` preserves originals.

## Field Roles
- **Searchable:** `title.value`, `description.value`, `vendor.value.text`, `category`, `attributes_search`, `embedding`
- **Filterable:** `vendor.value`, `category_level1/2/3`, `region_availability`, `inventory_status`, `unit_of_measure`, `sku`
- **Boosting:** title, vendor, category, numeric patterns via `attributes_search`, embeddings

## Deliverable
- Mapping JSON + analyzers: `infra/elasticsearch/mappings/products.json`
# Task 1 — Index Design and Mapping

## Overview

This document describes the Elasticsearch index design for the products dataset, including mapping types, analyzers, and data normalization strategies.

## Index Mapping

The products index mapping is defined in [`infra/elasticsearch/mappings/products.json`](../infra/elasticsearch/mappings/products.json).

### Analyzers

We define custom analyzers to optimize product search:

#### `product_analyzer` (Index-time)
```json
{
  "type": "custom",
  "tokenizer": "standard",
  "filter": ["lowercase", "product_synonyms", "english_stop", "english_stemmer"]
}
```
- **standard tokenizer**: Splits on whitespace and punctuation
- **lowercase**: Case-insensitive matching
- **product_synonyms**: Expands domain-specific terms (e.g., "wrench" ↔ "spanner")
- **english_stop**: Removes common words ("the", "a", "is")
- **english_stemmer**: Reduces words to roots ("running" → "run")

#### `product_search_analyzer` (Search-time)
```json
{
  "type": "custom",
  "tokenizer": "standard",
  "filter": ["lowercase", "product_synonyms"]
}
```
- No stemming at search time to avoid over-matching
- Synonyms applied so "wrench" finds "spanner" results

#### `keyword_normalizer`
```json
{
  "type": "custom",
  "filter": ["lowercase", "trim"]
}
```
- Used for exact-match keyword fields (vendor, category levels, SKU)
- Enables case-insensitive filtering

### Field Types

| Field | Type | Purpose |
|-------|------|---------|
| `id` | keyword | Unique identifier |
| `sku` | keyword (normalized) | Exact match lookups |
| `vendor.raw` | keyword | Original vendor name |
| `vendor.value` | keyword + text subfield | Normalized vendor for filtering/search |
| `title.raw` | text (not indexed) | Original title for display |
| `title.value` | text + keyword subfield | Cleaned title for search |
| `description.raw` | text (not indexed) | Original description for display |
| `description.value` | text | Cleaned description for search |
| `unit_of_measure` | keyword (normalized) | Filter by unit |
| `weight_kg/g/lb/oz` | float | Range queries in user's preferred unit |
| `category` | text + keyword subfield | Full-text and exact category search |
| `category_level1/2/3` | keyword (normalized) | Hierarchical filtering |
| `attributes.*` | mixed (keyword/float/int) | Faceted filtering |
| `region_availability` | keyword array | Multi-value filtering |
| `supplier_rating` | float | Range queries, boosting |
| `inventory_status` | keyword (normalized) | Filter by stock status |
| `bulk_pack_quantity` | integer | Range queries |

## TextField Structure

Text fields that require normalization use a `{raw, value}` structure:

```json
{
  "title": {
    "raw": "Nitrile Gloves ### $$ heavy duty heavy duty",
    "value": "Nitrile Gloves heavy duty"
  },
  "vendor": {
    "raw": "United Fasteners",
    "value": "united fasteners"
  }
}
```

- **`.raw`** - Original value for display/debugging (not indexed for title/description)
- **`.value`** - Normalized/cleaned value for search and filtering

This pattern applies to: `title`, `description`, `vendor`

## Data Normalization

Raw product data is cleaned and normalized before indexing. The normalization logic is in [`src/services/normalizer.py`](../src/services/normalizer.py) with configuration in [`src/config/normalizer.json`](../src/config/normalizer.json).

### Inconsistent Attribute Keys

**Problem**: Attribute keys have typos and variations:
```json
{"bulkaPck": "dozen", "opwer_hp": "3 HP", "colour": "red"}
```

**Solution**: Two-stage normalization:

1. **Explicit aliases**: Known variations mapped directly
   ```json
   {"colour": "color", "hp": "power_hp", "volt": "voltage"}
   ```

2. **Fuzzy matching**: Unknown keys matched against canonical list using [rapidfuzz](https://github.com/rapidfuzz/RapidFuzz) with 80% threshold
   - `"opwer_hp"` → matches `"power_hp"` (87% similarity)
   - `"bulkaPck"` → matches `"bulk_pack"` (82% similarity)

**Result**:
```json
{"bulk_pack": "dozen", "power_hp": 3.0, "color": "red"}
```

### Non-normalized Units

**Problem**: Units have inconsistent formats:
```
"kg", "kgs", "KG", "kilogram", "Grams", "lbs", "oz", "Liters"
```

**Solution**: 
1. **Unit mapping**: All variations normalized to canonical form
   ```json
   {"kgs": "kg", "Grams": "g", "lbs": "lb", "Liters": "L"}
   ```

2. **Weight conversion**: All weight units converted to multiple formats for user preference
   - `weight_kg`, `weight_g`, `weight_lb`, `weight_oz`
   - Users can filter/sort in their preferred unit

**Example**:
- Input: `"unit_of_measure": "Grams"`
- Output:
  ```json
  {
    "unit_of_measure": "g",
    "weight_kg": 0.001,
    "weight_g": 1.0,
    "weight_lb": 0.002205,
    "weight_oz": 0.035274
  }
  ```

### Multi-region Availability Arrays

**Problem**: Products available in multiple regions:
```json
{"region_availability": ["US", "CA", "MX", "BR"]}
```

**Solution**: 
- Stored as keyword array in Elasticsearch
- Enables `terms` queries for filtering by any region
- No normalization needed (already clean ISO codes)

**Query example**:
```json
{"terms": {"region_availability": ["US", "CA"]}}
```

### Duplicated and Ambiguous Text

**Problem**: Titles/descriptions contain:
- Junk characters: `"### $$ %% @@"`
- Repeated words: `"heavy duty heavy duty"`
- Extra whitespace

**Solution**: Text cleaning pipeline:
1. Remove junk patterns via regex: `[#$%@]{2,}`
2. Normalize whitespace
3. Remove consecutive duplicate words

**Example**:
- Input: `"Nitrile Gloves ### $$ %% @@ heavy duty heavy duty"`
- Output:
  ```json
  {
    "title": {
      "raw": "Nitrile Gloves ### $$ %% @@ heavy duty heavy duty",
      "value": "Nitrile Gloves heavy duty"
    }
  }
  ```

### Category Parsing

**Problem**: Categories as delimited strings with inconsistent separators:
```
"Industrial>Compressors>Air Compressors"
"Safety / PPE / Gloves"
```

**Solution**: Parse into hierarchy:
- Clean separators (`>`, `/`, `|`) → ` > `
- Extract up to 3 levels for faceted filtering

**Output**:
```json
{
  "category": "Industrial > Compressors > Air Compressors",
  "category_level1": "industrial",
  "category_level2": "compressors", 
  "category_level3": "air compressors"
}
```

### Bulk Pack Quantity Parsing

**Problem**: Various formats for pack sizes:
```
"100 pcs", "dozen", "6-pack", "50 units"
```

**Solution**: Extract numeric quantity:
- Parse numbers from strings: `"100 pcs"` → `100`
- Map words to numbers: `"dozen"` → `12`

## Field Usage Summary

### Searchable Fields (Full-text)
- `title.value` - Primary search field (cleaned)
- `description.value` - Secondary search field (cleaned)
- `category` - Category text search
- `vendor.value.text` - Vendor name search
- `attributes.notes` - Attribute notes

### Filterable Fields (Exact match)
- `vendor.value` - Filter by vendor
- `category_level1/2/3` - Category facets
- `region_availability` - Region filter
- `inventory_status` - Stock filter
- `unit_of_measure` - Unit filter
- `attributes.color`, `attributes.material` - Attribute facets
- `sku` - SKU lookup

### Numeric Range Fields
- `supplier_rating` - Rating filter/sort
- `weight_kg`, `weight_g`, `weight_lb`, `weight_oz` - Weight range queries (user preference)
- `bulk_pack_quantity` - Pack size filter
- `attributes.voltage`, `attributes.power_hp`, etc.

### Boosting Candidates
- `supplier_rating` - Higher rated products first
- `inventory_status` - In-stock products boosted
- `title` - Title matches weighted higher than description

## Synonyms

Product synonyms are loaded from [`data/synonyms.json`](../data/synonyms.json) and injected into the mapping at index creation time. This allows domain-specific term expansion:

```json
["pipe, tube, conduit", "wrench, spanner", "bolt, screw, fastener"]
```

## Files

| File | Purpose |
|------|---------|
| `infra/elasticsearch/mappings/products.json` | ES index mapping |
| `src/config/normalizer.json` | Normalization configuration |
| `src/services/normalizer.py` | Normalization logic |
| `src/services/elasticsearch.py` | Index creation & bulk indexing |
| `data/synonyms.json` | Product synonyms |

