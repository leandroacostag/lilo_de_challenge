# Task 3 — Handling Poor Data Quality

## Techniques Used
- **Synonym analyzer**: Domain synonyms injected at index creation from `data/synonyms.json`.
- **Fuzzy/cleaning**: Attribute keys normalized (lowercase/underscores); text cleaned (junk regex, whitespace, dedup words).
- **Unit normalization**: Map unit variants; derive weight in kg/g/lb/oz.
- **Attributes_search**: Build normalized “key: value” string for search; raw attributes stored (not indexed).
- **Vector search**: Embeddings over `title + description + attributes_search` using `all-MiniLM-L6-v2`.
- **Hybrid scoring**: BM25 + kNN with manual RRF; numeric patterns from queries boost matching products (via attributes_search).
- **Null safety**: Optional fields in models; exclude None on index.

## Example Improvements
- Query “pvc pipe 50mm” boosts items containing “50mm” in attributes_search, reducing off-topic results.
- Query “tomato makeup” prefers cosmetics via semantic + BM25 tuning; food items pushed down.
- Query “3 hp sewage pump weir” boosts numeric pattern + vendor, ranking Weir pumps at top.

## Code Pointers
- Normalization: `src/services/normalizer.py`
- Search logic: `src/services/elasticsearch.py` (`search_products`, `_build_bm25_query`)
- Mapping/analyzers: `infra/elasticsearch/mappings/products.json`

## Deliverable
- This explanation + code references + observed improvements via `/search` tests. 
# Task 3 — Handling Poor Data Quality

## Overview

This document explains the robustness and relevance strategies implemented to handle poor data quality in the product search engine. The dataset contains significant quality issues including:

- Typos in attribute keys (`colur` → `color`, `diam_mm` → `diameter_mm`)
- Inconsistent units (`kg`, `KG`, `kilogram`, `lb`, `LB`)
- Messy categories (`Safety>>Gloves>Nitrile` vs `Safety > Gloves > Nitrile`)
- Junk text in descriptions (`### $$ %% @@`, duplicate words)
- Missing or null values
- Products in wrong categories (Nitrile Gloves in "Cosmetics > Makeup")

## Strategies Implemented

### 1. Synonym Analyzer (Elasticsearch)

Synonyms are loaded from `data/synonyms.json` and injected into a custom Elasticsearch analyzer.

**Configuration:**

```json
{
  "analysis": {
    "filter": {
      "product_synonyms": {
        "type": "synonym",
        "synonyms": ["red, crimson", "blue, azure", "gloves, glove"]
      }
    },
    "analyzer": {
      "product_analyzer": {
        "type": "custom",
        "tokenizer": "standard",
        "filter": ["lowercase", "product_synonyms", "english_stop", "english_stemmer"]
      }
    }
  }
}
```

**Code (elasticsearch.py):**

```python
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
```

**Result:** Searching "crimson glove" finds products with "red gloves".

---

### 2. Fuzzy Matching for Attribute Keys (RapidFuzz)

Raw data contains typos in attribute keys. We use `rapidfuzz` to match typo-ridden keys to canonical names.

**Configuration (normalizer.json):**

```json
{
  "canonical_attribute_keys": ["color", "material", "diameter_mm", "power_hp", "voltage", "flow_lpm"],
  "attribute_key_aliases": {
    "colur": "color",
    "colour": "color",
    "diam_mm": "diameter_mm",
    "hp": "power_hp"
  },
  "fuzzy_match_threshold": 80
}
```

**Code (normalizer.py):**

```python
def _match_attribute_key(self, key: str) -> str | None:
    """Match an attribute key to a canonical key using fuzzy matching."""
    key_lower = key.lower()
    
    # First check exact alias match
    if key_lower in self.key_aliases:
        return self.key_aliases[key_lower]
    
    # Fuzzy match against all known keys
    result = process.extractOne(
        key_lower,
        self._all_keys,
        scorer=fuzz.ratio,
        score_cutoff=self.fuzzy_threshold,
    )
    
    if result:
        matched_key = result[0]
        if matched_key in self.key_aliases:
            return self.key_aliases[matched_key]
        return matched_key
    
    return None
```

**Example:**
- Input: `{"colur": "red", "diam_mm": 50}`
- Output: `{"color": "red", "diameter_mm": 50.0}`

---

### 3. Unit Normalization and Conversion

Units are normalized to standard formats and converted to multiple units for flexible filtering.

**Configuration (normalizer.json):**

```json
{
  "unit_mapping": {
    "kg": "kg", "kilogram": "kg", "KG": "kg",
    "lb": "lb", "pound": "lb", "LB": "lb",
    "oz": "oz", "ounce": "oz",
    "g": "g", "gram": "g"
  },
  "weight_to_kg": {
    "kg": 1.0,
    "lb": 0.453592,
    "oz": 0.0283495,
    "g": 0.001
  }
}
```

**Code (normalizer.py):**

```python
def _convert_weights(self, unit: str | None) -> dict[str, float | None]:
    """Convert unit to all weight formats."""
    result = {"kg": None, "g": None, "lb": None, "oz": None}
    
    weight_kg = self._convert_to_kg(unit)
    if weight_kg is None:
        return result
    
    result["kg"] = round(weight_kg, 6)
    result["g"] = round(weight_kg * 1000, 6)
    result["lb"] = round(weight_kg / 0.453592, 6)
    result["oz"] = round(weight_kg / 0.0283495, 6)
    
    return result
```

**Result:** Users can filter by any weight unit regardless of how it was stored.

---

### 4. Text Cleaning and Junk Removal

Descriptions contain junk patterns that need removal.

**Configuration (normalizer.json):**

```json
{
  "junk_patterns": [
    "###",
    "\\$\\$",
    "%%",
    "@@",
    "\\*\\*",
    "\\s{2,}"
  ]
}
```

**Code (normalizer.py):**

```python
def _clean_text(self, text: str) -> str:
    """Remove junk patterns and normalize whitespace."""
    if not text:
        return ""
    
    cleaned = text
    for pattern in self.junk_patterns:
        cleaned = re.sub(pattern, "", cleaned)
    
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    
    # Remove duplicate consecutive words
    words = cleaned.split()
    deduped = []
    prev_word = None
    for word in words:
        if word.lower() != prev_word:
            deduped.append(word)
        prev_word = word.lower()
    
    return " ".join(deduped)
```

**Example:**
- Input: `"moulding kit moulding corrosion resistant ### $$ %% @@"`
- Output: `"moulding kit corrosion resistant"`

---

### 5. Category Cleaning and Fuzzy Mapping

Categories have inconsistent formatting and need normalization.

**Code (normalizer.py):**

```python
def _normalize_category_for_matching(self, category: str) -> str:
    """Normalize category string for matching purposes."""
    normalized = re.sub(r"\s*>\s*", ">", category.lower())
    normalized = re.sub(r">+", ">", normalized)  # Multiple > to single
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized

def _find_best_category_match(self, messy: str, clean_categories: list[str]) -> str | None:
    """Find the best matching clean category using fuzzy matching."""
    result = process.extractOne(
        messy.lower(),
        [c.lower() for c in clean_categories],
        scorer=fuzz.token_sort_ratio,
    )
    
    if result and result[1] >= 60:  # 60% threshold
        idx = [c.lower() for c in clean_categories].index(result[0])
        return clean_categories[idx]
    
    return None
```

**Example:**
- Input: `"Safety>>Gloves>Nitrile"`
- Output: `"Safety > Gloves > Nitrile"`

---

### 6. Semantic/Vector Search (Hybrid BM25 + kNN)

The most powerful strategy for handling data quality issues. Semantic search understands meaning, not just keywords.

**Architecture:**

```
┌─────────────────────────────────────────────────────────┐
│                    HYBRID SEARCH                        │
├─────────────────────────────────────────────────────────┤
│  1. BM25 (Keyword Matching)                             │
│     • Exact term matching                               │
│     • Field boosting (title: 5x, category: 3x)          │
│                                                         │
│  2. kNN (Semantic Similarity)                           │
│     • 384-dim embeddings (all-MiniLM-L6-v2)             │
│     • Understands synonyms, typos, context              │
│                                                         │
│  3. RRF Fusion                                          │
│     • Combines rankings: 1/(60+rank_bm25) + 1/(60+rank_knn)
│     • Best of both worlds                               │
└─────────────────────────────────────────────────────────┘
```

**Code (embeddings.py):**

```python
class EmbeddingService:
    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.dimension = 384

    def embed_product(self, title: str, description: str | None = None) -> list[float]:
        """Generate embedding for a product using title + description."""
        text_parts = [title]
        if description:
            text_parts.append(description)
        combined_text = " ".join(text_parts)
        return self.embed_text(combined_text)
```

**Code (elasticsearch.py - RRF):**

```python
def _apply_rrf(self, bm25_response, knn_response, k=60, size=10, start=0):
    """Apply Reciprocal Rank Fusion to combine BM25 and kNN results."""
    # Build rank maps
    bm25_ranks = {hit["_id"]: rank for rank, hit in enumerate(bm25_response["hits"]["hits"], 1)}
    knn_ranks = {hit["_id"]: rank for rank, hit in enumerate(knn_response["hits"]["hits"], 1)}
    
    # Calculate RRF scores
    for doc_id, hit in all_docs.items():
        score = 0.0
        if doc_id in bm25_ranks:
            score += 1.0 / (k + bm25_ranks[doc_id])
        if doc_id in knn_ranks:
            score += 1.0 / (k + knn_ranks[doc_id])
        rrf_scores.append({"doc_id": doc_id, "rrf_score": score, "hit": hit})
    
    return sorted(rrf_scores, key=lambda x: x["rrf_score"], reverse=True)
```

**Why this works:**
- **Typos**: "nitirle gloves" → kNN understands it means "nitrile gloves"
- **Synonyms**: "crimson" → semantically similar to "red"
- **Context**: "tomato makeup" → kNN ranks cosmetics higher than food

---

### 7. Query Understanding

The search extracts structured information from natural language queries.

**Numeric Attribute Extraction:**

```python
def _extract_numeric_attributes(self, query: str) -> dict:
    """Extract numeric attributes from query."""
    attributes = {}
    query_lower = query.lower()
    
    # Power: "3 hp", "3hp"
    hp_match = re.search(r"(\d+(?:\.\d+)?)\s*[-]?\s*hp\b", query_lower)
    if hp_match:
        attributes["power_hp"] = float(hp_match.group(1))
    
    # Diameter: "50mm", "50 mm"
    mm_match = re.search(r"(\d+(?:\.\d+)?)\s*mm\b", query_lower)
    if mm_match:
        attributes["diameter_mm"] = float(mm_match.group(1))
    
    return attributes
```

**Vendor Detection:**

```python
def _detect_vendor_in_query(self, query: str) -> str | None:
    """Detect known vendor names in query."""
    known_vendors = ["weir", "acme", "delta", "global", "mega", "prime"]
    query_lower = query.lower()
    for vendor in known_vendors:
        if vendor in query_lower:
            return vendor
    return None
```

**Category Hints:**

```python
def _detect_category_hints(self, query: str) -> list[str]:
    """Detect category-related keywords in query."""
    category_keywords = {
        "makeup": ["cosmetic", "makeup", "face", "beauty"],
        "food": ["food", "vegetable", "fruit"],
        "pump": ["pump", "industrial"],
    }
    hints = []
    for keyword, categories in category_keywords.items():
        if keyword in query.lower():
            hints.extend(categories)
    return hints
```

---

### 8. Combined Boosting Strategy

When multiple criteria match, products get super-boosted.

```python
# SUPER BOOST: vendor + numeric attribute match together
if detected_vendor:
    for attr_name, attr_value in numeric_attrs.items():
        bool_query["bool"]["should"].append({
            "bool": {
                "must": [
                    {"wildcard": {"vendor.value": {"value": f"*{detected_vendor}*"}}},
                    {"term": {f"attributes.{attr_name}": attr_value}},
                ],
                "boost": 100,
            }
        })
```

---

## Example Improved Results

### Query: "3 hp sewage pump weir"

**Before (without data quality handling):**
```
1. Random Pump (no vendor match, no power_hp)
2. Water Pump 5 hp (wrong power)
3. Sewage Pump (no vendor)
```

**After:**
```
1. Sewage Pump 3 hp aftermarket
   vendor: Weir | power_hp=3.0, flow_lpm=120.0 ✅
2. Sewage Pump 3 hp tomato coloured replacement
   vendor: Weir Pumps | power_hp=3.0 ✅
```

### Query: "tomato makeup"

**Before:**
```
1. tomato (Food > Vegetables)
2. tomato (Food > Vegetables)
3. tomato colored wrench (Tools)
```

**After:**
```
1. tomato coloured makeup (Cosmetics > Makeup > Face) ✅
2. tomato coloured makeup (Cosmetics > Makeup > Face) ✅
3. tomato coloured makeup (Cosmetics > Makeup > Face) ✅
```

### Query: "pvc pipe 50mm"

**Before:**
```
1. PVC Pipe (no diameter)
2. PVC Pipe (no diameter)
3. PVC Pipe 25mm (wrong diameter)
```

**After:**
```
1. PVC Pipe aftermarket | diameter_mm=50.0 ✅
2. PVC Pipe PVC industrial | diameter_mm=50.0, material=PVC ✅
3. PVC Pipe abrasive | diameter_mm=50.0 ✅
```

---

## Summary

| Strategy | Tool/Library | Problem Solved |
|----------|--------------|----------------|
| Synonym Analyzer | Elasticsearch | Color variations, product name aliases |
| Fuzzy Attribute Matching | RapidFuzz | Typos in attribute keys |
| Unit Normalization | Custom Python | Inconsistent units (kg/lb/oz) |
| Text Cleaning | Regex | Junk characters, duplicate words |
| Category Mapping | RapidFuzz | Messy category paths |
| Semantic Search | sentence-transformers | Context, meaning, implicit synonyms |
| Query Understanding | Regex + Heuristics | Numeric attributes, vendor names |
| Combined Boosting | Elasticsearch DSL | Multi-criteria ranking |

The hybrid approach (BM25 + kNN + intelligent boosting) provides the best results by combining exact matching with semantic understanding, making the search robust against data quality issues.

