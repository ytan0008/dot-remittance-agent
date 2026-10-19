import pytest
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
        for n, intent in (("s1", "prepare"), ("s2", "compare"), ("s3", "scenario"), ("s4", "balance")):
            prompt = re.search(rf"'agent\.{n}': '([^']+)'", text).group(1)
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


def test_rules_spend_autonomously_within_mandate(evm):
    from finance.domain import now
    agent = Agent(evm)
    first = agent.chat("Send 0.001 ETH to family for a test payment", "chain", "en")
    draft = first["trace"][-1]["result"]
    assert draft["rail"] == "evm" and draft["status"] == "draft"
    refused = agent.chat("execute it", "chain", "en")
    assert "approval" in refused["message"]
    evm.grant_mandate("owner", "family", "0.002", "0.004", now() + 600)
    done = agent.chat("execute it", "chain", "en")
    result = done["trace"][-1]["result"]
    assert result["status"] == "completed" and result["authorized_by"] == "owner_mandate"
    assert "mandate" in done["message"]


@pytest.mark.parametrize("message,name", [
    ("用人民币给 Mia 汇款，让对方收到 100 澳元，用于生活费", "Mia"),
    ("Pay in CNY so Mia receives 100 AUD, send to Mia for rent", "Mia"),
    ("Dùng CNY chuyển cho Mia để họ nhận 100 AUD", "Mia"),
    ("CNY로 Mia에게 송금해서 상대가 100 AUD를 받게, 용도: 생활비", "Mia"),
])
def test_unregistered_name_prefills_the_form(local, message, name):
    reply = Agent(local).chat(message, "nm", "zh-CN")
    step = reply["trace"][-1]
    assert step["tool"] == "request_recipient_details" and step["result"]["prefill"]["name"] == name
    assert "面板" in reply["message"]
