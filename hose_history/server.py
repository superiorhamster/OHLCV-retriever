from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import io
import json
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from .collector import Collector
from .config import CollectorConfig
from .storage import Store
from .transport import Transport
from .universe import discover_universe

log = logging.getLogger(__name__)

# In-memory log buffer for streaming to UI
class InMemoryLogHandler(logging.Handler):
    def __init__(self, maxlen=300):
        super().__init__()
        self.buffer = deque(maxlen=maxlen)

    def emit(self, record):
        try:
            msg = self.format(record)
            self.buffer.append({
                "time": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "level": record.levelname,
                "message": msg
            })
        except Exception:
            self.handleError(record)

log_handler = InMemoryLogHandler()
log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
logging.getLogger("hose_history").addHandler(log_handler)
logging.getLogger("hose_history").setLevel(logging.INFO)


class RunManager:
    def __init__(self, data_dir: Path = Path("data")):
        self.data_dir = data_dir
        self.lock = threading.Lock()
        self.is_running = False
        self.current_transport: Transport | None = None
        self.current_run_id: str | None = None
        self.target_symbols: list[str] = []
        self.thread: threading.Thread | None = None

    def start_run(self, symbols: list[str] | Literal["ALL"], mode: str = "full",
                  start_date: str = "2000-07-28", end_date: str | None = None,
                  workers: int = 3, providers: tuple[str, ...] = ("kbs", "vci"),
                  refresh: bool = False):
        with self.lock:
            if self.is_running and self.thread and self.thread.is_alive():
                raise HTTPException(status_code=409, detail="A retrieval job is already currently running.")

            # Load universe
            store = Store(self.data_dir)
            cfg = CollectorConfig(
                start_date=start_date,
                end_date=end_date,
                max_workers=workers,
                providers=providers,
                data_dir=self.data_dir
            )
            snapshot = cfg.end if not refresh else datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            transport = Transport(cfg, snapshot)

            universe_path = self.data_dir / "metadata" / "symbols.parquet"
            if not universe_path.exists():
                universe = discover_universe(transport, cfg, store)
            else:
                universe = pd.read_parquet(universe_path)

            if symbols == "ALL":
                target = sorted(set(universe.symbol))
            else:
                target = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
                if not target:
                    raise HTTPException(status_code=400, detail="No valid symbols specified.")

            self.is_running = True
            self.current_transport = transport
            self.target_symbols = target

            def worker():
                try:
                    collector = Collector(cfg, transport, store)
                    self.current_run_id = f"{cfg.end}-{mode}"
                    log.info("Starting collection run for %d symbols in %s mode", len(target), mode)
                    collector.run(target, universe, mode=mode, refresh=refresh)
                    log.info("Collection run completed successfully.")
                except Exception as exc:
                    log.exception("Collection run encountered an error: %s", exc)
                finally:
                    store.export_reports()
                    store.close()
                    transport.close()
                    with self.lock:
                        self.is_running = False
                        self.current_transport = None

            self.thread = threading.Thread(target=worker, daemon=True)
            self.thread.start()

    def stop_run(self):
        with self.lock:
            if not self.is_running or not self.current_transport:
                return False
            log.warning("Stop signal triggered by user via API")
            self.current_transport.stop_event.set()
            return True

run_manager = RunManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Cleanup on shutdown
    if run_manager.is_running and run_manager.current_transport:
        run_manager.current_transport.stop_event.set()

app = FastAPI(title="HOSE OHLCV Retriever API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StartRequest(BaseModel):
    symbols: list[str] | Literal["ALL"]
    mode: Literal["full", "update"] = "full"
    start_date: str = "2000-07-28"
    end_date: str | None = None
    workers: int = Field(default=3, ge=1, le=10)
    providers: list[str] = Field(default_factory=lambda: ["kbs", "vci"])
    refresh: bool = False


@app.get("/api/universe")
def get_universe():
    data_dir = run_manager.data_dir
    symbols_path = data_dir / "metadata" / "symbols.parquet"
    if not symbols_path.exists():
        # Auto-discover or fallback
        store = Store(data_dir)
        cfg = CollectorConfig(data_dir=data_dir)
        transport = Transport(cfg, cfg.end)
        try:
            df = discover_universe(transport, cfg, store)
        finally:
            store.close()
            transport.close()
    else:
        df = pd.read_parquet(symbols_path)

    # Check which symbols have local processed files
    processed_root = data_dir / "processed" / "hose_ohlcv"
    local_data = {}
    if processed_root.exists():
        for p in processed_root.glob("symbol=*/part.parquet"):
            sym = p.parent.name.split("=", 1)[1]
            try:
                # Read metadata or fast date column
                part_df = pd.read_parquet(p, columns=["date"])
                local_data[sym] = {
                    "rows": len(part_df),
                    "start": str(min(part_df.date)) if not part_df.empty else None,
                    "end": str(max(part_df.date)) if not part_df.empty else None
                }
            except Exception:
                local_data[sym] = {"rows": 0, "start": None, "end": None}

    items = []
    for _, row in df.iterrows():
        sym = str(row.get("symbol", ""))
        loc = local_data.get(sym)
        items.append({
            "symbol": sym,
            "company_name": str(row.get("company_name", "")),
            "status": str(row.get("status", "current")),
            "listing_date": str(row.get("listing_date", "")) if pd.notna(row.get("listing_date")) else None,
            "delisting_date": str(row.get("delisting_date", "")) if pd.notna(row.get("delisting_date")) else None,
            "has_data": sym in local_data,
            "row_count": loc["rows"] if loc else 0,
            "start_date": loc["start"] if loc else None,
            "end_date": loc["end"] if loc else None,
        })

    return {
        "total": len(items),
        "current": sum(1 for x in items if x["status"] == "current"),
        "historical": sum(1 for x in items if x["status"] != "current"),
        "with_data": len(local_data),
        "symbols": sorted(items, key=lambda x: (not x["has_data"], x["symbol"])),
    }


@app.post("/api/retriever/start")
def start_retrieval(req: StartRequest):
    run_manager.start_run(
        symbols=req.symbols,
        mode=req.mode,
        start_date=req.start_date,
        end_date=req.end_date,
        workers=req.workers,
        providers=tuple(req.providers),
        refresh=req.refresh,
    )
    return {
        "status": "started",
        "mode": req.mode,
        "symbols_count": len(run_manager.target_symbols),
        "target_symbols": run_manager.target_symbols[:10] if len(run_manager.target_symbols) > 10 else run_manager.target_symbols,
    }


@app.post("/api/retriever/stop")
def stop_retrieval():
    stopped = run_manager.stop_run()
    if stopped:
        return {"status": "stopping", "message": "Graceful stop initiated. Current active symbols will finalize."}
    return {"status": "idle", "message": "No active retrieval process is running."}


@app.get("/api/retriever/status")
def get_retriever_status():
    data_dir = run_manager.data_dir
    db_path = data_dir / "metadata" / "progress.sqlite"

    counts = {"DONE": 0, "RUNNING": 0, "PENDING": 0, "PARTIAL": 0, "FAILED": 0}
    active_symbols = []
    run_id = run_manager.current_run_id

    if db_path.exists():
        try:
            with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as db:
                latest = db.execute("SELECT job_key FROM jobs ORDER BY updated_at DESC LIMIT 1").fetchone()
                if latest:
                    prefix = latest[0].rsplit(":", 1)[0]
                    if not run_id:
                        run_id = prefix
                    db_counts = dict(db.execute("SELECT status, COUNT(*) FROM jobs WHERE job_key LIKE ? GROUP BY status", (prefix + ":%",)))
                    counts.update(db_counts)
                    active_symbols = [r[0] for r in db.execute("SELECT symbol FROM jobs WHERE job_key LIKE ? AND status='RUNNING'", (prefix + ":%",))]
        except Exception as e:
            log.warning("Could not read progress sqlite: %s", e)

    return {
        "is_running": run_manager.is_running,
        "run_id": run_id or "idle",
        "total_targets": len(run_manager.target_symbols),
        "counts": counts,
        "active_symbols": active_symbols,
        "logs": list(log_handler.buffer),
    }


def load_symbol_with_providers(store: Store, symbol: str) -> pd.DataFrame:
    df = store.load(symbol)
    if df.empty:
        return df
    # If canonical prices are null, enrich with provider prices if available
    cols_needed = ["provider_open", "provider_high", "provider_low", "provider_close"]
    missing_cols = [c for c in cols_needed if c not in df.columns]
    if missing_cols or (df["close"].isna().all() if "close" in df else True):
        provider_files = sorted(store.root.glob(f"raw/*/normalized/*/{symbol}.parquet"))
        if provider_files:
            latest_pf = provider_files[-1]
            try:
                pdf = pd.read_parquet(latest_pf)
                cols_to_merge = ["date", *cols_needed]
                pdf_subset = pdf[[c for c in cols_to_merge if c in pdf.columns]].drop_duplicates("date")
                # Drop existing empty provider cols to avoid collision
                drop_existing = [c for c in cols_needed if c in df.columns]
                df_base = df.drop(columns=drop_existing) if drop_existing else df
                df = df_base.merge(pdf_subset, on="date", how="left")
            except Exception as e:
                log.warning("Could not merge provider parquet %s: %s", latest_pf, e)
    return df


@app.get("/api/preview/{symbol}")
def preview_symbol(
    symbol: str,
    slice: Literal["head", "tail", "all"] = "head",
    limit: int = Query(default=20, ge=1, le=1000),
    sort: Literal["asc", "desc"] = "desc"
):
    symbol = symbol.strip().upper()
    store = Store(run_manager.data_dir)
    try:
        path = store.symbol_path(symbol)
        if not path.exists():
            return {
                "has_data": False,
                "symbol": symbol,
                "message": f"No data collected yet for {symbol}."
            }

        df = load_symbol_with_providers(store, symbol)
        if df.empty:
            return {
                "has_data": False,
                "symbol": symbol,
                "message": f"Dataset for {symbol} is empty."
            }

        total_rows = len(df)
        df_sorted = df.sort_values("date", ascending=(sort == "asc"))

        if slice == "head":
            selected_df = df_sorted.head(limit)
        elif slice == "tail":
            selected_df = df_sorted.tail(limit)
        else:
            selected_df = df_sorted.head(limit)

        # Summary statistics
        earliest_date = str(min(df.date))
        latest_date = str(max(df.date))
        raw_close_count = int(df.close.notna().sum())
        chart_close_count = int(df.provider_close.notna().sum()) if "provider_close" in df else 0
        quality_flags = sorted(set(f for f in df.quality_flags.dropna().unique() if f))

        # Latest row quote
        latest_row = df.sort_values("date", ascending=False).iloc[0].to_dict()
        def clean_val(v):
            if pd.isna(v) or v is None:
                return None
            if isinstance(v, (np.integer, int)):
                return int(v)
            if isinstance(v, (np.floating, float)):
                return round(float(v), 2)
            return str(v)

        clean_latest = {k: clean_val(v) for k, v in latest_row.items()}

        # Clean selected rows for JSON response
        records = []
        for _, r in selected_df.iterrows():
            row_dict = {k: clean_val(v) for k, v in r.items()}
            records.append(row_dict)

        # Primary display columns ordered logically
        all_cols = list(df.columns)
        priority_cols = [
            "date", "symbol", "close", "provider_close", "open", "provider_open",
            "high", "provider_high", "low", "provider_low", "volume", "quality_flags", "source"
        ]
        ordered_cols = [c for c in priority_cols if c in all_cols] + [c for c in all_cols if c not in priority_cols]

        return {
            "has_data": True,
            "symbol": symbol,
            "total_rows": total_rows,
            "slice": slice,
            "limit": limit,
            "sort": sort,
            "earliest_date": earliest_date,
            "latest_date": latest_date,
            "metrics": {
                "raw_prices_count": raw_close_count,
                "chart_prices_count": chart_close_count,
                "has_raw_prices": raw_close_count > 0,
                "quality_flags": quality_flags,
                "latest_quote": clean_latest
            },
            "columns": ordered_cols,
            "rows": records
        }
    finally:
        store.close()


@app.get("/api/chart/{symbol}")
def chart_data(symbol: str, limit: int = Query(default=1000, ge=10, le=10000)):
    symbol = symbol.strip().upper()
    store = Store(run_manager.data_dir)
    try:
        path = store.symbol_path(symbol)
        if not path.exists():
            return {"symbol": symbol, "candles": [], "volumes": []}

        df = load_symbol_with_providers(store, symbol)
        if df.empty:
            return {"symbol": symbol, "candles": [], "volumes": []}

        df = df.sort_values("date", ascending=True).tail(limit)

        candles = []
        volumes = []
        for _, r in df.iterrows():
            d_str = str(r["date"])
            # Fall back to provider_* if canonical close is null
            c = r["close"] if pd.notna(r["close"]) else r.get("provider_close")
            o = r["open"] if pd.notna(r["open"]) else r.get("provider_open", c)
            h = r["high"] if pd.notna(r["high"]) else r.get("provider_high", c)
            l = r["low"] if pd.notna(r["low"]) else r.get("provider_low", c)
            vol = r.get("volume", 0)

            if pd.notna(c) and float(c) > 0:
                o_val, h_val, l_val, c_val = float(o), float(h), float(l), float(c)
                candles.append({
                    "time": d_str,
                    "open": round(o_val, 2),
                    "high": round(h_val, 2),
                    "low": round(l_val, 2),
                    "close": round(c_val, 2),
                })
                is_up = c_val >= o_val
                volumes.append({
                    "time": d_str,
                    "value": int(vol) if pd.notna(vol) else 0,
                    "color": "rgba(34, 197, 94, 0.5)" if is_up else "rgba(239, 68, 68, 0.5)"
                })

        return {
            "symbol": symbol,
            "candles": candles,
            "volumes": volumes,
        }
    finally:
        store.close()


@app.get("/api/export/{symbol}")
def export_symbol_csv(symbol: str):
    symbol = symbol.strip().upper()
    store = Store(run_manager.data_dir)
    try:
        path = store.symbol_path(symbol)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")
        df = store.load(symbol)
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        return StreamingResponse(
            io.BytesIO(buf.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={symbol}_ohlcv.csv"}
        )
    finally:
        store.close()


# Mount static assets if frontend/dist exists
dist_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if dist_dir.exists():
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="static")
