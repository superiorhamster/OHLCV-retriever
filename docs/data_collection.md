# Historical HOSE market data

This collector retrieves public data directly with HTTP. It does not require `vnstock`, paid subscriptions, credentials, or anti-bot workarounds. The dataset is an **incomplete approximation of the historical HOSE universe**, not a survivor-bias-free census.

## Reproduction

Python 3.11 or newer is required. Installation and execution:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
# Alternatively: uv venv .venv && uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python collect_hose.py --mode full
.venv/bin/python collect_hose.py --mode update
.venv/bin/python collect_hose.py --symbol FPT
.venv/bin/python collect_hose.py --symbol FPT --start 2006-01-01 --end 2026-09-26
.venv/bin/python collect_hose.py --symbol REE,FPT,HPG
.venv/bin/python collect_hose.py --limit 5
.venv/bin/python collect_hose.py --universe-only
.venv/bin/python collect_hose.py --status
.venv/bin/python collect_hose.py --refresh-universe --universe-only
.venv/bin/python collect_hose.py --config collector.example.json
.venv/bin/python -m pytest -q
HOSE_LIVE_TESTS=1 .venv/bin/python -m pytest -m integration -q
```

Rerun the same command after interruption. HTTP responses are reused and completed symbol jobs are skipped. `--refresh` requests a new response snapshot and recollects the selected range. `--providers kbs,vci` is useful for chart coverage investigation but **does not produce verified raw prices**. Use the default provider set for raw-price recovery.

SIGINT/Ctrl-C and SIGTERM stop after active requests, retaining cached responses and returning unfinished jobs to PENDING. An interrupted full run with an implicit end date retains its original end date on restart, including across midnight. Use `--status` for a read-only summary of the latest run without contacting providers.

The default end is the current calendar date in Asia/Ho_Chi_Minh. Data available during the current trading day can be provisional; run after the session and use `--refresh` if recollecting on the same day. Future explicit end dates do not fabricate sessions. Weekends and holidays are not filled.

## Architecture

`CollectorConfig` controls provider order, request pacing, retries, chunk sizes, discrepancy thresholds, and storage. `Transport` serializes requests to each provider, archives JSON responses, and retries transient failures. Provider adapters normalize observations while retaining provenance. `Collector` reconciles compatible fields, validates observations, compares providers, and writes through `Store`. Universe discovery is independent of quote availability.

Workers process symbols using `ThreadPoolExecutor`, default three. Each provider has one in-flight request and at least 0.5 seconds between requests. Timeout is 30 seconds; five retries use exponential backoff, jitter, and `Retry-After`. HTTP 401/403 disables that endpoint for the process; an independently public history endpoint can still work when a listing endpoint denies access. HTTP 429/500/502/503/504 and network errors are retried. No proxy rotation, login circumvention, or CAPTCHA bypass is attempted.

## Providers and measured coverage

The following results were observed using unauthenticated requests on 2026-09-26. They are observations, not service guarantees.

| Symbol | KBS earliest | VCI earliest | VCI daily rows | CafeF early session verified |
|---|---|---|---:|---|
| REE | 2016-05-18 | 2000-07-28 | 6367 | 2000-07-28 |
| SAM | 2016-06-06 | 2000-07-28 | 6367 | 2000-07-28 |
| FPT | 2016-09-21 | 2006-12-13 | 4929 | 2006-12-13 |
| HPG | 2016-05-25 | 2007-11-15 | 4700 | 2007-11-15 |
| VNM | 2016-06-27 | 2006-01-19 | 5155 | 2006-01-19 |

Full-range KBS and VCI discovery responses ended on 2026-09-25. The CafeF column records narrow early-window tests, not completed full backfills. VCI directly recovered more than eight years of history, including the first market session for REE and SAM. KBS early-window probes were empty; chunking did not recover those early observations from KBS.

### KBS

- History: `GET https://kbbuddywts.kbsec.com.vn/iis-server/investment/stocks/{symbol}/data_day`, with `sdate` and `edate` formatted `DD-MM-YYYY`.
- Current securities: `/stock/search/data`; profile: `/stockinfo/profile/{symbol}?l=1`. The profile's `LD` is a listing-date observation; its meaning across exchange transfers needs corroboration.
- Public requests worked without authentication or payment. Daily OHLCV is implemented. The upstream interface also exposes other chart intervals; they are outside this collector's scope.
- No documented hard record limit or request-rate guarantee was established. Configurable three-year windows are used. Early archives for the five tested stocks were missing.
- When a response starts more than the configurable prefix-probe threshold after the requested start, the omitted prefix is queried independently. Empty prefixes remain uncertain coverage, not invented sessions.
- Chart OHLC adjustment semantics are not sufficiently established. Values are retained as `provider_*` in normalized provider archives, never relabeled as raw OHLC.
- The observed current-stock directory contained 405 HOSE stocks. It excludes some historical securities, so it cannot define the entire universe.

### VCI / Vietcap

- History: `POST https://trading.vietcap.com.vn/api/chart/OHLCChart/gap-chart`, JSON `{"symbols":["REE"],"timeFrame":"ONE_DAY","to":<epoch>,"countBack":1000}`.
- Current securities: `GET https://trading.vietcap.com.vn/api/price/symbols/getAll`.
- Public requests worked without authentication or payment. Daily data reached 2000-07-28. A single discovery request accepted `countBack=10000`; this is not a proven maximum.
- The adapter pages backward using the earliest timestamp minus one second and filters the requested date window. A short page is not taken as proof of exhaustion.
- FLC, HBC, and POM histories were accessible during discovery, but accessibility does not prove complete or valid historical sessions.
- Chart prices appear adjusted in historical comparisons, but adjustment methodology is unverified. They remain explicitly unclassified chart prices. `accumulatedValue` is archived without conversion because its unit/meaning has not been verified.
- Rate limits and long-term interface stability are unknown.

### CafeF

- `GET https://cafef.vn/du-lieu/ajax/pagenew/datahistory/pricehistory.ashx` with `Symbol`, `StartDate`, `EndDate`, `PageIndex`, `PageSize`; request dates use `MM/DD/YYYY`, response dates `DD/MM/YYYY`.
- No authentication or payment was needed. Daily history reached REE/SAM's first session. The old `s.cafef.vn` endpoint redirects but drops query parameters; the adapter uses the observed redirect destination directly.
- Long date ranges were silently restricted to approximately three months. Requested page sizes of 50, 100, and 1000 all returned at most 20 rows. The adapter uses 90-day windows, actual returned pages, and repetition detection.
- Explicit raw OHLC and adjusted close are available. Adjusted open/high/low are not synthesized. Prices are labeled thousands of VND and trading values billions of VND on the public history page.
- `volume`/`value` mean matched trading, excluding separately supplied put-through trades. Early reported trading values can be rounded, zero, or inconsistent; raw provider values are retained and warnings identify anomalies.
- Delisted-symbol completeness, corporate-action methodology, rate limits, and contractual stability remain unknown.

### VNDIRECT

`https://finfo-api.vndirect.com.vn/v4/stock_prices/` timed out in discovery. Its historical request interface is documented in upstream public client discussions, but current accessibility and normalization are not verified. The opt-in adapter archives a successful response but refuses to publish values until units and semantics are verified. It is disabled by default. No historical-range, adjusted-price, delisting, rate, or authentication guarantee is made.

### SSI and other sources

SSI FastConnect documents daily OHLC and richer daily price fields, but requires issued credentials. Its suitability as a free source for this user has not been established, so it is not an implemented dependency. No paid service or invented alternative endpoint is used.

Primary technical references:

- [Upstream KBS adapter](https://raw.githubusercontent.com/thinh-vu/vnstock/main/vnstock/explorer/kbs/quote.py)
- [Upstream VCI adapter](https://raw.githubusercontent.com/thinh-vu/vnstock/main/vnstock/explorer/vci/quote.py)
- [CafeF history labels and units](https://cafef.vn/du-lieu/lich-su-giao-dich-ree-1.chn)
- [SSI authentication and API documentation](https://guide.ssi.com.vn/ssi-products/tieng-viet/fastconnect-data/danh-sach-cac-api)

## Universe and survivorship bias

Current KBS/VCI listings are unioned with confidently extracted delisted-company rows from official HOSE annual reports for 2020, 2022, 2023, and 2024. Reports, hashes, source URLs, pages, extraction status, and uncovered years are recorded. Failed extraction never becomes an empty, supposedly complete universe. Previously discovered historical securities survive refreshes.

The implementation run encountered rejected annual-report downloads. A small bundled extraction contains the 13 delisting entries successfully read earlier from the 2023 report, PDF page 47 / printed page 97, with exact source URL and evidence text. It is an auditable source snapshot, not an exhaustive hand-written symbol list. Other report years remain incomplete when retrieval/extraction fails. VCI's listing endpoint also returned 403 during implementation; this does not erase a successfully obtained KBS universe or authorize bypassing access restrictions.

This coverage is incomplete: early delistings, all other report years, ticker changes, and ticker reuse are not comprehensively resolved. A historical stock is retained even when all price providers fail. Additional sourced evidence can be supplied with `--universe-evidence file.csv` (required: `symbol`, `exchange`, `evidence_url`; optional listing/delisting dates, company name and previous symbol).

The panel includes the entire available history of evidenced HOSE stocks, including observations on other exchanges. Current exchange membership is **not** applied retroactively. `exchange_memberships.parquet` stores evidence and uncertain boundaries. Unknown dates remain null. A null membership boundary is not permission to assume membership forever. `security_id=unresolved:<symbol>` warns that issuer continuity is not established. Do not train an allegedly point-in-time HOSE strategy using current or ever-listed membership alone.

## Dataset schema

| Field | Meaning |
|---|---|
| `date` | Daily market trading date, Arrow date32, no timezone |
| `symbol` | Provider ticker, available from the Parquet partition |
| `open`, `high`, `low`, `close` | Verified raw prices in VND; Float64, nullable |
| `volume` | Selected provider's share volume; nullable Int64; see `volume_basis` |
| `value` | Reported matched trading value in VND when verified; nullable Float64 |
| `adjusted_open/high/low/close` | Only explicitly supplied adjusted prices in VND; nullable Float64 |
| `source` | Provider selected for the primary daily observation |
| `raw_source` | Provider of the complete raw OHLC group; null if unavailable |
| `adjusted_source` | Provider of explicit adjusted fields; null if unavailable |
| `volume_source` | Provider supplying the selected volume |
| `price_basis` | Provider's verified or unknown price classification |
| `volume_basis` | `matched_shares` or `provider_unspecified` |
| `security_id` | Provisional identity; unresolved ticker continuity is explicit |
| `adjustment_as_of` | Response snapshot identifier; not a historical availability timestamp |
| `retrieved_at` | UTC time the canonical observation was assembled |
| `quality_flags` | Semicolon-separated validation warnings |
| `foreign_buy/sell_volume`, `proprietary_buy/sell_volume` | Nullable integer share counts; currently unavailable |
| `foreign_buy/sell_value` | Nullable Float64 VND values; currently unavailable |

Unknown chart OHLC are available as `provider_open/high/low/close` in provider archives only. Adjusted-only or chart-only sessions may have null raw prices. Zero prices and impossible OHLC are flagged, not silently repaired. Invalid dates/numerics are quarantined through issue reports with the original payload retained. Nonintegral/negative volumes cannot enter the nullable integer share schema and are reported with raw evidence.

`symbols.parquet` contains symbol, company name, exchange, listing/delisting dates, status, previous symbol, source, evidence, observation date, and provisional security identity. `aliases.parquet` records only evidenced aliases; an empty file means none were established.

## Storage and research usage

```text
data/
  raw/{provider}/{snapshot}/{request-hash}.json
  raw/{provider}/normalized/{snapshot}/{symbol}.parquet
  raw/metadata/hose_annual_{year}.pdf
  processed/hose_ohlcv/symbol={symbol}/part.parquet
  metadata/symbols.parquet
  metadata/exchange_memberships.parquet
  metadata/aliases.parquet
  metadata/historical_evidence.parquet
  metadata/universe_manifest.json
  metadata/progress.sqlite
  reports/failed_symbols.parquet
  reports/validation_issues.parquet
  reports/provider_discrepancies.parquet
  reports/coverage.parquet
  reports/progress.parquet
  reports/summary.json
```

Symbol partitioning permits atomic replacement of one stock without rewriting the market. Daily panels are unique by symbol/date and sorted per symbol. Response snapshots are immutable and request keyed. Normalized provider extracts are a convenience; raw response envelopes remain the authoritative evidence.

```python
import pandas as pd
df = pd.read_parquet('data/processed/hose_ohlcv')
df = df.sort_values(['symbol', 'date'])
fpt = pd.read_parquet('data/processed/hose_ohlcv', filters=[('symbol', '=', 'FPT')])
issues = pd.read_parquet('data/reports/validation_issues.parquet')
```

No train/test split, global scaling, filling, adjustment-factor inference, or model features are applied. Today's provider-adjusted prices may incorporate subsequent corporate actions. They cannot be claimed to reflect information available on the historical date. Immutable snapshots preserve reproducibility from collection onward, not historical point-in-time availability before collection.

## Validation, fallback, and update semantics

Provider priority is KBS, VCI, optional VNDIRECT, then CafeF. Field availability and price-basis compatibility constrain selection. KBS/VCI cannot satisfy raw OHLC until their semantics are verified, so CafeF is normally necessary for raw prices. Secondary retrieval also supplies coverage evidence and overlap checks. Provider failures do not stop the other adapters.

Returned ranges, valid empty windows, malformed responses, and failed windows are distinct. Differences from other providers reveal observed omissions; arbitrary weekdays are not assumed to be missing sessions. The early HOSE trading calendar was not a modern five-day calendar. Late starts are possible truncation warnings, not proof that a company traded earlier.

Duplicate observations are logged before stable selection. Conflicting original records remain archived. Raw OHLC is selected as a group. Old raw rows are retained when a failed provider offers only chart prices during a retry.

Discrepancy reports record both observations, absolute and percentage differences (denominator = provider A), thresholds, and whether definitions are comparable. Zero denominators yield null percentages. Unknown chart bases and differing volume definitions are explicitly noncomparable. A large discrepancy does not establish which provider is correct.

Incremental updates fetch newer dates and unresolved failed intervals. A recent 14-day overlap plus one sentinel session per stored year audits explicit adjusted closes. Detected revisions trigger a complete selected-symbol refresh and atomic publication; failed refreshes preserve the previous panel. This audit is sampled and can miss revisions outside checked dates. `--refresh` supports a deliberate full reconciliation.

Failed intervals are retried only for their affected provider. An unavailable VCI archive therefore does not cause CafeF's entire raw history to be downloaded again on each update. Date-specific source failures remain visible separately from a successfully stored panel.

SQLite tracks PENDING/RUNNING/DONE/PARTIAL/FAILED jobs. DONE means the selected request completed with raw prices for recovered sessions; it does **not** certify a complete historical universe or every expected session. Reports retain prior failures as audit history; unresolved intervals are tracked separately. A single CLI process owns a data directory, with controlled worker threads inside it.

## Operational limitations

A full raw-price backfill can take many hours because CafeF exposes small pages and short windows. Use a controlled sample first and inspect `collector.log`, `reports/progress.parquet`, and `reports/summary.json`. Stop and rerun the identical command to resume. The summary is refreshed after each completed symbol and reports counts, earliest/latest observations, and partial/failed jobs. Inspect coverage reports for provider-specific missing periods.

Provider interfaces are public website interfaces, not guaranteed archival services. Rates, archive retention, adjustment methodology, and historical metadata can change. Availability of one symbol or window must not be generalized into a completeness claim.
