"""Transfer templates: reusable bank instructions for paying from your own bank — SWIFT international wires and common
domestic formats (SEPA, Australian BSB, UK Faster Payments, US ACH/wire, China CNAPS, India NEFT/IMPS).

Each field is checked as you type (BIC structure, IBAN checksum, ABA checksum, BSB/sort code/IFSC/CNAPS formats, the
SWIFT character set). A template produces a copy-ready instruction sheet and, for SWIFT, an MT103-style field preview
for reference. DOT never sends these instructions anywhere. Templates the assistant drafts, and templates whose bank
details change, stay unconfirmed until the owner checks them against an official source — a defence against the
classic "our bank details have changed" scam.
"""
import json
import re
import uuid
from datetime import date
from .domain import Denied, canonical, now, mask, units, decimals, from_minor

SCHEMA = """
CREATE TABLE IF NOT EXISTS transfer_templates (id TEXT PRIMARY KEY, body TEXT NOT NULL, created INTEGER NOT NULL, updated INTEGER NOT NULL);
"""
IBAN_LENGTH = {"AD": 24, "AE": 23, "AT": 20, "BE": 16, "BG": 22, "CH": 21, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "EE": 20,
               "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GR": 27, "HR": 21, "HU": 28, "IE": 22, "IL": 23, "IS": 26, "IT": 27,
               "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27, "MT": 31, "NL": 18, "NO": 15, "PL": 28, "PT": 25, "QA": 29,
               "RO": 24, "SA": 24, "SE": 24, "SI": 19, "SK": 24, "SM": 27, "TR": 26}
PURPOSES = ("EDUC", "RENT", "SALA", "SUPP", "GIFT", "CHAR", "MDCS", "LOAN", "TAXS", "OTHR")  # ISO 20022 purpose codes
CHARGES = ("SHA", "OUR", "BEN")
SWIFT_TEXT = re.compile(r"[A-Za-z0-9/\-?:().,'+ \n]*")  # SWIFT "x" character set
SENSITIVE = ("account", "iban", "account_number")

# field: (kind, required, max length)
F = lambda kind, required=True, max_len=140: dict(kind=kind, required=required, max=max_len)  # noqa: E731
FORMATS = {
    "swift": dict(currency=None, fields={
        "beneficiary_name": F("swift_text", True, 70), "beneficiary_address": F("swift_text", True, 105),
        "account": F("account_or_iban", True, 34), "bank_name": F("swift_text", True, 70), "bic": F("bic"),
        "bank_address": F("swift_text", False, 105), "intermediary_bic": F("bic", False), "charges": F("charges"),
        "reference": F("swift_text", False, 140), "purpose_code": F("purpose", False)}),
    "sepa": dict(currency="EUR", fields={
        "beneficiary_name": F("swift_text", True, 70), "iban": F("iban", True, 34), "bic": F("bic", False),
        "reference": F("swift_text", False, 140), "purpose_code": F("purpose", False)}),
    "au_bsb": dict(currency="AUD", fields={
        "account_name": F("text", True, 32), "bsb": F("bsb"), "account_number": F("digits_5_9", True, 9), "reference": F("text", False, 18)}),
    "uk_fps": dict(currency="GBP", fields={
        "account_name": F("text", True, 40), "sort_code": F("sort_code"), "account_number": F("digits_8", True, 8), "reference": F("text", False, 18)}),
    "us_ach": dict(currency="USD", fields={
        "beneficiary_name": F("text", True, 70), "routing_number": F("aba"), "account_number": F("digits_4_17", True, 17),
        "account_type": F("account_type"), "bank_name": F("text", False, 70), "reference": F("text", False, 80)}),
    "cn_cnaps": dict(currency="CNY", fields={
        "beneficiary_name": F("text", True, 60), "bank_name": F("text", True, 60), "branch_name": F("text", False, 60),
        "cnaps": F("cnaps", False), "account_number": F("cn_account", True, 25), "reference": F("text", False, 60)}),
    "in_neft": dict(currency="INR", fields={
        "beneficiary_name": F("text", True, 70), "ifsc": F("ifsc"), "account_number": F("digits_9_18", True, 18),
        "bank_name": F("text", False, 70), "reference": F("text", False, 30)}),
}


def compact(value):
    return re.sub(r"[\s-]", "", str(value or "")).upper()


def iban_ok(iban):
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{8,30}", iban):
        return "iban_format"
    if iban[:2] in IBAN_LENGTH and len(iban) != IBAN_LENGTH[iban[:2]]:
        return "iban_length"
    digits = "".join(str(int(ch, 36)) for ch in iban[4:] + iban[:4])
    return None if int(digits) % 97 == 1 else "iban_checksum"


def aba_ok(n):
    if not re.fullmatch(r"\d{9}", n):
        return "aba_format"
    d = [int(x) for x in n]
    return None if (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + d[2] + d[5] + d[8]) % 10 == 0 else "aba_checksum"


def luhn_ok(n):
    total = 0
    for i, ch in enumerate(reversed(n)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def check_field(kind, value, spec):
    """Returns (normalized value, [(level, code)])."""
    raw = str(value or "").strip()
    issues = []
    if not raw:
        return "", [("error", "required")] if spec["required"] else []
    if kind in ("bic",):
        v = compact(raw)
        if not re.fullmatch(r"[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?", v):
            issues.append(("error", "bic_format"))
        return v, issues
    if kind == "iban" or (kind == "account_or_iban" and re.match(r"^[A-Za-z]{2}\d{2}", raw)):
        v = compact(raw)
        problem = iban_ok(v)
        if problem:
            issues.append(("error", problem))
        return v, issues
    if kind == "account_or_iban":
        v = re.sub(r"\s", "", raw)
        if not re.fullmatch(r"[A-Za-z0-9-]{4,34}", v):
            issues.append(("error", "account_format"))
        return v, issues
    if kind == "bsb":
        v = re.sub(r"[\s-]", "", raw)
        return (v[:3] + "-" + v[3:] if re.fullmatch(r"\d{6}", v) else raw), [] if re.fullmatch(r"\d{6}", v) else [("error", "bsb_format")]
    if kind == "sort_code":
        v = re.sub(r"[\s-]", "", raw)
        ok = re.fullmatch(r"\d{6}", v)
        return (f"{v[:2]}-{v[2:4]}-{v[4:]}" if ok else raw), [] if ok else [("error", "sort_code_format")]
    if kind == "aba":
        v = re.sub(r"\s", "", raw)
        problem = aba_ok(v)
        return v, [("error", problem)] if problem else []
    if kind == "ifsc":
        v = compact(raw)
        return v, [] if re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", v) else [("error", "ifsc_format")]
    if kind == "cnaps":
        v = re.sub(r"\s", "", raw)
        return v, [] if re.fullmatch(r"\d{12}", v) else [("error", "cnaps_format")]
    if kind.startswith("digits_"):
        lo, hi = (int(x) for x in kind.split("_")[1:]) if kind.count("_") == 2 else (int(kind.split("_")[1]),) * 2
        v = re.sub(r"[\s-]", "", raw)
        return v, [] if re.fullmatch(rf"\d{{{lo},{hi}}}", v) else [("error", "account_digits")]
    if kind == "cn_account":
        v = re.sub(r"\s", "", raw)
        if not re.fullmatch(r"\d{8,25}", v):
            return v, [("error", "account_digits")]
        if len(v) in (16, 19) and v[0] == "6" and not luhn_ok(v):  # UnionPay cards carry a Luhn check digit
            issues.append(("warn", "card_luhn"))
        return v, issues
    if kind == "charges":
        v = raw.upper()
        return v, [] if v in CHARGES else [("error", "charges_invalid")]
    if kind == "purpose":
        v = raw.upper()
        return v, [] if v in PURPOSES else [("error", "purpose_invalid")]
    if kind == "account_type":
        v = raw.lower()
        return v, [] if v in ("checking", "savings") else [("error", "account_type_invalid")]
    if len(raw) > spec["max"]:
        issues.append(("error", "too_long"))
    if kind == "swift_text" and not SWIFT_TEXT.fullmatch(raw):
        issues.append(("error", "swift_charset"))  # e.g. Chinese characters: use the Latin spelling on the account
    return raw, issues


class TemplatesMixin:
    def _templates_schema(self):
        with self.store.tx() as c:
            c.executescript(SCHEMA)

    @staticmethod
    def transfer_formats():
        return dict(formats={k: dict(currency=v["currency"], fields=[dict(id=f, **spec) for f, spec in v["fields"].items()])
                             for k, v in FORMATS.items()}, purposes=list(PURPOSES), charges=list(CHARGES))

    def validate_template(self, fmt, fields, currency=None):
        if fmt not in FORMATS:
            raise Denied("unknown transfer format", "template_invalid")
        spec = FORMATS[fmt]
        fields = fields if isinstance(fields, dict) else {}
        unknown = set(fields) - set(spec["fields"])
        if unknown:
            raise Denied("unknown template fields", "template_invalid", fields=sorted(unknown))
        clean, issues = {}, []
        for name, fspec in spec["fields"].items():
            default = "SHA" if name == "charges" else "checking" if name == "account_type" else ""
            value, found = check_field(fspec["kind"], fields.get(name, default), fspec)
            if value:
                clean[name] = value
            issues += [dict(field=name, level=lvl, code=code) for lvl, code in found]
        currency = (spec["currency"] or currency or "").upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            issues.append(dict(field="currency", level="error", code="currency_invalid"))
        # cross-field checks
        bic, account = clean.get("bic", ""), clean.get("iban") or clean.get("account", "")
        if bic and len(bic) >= 6 and re.fullmatch(r"[A-Z]{2}\d{2}.*", account) and account[:2] != bic[4:6]:
            issues.append(dict(field="bic", level="warn", code="bic_country_mismatch"))
        if fmt == "swift" and currency == "CNY" and not clean.get("purpose_code"):
            issues.append(dict(field="purpose_code", level="warn", code="purpose_recommended"))
        if fmt == "swift" and currency == "EUR" and not re.fullmatch(r"[A-Z]{2}\d{2}.*", account):
            issues.append(dict(field="account", level="warn", code="iban_expected"))
        country = bic[4:6] if len(bic) >= 6 else (account[:2] if re.fullmatch(r"[A-Z]{2}\d{2}.*", account) else None)
        return dict(format=fmt, currency=currency, fields=clean, issues=issues, country=country,
                    ok=not any(i["level"] == "error" for i in issues))

    # ---------- storage ----------
    def _template_view(self, r, reveal=False):
        body = json.loads(r["body"])
        fields = dict(body["fields"])
        if not reveal:
            for k in SENSITIVE:
                if k in fields:
                    fields[k] = mask(fields[k])
        check = self.validate_template(body["format"], body["fields"], body["currency"])
        return dict(id=r["id"], created=r["created"], updated=r["updated"], **{k: v for k, v in body.items() if k != "fields"},
                    fields=fields, issues=check["issues"], ok=check["ok"], country=check["country"], masked=not reveal)

    def transfer_templates(self):
        with self.store.read() as c:
            rows = c.execute("SELECT * FROM transfer_templates ORDER BY updated DESC").fetchall()
        return [self._template_view(r) for r in rows]

    def transfer_template(self, tid, actor="viewer", reveal=False):
        with self.store.read() as c:
            r = c.execute("SELECT * FROM transfer_templates WHERE id=?", (tid,)).fetchone()
        if not r:
            raise Denied("template not found", "template_unknown")
        return self._template_view(r, reveal=reveal and actor == "owner")  # full numbers only for the owner

    def save_template(self, actor, name, fmt, fields, currency=None, recipient_id=None, amount=None, purpose="", notes="", tid=None):
        self.require(actor, "prepare")
        name = str(name or "").strip()
        if not name or len(name) > 80:
            raise Denied("give the template a name (1-80 characters)", "template_invalid")
        check = self.validate_template(fmt, fields, currency)
        if not check["ok"]:
            raise Denied("fix the highlighted bank details first", "template_fields", issues=check["issues"])
        if recipient_id and not any(r["id"] == recipient_id for r in self.recipients()):
            raise Denied("recipient not found", "recipient_missing")
        minor = units(str(amount), decimals(check["currency"])) if amount not in (None, "") else None
        body = dict(name=name, format=fmt, currency=check["currency"], fields=check["fields"], recipient_id=recipient_id or None,
                    amount=minor, purpose=str(purpose or "")[:200], notes=str(notes or "")[:300],
                    confirmed=actor == "owner", created_by=actor)
        with self.store.tx() as c:
            if tid:
                r = c.execute("SELECT body FROM transfer_templates WHERE id=?", (tid,)).fetchone()
                if not r:
                    raise Denied("template not found", "template_unknown")
                old = json.loads(r["body"])
                if actor != "owner":
                    raise Denied("only the owner can change a saved template", "owner_required")
                changed = {k for k in set(old["fields"]) | set(body["fields"]) if old["fields"].get(k) != body["fields"].get(k)}
                bank_changed = bool(changed & {"account", "iban", "account_number", "bic", "bsb", "sort_code", "routing_number",
                                               "ifsc", "cnaps", "intermediary_bic"})
                # Changed bank details must be confirmed again from an official source.
                body.update(confirmed=old.get("confirmed", False) and not bank_changed, created_by=old.get("created_by", actor),
                            bank_changed=bank_changed or old.get("bank_changed", False))
                c.execute("UPDATE transfer_templates SET body=?, updated=? WHERE id=?", (canonical(body), now(), tid))
                self.store.event(c, actor, "template.update", "ok", tid, format=fmt, bank_changed=bank_changed)
            else:
                tid = str(uuid.uuid4())
                c.execute("INSERT INTO transfer_templates VALUES (?,?,?,?)", (tid, canonical(body), now(), now()))
                self.store.event(c, actor, "template.add", "ok", tid, format=fmt, account=mask(body["fields"].get("account")
                                 or body["fields"].get("iban") or body["fields"].get("account_number") or ""))
        return self.transfer_template(tid, actor, reveal=True)

    def confirm_template(self, actor, tid):
        self.owner(actor)
        with self.store.tx() as c:
            r = c.execute("SELECT body FROM transfer_templates WHERE id=?", (tid,)).fetchone()
            if not r:
                raise Denied("template not found", "template_unknown")
            body = json.loads(r["body"])
            body.update(confirmed=True, bank_changed=False)
            c.execute("UPDATE transfer_templates SET body=?, updated=? WHERE id=?", (canonical(body), now(), tid))
            self.store.event(c, actor, "template.confirm", "ok", tid)
        return self.transfer_template(tid, actor, reveal=True)

    def delete_template(self, actor, tid):
        self.owner(actor)
        with self.store.tx() as c:
            if not c.execute("DELETE FROM transfer_templates WHERE id=?", (tid,)).rowcount:
                raise Denied("template not found", "template_unknown")
            self.store.event(c, actor, "template.delete", "ok", tid)
        return {"deleted": tid}

    # ---------- instruction sheet ----------
    def template_sheet(self, actor, tid, amount=None):
        """Copy-ready instructions for your own bank. Full numbers only for a confirmed template and the owner."""
        self.owner(actor)
        t = self.transfer_template(tid, actor, reveal=True)
        if not t["confirmed"]:
            raise Denied("confirm the bank details against an official source first", "template_unconfirmed")
        cur = t["currency"]
        minor = units(str(amount), decimals(cur)) if amount not in (None, "") else t["amount"]
        order = list(FORMATS[t["format"]]["fields"])  # the order bank forms ask for them
        rows = [dict(field=k, value=t["fields"][k]) for k in order if t["fields"].get(k)]
        if minor:
            rows.insert(0, dict(field="amount", value=f"{from_minor(minor, cur):.{decimals(cur)}f} {cur}"))
        else:
            rows.insert(0, dict(field="currency", value=cur))
        mt103 = None
        if t["format"] == "swift":
            f = t["fields"]
            value_date = date.today().strftime("%y%m%d")
            amt = f"{from_minor(minor, cur):.{decimals(cur)}f}".replace(".", ",") if minor else "(amount)"
            lines = [f":32A:{value_date}{cur}{amt}", ":50K:(your name and address as on your account)"]
            if f.get("intermediary_bic"):
                lines.append(f":56A:{f['intermediary_bic']}")
            lines += [f":57A:{f['bic']}", f":59:/{f['account']}", f["beneficiary_name"], *f["beneficiary_address"].splitlines()[:3]]
            if f.get("reference") or f.get("purpose_code"):
                lines.append(":70:" + " ".join(x for x in (f.get("purpose_code") and "/PURP/" + f["purpose_code"], f.get("reference")) if x)[:140])
            lines.append(f":71A:{f.get('charges', 'SHA')}")
            mt103 = "\n".join(lines)
        text = "\n".join(f"{r['field']}: {r['value']}" for r in rows)
        with self.store.tx() as c:
            self.store.event(c, actor, "template.sheet", "ok", tid)
        return dict(id=t["id"], name=t["name"], format=t["format"], currency=cur, rows=rows, text=text, mt103=mt103,
                    country=t["country"], note="instructions for your own bank; DOT does not send them. A real MT103 is generated by your bank.")
