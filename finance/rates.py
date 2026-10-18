"""Daily reference data is kept separate from executable payment quotes.

Sources: ECB reference rates via Frankfurter; when ECB does not publish a pair, Frankfurter's blended
composite of central-bank sources, labeled as such. Nothing here is ever synthesized.
"""
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
import math
import re
import threading
import time
import httpx
from .domain import Denied

SOURCES = {
    "ecb": dict(provider="ECB via Frankfurter", rate_type="ECB daily reference rate", frequency="daily (TARGET business days)"),
    "blended": dict(provider="Frankfurter blended", rate_type="blended composite of central-bank reference rates",
                    frequency="daily"),
}


class Rates:
    url = "https://api.frankfurter.dev/v2/rates"
    _cache = {}
    _lock = threading.Lock()

    def __init__(self, client=None, ttl=600):
        self.client = client
        self.ttl = ttl

    def _get(self, params):
        if self.client:
            return self.client.get(self.url, params=params)
        return httpx.get(self.url, params=params, timeout=15)

    def _series(self, source, target, start, end, source_key):
        params = dict(base=source, quotes=target)
        if source_key == "ecb":
            params["providers"] = "ecb"
        if start:
            params.update({"from": str(start), "to": str(end)})
        response = self._get(params)
        if response.status_code in (400, 404, 422):
            return []
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError()
        data = {}
        for row in rows:
            rate = Decimal(str(row["rate"]))
            if row["base"] != source or row["quote"] != target or not rate.is_finite() or rate <= 0:
                raise ValueError()
            observed = datetime.strptime(row["date"], "%Y-%m-%d").date()
            if observed > end:
                raise ValueError()
            data[str(observed)] = str(rate)
        return [{"date": d, "rate": r} for d, r in sorted(data.items())]

    def series(self, source, target, days):
        """Returns (source_key, rows). Tries ECB, then the labeled blended feed. Cached, never invented."""
        if not re.fullmatch(r"[A-Z]{3}", source) or not re.fullmatch(r"[A-Z]{3}", target) or source == target:
            raise Denied("distinct uppercase ISO currency pair required", "pair_invalid")
        key = (source, target, days)
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > time.time() - self.ttl and not self.client:
                if hit[1] is None:  # a pair the sources do not cover, confirmed recently
                    raise Denied("reference data unavailable or unsupported; no synthetic fallback", "rates_unavailable")
                return hit[1]
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=max(days, 14))
        try:
            for source_key in ("ecb", "blended"):
                rows = self._series(source, target, start, today, source_key)
                if rows:
                    result = (source_key, rows)
                    with self._lock:
                        self._cache[key] = (time.time(), result)
                    return result
        except Exception:
            raise Denied("reference data unavailable or unsupported; no synthetic fallback", "rates_unavailable") from None
        with self._lock:
            self._cache[key] = (time.time(), None)  # only confirmed "not covered", never network failures
        raise Denied("reference data unavailable or unsupported; no synthetic fallback", "rates_unavailable")

    @staticmethod
    def _label(source_key, source, target):
        meta = dict(SOURCES[source_key])
        if source_key == "ecb":
            derived = "EUR" not in (source, target)
            meta["derived"] = derived
            meta["derivation"] = "cross rate derived through the EUR base of ECB reference rates" if derived else "direct ECB quotation"
        else:
            meta["derived"] = True
            meta["derivation"] = "composite derived by Frankfurter from multiple central-bank publications"
        return meta

    def latest(self, source, target):
        source_key, rows = self.series(source, target, 14)
        last = rows[-1]
        previous = rows[-2] if len(rows) > 1 else None
        rate = Decimal(last["rate"])
        change = rate - Decimal(previous["rate"]) if previous else None
        return dict(kind="reference", note="daily reference data, not an executable quote",
                    direction=f"1 {source} = rate {target}", source=source, target=target,
                    rate=str(rate), observed=last["date"], previous=previous,
                    change=str(change) if change is not None else None,
                    change_pct=str(round(change / Decimal(previous["rate"]) * 100, 4)) if previous else None,
                    retrieved_at=datetime.now(timezone.utc).isoformat(), url=self.url,
                    **self._label(source_key, source, target))

    def fetch(self, source, target, days="0"):
        if str(days) not in ("0", "30", "90", "365"):
            raise Denied("supported windows: 0/latest, 30, 90, 365 days", "window_invalid")
        days = int(days)
        source_key, data = self.series(source, target, days or 14)
        if days:
            cutoff = str(datetime.now(timezone.utc).date() - timedelta(days=days))
            data = [r for r in data if r["date"] >= cutoff] or data
        values = [Decimal(r["rate"]) for r in data]
        latest, low, high = values[-1], min(values), max(values)
        percentile = (sum(v < latest for v in values) + Decimal("0.5") * sum(v == latest for v in values)) * 100 / len(values)
        position = "low" if percentile < Decimal("33.34") else "high" if percentile > Decimal("66.66") else "middle"
        first_day = datetime.strptime(data[0]["date"], "%Y-%m-%d").date()
        last_day = datetime.strptime(data[-1]["date"], "%Y-%m-%d").date()
        span = (last_day - first_day).days + 1
        expected = max(1, span if source_key == "blended" else round(span * 5 / 7))
        near = Decimal("0.005")
        return dict(kind="daily reference, not executable quote", **self._label(source_key, source, target),
                    url=self.url, direction=f"1 {source} = rate {target}", source=source, target=target,
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                    requested_days=days, first=data[0]["date"], last=data[-1]["date"], observations=len(data),
                    coverage_pct=str(min(100, round(len(data) * 100 / expected))),
                    latest=str(latest), minimum=str(low), maximum=str(high),
                    average=str(sum(values) / len(values)), percentile=str(percentile),
                    trend_pct=str(round((latest - values[0]) / values[0] * 100, 3)),
                    position=position, new_high=len(values) > 1 and latest == high and values.count(high) == 1,
                    new_low=len(values) > 1 and latest == low and values.count(low) == 1,
                    near_high=high > 0 and (high - latest) / high <= near,
                    near_low=low > 0 and (latest - low) / low <= near,
                    favorable_for_sender=position == "high",
                    interpretation=(f"Higher rate gives more {target} for a fixed {source} amount, which favors someone "
                                    f"sending {source}. For the reverse direction ({target}→{source}) the reading inverts. "
                                    "Percentile is a historical rank over the observed window, not a forecast probability "
                                    "or evidence of over- or under-valuation."),
                    coverage="available observation days only; weekends/holidays may be absent", series=data)

    def forecast(self, source, target, horizon_days=7):
        """Experimental drift forecast evaluated against an unchanged-rate baseline. Unavailable rather than invented."""
        generated = datetime.now(timezone.utc).isoformat()
        base = dict(kind="experimental forecast", source=source, target=target, horizon_days=horizon_days,
                    generated_at=generated, model="90-day log drift", baseline="unchanged rate (naive)")
        if horizon_days != 7:
            return dict(base, available=False, reason="only the 7-day horizon is evaluated; 30-day forecasting is deferred")
        try:
            source_key, rows = self.series(source, target, 400)
        except Denied as exc:
            return dict(base, available=False, reason=str(exc))
        dates = [date.fromisoformat(r["date"]) for r in rows]
        values = [float(r["rate"]) for r in rows]

        def drift_at(i):
            j = next((k for k in range(i, -1, -1) if (dates[i] - dates[k]).days >= 90), None)
            if j is None or j == i:
                return None
            return (math.log(values[i]) - math.log(values[j])) / (dates[i] - dates[j]).days

        origins = []
        for i in range(len(rows)):
            target_index = next((k for k in range(i + 1, len(rows)) if (dates[k] - dates[i]).days >= horizon_days), None)
            mu = drift_at(i)
            if target_index is None or mu is None:
                continue
            model = values[i] * math.exp(mu * horizon_days)
            origins.append((values[target_index], model, values[i]))
        if len(origins) < 60:
            return dict(base, available=False, reason=f"insufficient evaluated history ({len(origins)} origins, need 60)",
                        data_cutoff=rows[-1]["date"])
        model_mae = sum(abs(a - m) for a, m, _ in origins) / len(origins)
        naive_mae = sum(abs(a - n) for a, _, n in origins) / len(origins)
        ratios = [a / m - 1 for a, m, _ in origins]

        def quantile(xs, q):
            xs = sorted(xs)
            pos = (len(xs) - 1) * q
            lo, hi = math.floor(pos), math.ceil(pos)
            return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)

        split = int(len(ratios) * 0.6)
        lo_q, hi_q = quantile(ratios[:split], 0.1), quantile(ratios[:split], 0.9)
        holdout = ratios[split:]
        coverage = sum(lo_q <= r <= hi_q for r in holdout) / len(holdout)
        mu = drift_at(len(rows) - 1)
        point = values[-1] * math.exp(mu * horizon_days)
        q10, q90 = quantile(ratios, 0.1), quantile(ratios, 0.9)
        fmt = lambda x: f"{x:.6g}"
        return dict(base, available=True, data_cutoff=rows[-1]["date"], last_observed=rows[-1]["rate"],
                    point=fmt(point), interval_80=[fmt(point * (1 + q10)), fmt(point * (1 + q90))],
                    baseline_point=rows[-1]["rate"], backtest_origins=len(origins),
                    model_mae=fmt(model_mae), baseline_mae=fmt(naive_mae),
                    beats_baseline=model_mae < naive_mae, holdout_interval_coverage=f"{coverage * 100:.1f}",
                    **self._label(source_key, source, target),
                    caveat="Experimental. Historical backtest errors do not guarantee future accuracy; "
                           "if the model does not beat the unchanged-rate baseline, prefer the baseline.")
