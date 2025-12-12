# Product Search Engine

A high-performance product search engine built with **FastAPI**, **Elasticsearch**, and **sentence-transformers**. Features hybrid BM25 + vector search with user-level personalization.

## 🚀 Quick Start

### Prerequisites

- **Docker** and **Docker Compose** (for Elasticsearch)
- **Python 3.11+**
- **uv** (Python package manager)

### Installation

1. **Install uv** (if not already installed):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Install dependencies**:
   ```bash
   cd src
   uv sync
   ```

3. **Set up environment** (optional):
   ```bash
   cd src
   cp .env.example .env  # Edit if needed
   ```

### Running the Application

#### Option 1: Using the run script (Recommended)

```bash
./run.sh
```

This script will:
- Start Elasticsearch via Docker Compose
- Wait for Elasticsearch to be healthy
- Start the FastAPI server with uvicorn
- Handle cleanup on exit (Ctrl+C)

#### Option 2: Manual setup

1. **Start Elasticsearch**:
   ```bash
   cd infra/elasticsearch
   docker compose up -d
   ```

2. **Wait for Elasticsearch to be ready** (check health):
   ```bash
   curl -u elastic:changeme http://localhost:9200/_cluster/health
   ```

3. **Start the FastAPI server**:
   ```bash
   cd src
   source .venv/bin/activate  # or: uv run
   python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

4. **Access the application**:
   - **Web UI**: http://localhost:8000
   - **API Docs**: http://localhost:8000/docs
   - **Health Check**: http://localhost:8000/health

## 📁 Project Structure

```
.
├── data/                    # Data files (products, orders, synonyms)
│   ├── products.json
│   ├── orders.json
│   ├── synonyms.json
│   └── categories.json
├── docs/                    # Documentation
│   ├── task_1.md           # Index design and mapping
│   ├── task_2.md           # Core search functionality
│   ├── task_3.md           # Data quality handling
│   └── task_4.md           # User-level customization
├── infra/                   # Infrastructure configuration
│   └── elasticsearch/
│       ├── docker-compose.yml
│       └── mappings/        # ES index mappings
│           ├── products.json
│           └── orders.json
├── src/                     # Application source code
│   ├── config/              # Configuration files
│   │   └── normalizer.json
│   ├── models/              # Pydantic models
│   ├── services/            # Business logic
│   │   ├── elasticsearch.py
│   │   ├── embeddings.py
│   │   ├── migrations.py
│   │   └── normalizer.py
│   ├── static/              # Web UI
│   │   └── index.html
│   ├── tests/               # Test suites
│   ├── config.py            # Settings management
│   ├── main.py              # FastAPI app
│   └── pyproject.toml        # Dependencies
├── run.sh                   # Startup script
└── README.md               # This file
```

## 🔧 Configuration

### Environment Variables

Create a `.env` file in `src/` (or use defaults):

```bash
ELASTICSEARCH_URL=http://localhost:9200
ELASTICSEARCH_USER=elastic
ELASTICSEARCH_PASSWORD=changeme
DATA_PATH=../data
```

### Elasticsearch Settings

- **Default password**: `changeme` (set via `ELASTIC_PASSWORD` in docker-compose.yml)
- **Ports**: `9200` (HTTP), `9300` (transport)
- **Memory**: 512MB heap (configurable via `ES_JAVA_OPTS`)

## 🎯 Features

### Search Capabilities

- **Hybrid Search**: Combines BM25 (keyword) and kNN (semantic) search
- **Reciprocal Rank Fusion (RRF)**: Manually implemented for combining results
- **User Personalization**: Boosts products based on user purchase history
- **Numeric Attribute Extraction**: Parses queries like "3 hp", "50mm", "220v"
- **Vendor Detection**: Identifies vendor names in queries
- **Category Hints**: Understands category keywords

### Data Normalization

- **Fuzzy Attribute Matching**: Handles typos in attribute keys
- **Unit Normalization**: Converts weights/units to standard formats
- **Text Cleaning**: Removes junk patterns and normalizes text
- **Synonym Expansion**: Uses synonym analyzer for better matching

### API Endpoints

- `GET /` - Web UI for searching products
- `GET /search?q=...&size=20&start=0&user_id=...` - Search products
- `GET /users` - List all users with order counts
- `GET /health` - Health check
- `GET /stats` - Index statistics
- `GET /docs` - Interactive API documentation

## 🧪 Testing

### Run Search Quality Tests

```bash
cd src
uv run python -m pytest tests/test_search_queries.py -v
```

Or run directly:
```bash
cd src
uv run python tests/test_search_queries.py
```

### Test User Personalization

```bash
cd src
uv run python tests/test_user_personalization.py
```

## 📊 Index Management

### Re-index Products

The application automatically creates and populates indexes on startup if they don't exist. To force re-indexing:

1. Delete the index:
   ```bash
   curl -u elastic:changeme -X DELETE http://localhost:9200/products
   ```

2. Restart the application (it will re-create and populate)

### Check Index Stats

```bash
curl -u elastic:changeme http://localhost:8000/stats
```

## 🛠️ Development

### Code Quality

This project uses **ruff** for linting and formatting:

```bash
cd src
uv run ruff check .
uv run ruff format .
```

### Dependencies

Managed via `uv` and `pyproject.toml`. Key dependencies:

- `fastapi` - Web framework
- `elasticsearch[async]` - Elasticsearch client
- `sentence-transformers` - Embedding generation
- `rapidfuzz` - Fuzzy string matching
- `pydantic` - Data validation

## 🐳 Docker

### Elasticsearch Container

The Elasticsearch container is managed via Docker Compose:

```bash
cd infra/elasticsearch
docker compose up -d      # Start
docker compose down       # Stop
docker compose down -v    # Stop and remove volumes
```

### Health Check

```bash
curl -u elastic:changeme http://localhost:9200/_cluster/health?pretty
```

## 📝 Challenge Tasks

This project implements a product search engine with the following tasks:

1. **Task 1**: Index design and mapping with analyzers
2. **Task 2**: Core search functionality (BM25 + vector search)
3. **Task 3**: Handling poor data quality (normalization, fuzzy matching, synonyms)
4. **Task 4**: User-level customization and boosting

See `docs/task_*.md` for detailed documentation.

## 🔍 Example Queries

Try these in the web UI:

- `3 hp sewage pump weir` - Should find Weir pumps with 3 HP
- `nitrile glove bulk pack` - Should find nitrile gloves in bulk
- `pvc pipe 50mm` - Should find PVC pipes with 50mm diameter
- `tomato` - Should return food items
- `tomato makeup` - Should return cosmetics (not food)

## 🚨 Troubleshooting

### Elasticsearch not starting

- Check Docker is running: `docker ps`
- Check logs: `docker logs elasticsearch`
- Verify ports 9200/9300 are not in use

### Import errors

- Ensure you're in the `src/` directory
- Run `uv sync` to install dependencies
- Activate virtual environment: `source .venv/bin/activate`

### Search not working

- Verify Elasticsearch is healthy: `curl -u elastic:changeme http://localhost:9200/_cluster/health`
- Check indexes exist: `curl -u elastic:changeme http://localhost:8000/stats`
- Review application logs for errors

## 📄 License

This project is part of a data engineering challenge.

## 👤 Author

Built as a demonstration of Elasticsearch search capabilities and data engineering best practices.

