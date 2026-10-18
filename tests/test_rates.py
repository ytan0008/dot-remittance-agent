import math
from datetime import date, timedelta
import httpx
import pytest
from finance.domain import Denied
from finance.rates import Rates


def rows(n, base="AUD", quote="CNY", start=4.5, step=0.0):
    today = date.today()
    return [{"date": str(today - timedelta(days=n - i)), "base": base, "quote": quote, "rate": round(start + step * i + 0.02 * math.sin(i), 6)}
            for i in range(n)]


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_reference_statistics_and_direction():
    data = [{"date": "2026-01-01", "base": "AUD", "quote": "CNY", "rate": 4.5},
            {"date": "2026-01-02", "base": "AUD", "quote": "CNY", "rate": 4.7}]
    with client(lambda req: httpx.Response(200, json=data)) as c:
        result = Rates(c).fetch("AUD", "CNY", "30")
    assert result["average"] == "4.6"
    assert result["percentile"] == "75.0"
    assert result["observations"] == 2
    assert result["position"] == "high" and result["new_high"] is True
    assert "not executable" in result["kind"] and "reverse direction" in result["interpretation"]
    assert result["provider"] == "ECB via Frankfurter" and result["derived"] is True  # AUD/CNY is an EUR cross


def test_reference_unavailable_does_not_invent():
    with client(lambda req: httpx.Response(422, json={})) as c:
        with pytest.raises(Denied, match="unavailable"):
            Rates(c).fetch("AAA", "BBB")


def test_blended_fallback_is_labeled():
    def handler(req):
        if req.url.params.get("providers") == "ecb":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=rows(5, quote="VND", start=17900))
    with client(handler) as c:
        latest = Rates(c).latest("AUD", "VND")
    assert latest["provider"] == "Frankfurter blended" and latest["derived"] is True
    assert latest["change"] is not None and latest["note"].startswith("daily reference")


def test_forecast_backtested_against_baseline():
    with client(lambda req: httpx.Response(200, json=rows(400, step=0.001))) as c:
        f = Rates(c).forecast("AUD", "CNY")
    assert f["available"] and float(f["interval_80"][0]) <= float(f["point"]) <= float(f["interval_80"][1])
    assert {"model_mae", "baseline_mae", "beats_baseline", "holdout_interval_coverage", "data_cutoff"} <= set(f)
    with client(lambda req: httpx.Response(200, json=rows(40))) as c:
        short = Rates(c).forecast("AUD", "CNY")
    assert short["available"] is False and "insufficient" in short["reason"]
    assert Rates().forecast("AUD", "CNY", 30)["available"] is False
