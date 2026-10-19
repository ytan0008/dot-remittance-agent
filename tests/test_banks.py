import json
from types import SimpleNamespace
import pytest
from finance.banks import page_text, fetch_page, clean_pricing
from finance.domain import Denied

BOC = """<html><head><script>var x=1</script></head><body><table>
<tr><th>货币名称</th><th>现汇买入价</th><th>现钞买入价</th></tr>
<tr><td>澳大利亚元</td><td>463.12</td><td>448.71</td></tr></table></body></html>"""


class FakeHTTP:
    def __init__(self, pages):
        self.pages, self.seen = pages, []

    def get(self, url, **kw):
        self.seen.append(url)
        status, body, loc = self.pages.get(url, (404, "", None))
        return SimpleNamespace(status_code=status, content=body.encode(), encoding="utf-8", headers={"location": loc} if loc else {})


def test_page_text_and_url_guard(monkeypatch):
    text = page_text(BOC)
    assert "var x" not in text and "澳大利亚元 | 463.12" in text
    with pytest.raises(Denied):
        fetch_page("http://www.boc.cn/")  # https only
    monkeypatch.setattr("finance.banks._public_host", lambda h: h != "intranet.local")
    with pytest.raises(Denied):
        fetch_page("https://intranet.local/rates", FakeHTTP({}))
    http = FakeHTTP({"https://bank.example/a": (302, "", "https://intranet.local/x")})
    with pytest.raises(Denied):
        fetch_page("https://bank.example/a", http)  # a redirect into a private network is refused too


def test_ai_reads_bank_pages_and_scenarios(local, monkeypatch):
    monkeypatch.setattr("finance.banks._public_host", lambda h: True)
    http = FakeHTTP({"https://www.boc.cn/sourcedb/whpj/": (200, BOC, None)})
    prompts = []
    local.page_reader = lambda p: prompts.append(p) or json.dumps({"found": True, "rate": "4.6312", "rate_kind": "spot buying",
                                                                  "fee_receive": {"amount": "20", "currency": "CNY"}})
    banks = local.refresh_bank("owner", "boc", "AUD", "CNY", client=http)
    boc = next(b for b in banks if b["id"] == "boc")
    assert boc["side"] == "receive" and boc["pricing"]["rate"] == "4.6312" and boc["pricing"]["origin"] == "ai"
    assert boc["pricing"]["sources"] == ["https://www.boc.cn/sourcedb/whpj/"] and "463.12" in prompts[0]
    local.set_bank_pricing("owner", "cba", "AUD", "CNY", {"rate": "4.55", "fee_send": {"amount": "6", "currency": "AUD"},
                                                          "intermediary": {"amount": "15", "currency": "AUD"}})
    with pytest.raises(Denied):
        local.set_bank_pricing("agent", "cba", "AUD", "CNY", {"rate": "9"})  # only a person enters figures
    r = local.exchange_scenarios("AUD", "CNY", "1000", "send", "cba", "boc")
    by = {(s["convert_at"], s["timing"]): s for s in r["scenarios"]}
    at_cba = by[("send_bank", "once")]
    assert at_cba["legs"][0]["spend"] == 100000 and at_cba["total_receive"] == int((1000 - 6 - 15) * 4.55 * 100) - 2000
    at_boc = by[("receive_bank", "once")]
    assert at_boc["total_receive"] == int((1000 - 21) * 4.6312 * 100) - 2000 and at_boc["rank"] == 1  # the better rate wins
    assert "send_fee" not in at_cba["unknown"] and r["forecast"] is None  # the test rates have no forecast: no split plans
    with pytest.raises(Denied):
        local.refresh_bank("owner", "nope", "AUD", "CNY")
    local.page_reader = lambda p: None
    with pytest.raises(Denied) as err:
        local.refresh_bank("owner", "boc", "AUD", "CNY", client=http)
    assert err.value.code == "bank_needs_model"


def test_clean_pricing_drops_nonsense():
    c = clean_pricing({"rate": "-3", "fee_pct": "45", "fee_send": {"amount": "x", "currency": "AUD"}, "fee_receive": {"amount": "5", "currency": "cny"}})
    assert c["rate"] is None and c["fee_pct"] is None and c["fee_send"] is None and c["fee_receive"] == {"amount": "5", "currency": "CNY"}


def test_knowledge_fills_in_when_the_pages_cannot_be_read(local, monkeypatch):
    monkeypatch.setattr("finance.banks._public_host", lambda h: True)
    http = FakeHTTP({})  # every page answers 404
    asked = []
    local.page_reader = lambda p: asked.append(p) or json.dumps({"found": True, "rate": "9.99", "fee_send": {"amount": "0", "currency": "AUD"},
                                                                "intermediary": {"amount": "20", "currency": "AUD"}, "rate_margin_pct": "3", "as_of": "2025"})
    cba = next(b for b in local.refresh_bank("owner", "cba", "AUD", "CNY", client=http) if b["id"] == "cba")["pricing"]
    assert cba["origin"] == "ai_knowledge" and cba["rate"] is None and cba["rate_margin_pct"] == "3" and "general knowledge" in asked[0]
    s = next(x for x in local.exchange_scenarios("AUD", "CNY", "1000", "send", "cba")["scenarios"] if x["timing"] == "once")
    assert s["rate_source"] == "estimate" and s["estimated"] and s["legs"][0]["rate"] == "4.500800"  # 4.64 less 3%
    local.page_reader = lambda p: json.dumps({"found": False})
    with pytest.raises(Denied):
        local.refresh_bank("owner", "nab", "AUD", "CNY", client=http)  # only now: enter by hand
