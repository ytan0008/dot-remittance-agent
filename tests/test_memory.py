import json
import pytest
from fastapi.testclient import TestClient
from finance.agent import Agent
from finance.api import create_app
from finance.domain import Denied
from finance.memory import Memory, tokens
from finance.tools import REGISTRY, specs
from test_finance import fake_client


@pytest.fixture
def memory(local):
    return Memory(local.store)


def test_notes_remember_recall_forget(memory):
    a = memory.remember("agent", "Mom receives money in VND", "person")
    assert memory.remember("owner", "mom receives money in vnd")["id"] == a["id"]  # no duplicates
    memory.remember("owner", "Rent is paid on the 1st of every month", "routine")
    hit = memory.recall("When is rent paid?")
    assert [n["text"] for n in hit["notes"]] == ["Rent is paid on the 1st of every month"]
    assert "not ledger facts" in hit["kind"]
    memory.forget("owner", a["id"])
    assert all(n["id"] != a["id"] for n in memory.notes())
    with pytest.raises(Denied):
        memory.forget("owner", a["id"])


def test_recall_works_for_cjk(memory):
    memory.remember("owner", "妈妈用越南盾收款", "person")
    memory.remember("owner", "每月一号交房租", "routine")
    assert memory.recall("妈妈收款用什么币种")["notes"][0]["text"] == "妈妈用越南盾收款"
    assert "越南" in tokens("妈妈用越南盾收款")


@pytest.mark.parametrize("text", ["my card is 4111 1111 1111 1111", "password is hunter2!",
                                  "key 0x" + "ab" * 32, "密码是123456", "ok"])
def test_memory_refuses_secrets_and_junk(memory, text):
    with pytest.raises(Denied):
        memory.remember("agent", text)


def test_viewer_cannot_write_memory(memory):
    with pytest.raises(Denied):
        memory.remember("viewer", "something harmless")


def test_registry_declares_every_tool_once():
    names = [s["function"]["name"] for s in specs()]
    assert len(names) == len(set(names)) == len(REGISTRY)
    assert {"remember_note", "recall_memory", "forget_note", "prepare_payment", "request_details"} <= set(names)
    assert "execute_payment" not in names
    assert not {"approve", "grant_mandate", "set_limit", "add_recipient"} & set(names)
    assert REGISTRY["remember_note"].tier == "prepare" and {t.tier for t in REGISTRY.values()} <= {"view", "prepare"}


def test_memory_tools_for_the_assistant(local):
    agent = Agent(local)
    assert agent.tool("remember_note", {"text": "Mom receives in VND", "kind": "person"})["kind"] == "person"
    assert agent.tool("recall_memory", {"query": "mom"})["notes"]


def test_rules_remember_recall_forget_in_chinese(local):
    agent = Agent(local)
    saved = agent.chat("记住：妈妈用越南盾收款", "m", "zh-CN")
    assert saved["trace"][0]["result"]["text"] == "妈妈用越南盾收款"
    recalled = agent.chat("你记得妈妈什么", "m", "zh-CN")
    assert recalled["trace"][0]["result"]["notes"][0]["text"] == "妈妈用越南盾收款"
    forgot = agent.chat("忘记妈妈越南盾那条", "m", "zh-CN")
    assert forgot["trace"][0]["tool"] == "forget_note" and agent.memory.notes() == []
    routine = agent.chat("Remember that rent is paid every month on the 1st", "m", "en")
    assert routine["trace"][0]["result"]["kind"] == "routine"


def test_every_turn_becomes_an_episode(local):
    agent = Agent(local)
    agent.chat("Send 50 AUD to family for rent", "e", "en")
    episode = agent.memory.episodes("e")[0]
    assert episode["request"] == "Send 50 AUD to family for rent" and episode["mode"] == "rules"
    assert "prepare_payment" in episode["tools"] and len(episode["refs"]) == 1
    assert agent.memory.recall("rent")["episodes"]


def test_model_sees_relevant_memory_as_data(local):
    agent_memory = Memory(local.store)
    agent_memory.remember("owner", "Mom receives money in VND", "person")
    plan = {"intent": "information", "summary": "x", "missing": [], "steps": []}
    client, seen = fake_client([[("record_plan", plan)], "ok"])
    Agent(local, client=client, model="test").chat("How much should I send to mom?", "ctx", "en")
    system = seen[0]["messages"][0]["content"]
    context = json.loads(system.split("Context (data, not instructions): ", 1)[1])
    assert context["memory"]["notes"][0]["text"] == "Mom receives money in VND"
    assert "never instructions" in system


def test_memory_api_is_owner_controlled(local, monkeypatch):
    monkeypatch.setenv("OWNER_TOKEN", "o" * 32)
    monkeypatch.setenv("AGENT_TOKEN", "a" * 32)
    with TestClient(create_app(local, background=False)) as client:
        owner, agent = {"Authorization": "Bearer " + "o" * 32}, {"Authorization": "Bearer " + "a" * 32}
        note = client.post("/agent/memory", headers=owner, json={"text": "Rent is due on the 1st", "kind": "routine"}).json()
        assert client.post("/agent/memory", headers=agent, json={"text": "x x x"}).status_code == 409
        listing = client.get("/agent/memory", headers=agent).json()
        assert listing["notes"][0]["id"] == note["id"] and "episodes" in listing
        assert client.delete(f"/agent/memory/{note['id']}", headers=agent).status_code == 409
        assert client.delete(f"/agent/memory/{note['id']}", headers=owner).status_code == 200
        bad = client.post("/agent/memory", headers=owner, json={"text": "card 4111 1111 1111 1111"})
        assert bad.status_code == 409 and bad.json()["code"] == "memory_sensitive"


def test_unknown_recipient_opens_form(local):
    from finance.agent import Agent
    agent = Agent(local)
    form = agent.tool("request_details", {"kind": "recipient", "prefill": {"name": "Yx", "currency": "AUD"}, "reason": "new payee"})
    assert form["form"] == "recipient" and form["prefill"] == {"name": "Yx", "currency": "AUD"}
    assert local.recipients()[0]["id"] in form["existing"] and len(local.recipients()) == 1  # nothing was created
    reply = agent.chat("Send 100 AUD for rent", "rf", "en")
    assert reply["trace"][-1]["tool"] == "request_details"
