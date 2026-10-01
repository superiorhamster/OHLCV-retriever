from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import itertools
import json
import logging
import math

import pandas as pd

from .providers import PROVIDERS, HistoryResult
from .schema import PRICE, ADJUSTED, deduplicate, frame, merge_incremental, parse_date, validation_issues
from .storage import atomic_parquet
from .transport import atomic_json, CollectionInterrupted

log = logging.getLogger(__name__)


def compare_providers(frames, symbol, config):
    discrepancies = []
    for (pa, a), (pb, b) in itertools.combinations(frames.items(), 2):
        if a.empty or b.empty:
            continue
        a, b = deduplicate(a).set_index("date"), deduplicate(b).set_index("date")
        for day in a.index.intersection(b.index):
            ra, rb = a.loc[day], b.loc[day]
            pairs = [(f, f, f) for f in ("close", "adjusted_close", "provider_close", "volume")]
            # Chart-vs-explicit adjusted close is diagnostic only, with both bases recorded.
            if pd.notna(ra.get("provider_close")) and pd.notna(rb.get("adjusted_close")):
                pairs.append(("close", "provider_close", "adjusted_close"))
            if pd.notna(ra.get("adjusted_close")) and pd.notna(rb.get("provider_close")):
                pairs.append(("close", "adjusted_close", "provider_close"))
            for field, field_a, field_b in pairs:
                va, vb = ra.get(field_a), rb.get(field_b)
                if pd.isna(va) or pd.isna(vb) or va == vb:
                    continue
                if not math.isfinite(float(va)) or not math.isfinite(float(vb)):
                    continue  # Validation records these values; percentages would be meaningless.
                diff = abs(float(va) - float(vb))
                pct = 100 * diff / abs(float(va)) if va != 0 else None
                comparable = (field_a == field_b == "close") or (field == "volume" and ra.get("volume_basis") == rb.get("volume_basis") == "matched_shares")
                threshold = config.volume_diff_pct if field == "volume" else config.close_diff_pct
                discrepancies.append({"symbol": symbol, "date": str(day), "provider_a": pa,
                    "provider_b": pb, "field": field, "value_a": float(va), "value_b": float(vb),
                    "field_a": field_a, "field_b": field_b,
                    "absolute_difference": diff, "percentage_difference": pct,
                    "percentage_denominator": pa, "material": pct is None or pct > threshold,
                    "comparable": comparable, "reason": "same_verified_basis" if comparable else "basis_not_verified"})
    return discrepancies


def build_panel(frames, symbol, snapshot, issues):
    available = [df for df in frames.values() if not df.empty]
    if not available:
        return frame([])
    all_rows = pd.concat(available, ignore_index=True)
    # Stable priority comes from frames insertion order. Raw OHLC are selected as a group.
    priority = {p: n for n, p in enumerate(frames)}
    all_rows["priority"] = all_rows.source.map(priority)
    all_rows = all_rows.sort_values("priority", kind="stable")
    result = []
    flags = {}
    for issue in issues:
        flags.setdefault(issue.get("date"), set()).add(issue["code"])
    for day, candidates in all_rows.groupby("date", sort=True):
        selected = candidates.iloc[0]
        raw = candidates[candidates[PRICE].notna().all(axis=1)]
        if not raw.empty:
            selected = raw.iloc[0]
        record = selected.drop(labels=["priority"]).to_dict()
        record["source"] = selected.source
        record["raw_source"] = selected.source if not raw.empty else None
        record["volume_source"] = selected.source if pd.notna(selected.volume) else None
        # Only explicit adjusted series qualify; never construct adjustment factors.
        adjusted = candidates[candidates.adjusted_close.notna()]
        for col in ADJUSTED:
            record[col] = None
        record["adjusted_source"] = None
        if not adjusted.empty:
            ar = adjusted.iloc[0]
            for col in ADJUSTED:
                record[col] = ar[col]
            record["adjusted_source"] = ar.source
        day_flags = flags.get(str(day), set()).copy()
        if raw.empty:
            day_flags.add("raw_prices_unavailable")
        record.update({"symbol": symbol, "security_id": "unresolved:" + symbol,
            "adjustment_as_of": snapshot, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "quality_flags": ";".join(sorted(day_flags))})
        # Unknown chart values live in provider archives, not canonical price columns.
        for col in ["provider_" + p for p in PRICE]:
            record.pop(col, None)
        result.append(record)
    panel = frame(result).drop(columns=["provider_" + p for p in PRICE])
    for col in ["volume", "foreign_buy_volume", "foreign_sell_volume", "proprietary_buy_volume", "proprietary_sell_volume"]:
        invalid = panel[col].notna() & ((panel[col] % 1 != 0) | (panel[col] < 0))
        # Invalid share counts cannot satisfy the integer schema; raw payload plus issue retains evidence.
        panel.loc[invalid, col] = pd.NA
        panel[col] = panel[col].astype("Int64")
    return deduplicate(panel)


def incremental_start(old, requested_start):
    if old.empty:
        return parse_date(requested_start)
    return max(parse_date(requested_start), max(old.date) + timedelta(days=1))


class Collector:
    def __init__(self, config, transport, store):
        self.config, self.transport, self.store = config, transport, store
        self.providers = {name: PROVIDERS[name](transport, config) for name in config.providers}

    def _collect(self, symbol, start, end, provider_starts=None):
        frames, errors, issues, coverage = {}, [], [], []
        for name, provider in self.providers.items():
            provider_start = (provider_starts or {}).get(name, start)
            if provider_start > end:
                continue
            if frames:
                log.info("%s fallback/overlap -> %s (coverage, field availability and validation)", symbol, name)
            try:
                result = provider.get_history(symbol, str(provider_start), str(end))
            except CollectionInterrupted:
                raise
            except Exception as exc:
                log.exception("%s %s provider failure; trying remaining providers", symbol, name)
                result = HistoryResult(frame([]), errors=[{"symbol": symbol, "source": name,
                    "requested_start": str(provider_start), "requested_end": str(end), "error": str(exc)}])
            df = result.data
            issues.extend(result.issues)
            issues.extend(validation_issues(df, symbol, name, value_price_tolerance=self.config.value_price_tolerance))
            errors.extend(result.errors)
            coverage.extend(result.coverage)
            if not df.empty:
                self.store.save_provider(symbol, name, self.transport.snapshot, df)
                frames[name] = deduplicate(df)
        # A late start is evidence of possible truncation, not proof of missing sessions.
        if frames:
            earliest = min(min(df.date) for df in frames.values())
            for name, df in frames.items():
                if min(df.date) > earliest:
                    issues.append({"symbol": symbol, "source": name, "date": str(min(df.date)),
                        "code": "possible_truncation", "detail": f"Another source begins {earliest}; this source begins {min(df.date)}"})
            # Record observed session omissions only where another source has an observation.
            dates = set().union(*(set(df.date) for df in frames.values()))
            for name, df in frames.items():
                missing = sorted(dates - set(df.date))
                if missing:
                    coverage.append({"symbol": symbol, "source": name, "status": "sessions_observed_elsewhere",
                        "requested_start": str(start), "requested_end": str(end), "records": len(missing),
                        "missing_dates": ",".join(map(str, missing))})
        discrepancies = compare_providers(frames, symbol, self.config)
        panel = build_panel(frames, symbol, self.transport.snapshot, issues)
        self.store.report("validation_issues", issues)
        self.store.report("provider_discrepancies", discrepancies)
        self.store.report("coverage", coverage)
        self.store.report("failed_symbols", errors)
        self.store.record_intervals(coverage, errors)
        return panel, errors, issues

    def _audit(self, symbol, old, end):
        """Small overlap plus annual sentinel windows; refresh on explicit adjusted-price revisions."""
        if old.empty or "adjusted_source" not in old:
            return False
        revised = False
        for name, provider in self.providers.items():
            historic = old[(old.adjusted_source == name) & old.adjusted_close.notna()]
            if historic.empty:
                continue
            sentinels = historic.sort_values("date").groupby(historic.date.map(lambda d: d.year)).head(1)
            windows = [(d, d) for d in sentinels.date]
            windows.append((max(min(old.date), max(old.date) - timedelta(days=self.config.audit_days)), min(end, max(old.date))))
            for a, b in windows:
                result = provider.get_history(symbol, str(a), str(b))
                if result.errors:
                    self.store.report("failed_symbols", result.errors)
                    self.store.report("validation_issues", [{"symbol": symbol, "source": name, "date": str(a),
                        "code": "revision_audit_failed", "detail": "Historical adjusted consistency unverified"}])
                    continue
                if result.data.empty:
                    continue
                joined = historic.merge(deduplicate(result.data), on="date", suffixes=("_old", "_new"))
                mismatch = joined.adjusted_close_new.notna() & (joined.adjusted_close_old != joined.adjusted_close_new)
                if mismatch.any():
                    revised = True
                    self.store.report("validation_issues", [{"symbol": symbol, "source": name, "date": str(a),
                        "code": "adjustment_revision", "detail": "Explicit adjusted close changed; refreshing symbol history atomically"}])
                    break
        return revised

    def collect_symbol(self, symbol, mode, run_id, refresh=False):
        key = run_id + ":" + symbol
        if not refresh and self.store.done(key) and self.store.symbol_path(symbol).exists():
            log.info("%s DONE (resumed)", symbol)
            return
        self.store.checkpoint(key, symbol, "RUNNING")
        try:
            self._profile(symbol)
            old = self.store.load(symbol)
            start, end = parse_date(self.config.start_date), parse_date(self.config.end)
            revision = False
            provider_starts = {}
            if mode == "update" and not old.empty:
                revision = self._audit(symbol, old, end)
                if revision:
                    start = min(start, min(old.date))
                else:
                    start = incremental_start(old, self.config.start_date)
                    # Retry the earliest unresolved failed request for this symbol as well.
                    for name in self.providers:
                        failed_start = self.store.unresolved_start(symbol, name)
                        if failed_start:
                            provider_starts[name] = min(start, parse_date(failed_start))
            if start > end and not provider_starts:
                self.store.checkpoint(key, symbol, "DONE", "No newer dates requested")
                return
            new, errors, issues = self._collect(symbol, start, end, provider_starts)
            if new.empty:
                if mode == "update" and not old.empty:
                    self.store.checkpoint(key, symbol, "PARTIAL" if errors else "DONE", "No new observations; prior data retained; see provider coverage")
                    return
                self.store.report("failed_symbols", [{"symbol": symbol, "source": "all", "requested_start": str(start),
                    "requested_end": str(end), "error": "No observations recovered; empty responses do not prove unsupported symbol"}])
                self.store.checkpoint(key, symbol, "FAILED", "No observations recovered")
                return
            if revision:
                # Do not publish a partially refreshed adjustment series.
                if errors:
                    self.store.checkpoint(key, symbol, "PARTIAL", "Refresh failed; prior panel retained")
                    return
                merged = merge_incremental(old[~old.date.between(start, end)], new)
            else:
                merged = merge_incremental(old, new)
            self.store.save(symbol, merged)
            self._record_observed_dates(symbol, merged)
            state = "PARTIAL" if errors or new.close.isna().any() or any(x["code"] == "quarantined_parse_error" for x in issues) else "DONE"
            self.store.checkpoint(key, symbol, state, f"{len(merged)} stored rows; {len(errors)} provider failures")
            log.info("%s %s: %d stored rows", symbol, state, len(merged))
        except CollectionInterrupted:
            self.store.checkpoint(key, symbol, "PENDING", "Interrupted; responses cached for resume")
            log.info("%s PENDING (interrupted)", symbol)
        except Exception as exc:
            log.exception("%s collection failed", symbol)
            self.store.report("failed_symbols", [{"symbol": symbol, "source": "collector", "error": str(exc)}])
            self.store.checkpoint(key, symbol, "FAILED", str(exc))

    def _record_observed_dates(self, symbol, panel):
        path = self.config.data_dir / "metadata" / "symbols.parquet"
        if panel.empty or not path.exists():
            return
        with self.store.lock:
            symbols = pd.read_parquet(path)
            mask = symbols.symbol == symbol
            symbols.loc[mask, "earliest_observed_date"] = str(min(panel.date))
            symbols.loc[mask, "latest_observed_date"] = str(max(panel.date))
            atomic_parquet(symbols, path)

    def _profile(self, symbol):
        provider = self.providers.get("kbs")
        if provider is None or not hasattr(provider, "profile"):
            return
        try:
            obj = provider.profile(symbol)
            if not isinstance(obj, dict) or not obj.get("LD"):
                return
            observed = str(parse_date(obj["LD"]))
            path = self.config.data_dir / "metadata" / "symbols.parquet"
            if not path.exists():
                return
            with self.store.lock:
                symbols = pd.read_parquet(path)
                mask = (symbols.symbol == symbol) & symbols.listing_date.isna()
                symbols.loc[mask, "listing_date"] = observed
                symbols.loc[mask, "listing_date_source"] = "kbs_profile_current_exchange_unverified"
                atomic_parquet(symbols, path)
                # Do not turn a current-exchange profile date into an original listing boundary.
            self.store.report("coverage", [{"symbol": symbol, "source": "kbs_profile", "status": "listing_date_observation",
                "listing_date": observed, "exchange": obj.get("EX"),
                "detail": "Not used to truncate cross-exchange history; original listing identity unverified"}])
        except Exception as exc:
            self.store.report("universe_issues", [{"symbol": symbol, "source": "kbs_profile", "error": str(exc)}])

    def run(self, symbols, universe, *, mode="full", refresh=False):
        settings = asdict(self.config)
        settings["end_date"] = self.config.end
        settings.pop("data_dir")
        digest = hashlib.sha256(json.dumps({"settings": settings, "mode": mode}, sort_keys=True, default=str).encode()).hexdigest()[:16]
        run_id = f"{self.config.end}-{mode}-{digest}"
        if refresh:
            run_id += "-" + self.transport.snapshot
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(self.config.data_dir / "reports" / "run_config.json", {"run_id": run_id, **settings})
        for symbol in symbols:
            key = run_id + ":" + symbol
            if not self.store.done(key):
                self.store.checkpoint(key, symbol, "PENDING")
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
            # Bound queued work, allowing useful progress snapshots during long backfills.
            pending = {}
            iterator = iter(symbols)
            for _ in range(min(self.config.max_pending, len(symbols))):
                symbol = next(iterator)
                pending[pool.submit(self.collect_symbol, symbol, mode, run_id, refresh)] = symbol
            while pending:
                future = next(as_completed(pending))
                future.result()
                del pending[future]
                self.store.export_reports()
                atomic_json(self.config.data_dir / "reports" / "summary.json", self.store.summary(universe, symbols, run_id))
                symbol = None if self.transport.stop_event.is_set() else next(iterator, None)
                if symbol:
                    pending[pool.submit(self.collect_symbol, symbol, mode, run_id, refresh)] = symbol
        self.store.export_reports()
        summary = self.store.summary(universe, symbols, run_id)
        summary["interrupted"] = self.transport.stop_event.is_set()
        atomic_json(self.config.data_dir / "reports" / "summary.json", summary)
        return summary
