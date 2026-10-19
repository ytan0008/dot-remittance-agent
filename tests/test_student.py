import json
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from finance import mailer
from finance.agent import Agent
from finance.api import create_app
from finance.domain import Denied, now

TODAY = date.today()


def d(days):
    return str(TODAY + timedelta(days=days))


def first_of_next_month():
    return (TODAY.replace(day=28) + timedelta(days=4)).replace(day=1)


def test_scholarship_tracker_and_deadline_reminders(local):
    s = local.add_scholarship("owner", name="Global Excellence", provider="UniSyd", amount="5000", currency="AUD", deadline=d(5),
                              documents=["Transcript", {"name": "Personal statement", "done": True}, "Reference letter"])
    assert (s["docs_total"], s["docs_done"], s["days_left"], s["open"], s["amount"]) == (3, 1, 5, True, 500000)
    local.add_scholarship("agent", name="Travel grant", kind="grant", deadline=d(40))  # the agent may start tracking one
    with pytest.raises(Denied):
        local.add_scholarship("viewer", name="x")
    with pytest.raises(Denied):
        local.add_scholarship("owner", name="bad link", url="javascript:alert(1)")
    assert [x["name"] for x in local.scholarships()] == ["Global Excellence", "Travel grant"]
    local.refresh_reminders()
    rem = [r for r in local.reminders() if r["kind"] == "scholarship_due"]
    assert rem and rem[0]["data"]["missing"] == 2 and rem[0]["data"]["days_left"] == 5
    docs = [dict(x, done=True) for x in s["documents"]]
    u = local.update_scholarship("owner", s["id"], status="submitted", documents=docs)
    assert u["docs_done"] == 3 and not u["open"]
    local.refresh_reminders()
    assert not [r for r in local.reminders() if r["kind"] == "scholarship_due"]  # submitted: nothing left to chase
    with pytest.raises(Denied):
        local.update_scholarship("agent", s["id"], status="awarded")


def test_cashflow_spreads_living_costs_and_lands_tuition(local):
    with pytest.raises(Denied):
        local.add_term("owner", name="bad", currency="AUD", start=d(10), end=d(1))
    nxt = first_of_next_month()
    local.add_term("owner", name="Semester 2", currency="AUD", start=d(-20), end=str(nxt + timedelta(days=60)), tuition="3000",
                   tuition_due=d(3), living="1500", income="800")
    plan = local.cashflow("AUD")
    assert plan["opening"]["total"] == 100000 and plan["terms"] == ["Semester 2"]
    month = next(m for m in plan["months"] if m["month"] == nxt.strftime("%Y-%m"))
    assert (month["living"], month["income"]) == (150000, 80000)  # a full month sums exactly
    assert any(e["kind"] == "tuition" and e["amount"] == -300000 for e in plan["events"])
    assert plan["first_negative"] == d(3) and plan["lowest"]["amount"] < 0
    assert local.cashflow("AUD")["months"][0]["tuition"] == 300000


def test_cashflow_without_terms_uses_spending_baseline(local):
    for i in range(3):
        local.add_expense("owner", d(-10 - i * 20), -30000, "AUD", "Woolworths", "groceries")
    plan = local.cashflow("AUD", months=2)
    assert "no_terms" in plan["notes"] and "baseline_used" in plan["notes"]
    assert plan["baseline_monthly"] > 0 and plan["lowest"]["amount"] < plan["opening"]["total"]


def _comfortable(local):
    local.add_budget("owner", "holding", "Bank account", "AUD", "6000")
    local.add_budget("owner", "buffer", "Emergency", "AUD", "500")
    local.add_term("owner", name="Term", currency="AUD", start=d(-40), end=d(200), living="1500", income="1500")


def test_afford_yes_careful_no(local):
    _comfortable(local)
    yes = local.afford("viewer", "120", "AUD", label="Headphones")
    assert yes["verdict"] == "yes" and yes["cash"] == 700000 and yes["lowest_after"] >= yes["buffer"]
    local.add_expense("owner", str(TODAY), -140000, "AUD", "Rent top-up", "rent")
    tight = local.afford("agent", "300", "AUD")
    assert tight["verdict"] == "careful" and any(r["code"] == "month_over" for r in tight["reasons"])
    assert tight["wait_until"] == str(first_of_next_month())  # the next month's budget covers it
    no = local.afford("owner", "9000", "AUD")
    assert no["verdict"] == "no" and any(r["code"] == "negative" for r in no["reasons"]) and no["shortfall"] > 0
    with pytest.raises(Denied):
        local.afford("owner", "-5", "AUD")
    with pytest.raises(Denied):
        local.afford("owner", "10", "AUD", day=d(-3))


def test_afford_counts_upcoming_tuition(local):
    _comfortable(local)
    local.add_term("owner", name="Fees", currency="AUD", start=d(1), end=d(30), tuition="5000", tuition_due=d(10))
    r = local.afford("owner", "1600", "AUD")  # lowest point after tuition: 2000 - 1600 < 500 buffer
    assert r["verdict"] != "yes"
    assert next(x for x in r["reasons"] if x["code"] == "upcoming")["amount"] == 500000


def test_spending_insights_tips(local):
    assert local.spending_insights("month")["tips"][0]["kind"] == "no_data"
    for window in (1, 2, 3):  # a steady baseline of 100 AUD eating out per 30 days
        local.add_expense("owner", d(-30 * window - 5), -10000, "AUD", "Thai Kitchen", "dining")
    local.add_expense("owner", d(-2), -25000, "AUD", "Thai Kitchen", "dining")
    for i in range(7):
        local.add_expense("owner", d(-i), -550, "AUD", f"Starbucks {1000 + i}", "dining")
    local.add_expense("agent", d(0), -1200, "AUD", "Bubble tea", "dining")  # pending
    r = local.spending_insights("month", "en")
    kinds = [t["kind"] for t in r["tips"]]
    assert {"category_up", "frequent", "pending", "top_category"} <= set(kinds)
    up = next(t for t in r["tips"] if t["kind"] == "category_up")
    assert "Eating out" in up["text"] and "Cooking" in up["text"]
    assert r["total"] == 25000 + 7 * 550 and r["change_pct"] > 100
    zh = local.spending_insights("week", "zh-CN")
    assert any("外出就餐" in t["text"] or "Starbucks" in t["text"] for t in zh["tips"])
    with pytest.raises(Denied):
        local.spending_insights("year")


def test_insights_compare_with_term_budget(local):
    local.add_term("owner", name="Term", currency="AUD", start=d(-60), end=d(60), living="300")
    local.add_expense("owner", d(-1), -60000, "AUD", "Coles", "groceries")
    r = local.spending_insights("week", "en")
    over = next(t for t in r["tips"] if t["kind"] == "budget_over")
    assert over["severity"] == "warn" and "over your term budget" in over["text"]


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_FROM", "dot@test.example")
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def test_email_settings_validation(local, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    for bad in ("not-an-email", "a@b.com\nBcc: x@y.com", "a@b"):
        with pytest.raises(Denied):
            local.set_email("owner", bad, "weekly")
    with pytest.raises(Denied):
        local.set_email("agent", "me@uni.edu", "weekly")
    s = local.set_email("owner", "me@uni.edu", "weekly", True, "zh-CN")
    assert s["configured"] is False and s["digest"] == "weekly" and s["language"] == "zh-CN"
    assert local.email_tick() == []  # nothing is sent without SMTP
    with pytest.raises(Denied) as err:
        local.send_report("owner")
    assert err.value.code == "email_unconfigured"


def test_email_report_digest_and_reminders(local, smtp):
    with pytest.raises(Denied):
        local.send_report("owner")  # no address yet
    local.set_email("owner", "me@uni.edu", "weekly", True, "en")
    local.add_expense("owner", d(-1), -4500, "AUD", "Coles", "groceries")
    r = local.send_report("owner", "week")
    msg = smtp.sent[-1]
    assert msg["To"] == "me@uni.edu" and "weekly money check" in msg["Subject"]
    body = msg.get_body(("plain",)).get_content()
    assert "Groceries: 45.00 AUD" in body and "Suggestions" in body
    assert "<script" not in msg.get_body(("html",)).get_content()
    assert r["to"] != "me@uni.edu"  # masked
    with pytest.raises(Denied) as err:
        local.send_report("owner")
    assert err.value.code == "email_rate"
    log = local.email_settings()["log"]
    assert log[0]["status"] == "sent" and "me@uni.edu" not in json.dumps(log)
    # A due weekly digest and a new important reminder each go out once.
    with local.store.tx() as c:
        s = json.loads(c.execute("SELECT value FROM student_settings WHERE key='email'").fetchone()[0])
        s["last_digest"] = now() - 8 * 86400
        local._put_setting(c, "email", s)
    local.add_scholarship("owner", name="Merit award", deadline=d(2), documents=["CV"])
    local.refresh_reminders()
    assert local.email_tick() == ["digest", "reminders"]
    assert "Merit award" in smtp.sent[-1].get_body(("plain",)).get_content()
    assert local.email_tick() == []


def test_student_api_and_agent(local, smtp, monkeypatch):
    monkeypatch.setenv("OWNER_TOKEN", "o" * 32)
    monkeypatch.setenv("AGENT_TOKEN", "a" * 32)
    monkeypatch.setenv("VIEWER_TOKEN", "v" * 32)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app(local, background=False)) as client:
        owner, viewer = {"Authorization": "Bearer " + "o" * 32}, {"Authorization": "Bearer " + "v" * 32}
        sid = client.post("/scholarships", headers=owner, json={"name": "Equity grant", "deadline": d(20), "documents": ["ID"]}).json()["id"]
        assert client.patch(f"/scholarships/{sid}", headers=owner, json={"status": "preparing"}).json()["status"] == "preparing"
        assert client.post("/terms", headers=owner, json={"name": "T1", "currency": "AUD", "start": d(0), "end": d(90),
                                                          "living": "1200", "income": "900"}).status_code == 200
        assert client.get("/cashflow?currency=AUD", headers=viewer).json()["terms"] == ["T1"]
        assert client.post("/afford", headers=viewer, json={"amount": "50", "currency": "AUD"}).json()["verdict"] in ("yes", "careful")
        assert client.get("/insights?period=week&lang=ja", headers=viewer).json()["language"] == "ja"
        assert client.get("/email", headers=viewer).status_code == 409
        assert client.put("/email", headers=owner, json={"address": "me@uni.edu", "digest": "monthly"}).json()["digest"] == "monthly"
        assert "subject" in client.post("/email/preview", headers=owner, json={"period": "month"}).json()
    agent = Agent(local)
    reply = agent.chat("我能买得起 300 澳元的耳机吗", "s1", "zh-CN")
    assert reply["trace"][-1]["tool"] == "afford_check" and "300.00 AUD" in reply["message"]
    reply = agent.chat("show my scholarship deadlines", "s2", "en")
    assert reply["trace"][-1]["tool"] == "list_scholarships" and "Equity grant" in reply["message"]
    reply = agent.chat("给我本周的消费总结和建议", "s3", "zh-CN")
    assert reply["trace"][-1]["tool"] == "spending_insights"
