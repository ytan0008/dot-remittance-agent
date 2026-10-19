import json
import math
from datetime import date, timedelta
from fastapi.testclient import TestClient
import pytest
from finance.api import create_app
from finance.domain import Denied, now
from test_student import smtp  # noqa: F401  (fixture)

TODAY = date.today()
D = lambda n: str(TODAY + timedelta(days=n))


def student(local):
    local.set_cash("owner", "AUD", "1000")
    local.set_cash("owner", "CNY", "60000")
    local.add_term("owner", name="Semester 1", currency="AUD", start=D(0), end=D(90), tuition="5000", tuition_due=D(10), living="0")


def test_plan_both_sides_and_the_sandbox(local):
    student(local)
    tuition = local.save_plan("owner", "CNY", "AUD", "4000", "receive", D(8), "Tuition", "tuition")
    assert tuition["receive"] == 400000 and tuition["spend"] == math.ceil(4000 / 0.2155 * 100) and tuition["side"] == "receive"
    spend = local.save_plan("agent", "CNY", "AUD", "1000", "spend", purpose="Books")  # the assistant may draft a plan
    assert spend["spend"] == 100000 and spend["receive"] == 21550 and spend["origin"] == "agent"
    sim = local.simulate("AUD")
    rows = {r["currency"]: r for r in sim["rows"]}
    assert rows["AUD"]["before"] == 100000 and rows["AUD"]["after"] == 100000 + 400000 + 21550
    assert rows["CNY"]["after"] == 6000000 - tuition["spend"] - 100000
    # Needs: tuition 5000 (term) + the purpose-only "Books" plan, which is spent once received.
    assert rows["AUD"]["need"] == 500000 + 21550 and rows["AUD"]["gap_now"] == 500000 + 21550 - 100000
    assert rows["AUD"]["gap_after"] == 0 and rows["AUD"]["known"]
    # Pretend money and a worse rate are for that one call only.
    what_if = {r["currency"]: r for r in local.simulate("AUD", extra=[{"currency": "USD", "amount": "300"}], rate_shift="-3")["rows"]}
    assert what_if["USD"]["before"] == 30000 and "USD" not in local.cash_balances()
    assert what_if["CNY"]["outflow"] > rows["CNY"]["outflow"]  # a worse rate costs more source money for the same AUD
    with pytest.raises(Denied):
        local.simulate(rate_shift="90")


def test_gaps_buffer_stress_and_suggestions(local):
    student(local)
    local.add_budget("owner", "buffer", "Emergency", "AUD", "500")
    sugg = local.plan_suggestions()
    assert sugg[0]["target"] == "AUD" and sugg[0]["source"] == "CNY" and sugg[0]["kind"] == "tuition"
    assert sugg[0]["amount"] == 500000 + 50000 - 100000  # the buffer stays untouched
    plan = local.save_plan("owner", "CNY", "AUD", "4500", "receive", D(9), "Tuition", "tuition", sugg[0]["need_ref"])
    assert local.plan_suggestions() == []  # covered, and the need is linked to the plan
    gaps = local.currency_gaps("AUD")
    assert gaps["gaps"][0]["currency"] == "AUD" and gaps["gaps"][0]["gap_after"] == 0 and gaps["gaps"][0]["gap_stressed"] == 0
    local.save_plan("owner", "CNY", "AUD", "900", "spend", D(9), "Tuition", "tuition", plan_id=plan["id"])  # pay in CNY instead: falls short
    gap = local.currency_gaps("AUD")["gaps"][0]
    assert gap["gap_after"] == 550000 - 100000 - 19395 and gap["gap_stressed"] > gap["gap_after"]


def test_plan_reminders_and_status(local):
    student(local)
    p = local.save_plan("owner", "CNY", "AUD", "100000", "spend", D(2), "Too much")  # takes out more CNY than held
    local.refresh_reminders()
    kinds = {r["kind"]: r for r in local.reminders()}
    assert kinds["plan_short"]["severity"] == "alert" and kinds["plan_due"]["severity"] == "alert"
    local.save_plan("owner", "CNY", "AUD", "1000", "spend", D(2), "Small", plan_id=p["id"])
    local.refresh_reminders()
    kinds = {r["kind"]: r for r in local.reminders()}
    assert "plan_short" not in kinds and kinds["currency_gap"]["severity"] == "alert"  # the "Small" plan's own need is due in 2 days
    with pytest.raises(Denied):
        local.set_plan_status("agent", p["id"], "done")  # only a person says it happened
    assert local.set_plan_status("owner", p["id"], "done")["status"] == "done"
    assert local.exchange_plans() == [] and len(local.exchange_plans(include_closed=True)) == 1
    with pytest.raises(Denied):
        local.delete_plan("agent", p["id"])
    local.delete_plan("owner", p["id"])
    with pytest.raises(Denied):
        local.save_plan("owner", "CNY", "CNY", "1")
    with pytest.raises(Denied):
        local.save_plan("viewer", "CNY", "AUD", "1")


def test_plans_are_the_watch_needs(local):
    p = local.save_plan("owner", "AUD", "CNY", "5000", "receive", D(3), "Rent", min_rate="4.70")
    assert local.watch("AUD", "CNY")["active"]  # a planned pair is watched
    needs = local.pair_plan_needs("AUD", "CNY")
    assert needs == dict(amount=500000, deadline=D(3), min_rate="4.70", note="Rent", plans=1)
    assert p["below_min_rate"] is True  # 4.64 < 4.70


def test_virtual_ledger_shows_simulated_payments(local):
    from conftest import approved
    t = approved(local)
    ledger = local.virtual_ledger()
    move = next(m for m in ledger["moves"] if m["id"] == t["id"])
    assert move["effect"] == "open" and move["amount"] < 0 and ledger["funds"]


def test_daily_digest_with_money_and_quiet_skip(local, smtp):
    student(local)
    local.save_plan("owner", "CNY", "AUD", "1000", "spend", D(9), "Tuition", "tuition")
    local.set_email("owner", "me@uni.edu", "daily", False, "en", skip_quiet=True)
    assert local.email_tick() == ["digest"]
    body = smtp.sent[-1].get_body(("plain",)).get_content()
    assert "daily money check" in smtp.sent[-1]["Subject"] and "Currency gaps" in body and "AUD: short" in body and "Exchange plans" in body
    with local.store.tx() as c:  # next day, nothing changed: no second identical email
        s = json.loads(c.execute("SELECT value FROM student_settings WHERE key='email'").fetchone()[0])
        s["last_digest"] = now() - 86400 - 60
        local._put_setting(c, "email", s)
    assert local.email_tick() == []
    with pytest.raises(Denied):
        local.set_email("owner", "me@uni.edu", "hourly")
    assert local.set_email("owner", "me@uni.edu", "weekly", weekday=4)["weekday"] == 4


def test_plans_api_and_chat(local, monkeypatch):
    monkeypatch.setenv("OWNER_TOKEN", "o" * 32)
    monkeypatch.setenv("AGENT_TOKEN", "a" * 32)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    student(local)
    with TestClient(create_app(local, background=False)) as client:
        owner, agent = {"Authorization": "Bearer " + "o" * 32}, {"Authorization": "Bearer " + "a" * 32}
        p = client.post("/exchange-plans", headers=agent, json={"source": "CNY", "target": "AUD", "amount": "2000", "due": D(9)}).json()
        assert p["status"] == "planned" and p["receive"] == 200000
        assert client.post(f"/exchange-plans/{p['id']}/status", headers=agent, json={"status": "done"}).status_code == 409
        sim = client.post("/simulate", headers=owner, json={"display": "AUD", "extra": [{"currency": "AUD", "amount": "-100"}]}).json()
        assert next(r for r in sim["rows"] if r["currency"] == "AUD")["before"] == 90000
        m = client.get("/overview/money?display=AUD", headers=owner).json()
        assert m["plans"][0]["id"] == p["id"] and m["simulation"]["rows"] and "gaps" in m and "ledger" in m
        assert client.get("/gaps", headers=owner).json()["stress_pct"] == -3
    from finance.agent import Agent
    a = Agent(local)
    reply = a.chat("模拟一下按计划换完还剩多少", "sim", "zh-CN")
    assert reply["trace"][-1]["tool"] == "simulate_exchange" and "AUD" in reply["message"]
    reply = a.chat("I plan to exchange 300 AUD to CNY", "plan", "en")
    assert reply["trace"][-1]["tool"] == "plan_exchange" and len(local.exchange_plans()) == 2
    reply = a.chat("换钱计划", "plan2", "zh-CN")
    assert reply["trace"][-1]["tool"] == "request_details" and reply["trace"][-1]["result"]["form"] == "plan"


def test_dated_sandbox_timeline(local):
    student(local)
    plan = local.save_plan("owner", "CNY", "AUD", "4000", "receive", D(5), "Tuition", "tuition")
    local.add_recurring("owner", "Spotify", 1299, "AUD", "subscriptions", "monthly", D(-20))
    local.add_obligation("owner", title="Rent", amount="800", currency="AUD", due_date=D(3))
    tl = local.timeline("AUD", days=60)
    keys = {e["key"] for e in tl["events"]}
    assert f"plan:{plan['id']}" in keys and any(k.startswith("rec:") for k in keys) and any(k.startswith("bill:") for k in keys)
    assert any(k.startswith("tuition:") for k in keys)
    dates = [e["date"] for e in tl["events"]]
    assert dates == sorted(dates) and tl["today"] == str(TODAY)
    aud = [e for e in tl["events"] if e["currency"] == "AUD"]
    assert aud[-1]["balance"] == tl["end_balances"]["AUD"]
    # Switching the plan off removes its two legs; a scenario from the Send page adds its own.
    off = local.timeline("AUD", off=[f"plan:{plan['id']}"], days=60,
                         scenario={"source": "CNY", "target": "AUD", "label": "BOC", "legs": [{"date": D(1), "spend": 100000, "receive": 21000}]})
    assert f"plan:{plan['id']}" not in {e["key"] for e in off["events"]}
    assert next(g for g in off["sources"] if g["key"] == f"plan:{plan['id']}")["on"] is False
    assert sum(e["amount"] for e in off["events"] if e["key"] == "scenario" and e["currency"] == "AUD") == 21000
    assert "AUD" in off["negative"] or off["lowest"]["AUD"]["amount"] >= 0


def test_goals_become_exchange_plans_with_their_progress(local, tmp_path):
    from conftest import FakeRates
    from finance.service import Finance
    g = local.create_goal("owner", title="Family support", source="AUD", target="CNY", target_amount="2000", deadline=D(30), category="family")
    with local.store.tx() as c:  # a completed payment linked to the goal
        c.execute("INSERT INTO transfers(id,idem,request,body,status,created,rail,goal_id) VALUES (?,?,?,?,?,?,?,?)",
                  ("t-done", "k1", "{}", json.dumps({"receive": 50000, "source": "AUD", "target": "CNY", "rail": "sandbox"}), "completed", 1, "sandbox", g["id"]))
    again = Finance(local.config, rates=FakeRates())  # the next start converts it
    plan = next(p for p in again.exchange_plans() if p["id"] == g["id"])
    assert plan["kind"] == "goal" and plan["total"] == 200000 and plan["sent"] == 50000 and plan["progress_pct"] == 25
    assert plan["amount"] == 150000 and plan["receive"] == 150000  # only what is left still needs exchanging
    assert all(x["id"] != g["id"] for x in again.goals())  # the goal itself is archived
    assert again.save_plan("owner", "AUD", "CNY", "100", recipient_id="family", category="family")["recipient_id"] == "family"
    with pytest.raises(Denied):
        again.save_plan("owner", "AUD", "CNY", "100", recipient_id="nobody")
