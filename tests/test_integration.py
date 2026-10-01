import os
import pytest

from hose_history.config import CollectorConfig
from hose_history.providers import VCIProvider
from hose_history.transport import Transport


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("HOSE_LIVE_TESTS") != "1", reason="Set HOSE_LIVE_TESTS=1 to request live data")
@pytest.mark.parametrize("cls", [VCIProvider])
def test_first_market_session(tmp_path, cls):
    cfg = CollectorConfig(data_dir=tmp_path)
    transport = Transport(cfg, "integration")
    try:
        result = cls(transport, cfg).get_history("REE", "2000-07-28", "2000-07-28")
        if result.errors and any("403" in e["error"] or "access denied" in e["error"] for e in result.errors):
            pytest.skip(f"{cls.name} denied public request; no bypass attempted")
        assert not result.errors and len(result.data) == 1
    finally:
        transport.close()
