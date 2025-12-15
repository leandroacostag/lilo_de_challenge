# Task 5 — Design, Trade-offs, and Maintenance

## Indexing & Search Design (concise)
- **Hybrid search**: BM25 (title/description/vendor/category/attributes_search) + kNN embeddings (all-MiniLM-L6-v2) over `title + description + attributes_search`, fused via manual RRF.
- **Attributes**: stored raw (not indexed); `attributes_search` is a normalized “key: value” text used for search and embeddings. Numeric patterns from queries boost matches in `attributes_search` (keyless).
- **Anatomy**: analyzers/synonyms in `infra/elasticsearch/mappings/products.json`; normalization in `src/services/normalizer.py`; search in `src/services/elasticsearch.py`.
- **Security**: ES auth via env vars; mappings kept in repo (`infra/elasticsearch/mappings`).

## Key Trade-offs
- **Attributes not indexed**: keeps index small; search relies on `attributes_search` text + embeddings. If stricter numeric filtering is needed later, index numeric fields selectively.
- **Manual RRF**: avoids license constraints; simple, transparent fusion.
- **Embeddings scope**: include attributes_search for better semantic recall on attributes; model kept light (MiniLM) for speed.
- **Synonyms externalized**: easy to update via `data/synonyms.json` without code changes.

## Example Queries & Outcomes
- `3 hp sewage pump weir` → Weir pumps boosted via vendor match + numeric pattern.
- `nitrile glove bulk pack` → Gloves in bulk rank highest; junk categories suppressed by semantics.
- `pvc pipe 50mm` → Pipes mentioning 50mm in attributes_search are boosted.
- `tomato makeup` → Cosmetics ranked above food via semantics + BM25 tuning.

## Handling Messy Data
- Text cleaning (junk regex, whitespace, dedup words); raw preserved.
- Attribute key normalization for `attributes_search`; raw attributes kept for UI.
- Unit normalization for weight; multiple unit fields stored.
- Optional fields everywhere; exclude None on index.

## Synonyms & Taxonomy Maintenance
- Synonyms: edit `data/synonyms.json`, re-run index creation (migrations) to inject.
- Categories: parsed into level1/2/3; updates via normalization logic if new separators/variants appear.

## Relevance Tuning & A/B
- Adjust boosts in `_build_bm25_query` (title/category/vendor/attributes_search).
- Tweak RRF constants (k, fetch sizes) and embedding weighting.
- Add/remove query-time boosts (phrase matches, numeric pattern boosts).
- A/B: run side-by-side `/search` with different params; log top-N diffs; evaluate click/purchase signals from orders.

## Data Quality Monitoring
- Track null/empty fields during normalization (logs).
- Monitor index sizes and field counts; attributes kept non-indexed to avoid bloat.
- Periodically refresh synonyms/categories from domain SMEs or analytics feedback.

## UI / Demo
- Simple UI at `/` (see `src/static/index.html`): search, pagination, user impersonation, shows attributes (raw) and scores (BM25/kNN/RRF). 

