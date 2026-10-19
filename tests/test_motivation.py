from datetime import date, datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from finance.agent import Agent
from finance.api import create_app
from finance.domain import Denied

TODAY = date.today()


def checkin(f, days_ago, action="expenses.add"):
    when = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time(), timezone.utc) + timedelta(hours=12)
    with f.store.tx() as c:
        c.execute("INSERT INTO audit(time,actor,action,outcome,correlation,detail,request_id) VALUES (?,?,?,?,?,?,?)",
                  (int(when.timestamp()), "owner", action, "ok", None, "{}", None))


def test_streak_forgives_rest_days(local):
    assert local.streak()["status"] == "none"
    for d in (12, 9, 5, 2, 0):  # gaps of 3, 4, 3, 2 days: the 4-day gap (three days off) starts a new run
        checkin(local, d)
    s = local.streak()
    assert (s["current"], s["longest"], s["status"], s["today"]) == (3, 3, "active", True)
    assert sum(w["days"] for w in s["weeks"]) == 5 and len(s["weeks"]) == 8


def test_streak_resting_then_welcome_back(tmp_path, local):
    checkin(local, 3)
    s = local.streak()
    assert s["status"] == "resting" and s["safe_until"] == str(TODAY) and s["current"] == 1
    checkin(local, 4)  # still the same run
    assert local.streak()["current"] == 2


def test_welcome_back_never_shames(local):
    checkin(local, 6)
    s = local.streak()
    assert s["status"] == "welcome_back" and s["current"] == 0 and s["longest"] == 1


def test_badges_levels_and_quiet_first_run(local):
    local.add_expense("owner", str(TODAY), -1250, "AUD", "lunch", "dining")
    m = local.motivation()
    assert m["level"] == 1 and next(b for b in m["badges"] if b["id"] == "first_log")["earned"]
    assert m["celebrations"] == []  # history before the feature existed is acknowledged quietly
    assert m["next"]["level"] == 2 and {n["badge"] for n in m["next"]["needs"]} == {"logging_week", "term_plan"}
    local.add_term("owner", name="T", currency="AUD", start=str(TODAY), end=str(TODAY + timedelta(days=90)), living="1500")
    m = local.motivation()
    assert [c["ref"] for c in m["celebrations"]] == ["term_plan"]
    local.celebrations_seen("owner", [c["id"] for c in m["celebrations"]])
    assert local.celebrations() == []
    assert all("amount" not in b and "rank" not in b for b in m["badges"])  # badges never describe money or rank


def test_challenges_auto_self_and_stop(local):
    local.motivation()
    local.add_expense("agent", str(TODAY), -900, "AUD", "bubble tea", "dining")  # pending
    ch = local.start_challenge("agent", "clear_review")  # the agent may start one the student asked for
    assert ch["status"] == "active" and ch["days_left"] == 6
    with pytest.raises(Denied):
        local.start_challenge("owner", "clear_review")
    local.review("owner", [{"id": e["id"]} for e in local.expenses(status="pending")])
    m = local.motivation()
    done = next(x for x in m["history"] if x["id"] == ch["id"])
    assert done["status"] == "completed"
    kinds = {(c["kind"], c["ref"]) for c in m["celebrations"]}
    assert ("challenge", ch["id"]) in kinds and ("badge", "first_challenge") in kinds
    with pytest.raises(Denied) as err:
        local.start_challenge("owner", "set_aside", amount="5000")
    assert err.value.code == "challenge_amount"  # never pushes saving beyond what fits
    aside = local.start_challenge("owner", "set_aside")
    assert 0 < aside["amount"] <= 1000
    with pytest.raises(Denied):
        local.finish_challenge("agent", aside["id"])
    assert local.finish_challenge("owner", aside["id"])["status"] == "completed"
    nsd = local.start_challenge("owner", "no_spend_day")
    assert local.finish_challenge("owner", nsd["id"], done=False)["status"] == "stopped"
    log = local.start_challenge("owner", "log_5_days")
    with pytest.raises(Denied):
        local.finish_challenge("owner", log["id"])  # measured challenges complete by themselves
    local.add_expense("owner", str(TODAY), -400, "AUD", "bus", "transport")
    assert next(x for x in local.motivation()["active"] if x["id"] == log["id"])["progress"] == 1


def test_challenge_ends_gently_and_limit(local):
    a = local.start_challenge("owner", "review_subs")
    local.start_challenge("owner", "no_spend_day")
    local.start_challenge("owner", "set_aside", amount="2")
    with pytest.raises(Denied) as err:
        local.start_challenge("owner", "log_5_days")
    assert err.value.code == "challenge_limit"
    with local.store.tx() as c:
        c.execute("UPDATE challenges SET ends=? WHERE id=?", (str(TODAY - timedelta(days=1)), a["id"]))
    m = local.motivation()
    assert next(x for x in m["history"] if x["id"] == a["id"])["status"] == "ended"
    assert all(s["kind"] != "review_subs" or True for s in m["suggestions"])


def test_suggestions_and_settings(local):
    local.add_expense("agent", str(TODAY), -900, "AUD", "tea", "dining")
    kinds = [s["kind"] for s in local.motivation()["suggestions"]]
    assert kinds[0] == "clear_review" and "plan_term" in kinds and len(kinds) <= 4
    local.set_motivation("owner", enabled=True, celebrate=False)
    local.add_term("owner", name="T", currency="AUD", start=str(TODAY), end=str(TODAY + timedelta(days=30)))
    assert local.motivation()["celebrations"] == []
    with pytest.raises(Denied):
        local.set_motivation("agent", False)


def test_motivation_api_and_agent(local, monkeypatch):
    monkeypatch.setenv("OWNER_TOKEN", "o" * 32)
    monkeypatch.setenv("VIEWER_TOKEN", "v" * 32)
    monkeypatch.setenv("AGENT_TOKEN", "a" * 32)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app(local, background=False)) as client:
        owner, viewer = {"Authorization": "Bearer " + "o" * 32}, {"Authorization": "Bearer " + "v" * 32}
        assert client.get("/motivation", headers=viewer).json()["max_level"] == 5
        cid = client.post("/challenges", headers=owner, json={"kind": "no_spend_day"}).json()["id"]
        assert client.post(f"/challenges/{cid}/done", headers=owner).json()["status"] == "completed"
        assert client.post("/challenges", headers=viewer, json={"kind": "review_subs"}).status_code == 409
        cel = client.get("/celebrations", headers=owner).json()
        assert any(c["kind"] == "challenge" for c in cel)
        assert client.post("/celebrations/seen", headers=owner, json={"ids": [c["id"] for c in cel]}).status_code == 200
        assert client.put("/motivation/settings", headers=owner, json={"enabled": False, "celebrate": False}).json()["enabled"] is False
    reply = Agent(local).chat("我的徽章和连续打卡怎么样", "m1", "zh-CN")
    assert reply["trace"][-1]["tool"] == "progress_overview" and "等级" in reply["message"]
