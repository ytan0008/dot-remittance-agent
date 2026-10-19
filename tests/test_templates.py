import pytest
from fastapi.testclient import TestClient
from finance.agent import Agent
from finance.api import create_app
from finance.domain import Denied
from finance.templates import luhn_ok

SWIFT = dict(beneficiary_name="UNSW Sydney", beneficiary_address="High St, Kensington NSW 2052, Australia",
             account="GB82WEST12345698765432", bank_name="NatWest", bic="NWBK GB2L", charges="SHA",
             reference="Student 5123456 tuition T1", purpose_code="EDUC")


def issues(result):
    return {(i["field"], i["level"], i["code"]) for i in result["issues"]}


def test_swift_validation(local):
    ok = local.validate_template("swift", SWIFT, "GBP")
    assert ok["ok"] and ok["fields"]["bic"] == "NWBKGB2L" and ok["country"] == "GB" and not ok["issues"]
    bad = local.validate_template("swift", dict(SWIFT, beneficiary_name="张三", bic="NWBK", account="GB82WEST12345698765433"), "GBP")
    assert {("beneficiary_name", "error", "swift_charset"), ("bic", "error", "bic_format"), ("account", "error", "iban_checksum")} <= issues(bad)
    warn = local.validate_template("swift", dict(SWIFT, bic="DEUTDEFF", purpose_code=""), "CNY")
    assert warn["ok"] and {("bic", "warn", "bic_country_mismatch"), ("purpose_code", "warn", "purpose_recommended")} <= issues(warn)
    assert ("beneficiary_address", "error", "required") in issues(local.validate_template("swift", dict(SWIFT, beneficiary_address=""), "GBP"))
    with pytest.raises(Denied):
        local.validate_template("swift", dict(SWIFT, routing="x"), "GBP")
    with pytest.raises(Denied):
        local.validate_template("telex", {}, "GBP")


def test_domestic_formats(local):
    au = local.validate_template("au_bsb", dict(account_name="Jane Lee", bsb="062000", account_number="12345678"))
    assert au["ok"] and au["fields"]["bsb"] == "062-000" and au["currency"] == "AUD"
    uk = local.validate_template("uk_fps", dict(account_name="J Lee", sort_code="20 00 00", account_number="55779911"))
    assert uk["ok"] and uk["fields"]["sort_code"] == "20-00-00"
    assert ("routing_number", "error", "aba_checksum") in issues(
        local.validate_template("us_ach", dict(beneficiary_name="Jane", routing_number="021000022", account_number="123456789")))
    assert local.validate_template("us_ach", dict(beneficiary_name="Jane", routing_number="021000021", account_number="123456789"))["ok"]
    assert local.validate_template("in_neft", dict(beneficiary_name="Asha", ifsc="sbin0000001", account_number="123456789012"))["ok"]
    assert ("ifsc", "error", "ifsc_format") in issues(local.validate_template("in_neft", dict(beneficiary_name="A", ifsc="SBIN1000001", account_number="123456789")))
    sepa = local.validate_template("sepa", dict(beneficiary_name="Uni Wien", iban="DE89 3704 0044 0532 0130 00"))
    assert sepa["ok"] and sepa["currency"] == "EUR"
    card = "622200001111222"
    bad_card = next(card + d for d in "0123456789" if not luhn_ok(card + d))
    cn = local.validate_template("cn_cnaps", dict(beneficiary_name="张三", bank_name="中国银行", cnaps="104100000004", account_number=bad_card))
    assert cn["ok"] and ("account_number", "warn", "card_luhn") in issues(cn)  # Chinese names are fine domestically


def test_confirmation_masking_and_changed_details(local):
    t = local.save_template("owner", "Tuition UNSW", "swift", SWIFT, "AUD", amount="12500", purpose="tuition")
    assert t["confirmed"] and t["fields"]["account"] == "GB82WEST12345698765432" and t["amount"] == 1250000
    listed = local.transfer_templates()[0]
    assert listed["masked"] and "GB82WEST12345698765432" not in str(listed)
    assert local.transfer_template(t["id"], "viewer", reveal=True)["masked"]  # only the owner sees full numbers
    renamed = local.save_template("owner", "Tuition UNSW T2", "swift", SWIFT, "AUD", tid=t["id"])
    assert renamed["confirmed"]  # a new name does not touch bank details
    changed = local.save_template("owner", "Tuition UNSW", "swift", dict(SWIFT, account="DE89370400440532013000"), "AUD", tid=t["id"])
    assert not changed["confirmed"] and changed["bank_changed"]
    with pytest.raises(Denied) as err:
        local.template_sheet("owner", t["id"])
    assert err.value.code == "template_unconfirmed"
    assert local.confirm_template("owner", t["id"])["confirmed"]
    with pytest.raises(Denied) as err:
        local.save_template("owner", "x", "swift", dict(SWIFT, bic="??"), "AUD")
    assert err.value.code == "template_fields"


def test_agent_drafts_stay_unconfirmed(local):
    agent = Agent(local)
    r = agent.tool("draft_transfer_template", {"name": "Rent", "format": "au_bsb",
                                               "fields": {"account_name": "Landlord", "bsb": "062-000", "account_number": "98765432"}})
    assert r["confirmed"] is False and r["masked"] and "98765432" not in str(r)
    with pytest.raises(Denied):
        local.template_sheet("owner", r["id"])
    with pytest.raises(Denied):
        local.save_template("agent", "Rent", "au_bsb", {"account_name": "X", "bsb": "062000", "account_number": "11112222"}, tid=r["id"])
    check = agent.tool("check_bank_details", {"format": "swift", "fields": dict(SWIFT, bic="BAD")})
    assert check["ok"] is False


def test_sheet_and_mt103_preview(local):
    t = local.save_template("owner", "Tuition", "swift", dict(SWIFT, intermediary_bic="CHASUS33"), "AUD", amount="12500.5")
    s = local.template_sheet("owner", t["id"])
    assert s["rows"][0] == {"field": "amount", "value": "12500.50 AUD"}
    assert [r["field"] for r in s["rows"][1:4]] == ["beneficiary_name", "beneficiary_address", "account"]
    mt = s["mt103"].splitlines()
    assert mt[0].endswith("AUD12500,50") and ":56A:CHASUS33" in mt and ":57A:NWBKGB2L" in mt
    assert ":59:/GB82WEST12345698765432" in mt and ":70:/PURP/EDUC Student 5123456 tuition T1" in mt and mt[-1] == ":71A:SHA"
    assert local.template_sheet("owner", t["id"], amount="100")["rows"][0]["value"] == "100.00 AUD"
    with pytest.raises(Denied):
        local.template_sheet("agent", t["id"])


def test_template_api(local, monkeypatch):
    monkeypatch.setenv("OWNER_TOKEN", "o" * 32)
    monkeypatch.setenv("AGENT_TOKEN", "a" * 32)
    monkeypatch.setenv("VIEWER_TOKEN", "v" * 32)
    with TestClient(create_app(local, background=False)) as client:
        owner, viewer = {"Authorization": "Bearer " + "o" * 32}, {"Authorization": "Bearer " + "v" * 32}
        assert set(client.get("/transfer-formats", headers=viewer).json()["formats"]) == {"swift", "sepa", "au_bsb", "uk_fps", "us_ach", "cn_cnaps", "in_neft"}
        assert client.post("/transfer-templates/validate", headers=viewer, json={"format": "swift", "fields": SWIFT, "currency": "AUD"}).json()["ok"]
        tid = client.post("/transfer-templates", headers=owner, json={"name": "Tuition", "format": "swift", "fields": SWIFT, "currency": "AUD"}).json()["id"]
        assert client.get(f"/transfer-templates/{tid}?reveal=true", headers=viewer).json()["masked"] is True
        assert client.get(f"/transfer-templates/{tid}?reveal=true", headers=owner).json()["masked"] is False
        assert client.post(f"/transfer-templates/{tid}/sheet", headers=viewer, json={}).status_code == 409
        assert client.post(f"/transfer-templates/{tid}/sheet", headers=owner, json={"amount": "50"}).json()["mt103"].startswith(":32A:")
        assert client.delete(f"/transfer-templates/{tid}", headers=owner).status_code == 200
