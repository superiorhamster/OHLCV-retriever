"""Normalize without inventing adjustments or repairing provider observations."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

PRICE = ["open", "high", "low", "close"]
ADJUSTED = ["adjusted_" + c for c in PRICE]
NUMERIC = PRICE + ["value"] + ADJUSTED + ["provider_" + c for c in PRICE]
OPTIONAL_VOLUME = ["foreign_buy_volume", "foreign_sell_volume", "proprietary_buy_volume", "proprietary_sell_volume"]
OPTIONAL_VALUE = ["foreign_buy_value", "foreign_sell_value"]
CANONICAL = ["date", "symbol", *PRICE, "volume", "value", *ADJUSTED, "source"]


def parse_date(value, *, epoch=False):
    if epoch:
        return datetime.fromtimestamp(int(value), timezone.utc).astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognized daily date: {value!r}")


def chunks(start, end, *, years=3, days=None):
    start, end = parse_date(start), parse_date(end)
    if start > end:
        raise ValueError("start must be on or before end")
    if years <= 0 or (days is not None and days <= 0):
        raise ValueError("Chunk length must be positive")
    while start <= end:
        if days is not None:
            next_start = start + timedelta(days=days)
        else:
            try:
                next_start = start.replace(year=start.year + years)
            except ValueError:
                next_start = start.replace(year=start.year + years, day=28)
        stop = min(end, next_start - timedelta(days=1))
        yield start, stop
        start = stop + timedelta(days=1)


def frame(records):
    df = pd.DataFrame(records)
    for c in CANONICAL + NUMERIC + OPTIONAL_VOLUME + OPTIONAL_VALUE:
        if c not in df:
            df[c] = pd.NA
    for c in set(NUMERIC + OPTIONAL_VALUE):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Float64")
    for c in ["volume", *OPTIONAL_VOLUME]:
        vals = pd.to_numeric(df[c], errors="coerce")
        # Nonintegral share quantities remain observable as a validation error.
        if len(vals.dropna()) and ((vals.dropna() % 1) != 0).any():
            df[c] = vals.astype("Float64")
        else:
            df[c] = vals.astype("Int64")
    return df


def validation_issues(df, symbol, source, *, value_price_tolerance=0.5):
    issues = []
    def add(row, code, detail):
        issues.append({"symbol": symbol, "source": source, "date": str(row.get("date", "")),
                       "code": code, "detail": detail})
    if not df.empty and df.date.tolist() != sorted(df.date.tolist()):
        add({}, "non_monotonic_dates", "Provider order is not ascending; canonical output will be sorted")
    for _, row in df.iterrows():
        if pd.isna(row.symbol) or not str(row.symbol).strip():
            add(row, "missing_symbol", "Missing symbol")
        for prefix in ("", "adjusted_", "provider_"):
            vals = [row.get(prefix + p, pd.NA) for p in PRICE]
            if any(pd.notna(v) and (not float('-inf') < float(v) < float('inf')) for v in vals):
                add(row, "nonfinite_price", prefix or "raw")
            if any(pd.notna(v) and v <= 0 for v in vals):
                add(row, "nonpositive_price", prefix or "raw")
            if all(pd.notna(v) for v in vals):
                o, h, l, c = vals
                if h < max(o, c, l) or l > min(o, c, h):
                    add(row, "impossible_ohlc", prefix or "raw")
        for col in ["volume", *OPTIONAL_VOLUME]:
            v = row.get(col, pd.NA)
            if pd.notna(v) and (v < 0 or v % 1):
                add(row, "invalid_volume", f"{col}={v}")
        if pd.notna(row.get("value")) and row["value"] < 0:
            add(row, "negative_value", str(row["value"]))
        if (row.get("volume_basis") == "matched_shares" and pd.notna(row.get("value"))
                and pd.notna(row.volume) and row.volume > 0
                and pd.notna(row.low) and pd.notna(row.high) and row.low > 0):
            # Loose allowance for reported value rounding; never use this to repair units.
            implied = row["value"] / row.volume
            if implied < row.low * (1 - value_price_tolerance) or implied > row.high * (1 + value_price_tolerance):
                add(row, "value_price_inconsistency", "Reported value / matched volume inconsistent with raw price range; no correction applied")
    for _, row in df[df.duplicated(["symbol", "date"], keep=False)].iterrows():
        add(row, "duplicate_date", "All provider observations retained in raw response; first occurrence selected")
    return issues


def deduplicate(df):
    return df.drop_duplicates(["symbol", "date"], keep="first").sort_values(["symbol", "date"]).reset_index(drop=True)


def merge_incremental(old, new):
    if new.empty:
        return old.copy()
    # A failing raw provider must not erase previously recovered raw OHLC.
    # Select complete rows, never mix fields from different OHLC observations.
    if not old.empty:
        old_raw = set(zip(old.loc[old.close.notna(), "symbol"], old.loc[old.close.notna(), "date"]))
        downgrade = [pd.isna(r.close) and (r.symbol, r.date) in old_raw for r in new.itertuples()]
        new = new.loc[[not d for d in downgrade]]
    return deduplicate(pd.concat([new, old], ignore_index=True))
