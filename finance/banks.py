"""Bank exchange rates and wire fees, read from the banks' own public pages, and exchange scenarios built on them.

Pricing per bank and currency pair comes from, in this order:
- "ai": the backend fetches the bank's official public pages (rate tables, fee schedules), turns them into text and the
  AI model extracts the rate and the fees — with the source links and the time they were read;
- "ai_knowledge": when the pages cannot be read or say nothing, the model's own knowledge of the bank's standard
  published fees and its usual margin over the mid-market rate — clearly labelled as an estimate that may be dated;
- "user": the student types or corrects the figures, only when both of the above fail.
Everything is public information, not a quote: banks change rates many times a day and may charge more.

Scenarios combine a sending bank and a receiving bank: convert at the sending bank, or send the original currency and
let the receiving bank convert; pay at once, or in two parts (half now, half in a week at the experimental forecast).
Each counts every fee it knows about and names the ones it does not.
"""
import html
import ipaddress
import json
import re
import socket
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse, urljoin
import httpx
from .domain import Denied, canonical, now, decimals, from_minor, to_minor, floor_minor

SCHEMA = """
CREATE TABLE IF NOT EXISTS bank_pricing (bank TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, data TEXT NOT NULL,
    origin TEXT NOT NULL, status TEXT NOT NULL, error TEXT, urls TEXT, updated INTEGER NOT NULL, PRIMARY KEY (bank, source, target));
"""
# Official public pages for international transfers and exchange rates. Editable per bank in the app; a page that moved
# or is rendered by scripts simply yields "could not read" and asks for a hand entry.
BANKS = [
    dict(id="cba", name="Commonwealth Bank", country="AU", currencies=["AUD"],
         urls=["https://www.commbank.com.au/international/international-money-transfer.html"]),
    dict(id="westpac", name="Westpac", country="AU", currencies=["AUD"],
         urls=["https://www.westpac.com.au/personal-banking/services/money-transfers/international-money-transfers/"]),
    dict(id="nab", name="NAB", country="AU", currencies=["AUD"],
         urls=["https://www.nab.com.au/personal/international-banking/international-money-transfers"]),
    dict(id="anz", name="ANZ", country="AU", currencies=["AUD"],
         urls=["https://www.anz.com.au/personal/travel-international/sending-money-overseas/"]),
    dict(id="boc", name="Bank of China", country="CN", currencies=["CNY"],
         urls=["https://www.boc.cn/sourcedb/whpj/"]),
    dict(id="icbc", name="ICBC", country="CN", currencies=["CNY"], urls=["https://www.icbc.com.cn/"]),
    dict(id="ccb", name="China Construction Bank", country="CN", currencies=["CNY"], urls=["https://www.ccb.com/"]),
    dict(id="cmb", name="China Merchants Bank", country="CN", currencies=["CNY"], urls=["https://fx.cmbchina.com/hq/"]),
    dict(id="hsbc", name="HSBC", country="HK", currencies=["HKD", "AUD", "USD", "GBP", "CNY"],
         urls=["https://www.hsbc.com.au/international/international-money-transfers/"]),
    dict(id="wise", name="Wise", country="GB", currencies=["AUD", "CNY", "USD", "EUR", "GBP", "JPY", "KRW", "VND", "SGD", "NZD", "CAD"],
         urls=["https://wise.com/au/send-money/send-money-to-china"]),
]
BY_ID = {b["id"]: b for b in BANKS}
MAX_PAGE = 1_500_000
MAX_TEXT = 40_000


def _public_host(host):
    """Only fetch from public internet addresses (no localhost, private networks or metadata endpoints)."""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


def fetch_page(url, client=None):
    """GET a public https page (at most 3 redirects, size-capped) and return readable text."""
    for _ in range(4):
        parts = urlparse(url)
        if parts.scheme != "https" or not parts.hostname or not _public_host(parts.hostname):
            raise Denied("only public https pages can be read", "bank_url_invalid")
        get = client.get if client else httpx.get
        r = get(url, timeout=15, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0 (DOT student finance; reads public rate pages)",
                                                                 "Accept-Language": "en,zh;q=0.8"})
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            url = urljoin(url, r.headers["location"])
            continue
        if r.status_code != 200:
            raise Denied(f"the page answered {r.status_code}", "bank_fetch_failed")
        body = r.content[:MAX_PAGE]
        return page_text(body.decode(r.encoding or "utf-8", errors="replace"))
    raise Denied("too many redirects", "bank_fetch_failed")


def page_text(markup):
    text = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", markup)
    text = re.sub(r"(?i)</(tr|p|div|li|h\d|table|br)\s*>|<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</t[dh]\s*>", " | ", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text[:MAX_TEXT]


def pricing_prompt(bank, source, target, pages):
    return (f"These are public pages of {bank['name']} ({bank['country']}). A student sends money from {source} to {target}. "
            "Extract what this bank publishes for that, as JSON only: "
            '{"found": true|false, "rate": "target units per 1 source unit or null", "rate_kind": "e.g. telegraphic transfer buying rate", '
            '"rate_date": "YYYY-MM-DD or null", "fee_send": {"amount": "...", "currency": "..."} or null, "fee_pct": "percent or null", '
            '"intermediary": {"amount": "...", "currency": "..."} or null, "fee_receive": {"amount": "...", "currency": "..."} or null, '
            '"notes": "one short sentence"}. '
            f"The rate is how many {target} one {source} becomes through this bank: a bank in the sending country sells {target}; "
            f"a bank in the receiving country buys {source} (for example a Chinese bank's spot exchange buying rate for {source}). "
            "Tables are often quoted per 100 units of foreign currency: divide accordingly. fee_send is the bank's own charge for "
            "sending an international transfer online; fee_receive is what it charges for receiving one. Use null for anything the "
            "pages do not state; never guess, never use outside knowledge. found=false if the pages say nothing useful.\n\n"
            + "\n\n".join(f"PAGE {u}\n{t}" for u, t in pages))


def knowledge_prompt(bank, source, target):
    return (f"From your general knowledge (not live data), what does {bank['name']} ({bank['country']}) usually charge a personal "
            f"customer for an online international transfer from {source} to {target}? Reply with JSON only: "
            '{"found": true|false, "fee_send": {"amount": "...", "currency": "..."} or null, "fee_pct": "percent or null", '
            '"intermediary": {"amount": "...", "currency": "..."} or null, "fee_receive": {"amount": "...", "currency": "..."} or null, '
            '"rate_margin_pct": "typical markup of its exchange rate over the mid-market rate, in percent, or null", '
            '"as_of": "year your knowledge is from", "notes": "one short sentence"}. '
            "fee_send is the bank's own sending fee, fee_receive what it charges to receive an international transfer, "
            "intermediary a typical correspondent-bank deduction on this corridor. Use the bank's standard published fees; "
            "null for what you do not know; found=false if you know nothing about this bank.")


def _dec(v):
    try:
        d = Decimal(str(v).replace(",", "").strip())
        return d if d.is_finite() and d >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _money(v):
    if not isinstance(v, dict):
        return None
    amount, cur = _dec(v.get("amount")), str(v.get("currency") or "").upper()[:3]
    return dict(amount=str(amount), currency=cur) if amount is not None and re.fullmatch(r"[A-Z]{3}", cur) else None


def clean_pricing(raw):
    rate = _dec(raw.get("rate"))
    pct = _dec(raw.get("fee_pct"))
    margin = _dec(raw.get("rate_margin_pct"))
    return dict(rate=str(rate) if rate and rate > 0 else None, rate_margin_pct=str(margin) if margin is not None and margin < 10 else None, rate_kind=str(raw.get("rate_kind") or "")[:80] or None,
                rate_date=str(raw.get("rate_date") or "")[:10] or None, fee_send=_money(raw.get("fee_send")),
                fee_pct=str(pct) if pct is not None and pct < 10 else None, intermediary=_money(raw.get("intermediary")),
                fee_receive=_money(raw.get("fee_receive")), notes=str(raw.get("notes") or "")[:200])


class BanksMixin:
    page_reader = None  # set by the API: (prompt) -> model text, for reading bank pages

    def _banks_schema(self):
        with self.store.tx() as c:
            c.executescript(SCHEMA)

    def banks(self, source=None, target=None):
        """The bank list; with a pair, each bank's known pricing for it."""
        out = []
        prices = {}
        if source and target:
            with self.store.read() as c:
                for r in c.execute("SELECT * FROM bank_pricing WHERE source=? AND target=?", (source.upper(), target.upper())):
                    prices[r["bank"]] = dict(json.loads(r["data"]), origin=r["origin"], status=r["status"], error=r["error"],
                                             updated=r["updated"], urls=json.loads(r["urls"] or "[]"))
        for b in BANKS:
            row = dict(b, side=("send" if source and source.upper() in b["currencies"] else "receive" if target and target.upper() in b["currencies"] else None))
            row["pricing"] = prices.get(b["id"])
            out.append(row)
        return out

    def _bank(self, bank_id):
        if bank_id not in BY_ID:
            raise Denied("unknown bank", "bank_unknown")
        return BY_ID[bank_id]

    def _store_pricing(self, actor, bank_id, source, target, data, origin, status, error=None, urls=None):
        with self.store.tx() as c:
            c.execute("INSERT INTO bank_pricing VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(bank, source, target) DO UPDATE SET "
                      "data=excluded.data, origin=excluded.origin, status=excluded.status, error=excluded.error, urls=excluded.urls, updated=excluded.updated",
                      (bank_id, source, target, canonical(data), origin, status, error, json.dumps(urls or []), now()))
            self.store.event(c, actor, "bank.pricing", status, bank_id, pair=f"{source}-{target}", origin=origin)

    def _ask_pages(self, prompt):
        reply = self.page_reader(prompt) if self.page_reader else None
        if reply is None:
            raise Denied("the AI model is not available to read bank information; enter the figures by hand", "bank_needs_model")
        try:
            return json.loads(re.search(r"\{.*\}", reply, re.S).group(0))
        except (AttributeError, ValueError, TypeError):
            return {}

    @staticmethod
    def _useful(data):
        return bool(data and (data.get("rate") or data.get("fee_send") or data.get("fee_receive") or data.get("rate_margin_pct")))

    def refresh_bank(self, actor, bank_id, source, target, urls=None, client=None):
        """Read the bank's public pages and let the AI extract the rate and fees; if that fails, use what the AI knows."""
        self.require(actor, "prepare")
        bank, source, target = self._bank(bank_id), source.upper(), target.upper()
        urls = [u for u in (urls or bank["urls"]) if isinstance(u, str)][:3]
        pages, errors = [], []
        for u in urls:
            try:
                pages.append((u, fetch_page(u, client)))
            except (Denied, httpx.HTTPError) as exc:
                errors.append(f"{urlparse(u).hostname}: {getattr(exc, 'code', type(exc).__name__)}")
        if pages:
            raw = self._ask_pages(pricing_prompt(bank, source, target, pages))
            data = clean_pricing(raw) if raw.get("found") else {}
            if self._useful(data):
                data["sources"] = [u for u, _ in pages]
                self._store_pricing(actor, bank_id, source, target, data, "ai", "ok", None, urls)
                return self.banks(source, target)
            errors.append("the pages did not state the figures")
        # Second source: the model's own knowledge of the bank's standard fees (an estimate, labelled as one).
        raw = self._ask_pages(knowledge_prompt(bank, source, target))
        data = clean_pricing(raw) if raw.get("found") else {}
        data["rate"] = None  # rates move every day: never take one from memory
        if self._useful(data):
            data["sources"] = ["ai_knowledge"]
            data["as_of"] = str(raw.get("as_of") or "")[:10]
            self._store_pricing(actor, bank_id, source, target, data, "ai_knowledge", "ok", "; ".join(errors)[:300] or None, urls)
            return self.banks(source, target)
        self._store_pricing(actor, bank_id, source, target, {}, "ai", "failed", "; ".join(errors + ["no known figures"])[:300], urls)
        raise Denied("neither the bank's pages nor the AI's knowledge gave figures; enter them by hand", "bank_fetch_failed")

    def set_bank_pricing(self, actor, bank_id, source, target, values):
        """The student's own figures (from the bank's app, a statement or a phone call)."""
        self.owner(actor)
        self._bank(bank_id)
        data = clean_pricing(values or {})
        data["sources"] = ["entered by you"]
        self._store_pricing(actor, bank_id, source.upper(), target.upper(), data, "user", "ok")
        return self.banks(source, target)

    # ---------- scenarios ----------
    def _fee_in(self, fee, currency):
        """A fee converted into the given currency at the reference rate; None if it cannot be converted."""
        if not fee:
            return 0
        minor = to_minor(Decimal(fee["amount"]), fee["currency"])
        if fee["currency"] == currency:
            return minor
        try:
            rate = Decimal(self.rates.latest(fee["currency"], currency)["rate"])
        except Denied:
            return None
        return to_minor(from_minor(minor, fee["currency"]) * rate, currency)

    @staticmethod
    def _bank_rate(p, ref):
        """(rate, how it is known): the bank's published rate, else reference minus its usual margin, else the reference."""
        if p.get("rate"):
            return Decimal(p["rate"]), "bank"
        if p.get("rate_margin_pct"):
            return ref * (1 - Decimal(p["rate_margin_pct"]) / 100), "estimate"
        return ref, "reference"

    def exchange_scenarios(self, source, target, amount, mode="send", send_bank=None, receive_bank=None, due=None):
        source, target = source.upper(), target.upper()
        if mode not in ("send", "receive"):
            raise Denied("mode must be send or receive", "amount_mode")
        try:
            value = Decimal(str(amount).replace(",", ""))
            if not value.is_finite() or value <= 0:
                raise InvalidOperation
        except InvalidOperation:
            raise Denied("enter a positive amount", "amount_invalid") from None
        ref = Decimal(self.rates.latest(source, target)["rate"])
        try:
            fc = self.rates.forecast(source, target)
        except Denied:
            fc = {"available": False}
        drift = (Decimal(str(fc["point"])) / ref) if fc.get("available") else None
        prices = {b["id"]: b for b in self.banks(source, target)}
        senders = [send_bank] if send_bank else [b for b, x in prices.items() if x["side"] == "send" and (x["pricing"] or {}).get("status") == "ok"][:3]
        receivers = [receive_bank] if receive_bank else [b for b, x in prices.items() if x["side"] == "receive" and (x["pricing"] or {}).get("status") == "ok"][:2]
        today = date.today()
        later = min(date.fromisoformat(due), today + timedelta(days=7)) if due else today + timedelta(days=7)
        if later <= today:
            later = today + timedelta(days=1)
        out = []

        def leg(day, part, rate, fees_src, fee_dst):
            """One payment: how much leaves (source) and arrives (target) for this part of the amount."""
            if mode == "send":
                spend = to_minor(value * part, source)
                receive = floor_minor(from_minor(max(0, spend - fees_src), source) * rate, target) - fee_dst
            else:
                receive = to_minor(value * part, target)
                spend = to_minor(from_minor(receive + fee_dst, target) / rate, source) + fees_src
            return dict(date=str(day), spend=spend, receive=max(0, receive), rate=str(rate.quantize(Decimal("0.000001"))), fees=fees_src)

        def scenario(sid, convert_at, sb, rb, rate, rate_known):
            sp = (prices.get(sb) or {}).get("pricing") or {}
            rp = (prices.get(rb) or {}).get("pricing") or {}
            unknown = []
            fee_send = self._fee_in(sp.get("fee_send"), source) if sb else 0
            if sb and not sp.get("fee_send"):
                unknown.append("send_fee")
            pct = Decimal(sp["fee_pct"]) / 100 if sp.get("fee_pct") else Decimal(0)
            inter = self._fee_in(sp.get("intermediary"), source) if sp.get("intermediary") else 0
            if not sp.get("intermediary"):
                unknown.append("intermediary")
            fee_recv = self._fee_in(rp.get("fee_receive"), target) if rb and rp.get("fee_receive") else 0
            if rb and not rp.get("fee_receive"):
                unknown.append("receive_fee")
            if rate_known == "reference":
                unknown.append("bank_rate")
            fixed = (fee_send or 0) + (inter or 0)
            base_src = to_minor(value, source) if mode == "send" else to_minor(from_minor(to_minor(value, target), target) / rate, source)
            fees_src = fixed + int(base_src * pct)
            once = [leg(today, Decimal(1), rate, fees_src, fee_recv or 0)]
            plans = [("once", once)]
            if drift is not None:
                half_fees = fixed + int(base_src * pct / 2)  # every part pays the fixed fees again
                plans.append(("split", [leg(today, Decimal("0.5"), rate, half_fees, fee_recv or 0),
                                        leg(later, Decimal("0.5"), rate * drift, half_fees, fee_recv or 0)]))
            for timing, legs in plans:
                out.append(dict(id=f"{sid}-{timing}", send_bank=sb, receive_bank=rb, convert_at=convert_at, timing=timing, legs=legs,
                                total_spend=sum(x["spend"] for x in legs), total_receive=sum(x["receive"] for x in legs),
                                total_fees=sum(x["fees"] for x in legs) + (fee_recv or 0) * len(legs), unknown=unknown,
                                rate_source=rate_known if isinstance(rate_known, str) else ("bank" if rate_known else "reference"),
                                estimated=any(((prices.get(b) or {}).get("pricing") or {}).get("origin") == "ai_knowledge" for b in (sb, rb) if b)))

        for sb in senders or [None]:
            for rb in receivers or [None]:
                sp = (prices.get(sb) or {}).get("pricing") or {}
                rp = (prices.get(rb) or {}).get("pricing") or {}
                if sb:
                    rate, known = self._bank_rate(sp, ref)
                    scenario(f"{sb}-{rb or 'any'}-s", "send_bank", sb, rb, rate, known)
                if rb and (rp.get("rate") or rp.get("rate_margin_pct")):
                    rate, known = self._bank_rate(rp, ref)
                    scenario(f"{sb or 'any'}-{rb}-r", "receive_bank", sb, rb, rate, known)
                if not sb and not (rb and (rp.get("rate") or rp.get("rate_margin_pct"))):
                    scenario(f"ref-{rb or 'any'}", "reference", None, rb, ref, "reference")
        key = (lambda s: -s["total_receive"]) if mode == "send" else (lambda s: s["total_spend"])
        out.sort(key=key)
        for i, s in enumerate(out):
            s["rank"] = i + 1
        return dict(source=source, target=target, mode=mode, amount=str(value), reference=str(ref), forecast=fc if fc.get("available") else None,
                    later=str(later), scenarios=out[:8],
                    note="public bank information read by AI or entered by you — not a quote; fees the banks do not publish are listed as unknown")
