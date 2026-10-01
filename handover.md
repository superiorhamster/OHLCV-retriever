# Project Handover & Deployment Guide

## HOSE Historical OHLCV Market Data Retriever (v2.0)

This document provides a comprehensive architectural analysis and operational handover guide for deploying, running, and maintaining the **HOSE Historical OHLCV Market Data Retriever** in local, server, and containerized production environments.

---

## 1. Project Overview & Architecture Analysis

### 1.1 Mission & Core Philosophy
The **HOSE OHLCV Retriever** is an auditable, free-source historical market data pipeline and web platform built for quantitative research, backtesting, and production financial analysis on the **Ho Chi Minh Stock Exchange (HOSE / HSX)**.

Unlike common wrappers that rely on paid subscriptions, browser automation, or reverse-engineered private mobile tokens, this project operates on three fundamental principles:
1. **Free-Source Public HTTP Retrieval:** Retrieves data directly from unauthenticated public financial endpoints ([KBS](https://kbbuddywts.kbsec.com.vn) Buddy WTS, [VCI / Vietcap](https://trading.vietcap.com.vn), with unverified opt-in for [VNDIRECT](https://finfo-api.vndirect.com.vn)).
2. **Survivorship-Bias Mitigation:** Explicitly tracks delisted and historically traded securities by parsing official HOSE Annual Reports (PDFs for 2020, 2022, 2023, 2024) and maintaining auditable evidence records (`symbols.parquet`, `exchange_memberships.parquet`, `historical_evidence.parquet`).
3. **Auditable Provenance & Atomic Storage:** Every HTTP response is hashed (SHA-256) and archived immutably in `data/raw/`. Data processing uses strict type enforcement, discrepancy tracking, and atomic Parquet file swaps to guarantee resilience against interruptions and corruptions.

```
                      +------------------------------------------+
                      |         HOSE Universe Discovery          |
                      |   KBS / VCI Active + Annual Report PDFs  |
                      +--------------------+---------------------+
                                           |
                                           v
+----------------------------------------------------------------------------------+
|                              Multi-Provider Transport                            |
|             (Rate Limiting, Retries, Circuit Breaker, Raw JSON Archival)         |
+---------------------+------------------------------------+-----------------------+
                      |                                    |
            +---------v---------+                +---------v---------+
            |    KBS Adapter    |                |    VCI Adapter    |
            | (3-yr chunks,     |                | (gap-chart epoch, |
            |  prefix-probes)   |                |  countBack paging)|
            +---------+---------+                +---------+---------+
                      |                                    |
                      +-----------------+------------------+
                                        |
                                        v
                      +------------------------------------+
                      |       Collector & Normalizer       |
                      | (Discrepancy Check, Audit Revisions|
                      |  Quality Flags, Deduplication)     |
                      +-----------------+------------------+
                                        |
                 +----------------------+----------------------+
                 |                                             |
                 v                                             v
+---------------------------------+           +---------------------------------+
|        Storage & Reports        |           |       FastAPI Web Server        |
|  - Processed Parquet Partitions |           |  - Head/Tail Table Preview API  |
|  - SQLite Job Checkpoints       | <-------> |  - TradingView Chart API        |
|  - Audit & Coverage Parquets    |           |  - Live Progress & Log Stream   |
|  - summary.json Status Export   |           |  - React/Tailwind/Vite Frontend |
+---------------------------------+           +---------------------------------+
```

---

### 1.2 Repository Structure

```
OHLCV_Retriever_v2/
├── collect_hose.py                 # CLI entrypoint wrapper
├── pyproject.toml                  # Python package configuration & dependencies
├── collector.example.json          # Example JSON runtime configuration
├── handover.md                     # This deployment & operational guide
├── docs/
│   └── data_collection.md          # Technical documentation & coverage observations
├── hose_history/                   # Core Python package
│   ├── __init__.py
│   ├── cli.py                      # Argument parsing & execution control
│   ├── collector.py                # Multi-threaded collection orchestrator & audits
│   ├── config.py                   # Dataclass CollectorConfig validation
│   ├── providers.py                # KBS, VCI, and VND provider adapters
│   ├── schema.py                   # Data schema, parse helpers, and quality rules
│   ├── server.py                   # FastAPI REST API & static file mount
│   ├── storage.py                  # Parquet partitioning, SQLite checkpoints & atomic writes
│   ├── transport.py                # HTTP transport, rate pacing, retries & circuit breaker
│   ├── universe.py                 # Universe discovery & PDF extraction engine
│   └── resources/
│       └── hose_2023_delistings.txt # Bundled verified delisting evidence snapshot
├── frontend/                       # Web Dashboard (React + TypeScript + Tailwind)
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── src/                        # React UI source code
│   │   ├── App.tsx                 # Main application component
│   │   ├── api.ts                  # Axios/Fetch API client
│   │   ├── types.ts                # TypeScript interfaces
│   │   └── components/             # UI Components (Chart, Table, Controls, Logs)
│   └── dist/                       # Pre-compiled static assets (served by FastAPI)
├── tests/                          # Automated Pytest suite (unit & integration)
└── data/                           # Data directory (created at runtime, git-ignored)
    ├── raw/                        # Immutable JSON response payloads & annual PDFs
    ├── processed/hose_ohlcv/       # Final dataset partitioned by symbol (part.parquet)
    ├── metadata/                   # symbols.parquet, memberships, aliases, progress.sqlite
    └── reports/                    # discrepancies, validation issues, summary.json
```

---

### 1.3 Key Architectural Modules

| Module | File | Purpose |
|---|---|---|
| **CLI & Dispatcher** | [hose_history/cli.py](file:///home/anhpd/Project/Capstone/OHLCV_Retriever_v2/hose_history/cli.py) | Manages CLI arguments, file locks (`collector.lock`), signal handling (SIGINT/SIGTERM), and dispatches either the collector run or the web server (`--serve`). |
| **Transport Layer** | [hose_history/transport.py](file:///home/anhpd/Project/Capstone/OHLCV_Retriever_v2/hose_history/transport.py) | Wraps `httpx.Client`. Enforces per-provider rate limits (`request_delay=0.5s`), exponential backoff with jitter, retry headers (`Retry-After`), response caching, and an HTTP 401/403 circuit breaker. |
| **Provider Adapters** | [hose_history/providers.py](file:///home/anhpd/Project/Capstone/OHLCV_Retriever_v2/hose_history/providers.py) | Normalizes raw upstream vendor payloads into standard schemas. Implements 3-year chunking with prefix probing for KBS and epoch pagination for VCI. |
| **Universe Discovery** | [hose_history/universe.py](file:///home/anhpd/Project/Capstone/OHLCV_Retriever_v2/hose_history/universe.py) | Merges live exchange stock listings with parsed delisting tables extracted from HOSE annual report PDFs (`pdfplumber`) and bundled evidence. |
| **Collector Core** | [hose_history/collector.py](file:///home/anhpd/Project/Capstone/OHLCV_Retriever_v2/hose_history/collector.py) | Coordinates worker threads via `ThreadPoolExecutor`, performs discrepancy comparisons between vendors, applies quality flags, and audits historical adjusted closes during incremental updates. |
| **Storage Engine** | [hose_history/storage.py](file:///home/anhpd/Project/Capstone/OHLCV_Retriever_v2/hose_history/storage.py) | Manages atomic Parquet writes (`part.parquet`), transaction checkpoints in SQLite (`progress.sqlite`), and exports audit parquets to `data/reports/`. |
| **Web Server & API** | [hose_history/server.py](file:///home/anhpd/Project/Capstone/OHLCV_Retriever_v2/hose_history/server.py) | FastAPI service exposing endpoints for universe querying, starting/stopping retriever jobs in a background thread, log streaming, ticker preview (head/tail), candle charting, and CSV download. Mounts `frontend/dist` at `/`. |
| **Web Dashboard** | [frontend/src/App.tsx](file:///home/anhpd/Project/Capstone/OHLCV_Retriever_v2/frontend/src/App.tsx) | Clean dark-mode UI with TradingView Lightweight Charts, interactive ticker selection, live terminal log streaming, and paginated data inspection. |

---

## 2. System Requirements & Prerequisites

### 2.1 Hardware Specifications

| Component | Minimum (Evaluation / Light) | Recommended (Full Market Backfill) |
|---|---|---|
| **CPU** | 2 cores (x86_64 or ARM64) | 4+ cores (for multi-threaded collection) |
| **RAM** | 2 GB | 4 GB - 8 GB |
| **Storage** | 5 GB SSD free space | 20+ GB SSD free space (for all raw JSONs + parquets) |
| **Network** | Stable broadband connection | Unrestricted outbound HTTPS to Vietnam financial endpoints |

### 2.2 Software Dependencies
* **Operating System:** Linux (Ubuntu 20.04+, Debian 11+, Rocky Linux 9+, or CentOS Stream), macOS 12+, or Windows with WSL2.
* **Python:** Version `3.11` or `3.12` (Python 3.11+ is required for native datetime/zoneinfo and modern typing support).
* **Node.js (Optional):** Node `v18.0+` & `npm` (only needed if building or modifying the frontend; the repository already includes pre-built production assets in `frontend/dist`).

### 2.3 Network / Outbound Firewall Whitelist
Ensure the host can access the following public endpoints over HTTPS (port 443):
* `kbbuddywts.kbsec.com.vn` (KBS daily quotes & stock directory)
* `trading.vietcap.com.vn` (Vietcap / VCI stock listing & historical chart)
* `staticfile.hsx.vn` (Official HOSE Annual Report PDFs)

---

## 3. Installation & Local Setup

### 3.1 Clone & Setup Python Virtual Environment

```bash
# Clone the repository
git clone <REPO_URL> OHLCV_Retriever_v2
cd OHLCV_Retriever_v2

# Create virtual environment with Python 3.11+
python3 -m venv .venv
source .venv/bin/activate

# Upgrade pip and install package with all web and testing dependencies
pip install --upgrade pip
pip install -e '.[web,test]'
```

### 3.2 Build Frontend (Optional if `frontend/dist` already exists)

```bash
cd frontend
npm install
npm run build
cd ..
```
The compiled output is saved to `frontend/dist/` and will be automatically mounted by FastAPI.

### 3.3 Run Automated Tests

Verify system integrity:
```bash
.venv/bin/python -m pytest -q
```
*Expected result: 34 passed unit tests.*

---

## 4. Operational Modes: CLI vs. Web Dashboard

### 4.1 CLI Headless Execution (Automated / Batch Jobs)

The CLI entrypoint is `collect_hose.py` (or the console script `collect-hose`).

#### Common CLI Commands

```bash
# 1. Check current collection status without hitting network (read-only SQLite check)
./.venv/bin/python collect_hose.py --status

# 2. Discover and export stock universe only (mitigating survivorship bias)
./.venv/bin/python collect_hose.py --universe-only

# 3. Targeted test run on selected tickers (e.g. FPT, REE, HPG)
./.venv/bin/python collect_hose.py --symbol FPT,REE,HPG

# 4. Collect a specific date range for a symbol
./.venv/bin/python collect_hose.py --symbol FPT --start 2006-01-01 --end 2026-09-30

# 5. Run full backfill across entire HOSE universe (resumable)
./.venv/bin/python collect_hose.py --mode full --workers 3

# 6. Run daily incremental update (queries only missing dates & audits recent adjustments)
./.venv/bin/python collect_hose.py --mode update --workers 3

# 7. Force snapshot refresh (ignores existing cache)
./.venv/bin/python collect_hose.py --symbol FPT --refresh
```

#### Safe Interruption & Resume Semantics
* You can safely stop a running collection job at any time using **Ctrl-C (`SIGINT`)** or **`kill <PID>` (`SIGTERM`)**.
* The transport layer finishes any in-flight HTTP request, caches received envelopes, sets the status of unfinished jobs back to `PENDING` in SQLite, and safely releases `data/metadata/collector.lock`.
* Simply rerunning the same command will resume where it left off without duplicate network requests.

---

### 4.2 Web Dashboard & REST API Execution

Launch the FastAPI application that serves both the JSON REST API and the React web interface:

```bash
./.venv/bin/python collect_hose.py --serve --host 0.0.0.0 --port 8000
```

Access the dashboard at **`http://<SERVER_IP>:8000`**.

#### Features Available in Web UI:
1. **Universe Browser:** Filter by active vs. delisted stocks, search by ticker or company name, inspect local data availability and date spans.
2. **Retriever Controls:** Start full backfills, incremental updates, or custom ticker jobs with custom worker counts and date bounds directly from the browser; trigger graceful stop anytime.
3. **Live Progress:** Real-time job status counts (DONE, RUNNING, PENDING, PARTIAL, FAILED) and terminal log streaming buffer.
4. **Data Previewer & Charting:** Interactive TradingView candlestick & volume chart, Head/Tail/Full table inspector, quality flags inspection, and one-click CSV export.

---

## 5. Production Deployment Strategies

### Option A: Systemd Services on Linux Host (Recommended)

This strategy deploys:
1. A continuous **Systemd Web Service** (`hose-retriever.service`) to keep the API and UI live.
2. A scheduled **Systemd Timer** (`hose-collector.timer`) to run daily incremental market updates at 16:30 ICT (after HOSE closes).

#### Step 1: Create the Web Service Unit
Create `/etc/systemd/system/hose-retriever.service`:

```ini
[Unit]
Description=HOSE OHLCV Retriever Web Service & API
After=network.target

[Service]
Type=simple
User=anhpd
Group=anhpd
WorkingDirectory=/home/anhpd/Project/Capstone/OHLCV_Retriever_v2
ExecStart=/home/anhpd/Project/Capstone/OHLCV_Retriever_v2/.venv/bin/python collect_hose.py --serve --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5s
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hose-retriever.service
sudo systemctl status hose-retriever.service
```

#### Step 2: Configure Daily Scheduled Incremental Collection
Create `/etc/systemd/system/hose-collector.service`:

```ini
[Unit]
Description=HOSE Daily Market Data Incremental Collection Job
After=network.target

[Service]
Type=oneshot
User=anhpd
Group=anhpd
WorkingDirectory=/home/anhpd/Project/Capstone/OHLCV_Retriever_v2
ExecStart=/home/anhpd/Project/Capstone/OHLCV_Retriever_v2/.venv/bin/python collect_hose.py --mode update --workers 3
Environment="PYTHONUNBUFFERED=1"
```

Create `/etc/systemd/system/hose-collector.timer`:

```ini
[Unit]
Description=Run daily HOSE collection at 16:30 ICT (Mon-Fri)

[Timer]
# Runs at 16:30 Asia/Ho_Chi_Minh timezone (UTC+7 -> 09:30 UTC)
OnCalendar=Mon..Fri *-*-* 09:30:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
```

Enable the timer:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hose-collector.timer
sudo systemctl list-timers --all | grep hose
```

#### Step 3: Nginx Reverse Proxy with HTTPS
Create `/etc/nginx/sites-available/hose-retriever.conf`:

```nginx
server {
    listen 80;
    server_name ohlcv.yourdomain.com; # Replace with your domain or server IP

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Keep alive for log polling / streaming
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

Enable the site and obtain an SSL certificate:
```bash
sudo ln -s /etc/nginx/sites-available/hose-retriever.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d ohlcv.yourdomain.com
```

---

### Option B: Containerized Deployment (Docker & Docker Compose)

A production-grade multi-stage container build bundles both frontend build artifacts and Python runtime into a minimal, secure container.

#### 1. Multi-Stage `Dockerfile`
Create `Dockerfile` in the project root:

```dockerfile
# -------------------------------------------------------------
# Stage 1: Build Frontend SPA
# -------------------------------------------------------------
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# -------------------------------------------------------------
# Stage 2: Python Runtime Environment
# -------------------------------------------------------------
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Ho_Chi_Minh

WORKDIR /app

# Install OS dependencies (certificates, timezone data)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Install Python package dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[web]"

# Copy application source code
COPY hose_history/ hose_history/
COPY collect_hose.py collector.example.json ./

# Copy compiled frontend from Stage 1 into frontend/dist
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Create persistent data volume mount point
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["python", "collect_hose.py", "--serve", "--host", "0.0.0.0", "--port", "8000"]
```

#### 2. `docker-compose.yml`
Create `docker-compose.yml` in the project root:

```yaml
version: '3.8'

services:
  hose-retriever:
    build:
      context: .
      dockerfile: Dockerfile
    image: hose-ohlcv-retriever:v2.0
    container_name: hose_retriever_app
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      # Mount host data directory for persistent Parquet and raw storage
      - ./data:/app/data
    environment:
      - TZ=Asia/Ho_Chi_Minh
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/retriever/status')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

  # Optional cron worker service for automatic daily updates
  hose-cron-updater:
    image: hose-ohlcv-retriever:v2.0
    container_name: hose_retriever_cron
    restart: unless-stopped
    volumes:
      - ./data:/app/data
    environment:
      - TZ=Asia/Ho_Chi_Minh
    # Uses sleep loop or cron daemon inside container to trigger incremental update
    entrypoint: ["/bin/sh", "-c"]
    command:
      - |
        while true; do
          CURRENT_HOUR=$$(date +%H)
          CURRENT_MIN=$$(date +%M)
          # Run at 16:30 ICT
          if [ "$$CURRENT_HOUR" = "16" ] && [ "$$CURRENT_MIN" = "30" ]; then
            echo "[CRON] Starting daily incremental update..."
            python collect_hose.py --mode update --workers 3
            sleep 60
          fi
          sleep 30
        done
```

#### Running with Docker:
```bash
# Build and run in background
docker compose up -d --build

# View real-time logs
docker compose logs -f hose-retriever

# Check status
docker compose ps
```

---

## 6. Data Pipeline & Storage Reference

### 6.1 Storage Hierarchy

All output is organized under `data/`:

```text
data/
├── collector.log                       # Rolling execution log file
├── raw/                                # Authoritative evidence archive
│   ├── kbs/{snapshot}/{sha256}.json    # Verbatim response from KBS Buddy WTS
│   ├── vci/{snapshot}/{sha256}.json    # Verbatim response from Vietcap
│   ├── metadata/                       # Downloaded annual report PDFs (hose_annual_*.pdf)
│   └── kbs/normalized/{snapshot}/{sym}.parquet  # Normalized provider view
├── processed/                          # Final reconciled datasets
│   └── hose_ohlcv/
│       ├── symbol=FPT/part.parquet     # Canonical daily OHLCV for FPT
│       ├── symbol=REE/part.parquet     # Canonical daily OHLCV for REE
│       └── ...
├── metadata/                           # Universe definitions & operational state
│   ├── symbols.parquet                 # Master symbol directory (active & delisted)
│   ├── exchange_memberships.parquet    # Valid-from/until membership history
│   ├── aliases.parquet                 # Known ticker alias transitions
│   ├── historical_evidence.parquet     # Raw delisting evidence extracted from reports
│   ├── universe_manifest.json          # Report parsing confidence & uncovered years
│   ├── progress.sqlite                 # Job state machine (DONE/RUNNING/PENDING/PARTIAL)
│   └── collector.lock                  # Inter-process write lock (flock)
└── reports/                            # Auditing & quality reports
    ├── summary.json                    # Real-time summary statistics
    ├── progress.parquet                # Historical job audit trail
    ├── coverage.parquet                # Coverage bounds by provider
    ├── validation_issues.parquet       # Quality issues & parse exceptions
    ├── provider_discrepancies.parquet  # Discrepancy analysis between vendors
    └── failed_symbols.parquet          # Detailed vendor error traces
```

### 6.2 Data Schema: `processed/hose_ohlcv`

| Column | Type | Nullable | Description |
|---|---|---|---|
| `date` | `date32` | No | Market session date (no timezone) |
| `symbol` | `string` | No | Stock ticker symbol (partition key) |
| `open` | `float64` | Yes | Verified raw session open price (VND) |
| `high` | `float64` | Yes | Verified raw session high price (VND) |
| `low` | `float64` | Yes | Verified raw session low price (VND) |
| `close` | `float64` | Yes | Verified raw session close price (VND) |
| `volume` | `int64` | Yes | Matched trading volume (shares) |
| `value` | `float64` | Yes | Matched trading value (VND) |
| `adjusted_open` | `float64` | Yes | Explicit provider adjusted open |
| `adjusted_high` | `float64` | Yes | Explicit provider adjusted high |
| `adjusted_low` | `float64` | Yes | Explicit provider adjusted low |
| `adjusted_close`| `float64` | Yes | Explicit provider adjusted close |
| `source` | `string` | No | Primary provider selected (e.g. `kbs`, `vci`) |
| `raw_source` | `string` | Yes | Source of raw OHLC group |
| `adjusted_source` | `string` | Yes | Source of explicit adjusted prices |
| `volume_source` | `string` | Yes | Source of trading volume |
| `price_basis` | `string` | No | Classification (`raw_verified`, `unknown_chart`) |
| `volume_basis` | `string` | No | `matched_shares` or `provider_unspecified` |
| `security_id` | `string` | No | Provisional identity (`unresolved:<symbol>`) |
| `quality_flags` | `string` | No | Semicolon-separated audit flags (`raw_prices_unavailable`, etc.) |

---

## 7. Downstream Consumption: How to Query the Data

The dataset is partitioned by `symbol`, allowing high-performance zero-copy columnar reads with Pandas, Polars, or DuckDB.

### Python (Pandas)
```python
import pandas as pd

# 1. Read entire HOSE dataset
df = pd.read_parquet("data/processed/hose_ohlcv")

# 2. Filter specific stock with partition pushdown (very fast, reads only FPT partition)
fpt = pd.read_parquet("data/processed/hose_ohlcv", filters=[("symbol", "=", "FPT")])
fpt = fpt.sort_values("date")
print(fpt[["date", "close", "volume", "source", "quality_flags"]].tail())
```

### Python (Polars)
```python
import polars as pl

# Lazy query with predicate pushdown
q = (
    pl.scan_parquet("data/processed/hose_ohlcv")
    .filter(pl.col("symbol") == "REE")
    .select(["date", "open", "high", "low", "close", "volume"])
    .sort("date")
)
ree = q.collect()
print(ree.tail(10))
```

### SQL (DuckDB)
```sql
-- Query directly from parquet without importing
SELECT date, symbol, close, volume 
FROM read_parquet('data/processed/hose_ohlcv/**/*.parquet')
WHERE symbol IN ('FPT', 'HPG', 'VNM') AND date >= '2024-01-01'
ORDER BY symbol, date;
```

---

## 8. Troubleshooting & Operational Runbook

### Issue 1: VCI Returns HTTP 403
* **Symptom in log:** `AAA vci ... failed: vci: HTTP 403; no bypass attempted` followed by `vci: endpoint access denied earlier in this process`.
* **Explanation:** Vietcap occasionally enforces IP restrictions or anti-bot blocks on their `/api/chart/OHLCChart/gap-chart` endpoint.
* **System Behavior:** The built-in circuit breaker in `hose_history/transport.py` immediately isolates that endpoint for the duration of the run. It does **not** crash or halt the collector. Instead, fallback continues with **KBS**, which retrieves thousands of historical sessions.
* **Action:** No manual intervention is needed. To avoid even attempting VCI, pass `--providers kbs`.

### Issue 2: `collector.lock` Contention Error
* **Symptom in log:** `Another collector is writing this data directory`.
* **Explanation:** `hose_history/cli.py` applies an exclusive file lock on `data/metadata/collector.lock` to prevent concurrent write collisions.
* **Resolution:**
  1. Check if another CLI or background worker is running:
     ```bash
     ps aux | grep collect_hose
     ```
  2. If a process was hard-killed (e.g. `kill -9`), the lock file descriptor might remain held until the zombie process terminates. If no process is running, verify with `lsof data/metadata/collector.lock` and remove the stale lock file if necessary.

### Issue 3: Incomplete Historical Delistings
* **Symptom:** Discovered universe contains 405 current stocks and ~13 historical stocks.
* **Explanation:** The bundled evidence snapshot extracts delistings from the official 2023 annual report. Other years (2020, 2022, 2024) rely on online PDF downloads from `staticfile.hsx.vn`, which can be temporarily unavailable.
* **Action:** You can supply your own verified delisting evidence CSV using:
  ```bash
  ./.venv/bin/python collect_hose.py --refresh-universe --universe-evidence my_delistings.csv
  ```
  *(CSV requires columns: `symbol`, `exchange`, `evidence_url`).*

### Issue 4: Resetting or Cleaning Data
* **To clean temporary progress while keeping collected Parquet files:**
  Remove `data/metadata/progress.sqlite`.
* **To completely wipe and restart from scratch:**
  ```bash
  rm -rf data/
  ```

---

## 9. Handover Checklist & Contacts

- [x] **Core Python Engine Installed & Tested:** 34/34 pytest tests passing.
- [x] **Frontend Precompiled:** `frontend/dist/` populated and verified.
- [x] **Web & CLI Dual Mode Verified:** Tested `--status`, `--serve`, and symbol runs.
- [x] **Deployment Configs Provided:** Native Systemd, Nginx, Dockerfile, and Docker Compose configurations documented.
- [x] **Resilience Verified:** Tested graceful `SIGINT` interruption and SQLite checkpoint recovery.
