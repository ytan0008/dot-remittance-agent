import math
from datetime import date, timedelta
from fastapi.testclient import TestClient
import pytest
from finance.api import create_app
from finance.domain import Denied

TODAY = date.today()
CBA = """Date,Description,Amount,Balance
03/10/2026,WOOLWORTHS 1234 SYDNEY,-54.20,1200.00
05/10/2026,OPAL TRAVEL CARD,-40.00,1160.00
15/10/2026,SALARY ACME PTY,1500.00,2620.00
01/09/2026,RENT PAYMENT LANDLORD,-800.00,2000.00
"""


def test_cash_from_bank_csv_and_manual_entry(local):
    assert local.cash_position()["has_cash"] is False
    local.import_csv("owner", "cba.csv", CBA, "AUD")
    aud = local.cash_balances()["AUD"]
    assert (aud["amount"], aud["as_of"], aud["source"]) == (262000, "2026-10-15", "csv")  # balance after the newest transaction
    local.set_cash("owner", "CNY", "50000")
    pos = local.cash_position("CNY")
    assert pos["total"] == 5000000 + round(2620 * 4.64 * 100)
    assert [c["currency"] for c in pos["currencies"]] == ["CNY", "AUD"]  # display currency first
    local.set_cash("owner", "AUD", "3000.50")  # typed today: newer than the statement
    assert local.cash_balances()["AUD"]["source"] == "manual" and local.cash_balances()["AUD"]["amount"] == 300050
    assert all(x["currency"] != "ETH" for x in pos["sandbox"])
    with pytest.raises(Denied):
        local.set_cash("agent", "AUD", "1")
    with pytest.raises(Denied):
        local.set_cash("owner", "AU", "1")
    local.clear_cash("owner", "CNY")
    assert "CNY" not in local.cash_balances()


def test_exchange_needs_shortfall_and_goal(local):
    local.set_cash("owner", "AUD", "1000")
    local.set_cash("owner", "CNY", "60000")
    local.add_term("owner", name="Semester 1", currency="AUD", start=str(TODAY), end=str(TODAY + timedelta(days=90)),
                   tuition="5000", tuition_due=str(TODAY + timedelta(days=10)), living="1500")
    needs = local.exchange_needs()
    gap = next(n for n in needs if n["kind"] == "shortfall")
    assert gap["target"] == "AUD" and gap["funding"] == "CNY" and gap["have"] == 100000
    assert gap["need"] == 500000 + 150000 * 61 // 30 and gap["shortfall"] == gap["need"] - 100000
    assert gap["rate"] == "0.2155" and gap["cost"] == math.ceil(gap["shortfall"] / 0.2155) and gap["due"] == str(TODAY + timedelta(days=10))
    assert {i["kind"] for i in gap["items"]} == {"tuition", "living"}
    local.create_goal("owner", title="Family support", source="AUD", target="CNY", target_amount="2000", deadline=str(TODAY + timedelta(days=30)))
    goal = next(n for n in local.exchange_needs() if n["kind"] == "goal")
    assert goal["funding"] == "AUD" and goal["shortfall"] == 200000 and goal["cost"] == math.ceil(2000 / 4.64 * 100)  # costs round up, never understated
    local.set_cash("owner", "AUD", "20000")  # enough AUD now: no shortfall item
    assert not [n for n in local.exchange_needs() if n["kind"] == "shortfall"]


def test_cashflow_starts_from_real_cash(local):
    local.set_cash("owner", "AUD", "4321")
    plan = local.cashflow("AUD")
    assert plan["opening"]["total"] == 432100 and plan["opening"]["cash"] == 432100 and "cash_balance" in plan["notes"]


def test_money_api(local, monkeypatch):
    monkeypatch.setenv("OWNER_TOKEN", "o" * 32)
    monkeypatch.setenv("AGENT_TOKEN", "a" * 32)
    monkeypatch.setenv("VIEWER_TOKEN", "v" * 32)
    with TestClient(create_app(local, background=False)) as client:
        owner, viewer = {"Authorization": "Bearer " + "o" * 32}, {"Authorization": "Bearer " + "v" * 32}
        assert client.put("/cash", headers=owner, json={"currency": "AUD", "amount": "1500"}).json()["total"] == 150000
        assert client.put("/cash", headers=viewer, json={"currency": "AUD", "amount": "1"}).status_code == 409
        r = client.get("/overview/money?display=CNY", headers=viewer).json()
        assert r["position"]["display"] == "CNY" and r["position"]["total"] == round(1500 * 4.64 * 100)
        assert client.delete("/cash/AUD", headers=owner).json()["has_cash"] is False
