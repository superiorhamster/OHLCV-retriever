from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
import logging

import pandas as pd

from .config import CollectorConfig
from .schema import chunks, frame, parse_date
from .transport import ProviderError, Transport

log = logging.getLogger(__name__)
KBS_BASE = "https://kbbuddywts.kbsec.com.vn/iis-server/investment"
VCI_BASE = "https://trading.vietcap.com.vn/api"


@dataclass
class HistoryResult:
    data: pd.DataFrame
    coverage: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


class BaseProvider(ABC):
    name: str

    def __init__(self, transport: Transport, config: CollectorConfig):
        self.transport, self.config = transport, config

    def get_symbols(self):
        return []

    @abstractmethod
    def fetch_window(self, symbol, start, end):
        """Return normalized records and parser issues, or raise ProviderError."""

    def get_history(self, symbol: str, start: str, end: str):
        records, coverage, issues, errors = [], [], [], []
        for a, b in chunks(start, end, years=self.config.chunk_years):
            try:
                rows, problems = self.fetch_window(symbol, a, b)
                issues.extend(problems)
                if self.name == "kbs" and rows:
                    earliest = min(r["date"] for r in rows)
                    # A provider can cap a valid long response without signalling an error.
                    # Query its omitted prefix directly; never assume it must contain trades.
                    for _ in range(self.config.max_pages):
                        if (earliest - a).days <= self.config.prefix_probe_gap_days:
                            break
                        prefix_end = earliest - timedelta(days=1)
                        extra, prefix_issues = self.fetch_window(symbol, a, prefix_end)
                        issues.extend(prefix_issues)
                        coverage.append({"symbol": symbol, "source": self.name, "requested_start": str(a),
                            "requested_end": str(prefix_end), "records": len(extra),
                            "status": "prefix_probe_observed" if extra else "prefix_probe_empty"})
                        if not extra:
                            break
                        older = [r for r in extra if a <= r["date"] < earliest]
                        if not older:
                            raise ProviderError("kbs: prefix probe ignored requested boundaries")
                        rows.extend(older)
                        earliest = min(r["date"] for r in older)
                    else:
                        raise ProviderError("kbs: prefix probe safety limit reached")
                inside = []
                for row in rows:
                    if a <= row["date"] <= b:
                        inside.append(row)
                    else:
                        issues.append(self.issue(symbol, "outside_requested_range", str(row["date"])))
                records.extend(inside)
                dates = [r["date"] for r in inside]
                item = {"symbol": symbol, "source": self.name, "requested_start": str(a),
                        "requested_end": str(b), "returned_start": str(min(dates)) if dates else None,
                        "returned_end": str(max(dates)) if dates else None, "records": len(inside),
                        "status": "observed" if inside else "empty_unverified"}
                coverage.append(item)
                log.info("%s %s %s -> %s: %d rows (%s -> %s)", symbol, self.name, a, b,
                         len(inside), item["returned_start"], item["returned_end"])
            except ProviderError as exc:
                error = {"symbol": symbol, "source": self.name, "requested_start": str(a),
                         "requested_end": str(b), "error": str(exc)}
                errors.append(error)
                coverage.append({**error, "status": "failed", "records": 0})
                log.warning("%s %s %s -> %s failed: %s", symbol, self.name, a, b, exc)
                # A denied or offline provider should not be retried for every window.
                if "access denied" in str(exc) or "retries exhausted" in str(exc) or "HTTP 403" in str(exc) or "HTTP 401" in str(exc):
                    errors[-1]["requested_end"] = str(end)
                    coverage[-1]["requested_end"] = str(end)
                    break
        return HistoryResult(frame(records), coverage, issues, errors)

    def issue(self, symbol, code, detail):
        return {"symbol": symbol, "source": self.name, "date": None, "code": code, "detail": detail}


class KBSProvider(BaseProvider):
    name = "kbs"

    def get_symbols(self):
        obj = self.transport.request(self.name, "GET", KBS_BASE + "/stock/search/data")
        rows = obj if isinstance(obj, list) else obj.get("data", [])
        return [{"symbol": r["symbol"], "company_name": r.get("name"), "exchange": r.get("exchange"),
                 "status": "current", "source": self.name} for r in rows if r.get("type") == "stock"]

    def profile(self, symbol):
        return self.transport.request(self.name, "GET", KBS_BASE + f"/stockinfo/profile/{symbol}", params={"l": 1})

    def fetch_window(self, symbol, start, end):
        obj = self.transport.request(self.name, "GET", KBS_BASE + f"/stocks/{symbol}/data_day",
                                     params={"sdate": start.strftime("%d-%m-%Y"), "edate": end.strftime("%d-%m-%Y")})
        if not isinstance(obj, dict) or not isinstance(obj.get("data_day"), list):
            raise ProviderError("kbs: malformed history response")
        if obj.get("symbol", symbol).upper() != symbol:
            raise ProviderError("kbs: response symbol mismatch")
        records, issues = [], []
        for r in obj["data_day"]:
            try:
                records.append({"date": parse_date(r["t"]), "symbol": symbol, "source": self.name,
                    **{"provider_" + k: float(r[v]) for k, v in zip(("open", "high", "low", "close"), "ohlc")},
                    "volume": float(r["v"]), "price_basis": "unknown_chart", "volume_basis": "provider_unspecified"})
            except (KeyError, ValueError, TypeError) as exc:
                issues.append(self.issue(symbol, "quarantined_parse_error", f"{exc}: {r}"))
        return records, issues


class VCIProvider(BaseProvider):
    name = "vci"

    def get_symbols(self):
        obj = self.transport.request(self.name, "GET", VCI_BASE + "/price/symbols/getAll")
        if not isinstance(obj, list):
            raise ProviderError("vci: malformed listing response")
        return [{"symbol": r["symbol"], "company_name": r.get("organName"),
                 "exchange": "HOSE" if r.get("board") == "HSX" else r.get("board"),
                 "status": "current", "source": self.name} for r in obj if r.get("type") == "STOCK"]

    def fetch_window(self, symbol, start, end):
        cursor = int(datetime.combine(end + timedelta(days=1), time.min, timezone.utc).timestamp())
        records, issues, seen = [], [], set()
        for _ in range(self.config.max_pages):
            obj = self.transport.request(self.name, "POST", VCI_BASE + "/chart/OHLCChart/gap-chart",
                body={"timeFrame": "ONE_DAY", "symbols": [symbol], "to": cursor, "countBack": self.config.vci_count_back})
            if obj == []:
                break
            if not isinstance(obj, list) or len(obj) != 1 or not isinstance(obj[0], dict):
                raise ProviderError("vci: malformed history response")
            data = obj[0]
            if data.get("symbol", symbol).upper() != symbol:
                raise ProviderError("vci: response symbol mismatch")
            arrays = [data.get(k) for k in "tohlcv"]
            if not all(isinstance(a, list) for a in arrays) or len({len(a) for a in arrays}) != 1:
                raise ProviderError("vci: missing or unequal OHLCV arrays")
            if not arrays[0]:
                break
            try:
                stamps = [int(t) for t in data["t"]]
            except (ValueError, TypeError) as exc:
                raise ProviderError("vci: invalid timestamp") from exc
            earliest = min(stamps)
            if earliest >= cursor or earliest in seen:
                raise ProviderError("vci: historical cursor did not advance")
            seen.add(earliest)
            for i, stamp in enumerate(stamps):
                day = parse_date(stamp, epoch=True)
                if not start <= day <= end:
                    continue  # countBack intentionally extends before the requested start.
                try:
                    records.append({"date": day, "symbol": symbol, "source": self.name,
                        **{"provider_" + k: float(data[v][i]) for k, v in zip(("open", "high", "low", "close"), "ohlc")},
                        "volume": float(data["v"][i]), "price_basis": "unknown_chart", "volume_basis": "provider_unspecified"})
                except (TypeError, ValueError) as exc:
                    issues.append(self.issue(symbol, "quarantined_parse_error", f"{day}: {exc}"))
            if parse_date(earliest, epoch=True) <= start:
                break
            cursor = earliest - 1
        else:
            raise ProviderError("vci: page safety limit reached")
        return records, issues


class VNDProvider(BaseProvider):
    """Explicit opt-in: endpoint timed out during discovery, never enabled silently."""
    name = "vnd"

    def fetch_window(self, symbol, start, end):
        rows, seen = [], set()
        for page in range(1, self.config.max_pages + 1):
            obj = self.transport.request(self.name, "GET", "https://finfo-api.vndirect.com.vn/v4/stock_prices/",
                params={"q": f"code:{symbol}~date:gte:{start}~date:lte:{end}", "sort": "date", "size": 100, "page": page})
            if not isinstance(obj, dict) or not isinstance(obj.get("data"), list):
                raise ProviderError("vnd: unverified response contract")
            batch = obj["data"]
            if not batch:
                break
            fingerprint = tuple(str(x.get("date")) for x in batch)
            if fingerprint in seen:
                raise ProviderError("vnd: repeated page")
            seen.add(fingerprint)
            # Until units and semantics are verified, archive but do not publish values.
            raise ProviderError("vnd: response archived; units and semantics require verification before activation")
        return rows, []


PROVIDERS = {p.name: p for p in (KBSProvider, VCIProvider, VNDProvider)}
