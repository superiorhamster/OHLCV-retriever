from datetime import date

import pandas as pd
import pytest

from hose_history.schema import chunks, deduplicate, frame, merge_incremental, parse_date, validation_issues
from hose_history.collector import build_panel, incremental_start


@pytest.mark.parametrize("value,expected", [("28/07/2000", date(2000, 7, 28)), ("2000-07-28 07:00", date(2000, 7, 28)), ("2000-07-28", date(2000, 7, 28))])
def test_dates(value, expected):
    assert parse_date(value) == expected


def test_epoch_and_invalid_date():
    assert parse_date("964742400", epoch=True) == date(2000, 7, 28)
    with pytest.raises(ValueError):
        parse_date("01-02-03")


def test_chunk_coverage_leap_and_endpoints():
    windows = list(chunks("2020-02-29", "2026-03-01", years=3))
    assert windows[0][0] == date(2020, 2, 29)
    assert windows[-1][1] == date(2026, 3, 1)
    for left, right in zip(windows, windows[1:]):
        assert (right[0] - left[1]).days == 1
    assert sum((b-a).days+1 for a,b in windows) == (date(2026,3,1)-date(2020,2,29)).days+1
    assert len(list(chunks("2000-07-28", "2000-07-28", days=90))) == 1


def row(day="2000-07-28", **kw):
    return {"date": parse_date(day), "symbol": "REE", "source": "fixture", "open": 16., "high": 17.,
            "low": 15., "close": 16., "volume": 1000, "price_basis": "raw", "volume_basis": "matched_shares", **kw}


def test_duplicates_and_merge_latest_wins():
    old = frame([row(), row("2000-07-31")])
    new = frame([row(close=17.), row("2000-08-02")])
    merged = merge_incremental(old, new)
    assert len(merged) == 3
    assert merged.iloc[0].close == 17
    assert len(deduplicate(pd.concat([old, old]))) == 2


def test_validation_preserves_all_rows():
    df = frame([row("2000-07-31", high=10, volume=-1), row(open=0), row()])
    before = df.copy(deep=True)
    codes = {x["code"] for x in validation_issues(df, "REE", "fixture")}
    assert {"impossible_ohlc", "invalid_volume", "nonpositive_price", "duplicate_date", "non_monotonic_dates"} <= codes
    pd.testing.assert_frame_equal(df, before)


def test_strict_raw_and_adjustment_separation():
    chart = frame([row(source="kbs", open=None, high=None, low=None, close=None, provider_close=8.)])
    raw = frame([row(adjusted_close=2.)])
    panel = build_panel({"kbs": chart, "fixture": raw}, "REE", "2026-09-26", [])
    assert panel.iloc[0].close == 16
    assert panel.iloc[0].adjusted_close == 2
    assert pd.isna(panel.iloc[0].adjusted_open)
    assert panel.iloc[0].raw_source == "fixture"
    unknown = build_panel({"kbs": chart}, "REE", "snapshot", [])
    assert pd.isna(unknown.iloc[0].close)
    assert "raw_prices_unavailable" in unknown.iloc[0].quality_flags


def test_incremental_start():
    assert incremental_start(frame([row()]), "2000-01-01") == date(2000, 7, 29)
    assert incremental_start(frame([]), "2000-01-01") == date(2000, 1, 1)


def test_partial_retry_never_erases_existing_raw_prices():
    old = frame([row()])
    new = frame([row(source="kbs", open=None, high=None, low=None, close=None)])
    assert merge_incremental(old, new).iloc[0].close == 16
