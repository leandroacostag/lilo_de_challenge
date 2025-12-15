# Task 4 — User-Level Customization and Boosting

## Approach
- Endpoint accepts `user_id`. When provided:
  - Fetch user purchase history from `orders` index.
  - Apply boost based on past quantity ordered (1.2x to 2.5x).
  - Combine boosts inside the RRF fusion (BM25 + kNN).

## Query Flow
1. Build BM25 query (title/description/vendor/category/attributes_search).
2. Run kNN on embeddings (`title + description + attributes_search`).
3. Manual RRF combine; apply user boost if product was purchased by the user.

## Personas / Examples
- **user_017** (diverse buyer): queries “angle grinder” → previously purchased grinders get boosted.
- **user_135** (industrial pumps): “3 hp sewage pump” → pumps previously ordered by this user rank higher.

## Code
- Personalization: `src/services/elasticsearch.py` (`get_user_purchase_history`, `_apply_rrf`)
- Orders mapping: `infra/elasticsearch/mappings/orders.json`
- Tests/personas: `src/tests/test_user_personalization.py`

## Deliverable
- Explanation above + `/search?user_id=...` behavior + test personas. 
# Task 4 — User-Level Customization and Boosting

## Overview

This document explains the user-level ranking customization implemented in the product search engine. The system personalizes search results based on each user's purchase history from the orders index.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    PERSONALIZED SEARCH FLOW                     │
├─────────────────────────────────────────────────────────────────┤
│  1. User submits search query with user_id                      │
│  2. System fetches user's purchase history from orders index    │
│  3. Aggregates product_id → total_quantity_ordered              │
│  4. Runs hybrid search (BM25 + kNN)                             │
│  5. Applies RRF fusion with user-level boost multipliers        │
│  6. Returns personalized results                                │
└─────────────────────────────────────────────────────────────────┘
```

## Boosting Logic

Products the user has previously ordered receive a score multiplier based on total quantity ordered:

| Orders | Boost Multiplier | Rationale |
|--------|------------------|-----------|
| 1-5    | 1.2x             | Slight preference for known products |
| 6-20   | 1.5x             | Moderate preference for repeated purchases |
| 21-50  | 2.0x             | Strong preference for frequently ordered items |
| 50+    | 2.5x             | Maximum boost for power users of a product |

### Score Calculation

```
final_score = base_rrf_score × user_boost_multiplier
```

Where `base_rrf_score` comes from the hybrid BM25 + kNN fusion.

## Implementation

### 1. Fetching User Purchase History

Query the orders index to aggregate product quantities per user:

```python
async def get_user_purchase_history(self, user_id: str) -> dict[str, int]:
    """Get user's purchase history from orders index."""
    response = await self.client.search(
        index=self.ORDERS_INDEX,
        body={
            "size": 0,  # Only aggregations
            "query": {"term": {"user_id": user_id}},
            "aggs": {
                "products": {
                    "nested": {"path": "cart.items"},
                    "aggs": {
                        "by_product": {
                            "terms": {
                                "field": "cart.items.product_id",
                                "size": 1000,
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
    buckets = response["aggregations"]["products"]["by_product"]["buckets"]
    for bucket in buckets:
        purchase_history[bucket["key"]] = int(bucket["total_quantity"]["value"])
    
    return purchase_history
```

### 2. Applying User Boost in RRF

```python
def _apply_rrf(self, bm25_response, knn_response, user_purchase_history=None):
    # ... calculate base RRF score ...
    
    # Apply user purchase history boost
    user_boost = 1.0
    user_orders = 0
    product_id = hit["_source"].get("id")
    
    if product_id and product_id in user_purchase_history:
        user_orders = user_purchase_history[product_id]
        if user_orders >= 50:
            user_boost = 2.5
        elif user_orders >= 21:
            user_boost = 2.0
        elif user_orders >= 6:
            user_boost = 1.5
        elif user_orders >= 1:
            user_boost = 1.2
    
    final_score = base_score * user_boost
```

### 3. API Endpoint

```bash
GET /search?q=<query>&user_id=<user_id>
```

Response includes boosting metadata when applicable:

```json
{
  "query": "angle grinder",
  "user_id": "user_017",
  "results": [
    {
      "id": "d225d9d26fbdf1847f45d169",
      "title": "Angle Grinder abrasive",
      "score": 0.0303,
      "base_score": 0.0151,
      "user_boost": 2.0,
      "user_orders": 26
    }
  ]
}
```

## User Personas

### Persona 1: Industrial Worker (user_135)

**Profile:**
- Buys industrial equipment: pumps, pipes, compressors, masks
- Regular bulk orders for maintenance operations

**Top Purchases:**
| Product | Quantity |
|---------|----------|
| Respirator Mask abrasive bulk pack | 49 |
| Air Compressor kit | 45 |
| Industrial Lubricant 3 hp | 23 |
| PVC Pipe waterproof | 14 |
| Water Pump | 7 |

**Search Behavior:**
- When searching "mask", their frequently ordered Respirator Masks get boosted
- When searching "compressor", Air Compressors they've ordered move up
- Industrial equipment they've used before ranks higher

### Persona 2: Diverse Buyer (user_017)

**Profile:**
- Buys variety of products across categories
- Mix of tools, cosmetics, electrical, safety equipment

**Top Purchases:**
| Product | Quantity |
|---------|----------|
| Adjustable Wrench color blue | 73 |
| tomato coloured makeup | 53 |
| Power Cord | 50 |
| PVC Pipe PVC industrial | 50 |
| Nitrile Gloves industrial grade | 50 |

**Search Behavior:**
- When searching "wrench", their specific Adjustable Wrench gets 2.5x boost (73 orders)
- When searching "makeup", previously ordered cosmetics rank higher
- Cross-category purchases all get personalized boosting

## Example Queries

### Query: "angle grinder"

**Without user_id (baseline):**
```
1. Angle Grinder kit              [score: 0.0311]
2. Angle Grinder abrasive         [score: 0.0151]
3. Angle Grinder heavy duty       [score: 0.0267]
```

**With user_id=user_017:**
```
1. Angle Grinder kit              [score: 0.0311]
2. Angle Grinder abrasive         [score: 0.0303, BOOSTED 2.0x, 26 orders] ⬆️
3. Angle Grinder heavy duty       [score: 0.0267]
```

The "Angle Grinder abrasive" that user_017 has ordered 26 times gets boosted from position #3 to #2.

### Query: "industrial"

**Without user_id (baseline):**
```
1. Industrial Lubricant molding   [score: 0.0164]
2. Industrial Lubricant premium   [score: 0.0164]
3. Industrial Lubricant tomato    [score: 0.0161]
```

**With user_id=user_017:**
```
1. Nitrile Gloves moulding        [score: 0.0214, BOOSTED 1.5x, 8 orders] ⬆️
2. Industrial Lubricant molding   [score: 0.0164]
3. Industrial Lubricant premium   [score: 0.0164]
```

User_017's previously ordered Nitrile Gloves jumps to #1 position.

## Benefits

1. **Increased Reorder Rate**: Products users have ordered before are easier to find
2. **Personalized Experience**: Each user sees results tailored to their history
3. **Proportional Boosting**: Frequent purchases get stronger boosts
4. **Non-Destructive**: Products users haven't ordered still appear (just ranked lower)
5. **Transparent**: API response includes boost metadata for debugging/display

## Configuration

The boost multipliers can be adjusted based on business needs:

```python
# Current configuration
BOOST_TIERS = {
    (1, 5): 1.2,      # Light users
    (6, 20): 1.5,     # Regular users  
    (21, 50): 2.0,    # Heavy users
    (50, float('inf')): 2.5,  # Power users
}
```

## Future Enhancements

1. **Time Decay**: Recent orders weighted more than old orders
2. **Category Affinity**: Boost entire categories user frequently buys from
3. **Collaborative Filtering**: "Users like you also bought..."
4. **Negative Signals**: Products returned/complained about get demoted
5. **A/B Testing**: Compare conversion rates with different boost multipliers

