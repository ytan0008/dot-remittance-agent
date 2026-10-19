import pytest

from finance.domain import Denied
from finance.agent import Agent


@pytest.fixture
def planner(local):
    return Agent(local).rules


@pytest.mark.parametrize("message,intent,expected", [
    ("给 family 汇 100 澳元用于生活费", "prepare", {"amount": "100", "source": "AUD", "target": "CNY", "recipient": "family", "purpose": "生活费"}),
    ("Send 50 AUD to family for rent", "prepare", {"amount": "50", "source": "AUD", "recipient": "family", "purpose": "rent"}),
    ("family に生活費として 100 豪ドル送金", "prepare", {"amount": "100", "source": "AUD", "target": "CNY"}),
    ("Gửi 200 AUD cho family để chi tiêu", "prepare", {"amount": "200", "source": "AUD", "recipient": "family"}),
    ("查一下 AUD 兑 CNY 汇率", "rates", {"source": "AUD", "target": "CNY"}),
    ("If the rate becomes 3% less favorable on 1000 AUD to CNY?", "scenario", {"amount": "1000", "percent": "-3"}),
    ("환율 예측 AUD CNY", "forecast", {"source": "AUD", "target": "CNY"}),
])
def test_understanding(planner, message, intent, expected):
    got_intent, entities = planner.understand(message, "p")
    assert got_intent == intent
    assert expected.items() <= entities.items()


def test_follow_up_fills_missing_purpose(local):
    agent = Agent(local)
    first = agent.chat("Send 50 AUD to family", "f", "en")
    assert first["plan"]["missing"] and not first["trace"]
    second = agent.chat("monthly support", "f", "en")
    assert [t["tool"] for t in second["trace"]] == ["get_balances", "prepare_payment"]
    assert second["trace"][1]["result"]["details"]["purpose"] == "monthly support"


def test_rules_cannot_execute_unapproved(local):
    agent = Agent(local)
    agent.chat("Send 50 AUD to family for rent", "x", "zh-CN")
    reply = agent.chat("执行", "x", "zh-CN")
    assert "授权" in reply["message"]
    assert all(t["status"] == "draft" for t in local.history())


def suggestions():
    import re
    from pathlib import Path
    out = []
    for path in sorted(Path(__file__).resolve().parents[1].glob("frontend/dist/js/locales/*.js")):
        text = path.read_text(encoding="utf-8")
        for n, intent in (("s1", "prepare"), ("s2", "compare"), ("s3", "template"), ("s4", "balance")):
            prompt = re.search(rf"""'agent\.{n}': (?:'([^']+)'|"([^"]+)")""", text)
            prompt = prompt.group(1) or prompt.group(2)
            out.append((path.stem, prompt, intent))
    return out


@pytest.mark.parametrize("lang,prompt,intent", suggestions())
def test_every_localized_suggestion_is_understood(planner, lang, prompt, intent):
    got, entities = planner.understand(prompt, "sugg-" + lang)
    assert got == intent, (lang, prompt, entities)
    if intent == "prepare":
        assert {"amount", "source", "recipient", "purpose"} <= set(entities), (lang, entities)
        # Unambiguous wording: pay in CNY, the recipient receives 100 AUD.
        assert entities["source"] == "CNY" and entities["target"] == "AUD" and entities.get("receive") is True, (lang, entities)
    if intent == "scenario":
        assert entities["percent"] == "-3" and entities["amount"] == "1000"
    if intent == "compare":
        assert entities["source"] == "AUD" and entities["target"] == "CNY"


@pytest.mark.parametrize("message,name", [
    ("用人民币给 Mia 汇款，让对方收到 100 澳元，用于生活费", "Mia"),
    ("Pay in CNY so Mia receives 100 AUD, send to Mia for rent", "Mia"),
    ("Dùng CNY chuyển cho Mia để họ nhận 100 AUD", "Mia"),
    ("CNY로 Mia에게 송금해서 상대가 100 AUD를 받게, 용도: 생활비", "Mia"),
])
def test_unregistered_name_prefills_the_form(local, message, name):
    reply = Agent(local).chat(message, "nm", "zh-CN")
    step = reply["trace"][-1]
    assert step["tool"] == "request_details" and step["result"]["form"] == "recipient" and step["result"]["prefill"]["name"] == name
    assert "面板" in reply["message"]


def test_bank_details_in_chat_prefill_a_template_form(local):
    from finance.agent import Agent
    agent = Agent(local)
    reply = agent.chat("帮我做个SWIFT模板：收款人: UNSW Sydney, account GB82 WEST 1234 5698 7654 32, BIC NWBKGB2L, 银行: NatWest", "tpl", "zh-CN")
    step = reply["trace"][-1]
    assert step["tool"] == "request_details" and step["result"]["form"] == "template"
    pre = step["result"]["prefill"]
    assert pre["format"] == "swift" and pre["fields"]["bic"] == "NWBKGB2L" and pre["fields"]["beneficiary_name"] == "UNSW Sydney"
    assert "模板表单" in reply["message"] and local.transfer_templates() == []  # nothing is saved until the person checks it
    bsb = agent.chat("rent template: BSB 062-000, account number 12345678, name: J Smith", "tpl2", "en")["trace"][-1]["result"]["prefill"]
    assert bsb["format"] == "au_bsb" and bsb["fields"] == {"account_name": "J Smith", "account_number": "12345678", "bsb": "062-000"}


def test_execute_in_chat_points_to_the_person(local):
    from finance.agent import Agent
    from conftest import approved
    t = approved(local)
    reply = Agent(local).chat("execute it", "ex", "en")
    assert local.get(t["id"])["status"] == "approved" and "only you" in reply["message"]


def test_template_form_fills_what_the_model_left_out(local):
    from finance.agent import Agent
    from finance.tools import Context, REGISTRY
    agent = Agent(local)
    message = "SWIFT template please: name: UNSW Sydney, account GB82 WEST 1234 5698 7654 32, BIC NWBKGB2L"
    flat = REGISTRY["request_details"].run(Context(local, agent.memory, "s", message=message), kind="template",
                                           prefill={"bank_name": "NatWest"}, reason="")
    pre = flat["prefill"]
    assert pre["format"] == "swift" and pre["fields"]["bank_name"] == "NatWest" and pre["fields"]["bic"] == "NWBKGB2L"
    assert pre["fields"]["beneficiary_name"] == "UNSW Sydney" and "account" in pre["fields"]


def test_chat_can_get_things_done_with_confirmation(local):
    from finance.agent import Agent
    a = Agent(local)
    r = a.chat("加一个订阅 Spotify 12.99澳元", "act1", "zh-CN")
    step = r["trace"][-1]
    assert step["tool"] == "do_action" and step["result"]["kind"] == "action" and step["result"]["status"] == "pending"
    assert step["result"]["payload"]["action"] == "add_recurring" and "确认" in r["message"]
    assert local.recurring_list() == []  # nothing happens before the owner confirms
    local.decide("owner", step["result"]["id"], True)
    assert local.recurring_list()[0]["description"] == "Spotify" and local.recurring_list()[0]["amount"] == 1299
    r = a.chat("我现在有 3000 澳元", "act2", "zh-CN")
    pid = r["trace"][-1]["result"]["id"]
    local.decide("owner", pid, True)
    assert local.cash_balances()["AUD"]["amount"] == 300000
    r = a.chat("email digest weekly please", "act3", "en")
    assert r["trace"][-1]["result"]["payload"]["params"] == {"digest": "weekly"}
    with pytest.raises(Denied) as e:  # nowhere to send it yet: say so rather than quietly staying off
        local.decide("owner", r["trace"][-1]["result"]["id"], True)
    assert e.value.code == "email_address_needed"
    r = a.chat("send a weekly email digest to me@example.com", "act4", "en")
    local.decide("owner", r["trace"][-1]["result"]["id"], True)
    assert local.email_settings()["digest"] == "weekly" and local.email_settings()["address"] == "me@example.com"


def test_actions_are_checked_before_you_see_them(local):
    from finance.domain import Denied
    with pytest.raises(Denied):
        local.propose("agent", "action", {"action": "send_money", "params": {}})
    with pytest.raises(Denied):
        local.propose("agent", "action", {"action": "add_bill", "params": {"title": "Rent"}})  # missing amount and date
    with pytest.raises(Denied):
        local.decide("agent", local.propose("agent", "action", {"action": "clear_cash", "params": {"currency": "AUD"}})["id"], True)
