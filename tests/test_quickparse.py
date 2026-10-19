import json
from datetime import date
from types import SimpleNamespace
import pytest
from finance.domain import Denied
from finance.quickparse import parse_text

TUE = date(2026, 10, 20)  # a Tuesday


def items(text, default="AUD"):
    return [(str(i["date"]), str(i["amount"]), i["currency"], i["description"]) for i in parse_text(text, TUE, default)]


@pytest.mark.parametrize("text,expected", [
    ("午饭40澳刀", [("2026-10-20", "40", "AUD", "午饭")]),
    ("2026年10月 19号 午饭10澳元", [("2026-10-19", "10", "AUD", "午饭")]),
    ("午饭10澳元 打车25", [("2026-10-20", "10", "AUD", "午饭"), ("2026-10-20", "25", "AUD", "打车")]),
    ("昨天 打车 23元", [("2026-10-19", "23", "CNY", "打车")]),
    ("A$12,10 Sweet Monster", [("2026-10-20", "12.10", "AUD", "Sweet Monster")]),
    ("上周五 coles 21.50", [("2026-10-16", "21.50", "AUD", "coles")]),
    ("星期日 HungryPanda 38.95", [("2026-10-18", "38.95", "AUD", "HungryPanda")]),
    ("10/19 dinner 30", [("2026-10-19", "30", "AUD", "dinner")]),
    ("1,200 rent", [("2026-10-20", "1200", "AUD", "rent")]),
    ("iPhone 15 1299 dollars", [("2026-10-20", "1299", "AUD", "iPhone 15")]),
    ("12:30 lunch 15", [("2026-10-20", "15", "AUD", "lunch")]),
    ("ランチ 1200円", [("2026-10-20", "1200", "JPY", "ランチ")]),
    ("점심 15000원", [("2026-10-20", "15000", "KRW", "점심")]),
    ("ăn trưa 50000đ", [("2026-10-20", "50000", "VND", "ăn trưa")]),
    ("spent 20 on books", [("2026-10-20", "20", "AUD", "books")]),
])
def test_quick_lines(text, expected):
    assert items(text) == expected


def test_parse_quick_returns_every_item(local):
    r = local.parse_quick("午饭10澳元 打车25")
    assert [x["amount"] for x in r["items"]] == [-1000, -2500] and r["items"][0]["category"] == "dining" and r["by"] == "rules"
    with pytest.raises(Denied):
        local.parse_quick("午饭")


class FakeModel:
    def __init__(self, reply):
        self.reply, self.seen = reply, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.seen.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))])


def test_ai_reads_text_and_banking_screenshots(local):
    from finance.agent import Agent
    note = FakeModel(json.dumps({"items": [{"date": "2026-10-19", "amount": "10", "currency": "AUD", "description": "午饭", "category": "dining"}]}))
    r = Agent(local, client=note, model="m").parse_expense_text("中午吃了碗面花了十刀")
    assert r["by"] == "model" and r["amount"] == -1000 and r["currency"] == "AUD" and "十刀" in note.seen[0]["messages"][0]["content"]
    shot = FakeModel(json.dumps({"kind": "transactions", "items": [
        {"date": "2026-10-19", "amount": "12,10", "currency": "AUD", "description": "Sweet Monster"},
        {"date": "2026-10-19", "amount": "29.90", "currency": "AUD", "description": "SQ * Matcha Ya", "category": "dining"},
        {"date": "2026-10-18", "amount": "", "description": "Opal Fare"},  # pending, no amount: skipped
        {"date": "2030-01-01", "amount": "5", "description": "future"}]}))
    img = "data:image/png;base64,iVBORw0KGgo="
    r = Agent(local, client=shot, model="m").read_documents([img, img])
    assert r["available"] and r["kind"] == "transactions" and len(r["items"]) == 3
    assert r["items"][0]["amount"] == -1210 and r["items"][2]["date"] <= str(date.today())
    assert len(shot.seen[0]["messages"][0]["content"]) == 3  # the prompt and both images in one request
    with pytest.raises(Denied):
        Agent(local, client=shot, model="m").read_documents([img] * 5)
    empty = Agent(local, client=FakeModel('{"kind": "other", "items": []}'), model="m").read_documents([img])
    assert empty["available"] is False and empty["items"] == []
