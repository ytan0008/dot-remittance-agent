import json
from datetime import date, timedelta
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from finance.agent import Agent
from finance.api import create_app
from finance.domain import Denied
from finance.expenses import parse_amount, parse_date, suggest_category

CBA = """Date,Description,Amount,Balance
03/10/2026,WOOLWORTHS 1234 SYDNEY,-54.20,1200.00
05/10/2026,OPAL TRAVEL CARD,-40.00,1160.00
05/10/2026,OPAL TRAVEL CARD,-40.00,1120.00
15/10/2026,SALARY ACME PTY,1500.00,2620.00
01/09/2026,RENT PAYMENT LANDLORD,-800.00,2000.00
01/10/2026,RENT PAYMENT LANDLORD,-800.00,1200.00
"""
DEBIT_CREDIT = """交易日期;交易描述;支出;收入
2026-10-02;美团外卖 午餐;35,50;
2026-10-03;工资;;5000,00
"""


def test_amount_and_date_parsing():
    assert parse_amount("-1,234.50") == -1234.5 and parse_amount("(12.00)") == -12 and parse_amount("12,50") == 12.5
    assert parse_amount("1.234,50") == 1234.5 and parse_amount("45.00 DR") == -45 and parse_amount("abc") is None
    assert parse_date("13/10/2026") == date(2026, 10, 13) and parse_date("2026年10月3日") == date(2026, 10, 3)


def test_category_suggestions_and_learned_rules():
    assert suggest_category("WOOLWORTHS METRO")[0] == "groceries"
    assert suggest_category("午饭 麻辣烫")[0] == "dining"
    assert suggest_category("Netflix.com")[0] == "subscriptions"
    assert suggest_category("Refund", amount=500)[0] == "income"
    assert suggest_category("joes corner shop", {"joes corner shop": "groceries"})[0] == "groceries"


def test_csv_import_flags_duplicates_and_stays_pending(local):
    result = local.import_csv("owner", "cba.csv", CBA, "AUD")
    rows = result["rows"]
    assert len(rows) == 6 and all(r["status"] == "pending" for r in rows)
    opal = [r for r in rows if "OPAL" in r["description"]]
    assert sum(1 for r in opal if r["duplicate_of"]) == 1  # same day, merchant and amount inside one file
    assert {r["category"] for r in rows if "RENT" in r["description"]} == {"rent"}
    assert next(r for r in rows if "SALARY" in r["description"])["category"] == "income"
    assert result["date_order"] == "day/month"
    assert result["recurring_candidates"][0]["cadence"] == "monthly"  # rent on the 1st, two months running
    assert local.spending_summary("2026-10")["currencies"] == {}  # nothing counts until confirmed
    again = local.import_csv("owner", "cba.csv", CBA, "AUD")
    assert all(r["duplicate_of"] for r in again["rows"])  # re-importing the same statement is caught


def test_debit_credit_columns_and_semicolons(local):
    rows = local.import_csv("owner", "bank.csv", DEBIT_CREDIT, "CNY")["rows"]
    lunch = next(r for r in rows if "午餐" in r["description"])
    assert lunch["amount"] == -3550 and lunch["category"] == "dining"
    assert next(r for r in rows if "工资" in r["description"])["amount"] == 500000


def test_review_confirms_skips_and_learns(local):
    rows = local.import_csv("owner", "cba.csv", CBA, "AUD")["rows"]
    shop = next(r for r in rows if "WOOLWORTHS" in r["description"])
    dup = next(r for r in rows if r["duplicate_of"])
    items = [{"id": r["id"], "include": r["id"] != dup["id"]} for r in rows]
    items[[i["id"] for i in items].index(shop["id"])]["category"] = "shopping"
    result = local.review("owner", items)
    assert result == {"confirmed": 5, "skipped": 1, "learned": 1}
    summary = local.spending_summary("2026-10")["currencies"]["AUD"]
    assert summary["categories"]["shopping"] == 5420 and "income" not in summary["categories"]
    assert summary["total"] == 5420 + 4000 + 80000
    assert suggest_category("WOOLWORTHS 9999 MELBOURNE", local._rules_snapshot())[0] == "shopping"
    with pytest.raises(Denied):
        local.review("agent", items)


def test_quick_add_parsing(local):
    q = local.parse_quick("lunch 12.50")
    assert (q["amount"], q["currency"], q["category"], q["date"]) == (-1250, "AUD", "dining", str(date.today()))
    assert local.parse_quick("bus pass 40")["category"] == "transport"
    y = local.parse_quick("昨天 打车 23.5元")
    assert y["currency"] == "CNY" and y["amount"] == -2350 and y["date"] == str(date.today() - timedelta(days=1))
    assert local.parse_quick("cà phê 45000 VND")["amount"] == -45000
    with pytest.raises(Denied):
        local.parse_quick("lunch with friends")


def test_recurring_creates_expected_entries_to_confirm(local):
    first = local.add_expense("owner", str(date.today() - timedelta(days=30)), -80000, "AUD", "Rent", "rent", recurring="monthly")
    assert first["status"] == "confirmed"
    expected = local.expenses(status="expected")
    assert len(expected) == 1 and expected[0]["amount"] == -80000
    local.refresh_reminders()
    assert any(r["kind"] == "expense_expected" for r in local.reminders()) or expected[0]["date"] > str(date.today() + timedelta(days=1))
    local.review("owner", [{"id": expected[0]["id"], "amount": 85000}])  # adjust once, it sticks
    assert local.recurring_list()[0]["amount"] == 85000
    assert local.materialize_recurring() == 0  # no duplicate expected entries


def test_agent_logs_pending_expense(local):
    agent = Agent(local)
    entry = agent.tool("log_expense", {"text": "bubble tea 6.80"})
    assert entry["status"] == "pending" and entry["amount"] == -680
    reply = agent.chat("记一笔 午饭 35元", "exp", "zh-CN")
    assert reply["trace"][-1]["tool"] == "log_expense" and reply["trace"][-1]["result"]["currency"] == "CNY"


def test_receipt_extraction_with_and_without_model(local, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    img = "data:image/png;base64," + "A" * 100
    assert Agent(local).read_receipt(img)["available"] is False
    with pytest.raises(Denied):
        Agent(local).read_receipt("not an image")
    reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(
        {"date": "2026-10-12", "total": "23.40", "currency": "AUD", "merchant": "Coles Central", "category": "groceries"})))])
    seen = []
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: seen.append(kw) or reply)))
    result = Agent(local, client=client, model="gpt-6-luna").read_receipt(img)
    assert result == {**result, "available": True, "amount": -2340, "date": "2026-10-12", "category": "groceries", "merchant": "Coles Central"}
    assert seen[0]["messages"][0]["content"][1]["image_url"]["url"] == img
    assert local.expenses() == []  # extraction never saves; the student confirms first


def test_exchange_reminders_percentile_and_date(local):
    class Hist:
        def latest(self, s, t): return dict(rate="4.70", observed="2026-10-16", provider="test", derived=False)
        def fetch(self, s, t, d): return dict(percentile="85.0")
    local.rates = Hist()
    local.add_rate_alert("owner", source="AUD", target="CNY", condition="percentile", threshold="80")
    local.add_rate_alert("owner", source="AUD", target="CNY", condition="date", due_date=str(date.today()))
    local.add_rate_alert("owner", source="AUD", target="CNY", condition="date", due_date=str(date.today() + timedelta(days=5)))
    assert len(local.check_rate_alerts()) == 2 and local.check_rate_alerts() == []
    kinds = sorted(r["kind"] for r in local.reminders())
    assert kinds == ["exchange_due", "rate_favorable"]
    with pytest.raises(Denied):
        local.add_rate_alert("owner", source="AUD", target="CNY", condition="percentile", threshold="20")


def test_spending_api(local, monkeypatch):
    monkeypatch.setenv("OWNER_TOKEN", "o" * 32)
    monkeypatch.setenv("AGENT_TOKEN", "a" * 32)
    with TestClient(create_app(local, background=False)) as client:
        owner, agent = {"Authorization": "Bearer " + "o" * 32}, {"Authorization": "Bearer " + "a" * 32}
        imp = client.post("/expenses/import", headers=owner, json={"filename": "s.csv", "content": CBA, "currency": "AUD"}).json()
        assert len(imp["rows"]) == 6
        assert client.post("/expenses/import", headers=agent, json={"content": CBA}).status_code == 409
        r = client.post("/expenses/review", headers=owner, json={"items": [{"id": x["id"]} for x in imp["rows"]]}).json()
        assert r["confirmed"] == 6
        assert client.post("/expenses/parse", headers=owner, json={"text": "lunch 9"}).json()["amount"] == -900
        assert "AUD" in client.get("/expenses/summary?month=2026-10", headers=owner).json()["currencies"]
        assert client.get("/recurring", headers=owner).status_code == 200
