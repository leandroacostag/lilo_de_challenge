# Task 2 — Core Search Functionality

## API
- Endpoint: `GET /search?q=...&size=...&start=...&user_id=...`
- Uses hybrid BM25 + embeddings + manual boosts. Searchable fields: `title.value`, `description.value`, `vendor.value.text`, `category`, `attributes_search`, `embedding`.

## Query DSL (BM25 core)
```json
{
  "query": {
    "bool": {
      "must": [{
        "multi_match": {
          "query": "<q>",
          "fields": [
            "title.value^5",
            "category^3",
            "vendor.value.text^4",
            "description.value",
            "attributes_search^2"
          ],
          "type": "best_fields",
          "tie_breaker": 0.3
        }
      }],
      "should": [
        { "match_phrase": { "title.value": { "query": "<q>", "boost": 10 } } },
        { "match": { "category": { "query": "<q>", "boost": 3 } } }
      ]
    }
  }
}
```

## Example queries (expected behavior)
- `3 hp sewage pump weir` → Weir pumps with 3hp rank high.
- `nitrile glove bulk pack` → Nitrile gloves in bulk at the top.
- `pvc pipe 50mm` → Pipes with a 50mm attribute boosted via numeric pattern.
- `tomato` → Food items first.
- `tomato makeup` → Cosmetics first.

## Embeddings
- Model: `all-MiniLM-L6-v2`, text = `title + description + attributes_search`.
- kNN combined with BM25 via manual RRF in code (`search_products`).

## Deliverable
- API endpoint above + mapping already defined; sample responses come from `/search` calls. 
# Task 2 — Core Search Functionality

## Overview

Baseline keyword search implementation across product fields using Elasticsearch's `multi_match` query with field boosting, fuzziness, and highlighting.

## API Endpoint

```
GET /search?q={query}&size={size}&start={start}
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | string | required | Search query |
| `size` | int | 10 | Number of results (1-100) |
| `start` | int | 0 | Offset for pagination |

## Query DSL

The search uses a `multi_match` query across multiple fields with boosting:

```json
{
  "query": {
    "multi_match": {
      "query": "3 hp sewage pump weir",
      "type": "best_fields",
      "fields": [
        "title.value^3",
        "description.value",
        "vendor.value.text^2",
        "category^2",
        "attributes.notes"
      ],
      "fuzziness": "AUTO",
      "prefix_length": 2
    }
  },
  "highlight": {
    "fields": {
      "title.value": {},
      "description.value": {},
      "vendor.value.text": {},
      "category": {}
    }
  }
}
```

### Field Boosting

| Field | Boost | Rationale |
|-------|-------|-----------|
| `title.value` | 3x | Primary product identifier |
| `vendor.value.text` | 2x | Brand/vendor often important |
| `category` | 2x | Category context matters |
| `description.value` | 1x | Secondary content |
| `attributes.notes` | 1x | Additional details |

### Fuzziness

- `AUTO` fuzziness: adapts edit distance based on term length
- `prefix_length: 2`: first 2 characters must match exactly (prevents too-fuzzy matches)

## Example Queries and Responses

### 1. "3 hp sewage pump weir"

```bash
curl "http://localhost:8000/search?q=3%20hp%20sewage%20pump%20weir&size=3"
```

**Response:**
```json
{
  "query": "3 hp sewage pump weir",
  "total": 7999,
  "returned": 3,
  "results": [
    {
      "id": "cbec3986f6642412d8b4f5e5",
      "score": 29.35,
      "title": "Sewage Pump 3 hp",
      "vendor": "Delat Valves",
      "category": "Cosmetics > Makeup > Face",
      "highlights": {
        "title.value": ["<em>Sewage</em> <em>Pump</em> <em>3</em> <em>hp</em>"]
      }
    }
  ]
}
```

### 2. "nitrile glove bulk pack"

```bash
curl "http://localhost:8000/search?q=nitrile%20glove%20bulk%20pack&size=3"
```

**Response:**
```json
{
  "query": "nitrile glove bulk pack",
  "total": 5587,
  "returned": 3,
  "results": [
    {
      "id": "504ada52a315f96b0dd64e7a",
      "score": 44.99,
      "title": "Nitrile Gloves bulk pack",
      "vendor": "Cordillera Steel",
      "highlights": {
        "title.value": ["<em>Nitrile</em> <em>Gloves</em> <em>bulk</em> <em>pack</em>"]
      }
    }
  ]
}
```

### 3. "pvc pipe 50mm"

```bash
curl "http://localhost:8000/search?q=pvc%20pipe%2050mm&size=3"
```

**Response:**
```json
{
  "query": "pvc pipe 50mm",
  "total": 5264,
  "returned": 3,
  "results": [
    {
      "id": "e0de0fb5cd77ac44919c27b2",
      "score": 18.52,
      "title": "PVC Pipe PVC",
      "attributes": {
        "diameter_mm": 50.0
      },
      "highlights": {
        "title.value": ["<em>PVC</em> <em>Pipe</em> <em>PVC</em>"]
      }
    }
  ]
}
```

### 4. "tomato" (food items)

```bash
curl "http://localhost:8000/search?q=tomato&size=3"
```

**Response:**
```json
{
  "query": "tomato",
  "total": 8292,
  "returned": 3,
  "results": [
    {
      "id": "d1993ec449620da9a4685a78",
      "score": 8.39,
      "title": "Adjustable Wrench tomtao tomato coloured color blue",
      "category": "Food > Vegetables > Tomato",
      "highlights": {
        "category": ["Food > Vegetables > <em>Tomato</em>"]
      }
    }
  ]
}
```

### 5. "tomato makeup" (cosmetics)

```bash
curl "http://localhost:8000/search?q=tomato%20makeup&size=3"
```

**Response:**
```json
{
  "query": "tomato makeup",
  "total": 8426,
  "returned": 3,
  "results": [
    {
      "id": "5d50d591e486eb1e347013f2",
      "score": 24.80,
      "title": "tomato coloured makeup",
      "category": "Cosmetics > Makeup > Face",
      "highlights": {
        "title.value": ["<em>tomato</em> coloured <em>makeup</em>"],
        "category": ["Cosmetics > <em>Makeup</em> > Face"]
      }
    }
  ]
}
```

## Response Format

```json
{
  "query": "search terms",
  "total": 1234,
  "returned": 10,
  "results": [
    {
      "id": "product_id",
      "score": 12.34,
      "title": "Product Title (raw)",
      "description": "Description (raw)",
      "vendor": "Vendor Name (raw)",
      "category": "Category > Path",
      "sku": "SKU123",
      "supplier_rating": 4.5,
      "inventory_status": "in_stock",
      "attributes": {},
      "highlights": {
        "title.value": ["matched <em>terms</em>"]
      }
    }
  ]
}
```

## Implementation Files

| File | Purpose |
|------|---------|
| `src/main.py` | `/search` endpoint |
| `src/services/elasticsearch.py` | `search_products()` method |
| `infra/elasticsearch/mappings/products.json` | Index mapping with analyzers |

## Notes

- Results return `title.raw`, `description.raw`, `vendor.raw` for display
- Search is performed against `.value` (cleaned) fields
- Highlights show which terms matched
- Fuzziness handles typos (e.g., "tomaot" matches "tomato")
- Synonyms expand queries (configured in `data/synonyms.json`)

