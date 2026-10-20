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


def test_ai_reads_bank_pages_only_with_quotes_from_the_page(local, monkeypatch):
    monkeypatch.setattr("finance.banks._public_host", lambda h: True)
    http = FakeHTTP({"https://www.boc.cn/sourcedb/whpj/": (200, BOC, None)})
    prompts = []
    local.page_reader = lambda p: prompts.append(p) or json.dumps({
        "found": True, "rate": "4.6312", "rate_kind": "spot buying", "fee_receive": {"amount": "20", "currency": "CNY"},
        "evidence": {"rate": "澳大利亚元 | 463.12", "fee_receive": "Incoming remittance fee CNY 20"}})  # the fee quote is not on the page
    boc = next(b for b in local.refresh_bank("owner", "boc", "AUD", "CNY", client=http) if b["id"] == "boc")
    assert boc["side"] == "receive" and boc["pricing"]["rate"] == "4.6312" and boc["pricing"]["origin"] == "ai"
    assert boc["pricing"]["fee_receive"] is None and boc["pricing"]["unverified"] == ["fee_receive"]  # no quote, no figure
    assert boc["pricing"]["evidence"]["rate"] == "澳大利亚元 | 463.12" and "untrusted" in prompts[0] and "463.12" in prompts[0]
    with pytest.raises(Denied):
        local.refresh_bank("owner", "nope", "AUD", "CNY")
    local.page_reader = lambda p: None
    with pytest.raises(Denied) as err:
        local.refresh_bank("owner", "boc", "AUD", "CNY", client=http)
    assert err.value.code == "bank_needs_model"


def test_fees_stay_in_their_currency_and_only_sourced_scenarios_rank(local):
    local.set_bank_pricing("owner", "cba", "AUD", "CNY", {"rate": "4.55", "fee_send": {"amount": "6", "currency": "AUD"},
                                                          "intermediary": {"amount": "15", "currency": "AUD"}})
    local.set_bank_pricing("owner", "boc", "AUD", "CNY", {"rate": "4.6312", "fee_receive": {"amount": "20", "currency": "CNY"}})
    with pytest.raises(Denied):
        local.set_bank_pricing("agent", "cba", "AUD", "CNY", {"rate": "9"})  # only a person enters figures
    r = local.exchange_scenarios("AUD", "CNY", "1000", "send", "cba", "boc")
    by = {(s["convert_at"], s["timing"]): s for s in r["scenarios"]}
    at_cba, at_boc = by[("send_bank", "once")], by[("receive_bank", "once")]
    assert at_cba["total_receive"] == int((1000 - 6 - 15) * 4.55 * 100) - 2000
    assert at_boc["total_receive"] == int((1000 - 21) * 4.6312 * 100) - 2000
    # 21 AUD and 20 CNY are never added up as "41": each keeps its currency, the total converts CNY at the reference rate
    assert at_cba["fees"] == [{"kind": "send", "amount": 2100, "currency": "AUD"}, {"kind": "receive", "amount": 2000, "currency": "CNY"}]
    assert abs(at_cba["fees_total"]["amount"] - (2100 + 20 / 4.64 * 100)) <= 1 and at_cba["fees_total"]["converted"]
    assert at_boc["tier"] == "sourced" and at_boc["rank"] == 1 and at_cba["rank"] == 2  # the better rate wins
    assert at_cba["caveats"] == [] and r["forecast"] is None  # no forecast in the test data: no split plans
    # A bank that publishes no sending fee cannot win: one missing figure makes it provisional, not "best".
    local.set_bank_pricing("owner", "nab", "AUD", "CNY", {"rate": "4.70"})
    nab = next(s for s in local.exchange_scenarios("AUD", "CNY", "1000", "send", "nab")["scenarios"] if s["timing"] == "once")
    assert nab["tier"] == "partial" and nab["rank"] is None and "send_fee" in nab["unknown"]
    both = local.exchange_scenarios("AUD", "CNY", "1000", "send")["scenarios"]
    assert both[0]["tier"] == "sourced" and all(s["rank"] is None for s in both if s["tier"] != "sourced")


def test_deadlines_count_arrival_time_and_the_forecast_date(local, monkeypatch):
    from datetime import date, timedelta
    from finance.banks import add_business_days
    local.set_bank_pricing("owner", "cba", "AUD", "CNY", {"rate": "4.55", "fee_send": {"amount": "6", "currency": "AUD"}})
    today = date.today()
    soon = add_business_days(today, 1)  # a wire takes up to 3 business days: tomorrow is too soon
    s = next(x for x in local.exchange_scenarios("AUD", "CNY", "1000", "send", "cba", due=str(soon))["scenarios"] if x["timing"] == "once")
    assert not s["feasible"] and s["late"] == "arrives_late" and s["rank"] is None and s["latest_start"] < str(today)
    cutoff = today - timedelta(days=2)
    monkeypatch.setattr(local.rates, "forecast", lambda a, b, horizon_days=7: dict(available=True, data_cutoff=str(cutoff), horizon_days=7, point="4.70"))
    in_time = str(add_business_days(cutoff + timedelta(days=7), 3))
    r = local.exchange_scenarios("AUD", "CNY", "1000", "send", "cba", due=in_time)
    split = next(x for x in r["scenarios"] if x["timing"] == "split")
    assert r["forecast_day"] == str(cutoff + timedelta(days=7)) and split["legs"][1]["date"] == r["forecast_day"]  # exactly the forecast's date
    assert split["feasible"]
    early = str(add_business_days(today, 4))  # three days to pay: the 7-day forecast cannot be used
    split = next(x for x in local.exchange_scenarios("AUD", "CNY", "1000", "send", "cba", due=early)["scenarios"] if x["timing"] == "split")
    assert not split["feasible"] and split["late"] == "forecast_after_deadline" and split["rank"] is None


def test_third_party_comparison_fills_in_and_boc_australia_sends_and_receives(local, monkeypatch):
    from finance.banks import COMPARISON
    monkeypatch.setattr("finance.banks._public_host", lambda h: True)
    quotes = json.dumps({"providers": [{"alias": "national-australia-bank", "quotes": [{"fee": 0.0, "markup": 3.03, "rate": 4.5246,
                         "dateCollected": "2026-10-19T23:40:24Z", "deliveryEstimation": {"duration": {"min": "P1D", "max": "P2D"}}}]}]})
    http = FakeHTTP({COMPARISON: (200, quotes, None)})  # NAB's own pages answer 404
    local.page_reader = lambda p: json.dumps({"found": False})
    nab = next(b for b in local.refresh_bank("owner", "nab", "AUD", "CNY", client=http) if b["id"] == "nab")["pricing"]
    assert nab["origin"] == "third_party" and nab["rate"] == "4.5246" and nab["fee_send"] == {"amount": "0.0", "currency": "AUD"}
    assert nab["rate_date"] == "2026-10-19" and nab["days"] == [1, 2] and "Wise" in nab["notes"]
    s = next(x for x in local.exchange_scenarios("AUD", "CNY", "1000", "send", "nab")["scenarios"] if x["timing"] == "once")
    assert s["tier"] == "partial" and "intermediary" in s["unknown"] and s["days"] == [1, 2]  # an unpublished correspondent fee: provisional
    boc_au = next(b for b in local.banks("AUD", "CNY") if b["id"] == "boc_au")
    assert boc_au["sides"] == ["send", "receive"] and boc_au["name_zh"] == "中国银行（澳大利亚）"
    assert next(b for b in local.banks("CNY", "AUD") if b["id"] == "boc_au")["sides"] == ["send", "receive"]
    assert "receive" in next(b for b in local.banks("CNY", "AUD") if b["id"] == "cba")["sides"]  # tuition from China lands in Australia


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
    assert s["tier"] == "estimate" and s["rank"] is None  # what the AI remembers is a scenario for reference, never "best"
    local.page_reader = lambda p: json.dumps({"found": False})
    with pytest.raises(Denied):
        local.refresh_bank("owner", "nab", "AUD", "CNY", client=http)  # only now: enter by hand


def test_official_fees_with_a_third_party_rate(local, monkeypatch):
    from finance.banks import COMPARISON
    monkeypatch.setattr("finance.banks._public_host", lambda h: True)
    page = "<html><body><p>Make the most of $0 transfer fees when sending money overseas.</p></body></html>"
    quotes = json.dumps({"providers": [{"alias": "national-australia-bank", "quotes": [{"fee": 0.0, "markup": 3.03, "rate": 4.5246, "dateCollected": "2026-10-19T23:40:24Z"}]}]})
    url = "https://www.nab.com.au/personal/international-banking/international-money-transfers"
    http = FakeHTTP({url: (200, page, None), COMPARISON: (200, quotes, None)})
    local.page_reader = lambda p: json.dumps({"found": True, "fee_send": {"amount": "0", "currency": "AUD"},
                                              "evidence": {"fee_send": "Make the most of $0 transfer fees"}})
    nab = next(b for b in local.refresh_bank("owner", "nab", "AUD", "CNY", client=http) if b["id"] == "nab")["pricing"]
    assert nab["origin"] == "ai" and nab["fee_send"]["amount"] == "0" and nab["rate"] == "4.5246" and nab["rate_origin"] == "third_party"
    s = next(x for x in local.exchange_scenarios("AUD", "CNY", "1000", "send", "nab")["scenarios"] if x["timing"] == "once")
    assert s["tier"] == "partial" and s["rank"] is None  # no intermediary figure: provisional, not "best"
    local.set_bank_pricing("owner", "nab", "AUD", "CNY", {"rate": "4.5246", "fee_send": {"amount": "0", "currency": "AUD"},
                                                          "intermediary": {"amount": "0", "currency": "AUD"}})
    s = next(x for x in local.exchange_scenarios("AUD", "CNY", "1000", "send", "nab")["scenarios"] if x["timing"] == "once")
    assert s["tier"] == "sourced" and s["rank"] == 1


def test_banks_by_name():
    from finance.banks import find_bank
    assert find_bank("中国银行", "CNY") == "boc" and find_bank("中国银行", "AUD") == "boc_au" and find_bank("澳洲中行") == "boc_au"
    assert find_bank("Commonwealth") == "cba" and find_bank("招商银行") == "cmb" and find_bank("BOC Australia") == "boc_au"
    assert find_bank("中国银行悉尼分行的账户") == "boc_au" and find_bank("some bank") is None


def test_scenarios_accept_names(local):
    local.set_bank_pricing("owner", "boc", "CNY", "AUD", {"rate": "0.2130", "fee_send": {"amount": "50", "currency": "CNY"}})
    r = local.exchange_scenarios("CNY", "AUD", "45000", "send", "中国银行", "澳洲中行")
    assert {s["send_bank"] for s in r["scenarios"]} == {"boc"} and {s["receive_bank"] for s in r["scenarios"]} == {"boc_au"}


def test_banks_are_read_automatically_and_fresh_ones_are_skipped(local, monkeypatch):
    from finance.banks import COMPARISON
    monkeypatch.setattr("finance.banks._public_host", lambda h: True)
    asked = []
    local.page_reader = lambda p: asked.append(p) or json.dumps({"found": True, "fee_send": {"amount": "10", "currency": "AUD"}, "as_of": "2025"})
    st = local.auto_refresh_banks("AUD", "CNY", wait=True, client=FakeHTTP({}))
    both = [b["id"] for b in local.banks("AUD", "CNY") if b["sides"]]
    assert st["pending"] == [] and set(st["done"]) | set(st["failed"]) == set(both) and "boc_au" in both
    assert all((b["pricing"] or {}).get("status") == "ok" for b in local.banks("AUD", "CNY") if b["sides"])
    n = len(asked)
    local.auto_refresh_banks("AUD", "CNY", wait=True, client=FakeHTTP({}))
    assert len(asked) == n  # read within the day: not read again
    local.page_reader = None
    assert local.auto_refresh_banks("AUD", "CNY")["model"] is False  # no model: nothing is attempted


def test_the_worker_never_waits_for_bank_reading(local, monkeypatch):
    import time
    monkeypatch.setattr("finance.banks.fetch_page", lambda u, c=None: "no figures here")  # no network in tests
    monkeypatch.setattr("finance.banks.comparison_quotes", lambda *a, **k: {})
    local.save_plan("owner", "AUD", "CNY", "100")
    local.page_reader = lambda p: time.sleep(2) or json.dumps({"found": False})
    started = time.time()
    assert local.auto_refresh_plans() == 1
    assert time.time() - started < 1  # returns at once; the reading continues on its own threads
    assert local.auto_status("AUD", "CNY")["pending"]


def test_split_parts_add_up_and_are_a_forecast_scenario(local, monkeypatch):
    from datetime import date
    local.set_bank_pricing("owner", "cba", "AUD", "CNY", {"rate": "4.55", "fee_send": {"amount": "0", "currency": "AUD"},
                                                          "intermediary": {"amount": "0", "currency": "AUD"}})
    monkeypatch.setattr(local.rates, "forecast", lambda a, b, horizon_days=7: dict(available=True, data_cutoff=str(date.today()), horizon_days=7, point="4.70"))
    r = local.exchange_scenarios("AUD", "CNY", "100.01", "send", "cba")
    split = next(x for x in r["scenarios"] if x["timing"] == "split")
    assert split["total_spend"] == 10001 and [l["spend"] for l in split["legs"]] == [5000, 5001]  # no cent created or lost
    assert split["tier"] == "forecast" and split["estimated"] and split["rank"] is None
    with pytest.raises(Denied):
        local.exchange_scenarios("AUD", "CNY", "1e50", "send")


def test_evidence_must_be_the_exact_figure_in_its_currency():
    from finance.banks import verify_evidence
    for amount, quote, cur, keep in (("20", "Transfer fee 200 AUD", "AUD", False), ("6", "Transfer fee 6 USD", "AUD", False),
                                     ("0.06", "Transfer fee 6 AUD", "AUD", False), ("6", "Transfer fee 6 AUD", "AUD", True),
                                     ("0", "Make the most of $0 transfer fees", "AUD", True), ("20", "汇款手续费 20 元", "CNY", True),
                                     ("1,000", "Fee 1,000 JPY", "JPY", True)):
        data = {"fee_send": {"amount": amount.replace(",", ""), "currency": cur}}
        dropped = verify_evidence(data, {"fee_send": quote}, [("https://bank.example", quote)])
        assert (dropped == []) is keep, (amount, quote)


def test_fee_knowledge_keeps_only_quoted_figures_with_their_page():
    from finance.bank_kb import verify_fee_items, fee_lines
    page = ("International transfers\nTelegraphic transfer fee: AUD 20 per transfer\nCable charge 150 元\n"
            "汇款手续费：汇款金额的1‰，最低50元，最高260元\n\nAbout us\nOpening hours 9-5")
    pages = [("https://bank.example/fees", page)]
    assert "Opening hours" not in fee_lines(page) and "电" not in fee_lines("nothing\nhere") and "Cable charge" in fee_lines(page)
    items = [
        {"kind": "send_fee", "label": "TT fee", "amount": "20", "currency": "AUD", "quote": "Telegraphic transfer fee: AUD 20 per transfer"},
        {"kind": "cable_fee", "label": "电讯费", "amount": "150", "currency": "CNY", "quote": "Cable charge 150 元"},
        {"kind": "fx_fee", "label": "汇款手续费", "pct": "0.1", "min": "50", "max": "260", "quote": "汇款手续费：汇款金额的1‰，最低50元，最高260元"},
        {"kind": "send_fee", "label": "made up", "amount": "25", "currency": "AUD", "quote": "Telegraphic transfer fee: AUD 20 per transfer"},
        {"kind": "send_fee", "label": "not on page", "amount": "5", "currency": "AUD", "quote": "Fee AUD 5"},
        {"kind": "send_fee", "label": "wrong currency", "amount": "20", "currency": "USD", "quote": "Telegraphic transfer fee: AUD 20 per transfer"},
    ]
    kept = verify_fee_items(items, pages)
    assert [k["label"] for k in kept] == ["TT fee", "电讯费", "汇款手续费"]
    assert all(k["url"] == "https://bank.example/fees" and k["quote"] for k in kept)


def test_reading_a_bank_fills_its_fee_knowledge_and_ai_finds_more_banks(local, monkeypatch):
    monkeypatch.setattr("finance.banks._public_host", lambda h: True)
    page = "<p>International Money Transfer fee AUD 6</p><p>Cable charge AUD 10</p>"
    url = "https://www.commbank.com.au/international/international-money-transfer.html"
    answers = {
        "pricing": json.dumps({"found": True, "fee_send": {"amount": "6", "currency": "AUD"},
                               "evidence": {"fee_send": "International Money Transfer fee AUD 6"},
                               "fees": [{"kind": "send_fee", "label": "IMT fee", "amount": "6", "currency": "AUD", "quote": "International Money Transfer fee AUD 6"},
                                        {"kind": "cable_fee", "label": "Cable", "amount": "10", "currency": "AUD", "quote": "Cable charge AUD 10"},
                                        {"kind": "cable_fee", "label": "Invented", "amount": "99", "currency": "AUD", "quote": "Cable charge AUD 99"}]}),
        "discover": json.dumps({"banks": [{"name": "Macquarie Bank", "country": "AU", "website": "https://www.macquarie.com.au",
                                           "fee_page": "https://www.macquarie.com.au/fees", "currencies": ["AUD"]},
                                          {"name": "Bank of China", "country": "CN", "fee_page": "https://www.boc.cn/fees", "currencies": ["CNY", "AUD"]},
                                          {"name": "Agricultural Bank of China", "country": "CN", "fee_page": "https://www.abchina.com/fees", "currencies": ["CNY"]},
                                          {"name": "Fake", "country": "Australia", "website": "http://insecure.example"}]}),
    }
    local.page_reader = lambda p: answers["discover"] if "most often use" in p else answers["pricing"]
    local.refresh_bank("owner", "cba", "AUD", "CNY", client=FakeHTTP({url: (200, page, None)}))
    kb = local.bank_knowledge("cba")
    assert sorted(k["label"] for k in kb) == ["Cable", "IMT fee"] and all(k["url"] == url for k in kb)
    assert next(b for b in local.banks("AUD", "CNY") if b["id"] == "cba")["knowledge"]
    assert local.discover_banks("AUD") == 2  # Macquarie and ABC are new; Bank of China is already known; "Fake" is not a bank entry
    banks = {b["id"]: b for b in local.banks("AUD", "CNY")}
    assert banks["x_macquarie_bank"]["origin"] == "ai" and banks["x_macquarie_bank"]["sides"] == ["send"]
    assert banks["x_macquarie_bank"]["urls"][0] == "https://www.macquarie.com.au/fees"
    assert "https://www.boc.cn/fees" in banks["boc"]["urls"]  # a known bank only gains the page the AI pointed to
    assert not any("abchina" in u for u in banks["boc"]["urls"]) and "x_agricultural_bank_of_china" in banks  # never mixed up
    assert not local._discovery_stale("AUD")
