"""The bank knowledge base: which banks matter for a currency, and every fee each bank publishes — each fee with the
exact page text it was read from, the page's address and when it was read, so anyone can check it.

Two tables, refreshed on their own:
- bank_catalog: the banks the AI found for a currency (beyond the built-in list), with their official pages. An address
  the AI gives is only a lead: it is read like any other page (public https only), and a page that cannot be read says so.
- bank_fees: fee items found on a bank's pages by keyword (外汇手续费, 电讯费, cable charge, intermediary…), structured by
  the model and kept only when the quoted text is on the page and states every number given. They are reference
  information shown with their source; the scenario ranking keeps using the stricter checked figures in bank_pricing.
Every automatic read of a bank (at most daily) reads its fees again and replaces what that page said before.
"""
import json
import re
from urllib.parse import urlparse
from .domain import Denied, canonical, now

KB_SCHEMA = """
CREATE TABLE IF NOT EXISTS bank_catalog (id TEXT PRIMARY KEY, body TEXT NOT NULL, origin TEXT NOT NULL, updated INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS bank_discovery (currency TEXT PRIMARY KEY, updated INTEGER NOT NULL, found INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS bank_fees (bank TEXT NOT NULL, url TEXT NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL, body TEXT NOT NULL,
    fetched INTEGER NOT NULL, PRIMARY KEY (bank, url, kind, label));
"""
DISCOVERY_SECONDS = 30 * 24 * 3600  # the main banks for a currency are looked up again after a month
FEE_KINDS = ("send_fee", "cable_fee", "fx_fee", "intermediary", "receive_fee", "other")
# What fee lines look like, in the languages bank pages are written in.
FEE_WORDS = re.compile(
    r"手续费|手續費|电讯费|電訊費|电报费|電報費|邮电费|郵電費|汇款费|匯款費|汇费|中间行|中轉行|中转行|代理行|汇入|匯入|收款费|入账费|外汇|外匯|"
    r"cable charge|telegraphic|telex|swift|wire fee|transfer fee|international (money )?transfer|overseas transfer|correspondent|"
    r"intermediary|beneficiary bank|receiving fee|incoming|inward|outward|commission|service fee|handling fee|charges? (apply|of)",
    re.I)
SNIPPET_CHARS = 6000
HOME_CURRENCY = {"CN": "CNY", "AU": "AUD", "HK": "HKD", "US": "USD", "GB": "GBP", "JP": "JPY", "KR": "KRW", "VN": "VND", "NZ": "NZD",
                 "SG": "SGD", "CA": "CAD"}


def fee_lines(text):
    """The lines of a page that talk about fees (with one line of context each side): what the model should look at."""
    lines = text.split("\n")
    keep = set()
    for i, line in enumerate(lines):
        if FEE_WORDS.search(line):
            keep.update(range(max(0, i - 1), min(len(lines), i + 2)))
    return "\n".join(lines[i] for i in sorted(keep))[:SNIPPET_CHARS]


FEES_FIELD = (
    '"fees": [{"kind": "send_fee|cable_fee|fx_fee|intermediary|receive_fee|other", "label": "the fee\'s name as the page says it", '
    '"amount": "fixed amount or null", "currency": "ISO code or null", "pct": "percent or null (convert ‰ to percent)", '
    '"min": "minimum charge or null", "max": "maximum charge or null", "quote": "exact page text (at most 200 characters) '
    'containing every number you give"}] — every fee or charge these pages state for international transfers or currency '
    'exchange: sending fee (汇款手续费), cable/telegraph charge (电讯费/电报费, cable charge, SWIFT fee), foreign exchange fee '
    '(外汇手续费), intermediary/correspondent deductions (中间行/代理行费), receiving fee (汇入/收款手续费). Empty list if none.')


def discovery_prompt(currency):
    return (f"Which banks do people most often use to send or receive international transfers in {currency}? List up to 8 real "
            "banks (both banks in the country of that currency and major banks abroad that hold accounts in it, e.g. a Chinese "
            "bank's overseas branch). Reply with JSON only: "
            '{"banks": [{"name": "official English name", "name_zh": "Chinese name or null", "country": "two-letter country code", '
            '"website": "https://official home page", "fee_page": "https://official page listing international transfer fees, or null", '
            '"currencies": ["ISO codes it holds accounts in"]}]}. '
            "Only official domains of the bank itself; null for any address you are not sure of. Never invent a bank.")


def _https(url):
    try:
        u = urlparse(str(url or ""))
    except ValueError:
        return None
    return u.geturl()[:300] if u.scheme == "https" and u.hostname and "." in u.hostname and not u.username else None


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30]


def _same_bank(name, currency):
    """A built-in bank only when the whole name is one of its names: "Agricultural Bank of China" is not "Bank of China"."""
    from .banks import ALIASES, BY_ID, find_bank
    key = " ".join(str(name or "").lower().replace("_", " ").split())
    if not key or not (key in BY_ID or any(key in names for names in ALIASES.values())):
        return None
    return find_bank(key, currency)


def _num(v):
    from .banks import _dec
    d = _dec(v)
    return d if d is not None and d < 10 ** 9 else None


def verify_fee_items(items, pages):
    """Keep a fee item only if its quote is on one of the pages and contains every number it gives (in that currency,
    when one is named; as a percent or per-mille, when a percentage is given)."""
    from .banks import _norm, _figures, _pairs, CURRENCY_WORDS
    texts = {u: _norm(t) for u, t in pages}
    kept = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        quote = _norm(it.get("quote"))[:220]
        url = next((u for u, t in texts.items() if quote and quote in t), None)
        if not url:
            continue
        figures = _figures(quote)
        amount, pct, lo, hi = (_num(it.get(k)) for k in ("amount", "pct", "min", "max"))
        if not any(x is not None for x in (amount, pct, lo, hi)):
            continue
        # every number must be in the quote (a percentage may be written per mille: 0.1% is 1‰)
        if any(x is not None and x not in figures and not (k == "pct" and (x * 10) in figures) for k, x in
               (("amount", amount), ("pct", pct), ("min", lo), ("max", hi))):
            continue
        if pct is not None and not re.search(r"%|‰|percent|百分之|千分之", quote):
            continue
        currency = str(it.get("currency") or "").upper()[:3]
        if currency and currency in CURRENCY_WORDS and amount is not None:
            named = {c for c, _ in _pairs(quote)} | {c for c, words in CURRENCY_WORDS.items() if any(w in quote for w in words if len(w) > 1)}
            if named and currency not in named:
                continue
        kind = it.get("kind") if it.get("kind") in FEE_KINDS else "other"
        label = re.sub(r"\s+", " ", str(it.get("label") or "")).strip()[:80] or kind
        kept.append(dict(kind=kind, label=label, amount=str(amount) if amount is not None else None,
                         currency=currency if re.fullmatch(r"[A-Z]{3}", currency) else None,
                         pct=str(pct) if pct is not None else None, min=str(lo) if lo is not None else None,
                         max=str(hi) if hi is not None else None, quote=quote, url=url))
    return kept


class BankKnowledgeMixin:
    def _kb_schema(self, c):
        c.executescript(KB_SCHEMA)

    # ---------- which banks: built in, plus what the AI found per currency ----------
    def catalog_banks(self):
        with self.store.read() as c:
            return {r["id"]: dict(json.loads(r["body"]), id=r["id"], origin=r["origin"], found=r["updated"])
                    for r in c.execute("SELECT * FROM bank_catalog")}

    def _discovery_stale(self, currency):
        with self.store.read() as c:
            r = c.execute("SELECT updated FROM bank_discovery WHERE currency=?", (currency,)).fetchone()
        return r is None or now() - r[0] > DISCOVERY_SECONDS

    def discover_banks(self, currency):
        """Ask the model for the main banks of a currency and keep them (with their official pages) for the bank lists."""
        from .banks import BY_ID, find_bank
        currency = (currency or "").upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise Denied("currency must be an ISO code", "currency_invalid")
        with self.store.tx() as c:  # claimed first: two pages opening at once do not both ask
            c.execute("INSERT INTO bank_discovery VALUES (?,?,0) ON CONFLICT(currency) DO UPDATE SET updated=excluded.updated",
                      (currency, now()))
        raw = self._ask_pages(discovery_prompt(currency))
        found = 0
        with self.store.tx() as c:
            for b in (raw.get("banks") or [])[:8] if isinstance(raw.get("banks"), list) else []:
                if not isinstance(b, dict):
                    continue
                name = re.sub(r"\s+", " ", str(b.get("name") or "")).strip()[:80]
                country = str(b.get("country") or "").upper()
                if len(name) < 2 or not re.fullmatch(r"[A-Z]{2}", country):
                    continue
                currencies = sorted({str(x).upper() for x in (b.get("currencies") or []) if re.fullmatch(r"[A-Za-z]{3}", str(x))} | {currency})
                urls = [u for u in (_https(b.get("fee_page")), _https(b.get("website"))) if u]
                home = HOME_CURRENCY.get(country, currency)  # "Bank of China" in CN is not its Sydney branch
                known = _same_bank(name, home) or _same_bank(b.get("name_zh"), home)
                if known in BY_ID:  # a bank we already list: only its extra pages and currencies are added
                    old = c.execute("SELECT body FROM bank_catalog WHERE id=?", (known,)).fetchone()
                    body = json.loads(old[0]) if old else {}
                    body.update(extra_urls=sorted(set(body.get("extra_urls", []) + urls))[:3],
                                extra_currencies=sorted(set(body.get("extra_currencies", []) + currencies)))
                    c.execute("INSERT INTO bank_catalog VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body, updated=excluded.updated",
                              (known, canonical(body), "builtin", now()))
                    continue
                bid = "x_" + _slug(name)
                old = c.execute("SELECT body FROM bank_catalog WHERE id=?", (bid,)).fetchone()
                prev = json.loads(old[0]) if old else {}
                body = dict(name=name, name_zh=str(b.get("name_zh") or "")[:40] or None, country=country,
                            currencies=sorted(set(prev.get("currencies", [])) | set(currencies)), days=[1, 3],
                            urls=urls or prev.get("urls", []), website=_https(b.get("website")))
                c.execute("INSERT INTO bank_catalog VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body, updated=excluded.updated",
                          (bid, canonical(body), "ai", now()))
                found += 1
            c.execute("UPDATE bank_discovery SET found=? WHERE currency=?", (found, currency))
            self.store.event(c, "agent", "bank.discover", "ok", currency, found=found)
        return found

    # ---------- what each bank charges, with sources ----------
    def store_fee_items(self, bank_id, items, pages):
        """Replace what these pages said before with what they say now (only verified items)."""
        kept = verify_fee_items(items, pages)
        with self.store.tx() as c:
            for u, _ in pages:
                c.execute("DELETE FROM bank_fees WHERE bank=? AND url=?", (bank_id, u))
            for it in kept:
                c.execute("INSERT OR REPLACE INTO bank_fees VALUES (?,?,?,?,?,?)",
                          (bank_id, it["url"], it["kind"], it["label"], canonical(it), now()))
        return kept

    def bank_knowledge(self, bank_id=None):
        """Every known fee item, newest first, each with its quote, its page and when it was read."""
        sql, args = "SELECT * FROM bank_fees", ()
        if bank_id:
            sql, args = sql + " WHERE bank=?", (bank_id,)
        with self.store.read() as c:
            rows = c.execute(sql + " ORDER BY fetched DESC", args).fetchall()
        return [dict(json.loads(r["body"]), bank=r["bank"], fetched=r["fetched"]) for r in rows]
