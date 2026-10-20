"""Codex security audit, round two (N01–N07) and its controls, kept as regular tests."""
import sys
import os
import json
from pathlib import Path
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from contextlib import contextmanager
import pytest
import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from test_security_audit import isolated, f, app, signup, H, PASSWORD
from finance.domain import Denied


@pytest.fixture(autouse=True)
def block_streams(monkeypatch):
    def blocked(*a, **kw):
        raise RuntimeError("Network blocked by extended security audit")
    monkeypatch.setattr(httpx, "stream", blocked)


READ_PATHS = [
    "/account/export", "/agent/memory", "/audit", "/accounts", "/expenses",
    "/expenses/summary", "/exchange-plans", "/cashflow", "/budget",
    "/balances", "/recipients", "/transfers", "/settings", "/memory",
    "/goals", "/obligations", "/habits", "/reminders", "/rate-alerts",
    "/terms", "/scholarships", "/email", "/transfer-templates",
    "/fx-rules", "/overview/money",
]


@pytest.mark.parametrize("path", READ_PATHS)
def test_anonymous_route_matrix(app, path):
    with TestClient(app) as c:
        assert c.get(path).status_code == 401


@pytest.mark.parametrize("token", ["", "wrong", "owner", "../default", "null", "' OR 1=1", "a"*32, "o"*32])
def test_claim_rejects_invalid_owner_tokens(app, token):
    with TestClient(app) as c:
        assert signup(c, "alice").status_code == 200
        r = c.post("/auth/claim", headers=H, json={"owner_token": token})
        assert 400 <= r.status_code < 500
        assert c.get("/session").json()["user"]["original"] is False


@pytest.mark.parametrize("seed", range(5))
def test_same_rule_eight_parallel_requests_credit_once(f, monkeypatch, seed):
    f.set_cash("owner", "AUD", str(100 + seed))
    rule = f.add_fx_rule("owner", "AUD", "CNY", str(100 + seed), "4")
    gate = Barrier(8)
    def savings(*a, **kw):
        gate.wait(timeout=12)
        return None
    monkeypatch.setattr(f, "savings", savings)
    def run(_):
        try:
            f.execute_fx_rule("owner", rule["id"])
            return True
        except Denied:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        success = list(pool.map(run, range(8)))
    assert sum(success) == 1
    assert f.cash_balances()["AUD"]["amount"] == 0
    assert f.cash_balances()["CNY"]["amount"] == (100 + seed)*464


@pytest.mark.parametrize("seed", range(5))
def test_different_rules_share_one_atomic_balance(f, monkeypatch, seed):
    f.set_cash("owner", "AUD", "100")
    rules = [f.add_fx_rule("owner", "AUD", "CNY", "100", "4") for _ in range(6)]
    gate = Barrier(6)
    def savings(*a, **kw):
        gate.wait(timeout=12)
        return None
    monkeypatch.setattr(f, "savings", savings)
    def run(r):
        try:
            f.execute_fx_rule("owner", r["id"])
            return True
        except Denied:
            return False
    with ThreadPoolExecutor(max_workers=6) as pool:
        result = list(pool.map(run, rules))
    assert sum(result) == 1
    assert f.cash_balances()["CNY"]["amount"] == 46400


@pytest.mark.parametrize("n", range(1, 26))
def test_split_conserves_randomized_cent_amounts(f, n):
    from decimal import Decimal
    from random import Random
    cents = Random(n).randint(1, 1000000)
    f.set_bank_pricing("owner", "cba", "AUD", "CNY", {"rate":"4.55", "fee_send":{"amount":"0","currency":"AUD"},
                                                         "intermediary":{"amount":"0","currency":"AUD"}})
    f.rates.forecast = lambda *a: dict(available=True, data_cutoff=str(date.today()), horizon_days=7, point="4.70")
    result = f.exchange_scenarios("AUD", "CNY", str(Decimal(cents)/100), "send", "cba")
    split = next(s for s in result["scenarios"] if s["timing"] == "split")
    assert split["total_spend"] == cents
    assert split["rank"] is None


@pytest.mark.parametrize("quote,amount,currency", [
    ("AUD 60 or USD 6", "6", "AUD"),
    ("Fee AUD 60. Minimum transfer AUD 6", "6", "AUD"),
    ("Fee USD 60. AUD transfers are supported", "60", "AUD"),
    ("Transfer fee $6", "6", "AUD"),
])
def test_N01_ambiguous_monetary_evidence_must_not_be_certified(quote, amount, currency):
    from finance.banks import verify_evidence
    data = {"fee_send": {"amount": amount, "currency": currency}}
    assert "fee_send" in verify_evidence(data, {"fee_send": quote}, [("https://bank.example", quote)])


@pytest.mark.parametrize("currency", ["AUD","USD","EUR","GBP","CNY","JPY"])
@pytest.mark.parametrize("amount", ["6","20"])
def test_evidence_exact_amount_and_currency_control(currency, amount):
    from finance.banks import verify_evidence
    quote = f"Transfer fee {amount} {currency}"
    data = {"fee_send":{"amount":amount,"currency":currency}}
    assert verify_evidence(data, {"fee_send":quote}, [("https://bank.example",quote)]) == []


@pytest.mark.parametrize("bad", ["not-a-date","2026-02-30","../default","2026-99-99","0000-00-00"])
def test_N02_expense_patch_validates_dates(app, bad):
    with TestClient(app, raise_server_exceptions=False) as c:
        signup(c, "alice")
        r = c.post("/expenses", headers=H, json={"date":"2026-10-20","amount":-100,"currency":"AUD",
                                                "description":"groceries","category":"groceries"})
        assert r.status_code == 200
        change = c.patch("/expenses/"+r.json()["id"], headers=H, json={"date":bad})
        assert 400 <= change.status_code < 500, f"Invalid date stored: {change.status_code}"


@pytest.mark.parametrize("amount", [10**30, -(10**30)])
def test_N03_expense_patch_overflow_is_handled(app, amount):
    with TestClient(app, raise_server_exceptions=False) as c:
        signup(c, "alice")
        r = c.post("/expenses", headers=H, json={"date":"2026-10-20","amount":-100,"currency":"AUD",
                                                "description":"groceries","category":"groceries"})
        change = c.patch("/expenses/"+r.json()["id"], headers=H, json={"amount":amount})
        assert 400 <= change.status_code < 500, f"Uncaught overflow returns {change.status_code}"


@pytest.mark.parametrize("amount", ["not-a-number", "1.5", {}, [], 10**30])
def test_N03_review_nested_values_validated(app, amount):
    with TestClient(app, raise_server_exceptions=False) as c:
        signup(c, "alice")
        c.post("/expenses/import", headers=H, json={"currency":"AUD","filename":"a.csv",
                       "content":"Date,Description,Amount\n20/10/2026,COLES,-12\n"})
        row = c.get("/expenses?status=pending").json()[0]
        r = c.post("/expenses/review", headers=H, json={"items":[{"id":row["id"],"include":True,"amount":amount}]})
        assert 400 <= r.status_code < 500, f"Invalid nested amount returns {r.status_code}"


def test_N04_concurrent_signup_enforces_limit(tmp_path, monkeypatch):
    from finance.auth import Users, SIGNUPS_PER_HOUR
    users = Users(tmp_path/"users.db")
    original = users._db
    gate = Barrier(6)
    @contextmanager
    def synchronized():
        gate.wait(timeout=12)
        with original() as c:
            yield c
    monkeypatch.setattr(users, "_db", synchronized)
    def run(i):
        try:
            users.register(f"u{i}@example.invalid", PASSWORD, client="same-local-client")
            return True
        except Denied:
            return False
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run, range(6)))
    assert sum(results) <= SIGNUPS_PER_HOUR, f"{sum(results)} accounts bypass limit {SIGNUPS_PER_HOUR}"


def test_N05_future_statement_cannot_reuse_source_money(f):
    tomorrow = str(date.today()+timedelta(days=1))
    f.import_csv("owner", "future.csv", f"Date,Description,Amount,Balance\n{tomorrow},DEPOSIT,100,100\n", currency="AUD")
    for _ in range(2):
        r = f.add_fx_rule("owner","AUD","CNY","100","4")
        try:
            f.execute_fx_rule("owner",r["id"])
        except Denied:
            pass
    assert f.cash_balances().get("CNY",{}).get("amount",0) <= 46400, f"Future source balance reused: {f.cash_balances()}"


def test_N06_reimport_old_balance_cannot_undo_executed_debit(f):
    csv = f"Date,Description,Amount,Balance\n{date.today()},DEPOSIT,100,100\n"
    f.import_csv("owner","same.csv",csv,currency="AUD")
    r = f.add_fx_rule("owner","AUD","CNY","100","4")
    f.execute_fx_rule("owner",r["id"])
    f.import_csv("owner","same.csv",csv,currency="AUD")
    assert f.cash_balances()["AUD"]["amount"] == 0, "Duplicate import overwrites balance after debit"


def test_N07_expired_status_is_persisted(f):
    f.set_cash("owner","AUD","100")
    r=f.add_fx_rule("owner","AUD","CNY","100","4")
    with f.store.tx() as c:
        body=json.loads(c.execute("SELECT body FROM fx_rules WHERE id=?",(r["id"],)).fetchone()[0])
        body["due"]=str(date.today()-timedelta(days=1))
        c.execute("UPDATE fx_rules SET body=? WHERE id=?",(json.dumps(body),r["id"]))
    with pytest.raises(Denied):
        f.execute_fx_rule("owner",r["id"])
    assert next(x for x in f.fx_rules() if x["id"]==r["id"])["status"]=="expired"


def test_control_mid_transaction_failure_rolls_back(f, monkeypatch):
    f.set_cash("owner","AUD","100")
    r=f.add_fx_rule("owner","AUD","CNY","100","4")
    original=f._record_cash
    def failing(c, actor, currency, *args, **kw):
        if currency=="CNY":
            raise RuntimeError("Injected target-write failure")
        return original(c,actor,currency,*args,**kw)
    monkeypatch.setattr(f,"_record_cash",failing)
    with pytest.raises(RuntimeError):
        f.execute_fx_rule("owner",r["id"])
    assert f.cash_balances()["AUD"]["amount"]==10000
    assert "CNY" not in f.cash_balances()
    assert next(x for x in f.fx_rules() if x["id"]==r["id"])["status"]=="active"


@pytest.mark.parametrize("field,value", [("role","owner"),("workspace","default"),("claim_default",True),("user_id","default")])
def test_registration_mass_assignment_rejected(app, field, value):
    with TestClient(app) as c:
        r=c.post("/auth/register",headers=H,json={"email":"alice@example.invalid","password":PASSWORD,field:value})
        assert r.status_code==422


def test_deleted_session_replay_rejected(app):
    with TestClient(app) as c, TestClient(app) as attacker:
        signup(c,"alice")
        sid=c.cookies.get("finance_session")
        assert c.post("/account/delete",headers=H,json={"email":"alice@example.invalid","password":PASSWORD}).json()["deleted"]
        attacker.cookies.set("finance_session",sid)
        assert attacker.get("/account/export").status_code==401


@pytest.mark.parametrize("actor", ["agent","viewer"])
def test_owner_only_fx_rule_creation(f, actor):
    with pytest.raises(Denied):
        f.add_fx_rule(actor,"AUD","CNY","100","4")


@pytest.mark.parametrize("seed", range(3))
def test_cancel_during_execution_never_credits(f, monkeypatch, seed):
    from threading import Event
    f.set_cash("owner","AUD","100")
    r=f.add_fx_rule("owner","AUD","CNY","100","4")
    entered,release=Event(),Event()
    def wait(*a,**kw):
        entered.set()
        assert release.wait(10)
        return None
    monkeypatch.setattr(f,"savings",wait)
    def run():
        try:
            f.execute_fx_rule("owner",r["id"])
            return True
        except Denied:
            return False
    with ThreadPoolExecutor(max_workers=1) as pool:
        task=pool.submit(run)
        assert entered.wait(10)
        f.cancel_fx_rule("owner",r["id"])
        release.set()
        assert task.result() is False
    assert f.cash_balances()["AUD"]["amount"]==10000
    assert "CNY" not in f.cash_balances()


def test_a_current_statement_still_sets_the_balance_and_a_later_one_follows_a_debit(f):
    f.import_csv("owner", "a.csv", f"Date,Description,Amount,Balance\n{date.today() - timedelta(days=2)},DEPOSIT,100,100\n", currency="AUD")
    assert f.cash_balances()["AUD"]["amount"] == 10000
    r = f.add_fx_rule("owner", "AUD", "CNY", "40", "4")
    f.execute_fx_rule("owner", r["id"])
    assert f.cash_balances()["AUD"]["amount"] == 6000
    old = f.import_csv("owner", "old.csv", f"Date,Description,Amount,Balance\n{date.today() - timedelta(days=1)},DEPOSIT,5,105\n", currency="AUD")
    assert old["balance_note"] == "stale" and f.cash_balances()["AUD"]["amount"] == 6000
    future = f.import_csv("owner", "f.csv", f"Date,Description,Amount,Balance\n{date.today() + timedelta(days=1)},X,1,999\n", currency="AUD")
    assert future["balance_note"] == "future" and f.cash_balances()["AUD"]["amount"] == 6000


def test_review_rejects_a_bad_row_before_writing_anything(f):
    f.import_csv("owner", "a.csv", "Date,Description,Amount\n20/10/2026,COLES,-12\n21/10/2026,WOOLWORTHS,-8\n", currency="AUD")
    rows = f.expenses(status="pending")
    with pytest.raises(Denied):
        f.review("owner", [{"id": rows[0]["id"]}, {"id": rows[1]["id"], "amount": "12"}])
    assert len(f.expenses(status="pending")) == 2
