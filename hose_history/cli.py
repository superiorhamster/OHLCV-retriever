import argparse
from dataclasses import fields
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import signal
import sqlite3

from .collector import Collector
from .config import CollectorConfig
from .schema import parse_date
from .storage import Store
from .transport import Transport
from .universe import discover_universe


def main(argv=None):
    p = argparse.ArgumentParser(description="Auditable, free-source HOSE historical market data")
    p.add_argument("--mode", choices=["full", "update"], default="full")
    p.add_argument("--symbol", help="One symbol or a comma-separated controlled sample")
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--data-dir", type=Path, default=None)
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--providers", help="Priority order, default kbs,vci; VND is unverified opt-in")
    p.add_argument("--config", type=Path, help="JSON CollectorConfig settings")
    p.add_argument("--limit", type=int, help="Restrict to first N discovered symbols")
    p.add_argument("--refresh", action="store_true", help="Fresh response snapshot, ignoring previous completed jobs")
    p.add_argument("--refresh-universe", action="store_true")
    p.add_argument("--universe-evidence", type=Path, help="Additional sourced historical membership CSV/Parquet")
    p.add_argument("--universe-only", action="store_true")
    p.add_argument("--status", action="store_true", help="Read stored progress without network access")
    p.add_argument("--serve", action="store_true", help="Launch web UI and REST API server")
    p.add_argument("--port", type=int, default=8000, help="Web server port (default: 8000)")
    p.add_argument("--host", default="127.0.0.1", help="Web server host (default: 127.0.0.1)")
    args = p.parse_args(argv)
    if args.serve:
        import uvicorn
        from .server import app, run_manager
        run_manager.data_dir = Path(args.data_dir or "data")
        print(f"Starting HOSE OHLCV Retriever Web Server at http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)
        return
    values = json.loads(args.config.read_text()) if args.config else {}
    unknown = set(values) - {f.name for f in fields(CollectorConfig)}
    if unknown:
        p.error(f"Unknown configuration keys: {sorted(unknown)}")
    for arg, key in [(args.start, "start_date"), (args.end, "end_date"), (args.data_dir, "data_dir"), (args.workers, "max_workers")]:
        if arg is not None:
            values[key] = arg
    values["data_dir"] = Path(values.get("data_dir", "data"))
    if args.providers:
        values["providers"] = tuple(args.providers.split(","))
    elif "providers" in values:
        values["providers"] = tuple(values["providers"])
    config = CollectorConfig(**values)
    if args.status:
        db_path = config.data_dir / "metadata" / "progress.sqlite"
        if not db_path.exists():
            print(json.dumps({"status":"not_started", "data_dir":str(config.data_dir)}))
            return
        db = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
        try:
            latest = db.execute("SELECT job_key FROM jobs ORDER BY updated_at DESC LIMIT 1").fetchone()
            prefix = latest[0].rsplit(":", 1)[0] if latest else ""
            counts = dict(db.execute("SELECT status, COUNT(*) FROM jobs WHERE job_key LIKE ? GROUP BY status", (prefix + ":%",)))
            active = [r[0] for r in db.execute("SELECT symbol FROM jobs WHERE job_key LIKE ? AND status='RUNNING'", (prefix + ":%",))]
            print(json.dumps({"run_id":prefix, "counts":counts, "active_symbols":active}, indent=2))
        finally:
            db.close()
        return
    # Preserve the end date of an interrupted full run across calendar-day changes.
    manifest_path = config.data_dir / "reports" / "run_config.json"
    if args.mode == "full" and not args.refresh and args.end is None and values.get("end_date") is None and manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        db_path = config.data_dir / "metadata" / "progress.sqlite"
        if "-full-" in previous.get("run_id", "") and db_path.exists():
            with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as db:
                unfinished = db.execute("SELECT COUNT(*) FROM jobs WHERE job_key LIKE ? AND status IN ('PENDING','RUNNING')", (previous["run_id"] + ":%",)).fetchone()[0]
            if unfinished:
                values["end_date"] = previous["end_date"]
                config = CollectorConfig(**values)
    if parse_date(config.start_date) > parse_date(config.end):
        p.error("--start must not exceed --end")
    if args.limit is not None and args.limit <= 0:
        p.error("--limit must be positive")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(config.data_dir / "collector.log")])
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    snapshot = config.end if not args.refresh else datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    store, transport = Store(config.data_dir), Transport(config, snapshot)
    def stop(signum, _frame):
        logging.warning("Signal %s: stopping after active requests; resume by rerunning this command", signum)
        transport.stop_event.set()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    # Prevent concurrent CLI writers to the same dataset while allowing worker threads.
    import fcntl
    lock = (config.data_dir / "metadata" / "collector.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        p.error("Another collector is writing this data directory")
    try:
        universe = discover_universe(transport, config, store, refresh=args.refresh_universe, evidence_file=args.universe_evidence)
        if args.universe_only:
            store.export_reports()
            print(json.dumps({"symbols": len(universe), "current": int((universe.status == "current").sum()),
                              "historical": int((universe.status != "current").sum())}, indent=2))
            return
        if args.symbol:
            symbols = list(dict.fromkeys(s.strip().upper() for s in args.symbol.split(",")))
            if any(not re.fullmatch(r"[A-Z][A-Z0-9]{1,9}", s) for s in symbols):
                p.error("Invalid stock symbol")
            unknown = set(symbols) - set(universe.symbol)
            if unknown:
                logging.warning("Explicit symbols lack discovered HOSE evidence: %s; collecting without asserting membership", sorted(unknown))
        else:
            symbols = sorted(set(universe.symbol))
        if args.limit:
            symbols = symbols[:args.limit]
        summary = Collector(config, transport, store).run(symbols, universe, mode=args.mode, refresh=args.refresh)
        print(json.dumps({k: v for k, v in summary.items() if k != "per_symbol"}, indent=2))
    finally:
        store.export_reports()
        store.close()
        transport.close()
        lock.close()


if __name__ == "__main__":
    main()
