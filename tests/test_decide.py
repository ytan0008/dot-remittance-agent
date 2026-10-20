from datetime import date, timedelta
import pytest
from finance.domain import Denied


def forecast(point="0.2170", lo="0.2140", hi="0.2200", beats=True, recent=None):
    cutoff = date.today() - timedelta(days=1)
    rows = recent or [{"date": str(cutoff - timedelta(days=i)), "rate": r} for i, r in enumerate(["0.2150", "0.2140", "0.2160", "0.2130", "0.2145"] * 6)]
    return lambda s, t, horizon_days=7: dict(available=True, data_cutoff=str(cutoff), horizon_days=7, point=point, interval_80=[lo, hi],
                                             recent=rows, beats_baseline=beats)


def test_waiting_is_said_in_money(local, monkeypatch):
    monkeypatch.setattr(local.rates, "forecast", forecast())
    w = local.wait_value("CNY", "AUD", "130000", "spend")  # converting 130,000 CNY; today 1 CNY = 0.2155 AUD
    assert w["unit"] == "CNY" and 50 < w["p_better"] < 100
    assert abs(float(w["expected"]) - 130000 * (0.2170 / 0.2155 - 1)) < 0.02  # about +905 CNY worth if the point is right
    assert float(w["worst"]) < 0 < float(w["best"]) and w["beats_baseline"] is True
    assert w["position_pct"] == 80 and w["position_basis"] == "reference"  # 0.2155 beats 4 of every 5 recent days
    r = local.wait_value("CNY", "AUD", "9800", "receive", due=str(date.today() + timedelta(days=4)))
    assert float(r["expected"]) > 0 and r["can_wait"] is False  # 9,800 AUD costs less later — but the deadline cannot wait a week
    monkeypatch.setattr(local.rates, "forecast", lambda s, t, horizon_days=7: dict(available=False, reason="test"))
    assert local.wait_value("CNY", "AUD", "100")["available"] is False


def test_rules_confirm_or_act_within_their_limits(local, monkeypatch):
    local.set_cash("owner", "CNY", "130000")
    with pytest.raises(Denied):
        local.add_fx_rule("agent", "CNY", "AUD", "60000", "0.2150")  # only the person sets a rule
    ask = local.add_fx_rule("owner", "CNY", "AUD", "60000", "0.2150", mode="confirm")
    high = local.add_fx_rule("owner", "CNY", "AUD", "60000", "0.2200", mode="auto")  # today 0.2155: not yet
    assert local.check_fx_rules() == 0
    rules = {r["id"]: r for r in local.fx_rules()}
    assert rules[ask["id"]]["status"] == "triggered" and rules[high["id"]]["status"] == "active"
    local.refresh_reminders()
    assert any(r["kind"] == "fx_rule_ready" for r in local.reminders())
    done = local.execute_fx_rule("owner", ask["id"])
    assert done["status"] == "done" and done["result"]["spent"] == 6000000
    cash = local.cash_balances()
    assert cash["CNY"]["amount"] == 7000000 and cash["AUD"]["amount"] == int(60000 * 0.2155 * 100)  # 60,000 CNY moved, no more
    with pytest.raises(Denied):
        local.execute_fx_rule("owner", ask["id"])  # never twice
    auto = local.add_fx_rule("owner", "CNY", "AUD", "100000", "0.2100", mode="auto")
    assert local.check_fx_rules() == 1
    assert local.cash_balances()["CNY"]["amount"] == 0  # capped at what you have (70,000 left), not the 100,000 of the rule
    assert next(r for r in local.fx_rules() if r["id"] == auto["id"])["result"]["auto"] is True
    local.cancel_fx_rule("owner", high["id"])
    with pytest.raises(Denied):
        local.add_fx_rule("owner", "CNY", "AUD", "1", "0.2", due="2020-01-01")


def test_savings_and_the_rule_reminder_near_its_date(local, monkeypatch):
    monkeypatch.setattr(local.rates, "forecast", forecast())
    s = local.savings("CNY", "AUD", "0.2160", "60000")
    assert float(s["saved"]) > 0 and s["days"] == 30 and s["currency"] == "CNY"
    local.add_fx_rule("owner", "CNY", "AUD", "1000", "0.3000", due=str(date.today() + timedelta(days=2)))
    assert [k for _, k, *_ in local.rule_reminders()] == ["fx_rule_due"]


def test_month_budget(local):
    local.set_month_budget("owner", "AUD", "100")
    today = str(date.today())
    local.add_expense("owner", today, -9000, "AUD", "Coles", "groceries")
    assert local.spending_summary()["budget"]["spent"] == 9000
    assert [k for _, k, *_ in local.budget_reminders()] == ["budget_near"]
    local.add_expense("owner", today, -2000, "AUD", "Opal", "transport")
    assert [k for _, k, *_ in local.budget_reminders()] == ["budget_over"]
    assert local.set_month_budget("owner", "AUD", "") is None and local.spending_summary()["budget"] is None


def test_the_spread_is_shown_in_money(local):
    local.set_bank_pricing("owner", "boc", "CNY", "AUD", {"rate": "0.2130", "fee_send": {"amount": "50", "currency": "CNY"}})
    s = next(x for x in local.exchange_scenarios("CNY", "AUD", "130000", "send", "boc")["scenarios"] if x["timing"] == "once")
    assert s["spread_pct"] == "1.16" and abs(s["spread_cost"] - 130000 * (1 - 0.2130 / 0.2155) * 100) < 100  # about 1,508 CNY: far more than the fee
    assert local.bank_rate_history("boc", "CNY", "AUD")[-1]["rate"] == "0.2130"  # kept by day
