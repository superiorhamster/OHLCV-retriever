from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class CollectorConfig:
    start_date: str = "2000-07-28"
    end_date: str | None = None
    max_workers: int = 3
    max_retries: int = 5
    request_timeout: int = 30
    request_delay: float = 0.5
    chunk_years: int = 3
    vci_count_back: int = 1000
    max_pages: int = 1000
    backoff_base: float = 1.0
    backoff_cap: float = 60.0
    close_diff_pct: float = 1.0
    volume_diff_pct: float = 1.0
    audit_days: int = 14
    prefix_probe_gap_days: int = 31
    value_price_tolerance: float = 0.5
    max_pending: int = 6
    providers: tuple[str, ...] = ("kbs", "vci")
    data_dir: Path = field(default_factory=lambda: Path("data"))

    def __post_init__(self):
        for name in ("max_workers", "request_timeout", "chunk_years",
                     "vci_count_back", "max_pages", "max_pending", "prefix_probe_gap_days", "audit_days"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_retries < 0 or self.request_delay < 0:
            raise ValueError("Retries and request delay cannot be negative")
        if not 0 <= self.value_price_tolerance < 1:
            raise ValueError("value_price_tolerance must be in [0, 1)")
        if min(self.close_diff_pct, self.volume_diff_pct, self.backoff_base, self.backoff_cap) < 0:
            raise ValueError("Thresholds and backoff parameters cannot be negative")
        if not self.providers or set(self.providers) - {"kbs", "vci", "vnd"}:
            raise ValueError("Unknown or empty provider selection")

    @property
    def end(self) -> str:
        return self.end_date or datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()
