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


def test_what_others_pay_is_my_spending_but_never_my_money(local):
    today = date.today()
    d = lambda n: (today - timedelta(days=n)).strftime("%d/%m/%Y")
    local.set_month_budget("owner", "AUD", "1000")
    mine = local.add_account("owner", "My debit", "debit", "AUD", "2000")
    parents = local.add_account("owner", "Mum's card", "credit", "AUD", paid_by="other", payer_name="Mum and Dad")
    assert parents["paid_by"] == "other" and parents["payer_name"] == "Mum and Dad" and "owed" not in parents
    local.import_csv("owner", "p.csv", f"Date,Description,Amount\n{d(0)},WOOLWORTHS,-80.00\n{d(0)},PAYMENT RECEIVED THANK YOU,500.00\n",
                     account_id=parents["id"])
    local.import_csv("owner", "m.csv", f"Date,Description,Amount\n{d(0)},COLES,-20.00\n", account_id=mine["id"])
    local.review("owner", [{"id": e["id"], "category": "groceries"} for e in local.expenses(status="pending")])
    s = local.spending_summary()
    aud = s["currencies"]["AUD"]
    assert aud["total"] == 10000 and aud["mine"] == 2000 and aud["others"] == {"Mum and Dad": 8000}  # one total, split
    assert aud["category_split"]["groceries"] == {"mine": 2000, "others": 8000}
    assert aud["others_by_category"] == {"Mum and Dad": {"groceries": 8000}}
    assert s["budget"]["spent"] == 2000 and s["budget"]["others_spent"] == 8000 and s["budget"]["total_spent"] == 10000  # two budgets
    assert aud["cash_out"] == 2000  # only my 20 left my money
    assert not any(c["name"] == "Mum's card" for c in s["cards"]) and s["unmatched_transfers"] == 0
    assert local.cash_balances()["AUD"]["amount"] == 200000 and local._baseline_monthly("AUD") == 2000
    renamed = next(a for a in local.set_account_payer("owner", parents["id"], "other", "Grandma") if a["id"] == parents["id"])
    assert renamed["payer_name"] == "Grandma" and "Grandma" in local.spending_summary()["currencies"]["AUD"]["others"]
    back = next(a for a in local.set_account_payer("owner", parents["id"], "me") if a["id"] == parents["id"])
    assert back["paid_by"] == "me" and back["payer_name"] is None and "owed" in back


def test_can_i_afford_it_when_someone_else_pays(local):
    local.set_month_budget("owner", "AUD", "300", "500")  # mine 300, what others pay for me 500
    other = local.afford("owner", "100", "AUD", payer="other")
    assert other["payer"] == "other" and other["cash"] is None and other["reasons"][0]["code"] == "other_pays" and other["verdict"] == "yes"
    big = local.afford("owner", "900", "AUD", payer="other")  # beyond the month's budget: careful, never from my cash
    assert big["verdict"] == "careful" and any(r["code"] == "month_over" for r in big["reasons"])
    assert local.afford("owner", "100", "AUD").get("payer") is None
    with pytest.raises(Denied):
        local.afford("owner", "10", "AUD", payer="family")


def test_each_entry_can_say_who_paid(local):
    today = str(date.today())
    parents = local.add_account("owner", "Mum's card", "credit", "AUD", paid_by="other", payer_name="Mum and Dad")
    local.add_expense("owner", today, -3000, "AUD", "Dinner", "dining", paid_by="other", payer_name="Grandma")  # no account: the entry says
    on_card = local.add_expense("owner", today, -5000, "AUD", "Books", "shopping", account_id=parents["id"])  # the account says
    mine_on_card = local.add_expense("owner", today, -1000, "AUD", "Snack", "dining", account_id=parents["id"], paid_by="me")  # the entry wins
    local.add_expense("owner", today, -2000, "AUD", "Bus", "transport")  # nothing said: mine
    aud = local.spending_summary()["currencies"]["AUD"]
    assert aud["total"] == 11000 and aud["mine"] == 3000 and aud["others"] == {"Grandma": 3000, "Mum and Dad": 5000}
    local.update_expense("owner", on_card["id"], paid_by="me")
    assert local.spending_summary()["currencies"]["AUD"]["mine"] == 8000
    local.update_expense("owner", on_card["id"], paid_by="account")  # back to the account's payer
    assert local.spending_summary()["currencies"]["AUD"]["others"]["Mum and Dad"] == 5000
    assert local.expense(mine_on_card["id"])["paid_by"] == "me"
    with pytest.raises(Denied):
        local.add_expense("owner", today, -100, "AUD", "x", "dining", paid_by="uncle")


def test_two_budgets_and_their_reminders(local):
    today = str(date.today())
    local.set_month_budget("owner", "AUD", "100", "50")
    local.add_expense("owner", today, -9000, "AUD", "Rent share", "rent")  # 90% of mine
    local.add_expense("owner", today, -6000, "AUD", "Groceries", "groceries", paid_by="other", payer_name="Mum and Dad")  # 120% of theirs
    b = local.spending_summary()["budget"]
    assert (b["amount"], b["spent"], b["others_amount"], b["others_spent"]) == (10000, 9000, 5000, 6000)
    kinds = {k for _, k, *_ in local.budget_reminders()}
    assert "budget_near" in kinds and "budget_others_over" in kinds and "budget_over" not in kinds


def test_term_cash_flow_counts_what_others_pay_each_month(local):
    from datetime import timedelta
    start, end = date.today(), date.today() + timedelta(days=89)
    local.set_cash("owner", "AUD", "5000")
    local.add_term("owner", name="Term", currency="AUD", start=str(start), end=str(end), tuition="0", tuition_due=str(start),
                   living="1000", income="0")
    alone = local.cashflow("AUD", 3)
    local.set_month_budget("owner", "AUD", "400", "600")  # Mum and Dad pay up to 600 of my living costs a month
    helped = local.cashflow("AUD", 3)
    assert helped["others_monthly"] == 60000 and "others_pay" in helped["notes"]
    first = helped["months"][0]
    assert 0 < first["others"] <= first["living"]
    spent_alone = alone["opening"]["total"] - alone["lowest"]["amount"]
    spent_helped = helped["opening"]["total"] - helped["lowest"]["amount"]
    assert abs(spent_helped - spent_alone * 0.4) <= 200  # only the 400 of 1000 a month comes out of my money
    local.set_month_budget("owner", "AUD", "400", "5000")  # more than the living costs: never counted as income
    assert local.cashflow("AUD", 3)["lowest"]["amount"] >= helped["opening"]["total"] - 100


def test_a_receipt_scanned_twice_is_recognised(local):
    today = str(date.today())
    first = local.add_expense("owner", today, -4250, "AUD", "Woolworths Metro Sydney", "groceries", source="receipt")
    again = [dict(date=today, amount=-4250, currency="AUD", description="WOOLWORTHS 1234"),  # the same purchase, spelled differently
             dict(date=today, amount=-1200, currency="AUD", description="Coles")]          # a new one
    seen = local.likely_recorded(again)
    assert [(x["index"], x["id"]) for x in seen] == [(0, first["id"])]
    second = local.add_expense("owner", today, -4250, "AUD", "WOOLWORTHS 1234", "groceries", source="receipt")
    assert second["duplicate_of"] == first["id"]  # saved anyway on purpose: it is still flagged
    assert local.note_scan(["data:image/png;base64,AAAA"]) is None and local.note_scan(["data:image/png;base64,AAAA"]) is not None


def test_review_sets_who_paid(local):
    local.import_csv("owner", "a.csv", "Date,Description,Amount\n20/10/2026,COLES,-12\n21/10/2026,UBER,-8\n", currency="AUD")
    rows = {e["description"]: e["id"] for e in local.expenses(status="pending")}
    local.review("owner", [{"id": rows["COLES"], "paid_by": "other", "payer_name": "Mum and Dad"}, {"id": rows["UBER"], "paid_by": "me"}])
    paid = {e["description"]: (e["paid_by"], e["payer_name"]) for e in local.expenses(status="confirmed")}
    assert paid["COLES"] == ("other", "Mum and Dad") and paid["UBER"] == ("me", None)
