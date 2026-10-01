from datetime import date
from unittest.mock import Mock

import httpx
import pandas as pd
import pytest

from hose_history.collector import Collector, build_panel, compare_providers
from hose_history.config import CollectorConfig
from hose_history.providers import HistoryResult
from hose_history.schema import frame
from hose_history.storage import Store
from hose_history.transport import AccessDenied, Transport
from hose_history.universe import extract_delistings


def sample(close=10):
    return frame([{"date": date(2020,1,2), "symbol": "REE", "source": "fixture", "open": 10., "high": 12.,
                   "low": 9., "close": close, "volume": 100, "volume_basis": "matched_shares",
                   "price_basis": "raw_with_provider_adjusted_close", "adjusted_close": 5.}])


def test_partition_readable_with_pandas_and_checkpoint(tmp_path):
    s = Store(tmp_path)
    panel = build_panel({"fixture": sample()}, "REE", "snapshot", [])
    s.save("REE", panel)
    loaded = pd.read_parquet(tmp_path / "processed" / "hose_ohlcv")
    assert loaded.iloc[0].symbol == "REE" and loaded.iloc[0].close == 10
    # Simulate an in-progress atomic replacement. A dataset reader must ignore it.
    (store_path := s.symbol_path("REE").parent / ".pending-interrupted.tmp").write_bytes(b"unfinished")
    assert len(pd.read_parquet(tmp_path / "processed" / "hose_ohlcv")) == 1
    another = panel.copy()
    another["symbol"] = "FPT"
    another["raw_source"] = None
    another["close"] = pd.NA
    s.save("FPT", another)
    assert len(pd.read_parquet(tmp_path / "processed" / "hose_ohlcv")) == 2
    s.checkpoint("run:REE", "REE", "DONE")
    assert s.done("run:REE")
    s.export_reports()
    assert (tmp_path / "reports" / "provider_discrepancies.parquet").exists()
    s.close()


def test_fallback_recovers_after_provider_failure(tmp_path):
    cfg = CollectorConfig(data_dir=tmp_path)
    store = Store(tmp_path)
    c = Collector(cfg, Mock(snapshot="snapshot"), store)
    a, b = Mock(), Mock()
    a.get_history.return_value = HistoryResult(frame([]), errors=[{"symbol":"REE", "source":"kbs", "error":"HTTP 500"}])
    b.get_history.return_value = HistoryResult(sample())
    c.providers = {"kbs": a, "fixture": b}
    panel, errors, issues = c._collect("REE", date(2020,1,1), date(2020,1,3))
    assert panel.iloc[0].close == 10 and len(errors) == 1
    assert b.get_history.called
    store.close()


def test_unexpected_provider_failure_still_runs_fallback(tmp_path):
    store = Store(tmp_path)
    c = Collector(CollectorConfig(data_dir=tmp_path), Mock(snapshot="snapshot"), store)
    broken, good = Mock(), Mock()
    broken.get_history.side_effect = ValueError("malformed vendor data")
    good.get_history.return_value = HistoryResult(sample())
    c.providers = {"kbs": broken, "fixture": good}
    panel, errors, _ = c._collect("REE", date(2020,1,1), date(2020,1,3))
    assert len(panel) == 1 and errors[0]["source"] == "kbs"
    store.close()


def test_comparisons_zero_denominator_and_basis(tmp_path):
    a, b = sample(0), sample(10)
    out = compare_providers({"a": a, "b": b}, "REE", CollectorConfig())
    price = next(r for r in out if r["field"] == "close")
    assert price["percentage_difference"] is None and price["comparable"]


def test_transport_resume_and_403_circuit(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": []})
    cfg = CollectorConfig(data_dir=tmp_path, request_delay=0)
    t = Transport(cfg, "snapshot", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert t.request("kbs", "GET", "https://example.test/history") == {"data": []}
    assert t.request("kbs", "GET", "https://example.test/history") == {"data": []}
    assert len(calls) == 1
    t.close()
    denied = Transport(cfg, "other", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))))
    with pytest.raises(AccessDenied):
        denied.request("kbs", "GET", "https://example.test/history")
    with pytest.raises(AccessDenied, match="earlier"):
        denied.request("kbs", "GET", "https://example.test/history")
    denied.close()


def test_official_delisting_section_does_not_ingest_new_listings():
    text = "DANH SÁCH HỦY NIÊM YẾT NĂM 2023\n1 FLC Công ty Cổ phần Tập đoàn FLC 20/2/2023 709.997.807\nDANH SÁCH NIÊM YẾT MỚI NĂM 2023\n1 SIP Company 8/8/2023 100\n"
    out = extract_delistings(text, 2023, "https://hsx.vn/report.pdf", 47)
    assert len(out) == 1 and out[0]["symbol"] == "FLC"
    assert out[0]["delisting_date"] == "2023-02-20"


def test_revision_triggers_from_adjusted_close_only(tmp_path):
    cfg = CollectorConfig(data_dir=tmp_path)
    store = Store(tmp_path)
    c = Collector(cfg, Mock(snapshot="s"), store)
    old = build_panel({"fixture": sample()}, "REE", "s", [])
    revised = sample()
    revised["adjusted_close"] = 4.
    provider = Mock()
    provider.get_history.return_value = HistoryResult(revised)
    c.providers = {"fixture": provider}
    assert c._audit("REE", old, date(2020,1,3))
    store.close()
