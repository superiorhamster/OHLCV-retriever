from datetime import date
from unittest.mock import Mock

import pytest

from hose_history.config import CollectorConfig
from hose_history.providers import KBSProvider, VCIProvider, PROVIDERS
from hose_history.transport import ProviderError


def test_supported_providers_and_removed_provider_rejected():
    assert set(PROVIDERS) == {"kbs", "vci", "vnd"}
    assert CollectorConfig().providers == ("kbs", "vci")
    with pytest.raises(ValueError, match="Unknown"):
        CollectorConfig(providers=("cafef",))


def test_kbs_empty_is_not_malformed():
    t = Mock()
    t.request.return_value = {"symbol": "REE", "data_day": []}
    result = KBSProvider(t, CollectorConfig()).get_history("REE", "2000-01-01", "2000-01-02")
    assert result.data.empty and not result.errors
    assert result.coverage[0]["status"] == "empty_unverified"


def test_vci_parallel_array_lengths_checked():
    t = Mock()
    t.request.return_value = [{"symbol": "REE", "t": [964742400], "o": [], "h": [], "l": [], "c": [], "v": []}]
    result = VCIProvider(t, CollectorConfig()).get_history("REE", "2000-07-28", "2000-07-31")
    assert "unequal" in result.errors[0]["error"]


def test_vci_pages_back_without_treating_small_page_as_complete():
    def response(ts):
        return [{"symbol": "REE", "t": [ts], "o": [1], "h": [1], "l": [1], "c": [1], "v": [10]}]
    t = Mock()
    t.request.side_effect = [response(965001600), response(964742400)]
    r = VCIProvider(t, CollectorConfig()).get_history("REE", "2000-07-28", "2000-07-31")
    assert len(r.data) == 2 and not r.errors
    assert t.request.call_args_list[1].kwargs["body"]["to"] == 965001599
    assert r.data.close.isna().all() and r.data.provider_close.notna().all()


def test_kbs_recovers_silently_capped_prefix():
    t = Mock()
    def bar(day):
        return {"t":day + " 07:00", "o":10, "h":10, "l":10, "c":10, "v":100}
    t.request.side_effect = [{"data_day":[bar("2020-06-01")]}, {"data_day":[bar("2020-01-02")]}]
    result = KBSProvider(t, CollectorConfig()).get_history("REE", "2020-01-01", "2020-06-01")
    assert len(result.data) == 2 and not result.errors
    assert t.request.call_args_list[1].kwargs["params"]["edate"] == "31-05-2020"
