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


def test_payments_draw_on_the_balance_you_see(local):
    from conftest import approved
    local.set_cash("owner", "AUD", "3250")
    aud = next(b for b in local.balances() if b["currency"] == "AUD")
    assert aud["available"] == "325000" and aud["basis"] == "cash"  # the send page shows your overview balance
    assert next(b for b in local.balances() if b["currency"] == "USD")["basis"] == "test_funds"  # never entered: test money, labelled
    t = approved(local)
    local.execute("owner", t["id"])
    local.reconcile_open()
    done = local.get(t["id"])
    assert done["status"] == "completed"
    after = local.cash_balances()["AUD"]
    assert after["amount"] == 325000 - int(done["actual_cost"]) and after["source"] == "transfer"
    assert next(b for b in local.balances() if b["currency"] == "AUD")["total"] == str(after["amount"])  # one number everywhere
    local.fund("owner", "AUD", "50")
    assert local.cash_balances()["AUD"]["amount"] == after["amount"] + 5000


DEBIT = """Date,Description,Amount,Balance
02/10/2026,WOOLWORTHS SYDNEY,-40.00,960.00
10/10/2026,PAYMENT TO CBA MASTERCARD,-100.00,860.00
12/10/2026,TRANSFER TO SAVINGS,-200.00,660.00
"""
CARD = """Date,Description,Amount,Balance
05/10/2026,UBER EATS SYDNEY,-60.00,-60.00
06/10/2026,KMART SYDNEY,-40.00,-100.00
08/10/2026,KMART REFUND,15.00,-85.00
11/10/2026,PAYMENT RECEIVED THANK YOU,100.00,15.00
"""
SAVINGS = """Date,Description,Amount,Balance
12/10/2026,TRANSFER FROM EVERYDAY,200.00,1200.00
"""


def test_card_purchases_and_their_repayment_count_once(local):
    debit = local.add_account("owner", "CBA Everyday", "debit", "AUD")
    card = local.add_account("owner", "CBA Mastercard", "credit", "AUD")
    savings = local.add_account("owner", "CBA Savings", "debit", "AUD")
    with pytest.raises(Denied):
        local.add_account("owner", "x", "loan", "AUD")
    local.import_csv("owner", "debit.csv", DEBIT, account_id=debit["id"])
    local.import_csv("owner", "card.csv", CARD, account_id=card["id"])
    r = local.import_csv("owner", "savings.csv", SAVINGS, account_id=savings["id"])
    rows = local.expenses(status="pending")
    local.review("owner", [{"id": e["id"], "include": True} for e in rows])
    by = {e["description"]: e for e in local.expenses(status="confirmed")}
    pay, got = by["PAYMENT TO CBA MASTERCARD"], by["PAYMENT RECEIVED THANK YOU"]
    assert pay["kind"] == got["kind"] == "card_repayment" and pay["match_id"] == got["id"]  # matched on both sides
    assert by["TRANSFER TO SAVINGS"]["match_id"] == by["TRANSFER FROM EVERYDAY"]["id"] and r["matched"] == 1
    assert by["KMART REFUND"]["kind"] == "refund" and by["KMART REFUND"]["category"] == "shopping"
    s = local.spending_summary("2026-10")
    aud = s["currencies"]["AUD"]
    # 40 groceries + 60 dining + (40 - 15) shopping = 125: the 100 card repayment is not spending a second time
    assert aud["total"] == 12500 and aud["categories"]["shopping"] == 2500
    assert aud["cash_out"] == 4000 + 10000  # groceries and the card repayment left the debit card; the savings move did not
    assert s["cards"][0]["owed"] == -1500 and s["unmatched_transfers"] == 0  # paid 100 of 85: 15 in credit
    # your AUD balance = the two debit accounts, never the card's balance
    assert local.cash_balances()["AUD"]["amount"] == 66000 + 120000


def test_a_same_amount_pair_is_only_suggested_until_you_confirm_it(local):
    debit = local.add_account("owner", "Everyday", "debit", "AUD")
    card = local.add_account("owner", "Visa", "credit", "AUD")
    local.import_csv("owner", "d.csv", "Date,Description,Amount\n10/10/2026,NETBANK BPAY 4321,-100.00\n", account_id=debit["id"])
    local.import_csv("owner", "c.csv", "Date,Description,Amount\n05/10/2026,COLES,-100.00\n11/10/2026,PAYMENT,100.00\n", account_id=card["id"])
    local.review("owner", [{"id": e["id"], "include": True} for e in local.expenses(status="pending")])
    bpay = next(e for e in local.expenses(status="confirmed") if e["description"].startswith("NETBANK"))
    assert bpay["kind"] == "spend" and bpay["match_hint"]  # a purchase stays a purchase: same amount is not proof
    assert local.spending_summary("2026-10")["currencies"]["AUD"]["total"] == 20000
    local.confirm_match("owner", bpay["id"], True)
    assert local.spending_summary("2026-10")["currencies"]["AUD"]["total"] == 10000  # 100 at Coles, once
    local.unmatch("owner", bpay["id"])  # and it can be undone
    assert local.expense(bpay["id"])["kind"] == "spend" and local.spending_summary("2026-10")["currencies"]["AUD"]["total"] == 20000
