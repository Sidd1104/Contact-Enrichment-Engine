# Contact Enrichment Engine

A scalable, professional Python-based data engineering pipeline designed to ingest company and investor records from an Excel dataset, perform automated web searching, scrape relevant sites, extract key contacts and email/phone details using LLMs, and export the enriched dataset.

## Project Structure

```text
├── data/                    # Data storage
│   ├── input/               # Raw Excel and CSV files to import
│   ├── output/              # Final enriched datasets
│   └── temp/                # Temp storage for parsing/scraping caches
├── src/                     # Source Code
│   ├── config/              # Configuration loaders and schemas
│   ├── database/            # DB models, sessions, and migrations
│   ├── importer/            # Ingestion handlers for Excel datasets
│   ├── queue/               # Task scheduler and message broker setup
│   ├── workers/             # Celery background workers for scraping/extraction
│   ├── search/              # Search engine query wrappers (Google CSE, SerpAPI)
│   ├── scraper/             # Headless browser scrapers (Playwright)
│   ├── extractor/           # Text parsers and scraper cleanup
│   ├── validator/           # Validation rules for emails, phones, and links
│   ├── ai/                  # LLM integrations (Structured JSON outputs)
│   ├── exporter/            # Formatter and export modules for xlsx/csv
│   ├── cache/               # Redis key-value cache layer
│   ├── utils/               # Shared utilities (logging, decorators, rate limits)
│   └── monitoring/          # Logging, metrics, dashboard tracking
├── logs/                    # Runtime logs
├── tests/                   # Test suite
├── docs/                    # Architecture reports and specifications
├── scripts/                 # Utility scripts (analysis, setup, migrations)
├── .env.example             # Configuration variables template
├── .gitignore               # Ignored files for version control
├── requirements.txt         # Project dependencies
└── run.py                   # Main CLI entrypoint
```

## Getting Started

### 1. Prerequisites
- Python 3.12+
- PostgreSQL
- Redis

### 2. Environment Setup
Clone the repository, create a virtual environment, and install dependencies:

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment (Windows)
.venv\Scripts\activate

# Install dependencies (Phase 1 requirements)
pip install -r requirements.txt
```

Copy the environment file and configure variables:
```bash
cp .env.example .env
```

### 3. Usage
Run the command-line entrypoint to see helper prompts:
```bash
python run.py --help
```

Subcommands:
* **`import`**: Import raw data from Excel.
  ```bash
  python run.py import --file data/input/us_investors_enriched.xlsx
  ```
* **`run`**: Run the background scraping and AI enrichment pipeline.
  ```bash
  python run.py run --stage all
  ```
* **`export`**: Write final database records back to an Excel file.
  ```bash
  python run.py export --output data/output/final_output.xlsx
  ```
* **`status`**: Check enrichment statistics in the database.
  ```bash
  python run.py status
  ```

## Development Roadmap
- **Phase 1: Project Initialization & Excel Schema Analysis (Completed)**: Folder structures, baseline config files, and detailed data analysis.
- **Phase 2: Database Design & Importer Ingestion**: DB migrations, Pydantic schemas, and Excel import script.
- **Phase 3: Queue & Scraping Setup**: Celery integration, Playwright headless scrapers, Google Custom Search engine APIs.
- **Phase 4: LLM Contact Extraction**: Prompt engineering, JSON schemas, extraction & verification.
- **Phase 5: Validation, Export & Dashboard**: Integrity checking, export, and telemetry.
