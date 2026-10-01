from datetime import date
from unittest.mock import Mock

import httpx
import pandas as pd

from hose_history.collector import Collector, build_panel
from hose_history.config import CollectorConfig
from hose_history.providers import HistoryResult
from hose_history.schema import frame
from hose_history.storage import Store
from hose_history.storage import atomic_parquet
from hose_history.transport import Transport


def daily(day, close=10):
    return frame([{"date": day, "symbol":"REE", "source":"fixture", "open":10., "high":12.,
        "low":9., "close":float(close), "volume":100, "price_basis":"raw", "volume_basis":"matched_shares"}])


def test_update_requests_only_new_dates_and_preserves_old(tmp_path):
    cfg = CollectorConfig(data_dir=tmp_path, start_date="2020-01-01", end_date="2020-01-04")
    store = Store(tmp_path)
    old = build_panel({"fixture":daily(date(2020,1,2))}, "REE", "prior", [])
    store.save("REE", old)
    c = Collector(cfg, Mock(snapshot="now"), store)
    provider = Mock()
    provider.get_history.return_value = HistoryResult(daily(date(2020,1,3)))
    c.providers = {"fixture":provider}
    c.collect_symbol("REE", "update", "run")
    provider.get_history.assert_called_once_with("REE", "2020-01-03", "2020-01-04")
    assert len(store.load("REE")) == 2
    assert store.done("run:REE")
    # Same request resumes without issuing another network operation.
    c.collect_symbol("REE", "update", "run")
    assert provider.get_history.call_count == 1
    store.close()


def test_empty_weekend_update_is_not_failed(tmp_path):
    cfg = CollectorConfig(data_dir=tmp_path, end_date="2020-01-05")
    store = Store(tmp_path)
    store.save("REE", build_panel({"fixture": daily(date(2020,1,3))}, "REE", "old", []))
    c = Collector(cfg, Mock(snapshot="now"), store)
    provider = Mock()
    provider.get_history.return_value = HistoryResult(frame([]))
    c.providers = {"fixture":provider}
    c.collect_symbol("REE", "update", "weekend")
    assert store.done("weekend:REE") and len(store.load("REE")) == 1
    store.close()


def test_atomic_save_failure_does_not_mark_done(tmp_path, monkeypatch):
    cfg = CollectorConfig(data_dir=tmp_path, end_date="2020-01-05")
    store = Store(tmp_path)
    c = Collector(cfg, Mock(snapshot="now"), store)
    provider = Mock()
    provider.get_history.return_value = HistoryResult(daily(date(2020,1,3)))
    c.providers = {"fixture":provider}
    monkeypatch.setattr(store, "save", Mock(side_effect=OSError("disk full")))
    c.collect_symbol("REE", "full", "crash")
    assert not store.done("crash:REE")
    assert not store.symbol_path("REE").exists()
    store.close()


def test_unavailable_provider_does_not_force_daily_raw_redownload(tmp_path):
    cfg = CollectorConfig(data_dir=tmp_path, end_date="2020-01-04")
    store = Store(tmp_path)
    store.save("REE", build_panel({"fixture": daily(date(2020,1,3))}, "REE", "old", []))
    store.record_intervals([], [{"symbol":"REE", "source":"vci", "requested_start":"2000-07-28",
                                "requested_end":"2020-01-03", "error":"403"}])
    c = Collector(cfg, Mock(snapshot="now"), store)
    vci, fixture = Mock(), Mock()
    vci.get_history.return_value = HistoryResult(frame([]), errors=[{"symbol":"REE", "source":"vci", "error":"403"}])
    fixture.get_history.return_value = HistoryResult(frame([]))
    c.providers = {"vci":vci, "fixture":fixture}
    c.collect_symbol("REE", "update", "isolated")
    vci.get_history.assert_called_once_with("REE", "2000-07-28", "2020-01-04")
    fixture.get_history.assert_called_once_with("REE", "2020-01-04", "2020-01-04")
    store.close()


def test_failed_interval_is_cleared_after_success(tmp_path):
    store = Store(tmp_path)
    error = {"symbol":"REE", "source":"fixture", "requested_start":"2020-01-01", "requested_end":"2020-01-10", "error":"500"}
    store.record_intervals([], [error])
    assert store.unresolved_start("REE") == "2020-01-01"
    store.record_intervals([{**error, "status":"observed"}], [])
    assert store.unresolved_start("REE") is None
    store.close()


def test_observed_dates_do_not_become_listing_dates(tmp_path):
    store = Store(tmp_path)
    atomic_parquet(pd.DataFrame([{"symbol":"REE", "listing_date":None}]), tmp_path / "metadata" / "symbols.parquet")
    c = Collector(CollectorConfig(data_dir=tmp_path), Mock(snapshot="s"), store)
    c._record_observed_dates("REE", daily(date(2000,7,28)))
    meta = pd.read_parquet(tmp_path / "metadata" / "symbols.parquet").iloc[0]
    assert meta.earliest_observed_date == "2000-07-28" and pd.isna(meta.listing_date)
    store.close()


def test_retry_transient_failure_and_cache_survives_new_transport(tmp_path):
    attempts = []
    def handler(req):
        attempts.append(req)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After":"0"})
        return httpx.Response(200, json={"ok":True})
    cfg = CollectorConfig(data_dir=tmp_path, request_delay=0, backoff_base=0, backoff_cap=0)
    t = Transport(cfg, "s", httpx.Client(transport=httpx.MockTransport(handler)))
    assert t.request("kbs", "GET", "https://example.test") == {"ok":True}
    assert len(attempts) == 2
    t.close()
    def no_network(req):
        raise AssertionError("Should reuse cached response")
    t = Transport(cfg, "s", httpx.Client(transport=httpx.MockTransport(no_network)))
    assert t.request("kbs", "GET", "https://example.test") == {"ok":True}
    t.close()
