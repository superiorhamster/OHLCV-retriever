import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .schema import CANONICAL, NUMERIC, OPTIONAL_VALUE, OPTIONAL_VOLUME


def atomic_parquet(df: pd.DataFrame, path: Path, *, canonical=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    if canonical:
        for col in ["date"]:
            if col in table.column_names:
                i = table.column_names.index(col)
                table = table.set_column(i, pa.field(col, pa.date32()), table[col].cast(pa.date32()))
        for col in set(NUMERIC + OPTIONAL_VALUE):
            if col in table.column_names:
                i = table.column_names.index(col)
                table = table.set_column(i, pa.field(col, pa.float64()), table[col].cast(pa.float64()))
        for col in ["volume", *OPTIONAL_VOLUME]:
            if col in table.column_names:
                i = table.column_names.index(col)
                table = table.set_column(i, pa.field(col, pa.int64()), table[col].cast(pa.int64(), safe=True))
        # All nullable text columns must have concrete types, including all-null sources.
        for col in ["symbol", "source", "raw_source", "adjusted_source", "volume_source",
                    "security_id", "price_basis", "volume_basis", "adjustment_as_of", "retrieved_at", "quality_flags"]:
            if col in table.column_names:
                i = table.column_names.index(col)
                table = table.set_column(i, pa.field(col, pa.string()), table[col].cast(pa.string()))
    # Arrow ignores dot-prefixed files while another process reads the dataset.
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".pending-", suffix=".tmp")
    os.close(fd)
    try:
        pq.write_table(table, temp, compression="zstd")
        with open(temp, "rb") as f:
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class Store:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / "metadata").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "metadata" / "progress.sqlite", check_same_thread=False)
        self.lock = threading.RLock()
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS jobs (
          job_key TEXT PRIMARY KEY, symbol TEXT, status TEXT, updated_at TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS reports (
          kind TEXT, item_key TEXT, payload TEXT, PRIMARY KEY(kind, item_key));
        CREATE TABLE IF NOT EXISTS unresolved (
          symbol TEXT, provider TEXT, start TEXT, end TEXT, error TEXT,
          PRIMARY KEY(symbol, provider, start, end));
        """)

    def close(self):
        self.db.close()

    def checkpoint(self, key, symbol, status, detail=""):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?)",
                (key, symbol, status, datetime.now(timezone.utc).isoformat(), detail))
            self.db.commit()

    def done(self, key):
        with self.lock:
            row = self.db.execute("SELECT status FROM jobs WHERE job_key=?", (key,)).fetchone()
        return bool(row and row[0] == "DONE")

    def report(self, kind, rows):
        with self.lock:
            for row in rows:
                payload = json.dumps(row, sort_keys=True, default=str, allow_nan=False)
                key = hashlib.sha256(payload.encode()).hexdigest()
                self.db.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?)", (kind, key, payload))
            self.db.commit()

    def record_intervals(self, coverage, errors):
        with self.lock:
            for item in coverage:
                if item.get("status") in {"observed", "empty_unverified"}:
                    self.db.execute("DELETE FROM unresolved WHERE symbol=? AND provider=? AND start>=? AND end<=?",
                        (item["symbol"], item["source"], item["requested_start"], item["requested_end"]))
            for e in errors:
                if e.get("requested_start") and e.get("requested_end"):
                    self.db.execute("INSERT OR REPLACE INTO unresolved VALUES (?,?,?,?,?)",
                        (e["symbol"], e["source"], e["requested_start"], e["requested_end"], e["error"]))
            self.db.commit()

    def unresolved_start(self, symbol, provider=None):
        with self.lock:
            if provider:
                return self.db.execute("SELECT MIN(start) FROM unresolved WHERE symbol=? AND provider=?", (symbol, provider)).fetchone()[0]
            return self.db.execute("SELECT MIN(start) FROM unresolved WHERE symbol=?", (symbol,)).fetchone()[0]

    def export_reports(self):
        defaults = {
            "failed_symbols": ["symbol", "source", "error"],
            "validation_issues": ["symbol", "source", "date", "code", "detail"],
            "provider_discrepancies": ["symbol", "date", "provider_a", "provider_b", "field", "absolute_difference", "percentage_difference"],
            "coverage": ["symbol", "source", "requested_start", "requested_end", "returned_start", "returned_end", "status"],
            "universe_issues": ["source", "error"],
        }
        with self.lock:
            for kind, cols in defaults.items():
                rows = [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM reports WHERE kind=?", (kind,))]
                atomic_parquet(pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols),
                               self.root / "reports" / f"{kind}.parquet")
            jobs = pd.read_sql_query("SELECT * FROM jobs", self.db)
            atomic_parquet(jobs, self.root / "reports" / "progress.parquet")

    def symbol_path(self, symbol):
        return self.root / "processed" / "hose_ohlcv" / f"symbol={symbol}" / "part.parquet"

    def load(self, symbol):
        path = self.symbol_path(symbol)
        if not path.exists():
            return pd.DataFrame(columns=CANONICAL)
        df = pq.ParquetFile(path).read().to_pandas()
        df["symbol"] = symbol
        return df

    def save(self, symbol, df):
        atomic_parquet(df.drop(columns="symbol"), self.symbol_path(symbol), canonical=True)

    def save_provider(self, symbol, provider, snapshot, df):
        path = self.root / "raw" / provider / "normalized" / snapshot / f"{symbol}.parquet"
        atomic_parquet(df, path)

    def summary(self, universe, selected, run_id):
        root = self.root / "processed" / "hose_ohlcv"
        stats = []
        for p in sorted(root.glob("symbol=*/part.parquet")):
            df = pq.ParquetFile(p).read(columns=["date", "close"]).to_pandas()
            if not df.empty:
                stats.append({"symbol": p.parent.name.split("=", 1)[1], "rows": len(df),
                              "raw_rows": int(df.close.notna().sum()), "start": str(min(df.date)), "end": str(max(df.date))})
        with self.lock:
            jobs = list(self.db.execute("SELECT symbol,status FROM jobs WHERE job_key LIKE ?", (run_id + ":%",)))
        return {"run_id": run_id, "current_hose_stocks": int((universe.status == "current").sum()),
                "historical_or_delisted_discovered": int((universe.status != "current").sum()),
                "selected_symbols": len(selected), "successful_symbols": sum(s == "DONE" for _, s in jobs),
                "partial_symbols": sum(s == "PARTIAL" for _, s in jobs),
                "failed_symbols": [s for s, state in jobs if state == "FAILED"],
                "earliest_market_date": min((s["start"] for s in stats), default=None),
                "latest_market_date": max((s["end"] for s in stats), default=None),
                "symbols_with_stored_rows": len(stats), "stored_rows": sum(s["rows"] for s in stats),
                "stored_raw_price_rows": sum(s["raw_rows"] for s in stats),
                "historical_universe_complete": False, "per_symbol": stats}
