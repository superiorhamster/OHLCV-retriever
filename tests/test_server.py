from datetime import date
from pathlib import Path
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from hose_history.server import app, run_manager
from hose_history.storage import Store, atomic_parquet


@pytest.fixture
def test_client(tmp_path):
    # Set up mock data directory
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    run_manager.data_dir = data_dir

    # Create dummy symbols.parquet
    meta_dir = data_dir / "metadata"
    meta_dir.mkdir(parents=True)
    universe_df = pd.DataFrame([
        {"symbol": "FPT", "company_name": "FPT Corp", "status": "current", "listing_date": "2006-12-13", "delisting_date": None},
        {"symbol": "REE", "company_name": "REE Corp", "status": "current", "listing_date": "2000-07-28", "delisting_date": None},
        {"symbol": "FLC", "company_name": "FLC Group", "status": "historical", "listing_date": "2013-08-05", "delisting_date": "2023-02-20"},
    ])
    atomic_parquet(universe_df, meta_dir / "symbols.parquet")

    # Create sample processed data for FPT
    fpt_df = pd.DataFrame({
        "symbol": ["FPT"] * 4,
        "date": [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)],
        "provider_open": [60000.0, 61000.0, 62000.0, 63000.0],
        "provider_high": [61500.0, 62500.0, 63500.0, 64000.0],
        "provider_low": [59500.0, 60500.0, 61500.0, 62500.0],
        "provider_close": [61000.0, 62000.0, 63000.0, 63500.0],
        "volume": [1000000, 1200000, 1100000, 1500000],
        "open": [None, None, None, None],
        "high": [None, None, None, None],
        "low": [None, None, None, None],
        "close": [None, None, None, None],
        "quality_flags": ["raw_prices_unavailable"] * 4,
        "source": ["kbs"] * 4
    })
    store = Store(data_dir)
    store.save("FPT", fpt_df)
    store.close()

    client = TestClient(app)
    return client


def test_get_universe(test_client):
    res = test_client.get("/api/universe")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert data["current"] == 2
    assert data["historical"] == 1
    assert data["with_data"] == 1
    symbols = {s["symbol"]: s for s in data["symbols"]}
    assert "FPT" in symbols
    assert symbols["FPT"]["has_data"] is True
    assert symbols["FPT"]["row_count"] == 4
    assert symbols["REE"]["has_data"] is False


def test_preview_symbol_head_and_tail(test_client):
    # Preview head
    res_head = test_client.get("/api/preview/FPT?slice=head&limit=2")
    assert res_head.status_code == 200
    data_head = res_head.json()
    assert data_head["has_data"] is True
    assert data_head["symbol"] == "FPT"
    assert data_head["total_rows"] == 4
    assert len(data_head["rows"]) == 2
    assert data_head["slice"] == "head"
    assert "provider_close" in data_head["columns"]

    # Preview tail
    res_tail = test_client.get("/api/preview/FPT?slice=tail&limit=2")
    assert res_tail.status_code == 200
    data_tail = res_tail.json()
    assert len(data_tail["rows"]) == 2
    assert data_tail["slice"] == "tail"

    # Preview non-existent symbol
    res_none = test_client.get("/api/preview/UNKNOWN")
    assert res_none.status_code == 200
    assert res_none.json()["has_data"] is False


def test_chart_data(test_client):
    res = test_client.get("/api/chart/FPT")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "FPT"
    assert len(data["candles"]) == 4
    assert len(data["volumes"]) == 4
    first_candle = data["candles"][0]
    assert first_candle["time"] == "2024-01-02"
    assert first_candle["close"] == 61000.0


def test_export_csv(test_client):
    res = test_client.get("/api/export/FPT")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "attachment; filename=FPT_ohlcv.csv" in res.headers["content-disposition"]
    lines = res.text.strip().split("\n")
    assert len(lines) == 5  # header + 4 rows


def test_retriever_status_and_stop(test_client):
    res = test_client.get("/api/retriever/status")
    assert res.status_code == 200
    data = res.json()
    assert "is_running" in data
    assert "counts" in data
    assert "logs" in data

    res_stop = test_client.post("/api/retriever/stop")
    assert res_stop.status_code == 200
    assert res_stop.json()["status"] == "idle"
