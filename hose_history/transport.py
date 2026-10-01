"""Conservative public HTTP access with immutable, resumable response snapshots."""
import hashlib
import json
import logging
import random
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from .config import CollectorConfig

log = logging.getLogger(__name__)
RETRY_STATUS = {429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    pass


class AccessDenied(ProviderError):
    pass


class CollectionInterrupted(Exception):
    pass


def atomic_json(path: Path, obj):
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Transport:
    def __init__(self, config: CollectorConfig, snapshot: str, client=None):
        self.config, self.snapshot = config, snapshot
        self.client = client or httpx.Client(timeout=config.request_timeout, follow_redirects=True,
                                             headers={"User-Agent": "HOSE-Research-Collector/0.1", "Accept": "application/json"})
        self._locks = {p: threading.Lock() for p in ("kbs", "vci", "vnd", "metadata")}
        self._next = {}
        self._denied = set()
        self.stop_event = threading.Event()

    def close(self):
        self.client.close()

    def request(self, provider, method, url, *, params=None, body=None):
        query = {"method": method, "url": url, "params": params, "json": body}
        digest = hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()
        path = self.config.data_dir / "raw" / provider / self.snapshot / f"{digest}.json"
        with self._locks[provider]:
            if self.stop_event.is_set():
                raise CollectionInterrupted("Collector stopping; cached work retained")
            if path.exists():
                with path.open(encoding="utf-8") as f:
                    return json.load(f)["response"]
            endpoint = (provider, url)
            if endpoint in self._denied:
                raise AccessDenied(f"{provider}: endpoint access denied earlier in this process")
            last = None
            for attempt in range(self.config.max_retries + 1):
                if self.stop_event.wait(max(0, self._next.get(provider, 0) - time.monotonic())):
                    raise CollectionInterrupted("Collector stopping; cached work retained")
                retry_after = 0.0
                try:
                    response = self.client.request(method, url, params=params, json=body)
                    self._next[provider] = time.monotonic() + self.config.request_delay
                    if response.status_code in {401, 403}:
                        self._denied.add(endpoint)
                        atomic_json(path.with_suffix(".error.json"), {"request": query,
                            "status": response.status_code, "body": response.text,
                            "fetched_at": datetime.now(timezone.utc).isoformat()})
                        raise AccessDenied(f"{provider}: HTTP {response.status_code}; no bypass attempted")
                    if response.status_code not in RETRY_STATUS:
                        response.raise_for_status()
                        try:
                            obj = response.json()
                        except ValueError as exc:
                            atomic_json(path.with_suffix(".error.json"), {"request": query,
                                "status": response.status_code, "body": response.text,
                                "fetched_at": datetime.now(timezone.utc).isoformat()})
                            raise ProviderError(f"{provider}: malformed JSON") from exc
                        atomic_json(path, {"request": query, "response": obj,
                            "status": response.status_code, "fetched_at": datetime.now(timezone.utc).isoformat(),
                            "final_url": str(response.url)})
                        return obj
                    last = f"HTTP {response.status_code}"
                    header = response.headers.get("Retry-After")
                    if header:
                        try:
                            retry_after = float(header)
                        except ValueError:
                            try:
                                retry_after = max(0, parsedate_to_datetime(header).timestamp() - time.time())
                            except (TypeError, ValueError):
                                pass
                except httpx.RequestError as exc:
                    last = str(exc)
                except httpx.HTTPStatusError as exc:
                    raise ProviderError(f"{provider}: HTTP {exc.response.status_code}") from exc
                if attempt < self.config.max_retries:
                    delay = max(retry_after, min(self.config.backoff_cap,
                        self.config.backoff_base * 2 ** attempt) + random.uniform(0, 1))
                    log.warning("%s retry %d/%d in %.1fs: %s", provider, attempt + 1,
                                self.config.max_retries, delay, last)
                    self._next[provider] = time.monotonic() + delay
            raise ProviderError(f"{provider}: retries exhausted: {last}")
