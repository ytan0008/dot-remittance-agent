import json
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from finance.agent import Agent
from finance.api import create_app
from finance.domain import Denied

TODAY = date.today()


class Market:
    """Reference data with a controllable 90-day position and forecast."""
    def __init__(self, rate="4.70", percentile=90, forecast=None):
        self.rate, self.percentile, self.fc = rate, percentile, forecast

    def latest(self, s, t):
        return dict(rate=self.rate, observed="2026-10-16", provider="test", derived=False, source=s, target=t)

    def fetch(self, s, t, days="0"):
        return dict(percentile=str(self.percentile), average="4.60", maximum="4.80", minimum="4.40",
                    series=[{"date": "2026-10-1%d" % i, "rate": r} for i, r in enumerate(["4.60", "4.62", "4.65", "4.66", "4.68", self.rate])])

    def forecast(self, s, t, horizon_days=7):
        if self.fc is None:
            return dict(available=False, reason="test")
        return dict(available=True, point=self.fc, interval_80=["4.6", "4.9"], beats_baseline=True)


def advice(f, **market):
    f.rates = Market(**market)
    f._advice_cache = {}
    return f.exchange_advice("AUD", "CNY", "en", use_model=False)


def test_rule_judgment(local):
    assert advice(local, percentile=90)["verdict"] == "good_time"
    assert advice(local, percentile=20)["verdict"] == "wait"
    assert advice(local, percentile=55)["verdict"] == "neutral"
    # a credible forecast of a clearly better rate, with no deadline, says hold on rather than "now"
    assert advice(local, percentile=90, forecast="4.80")["verdict"] == "neutral"
    local.set_watch("owner", "AUD", "CNY", amount="5000", deadline=str(TODAY + timedelta(days=3)))
    r = advice(local, percentile=20)
    assert r["verdict"] == "deadline" and any(x["code"] == "deadline" and x["days"] == 3 for x in r["reasons"])
    local.set_watch("owner", "AUD", "CNY", min_rate="4.75")
    r = advice(local, percentile=95)
    assert r["verdict"] == "below_floor" and r["needs"]["min_rate"] == "4.75"


def test_model_judges_within_student_limits(local):
    calls = []

    def judge(prompt):
        calls.append(prompt)
        return '```json\n{"verdict": "good_time", "confidence": "high", "reason": "4.70 is near the 90-day high."}\n```'
    local.exchange_judge = judge
    local.rates = Market(percentile=60)
    local._advice_cache = {}
    r = local.exchange_advice("AUD", "CNY", "en")
    assert (r["verdict"], r["judged_by"], r["explanation"]) == ("good_time", "model", "4.70 is near the 90-day high.")
    assert '"percentile_90d": 60.0' in calls[0]
    local.exchange_advice("AUD", "CNY", "en")
    assert len(calls) == 1  # same data and needs: cached, no second model call
    local.set_watch("owner", "AUD", "CNY", min_rate="4.90")  # the student's floor overrides the model
    r = local.exchange_advice("AUD", "CNY", "en")
    assert r["verdict"] == "below_floor" and r["judged_by"] == "model" and len(calls) == 2
    local.exchange_judge = lambda p: "not json"
    local.set_watch("owner", "AUD", "CNY")
    assert local.exchange_advice("AUD", "CNY", "en")["judged_by"] == "rules"


def test_watches_follow_goals_and_respect_off(local):
    local.rates = Market()
    local.create_goal("owner", title="Tuition top-up", source="AUD", target="CNY", target_amount="20000",
                      deadline=str(TODAY + timedelta(days=40)))
    local.sync_watches()
    w = local.watch("AUD", "CNY")
    assert w["origin"] == "auto" and w["deadline"] == str(TODAY + timedelta(days=40)) and w["amount"] == 2000000
    local.set_watch("owner", "AUD", "CNY", active=False)
    local.sync_watches()
    assert local.watch("AUD", "CNY")["active"] is False and local.watch("AUD", "CNY")["origin"] == "user"
    with pytest.raises(Denied):
        local.set_watch("viewer", "AUD", "CNY")
    with pytest.raises(Denied):
        local.set_watch("owner", "AUD", "CNY", deadline=str(TODAY - timedelta(days=1)))
    assert local.set_watch("agent", "AUD", "USD", amount="300", note="rent")["note"] == "rent"


def test_reminds_on_actionable_change_and_keeps_event_reminders(local):
    local.exchange_judge = lambda p: '{"verdict": "good_time", "confidence": "medium", "reason": "Near the 90-day high."}'
    local.rates = Market(percentile=92)
    local.set_watch("owner", "AUD", "CNY")
    assert len(local.check_watches()) == 1
    assert local.check_watches() == []  # unchanged judgment: no repeat
    local.refresh_reminders()  # one-off events must survive the live-state cleanup
    rem = [r for r in local.reminders() if r["kind"] == "ai_good_time"]
    assert rem and rem[0]["data"]["why"] == "Near the 90-day high." and rem[0]["severity"] == "warn"
    local.add_rate_alert("owner", source="AUD", target="CNY", condition="date", due_date=str(TODAY))
    local.check_rate_alerts()
    local.refresh_reminders()
    assert any(r["kind"] == "exchange_due" for r in local.reminders())


def test_watch_api_and_agent(local, monkeypatch):
    monkeypatch.setenv("OWNER_TOKEN", "o" * 32)
    monkeypatch.setenv("AGENT_TOKEN", "a" * 32)
    monkeypatch.setenv("VIEWER_TOKEN", "v" * 32)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    local.rates = Market(percentile=88)
    with TestClient(create_app(local, background=False)) as client:
        owner, viewer = {"Authorization": "Bearer " + "o" * 32}, {"Authorization": "Bearer " + "v" * 32}
        r = client.get("/exchange-advice?source=AUD&target=CNY&lang=zh-CN", headers=viewer).json()
        assert r["verdict"] == "good_time" and r["judged_by"] == "rules"  # no model configured
        w = client.put("/watches", headers=owner, json={"source": "AUD", "target": "CNY", "amount": "3000", "deadline": str(TODAY + timedelta(days=20)),
                                                       "min_rate": "4.5", "note": "spring tuition"}).json()
        assert w["min_rate"] == "4.5" and w["origin"] == "user"
        assert client.put("/watches", headers=viewer, json={"source": "AUD", "target": "CNY"}).status_code == 409
        assert [x["source"] for x in client.get("/watches", headers=viewer).json()] == ["AUD"]
    reply = Agent(local).chat("现在适合换汇吗 AUD CNY", "w1", "zh-CN")
    assert reply["trace"][-1]["tool"] == "exchange_advice" and "AI 盯盘" in reply["message"]
    reply = Agent(local).chat("什么时候换汇比较好", "w2", "zh-CN")  # no pair given: uses the watched pair
    assert reply["trace"][-1]["tool"] == "exchange_advice"
    assert json.loads(json.dumps(reply["trace"][-1]["result"]))["source"] == "AUD"
