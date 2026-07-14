# Contact Enrichment Engine

A high-performance, professional Python-based data engineering pipeline designed to ingest company and investor records from Excel sheets, resolve official website URLs using Google Search, scrape contact pages, extract emails/phones using LLMs (Gemini), and save enriched data directly back to the spreadsheet.

---

## 🚀 Quick Start Guide

### 1. Prerequisites
* **Python 3.12+**
* An active **Google Gemini API Key** (for search grounding and structured data extraction)

### 2. Installation & Environment Setup
Clone the repository and set up a virtual environment:

```bash
# Create virtual environment
python -m venv .venv

# Activate the virtual environment
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install all required dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables (`.env`)
Create a `.env` file in the root directory and add your API keys:

```bash
# Copy template
cp .env.example .env
```

Open `.env` and fill in your keys:
```env
# Google Gemini API Configuration (Mandatory)
GEMINI_API_KEY="your-gemini-api-key-here"

# Playwright Browser Configuration
DISABLE_BROWSER_FALLBACK=false
```

### 4. Input Dataset
Place your raw Excel dataset (e.g. `us_investors_export 2.xlsx`) inside the input directory:
`data/input/`

The engine will **automatically detect the most recently modified Excel file** inside that directory.

---

## 💻 CLI Usage

All operations are run through the `run.py` CLI script.

### Start the Pipeline
Runs website discovery, scraping, AI extraction, and updates the Excel sheet:
```bash
python run.py run -p turbo
```
* Use `-p development` or `-p testing` for smaller batch sizes during local development.
* Use `-p turbo` for high-throughput execution with 50 parallel workers.

### Custom Profile Execution
Run the pipeline with a custom profile and target a specific file:
```bash
python run.py profile turbo -f data/input/us_investors_export.xlsx
```

### Perform Health Check
Run system pre-flight checks and diagnose resource health:
```bash
python run.py health
```

### Check Database Status
Display the count of completed and pending records in the database:
```bash
python run.py status
```

### Export Results manually
Export completed contacts manually to CSV/Excel formats:
```bash
python run.py export -d data/export
```

---

## 🛠️ Key Architectural Optimizations

1. **429 Rate Limit Mitigation**: All Gemini Search Grounding calls and search-grounded AI queries are strictly serialized (concurrency of 1) with an automatic 4-second cooldown to stay under the 15 RPM free-tier threshold.
2. **Dynamic Excel Writing**: The pipeline writes results back in-place to the raw input Excel sheet. If `Source Website` or `Confidence` columns do not exist in the raw sheet, the engine dynamically appends them to prevent any data loss.
3. **Smooth Console telemetry**: CPU-heavy subprocess-based screen clears (`cls` / `clear`) have been replaced with direct ctypes virtual terminal ANSI clears, eliminating console lag and flickering.
4. **Concurrent Subpage Crawling**: Candidates subpages are scraped concurrently via `asyncio.gather`, improving extraction speed per domain.
