"""Cash position and exchange needs for the overview.

How much money you have: per currency, the latest known balance — typed in by you, or taken from the balance column of
an imported bank CSV, whichever is newer. Simulated sandbox funds are shown apart and never mixed in.
What to exchange: upcoming needs per currency (tuition, a term's living costs, bills, goals) against
the cash you hold in that currency; a shortfall becomes "exchange about X from your main currency at today's rate".
Every figure is a reference estimate, not a quote.
"""
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from .domain import Denied, now, units, decimals, from_minor, to_minor

SCHEMA = """
CREATE TABLE IF NOT EXISTS cash_balances (id INTEGER PRIMARY KEY AUTOINCREMENT, currency TEXT NOT NULL, amount INTEGER NOT NULL,
    as_of TEXT NOT NULL, source TEXT NOT NULL, label TEXT, created INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS cash_currency ON cash_balances(currency, as_of);
CREATE TABLE IF NOT EXISTS sandbox_currencies (currency TEXT PRIMARY KEY, added INTEGER NOT NULL);
"""
HORIZON = 60  # days of upcoming needs considered


class MoneyMixin:
    def _money_schema(self):
        with self.store.tx() as c:
            c.executescript(SCHEMA)
            # One source of truth: where you entered a balance, the payment ledger follows it.
            for (cur,) in c.execute("SELECT DISTINCT currency FROM cash_balances").fetchall():
                self._sync_ledger(c, cur)

    @staticmethod
    def _latest_cash(c, currency):
        # a balance dated in the future is not money you have today (older data may hold one)
        r = c.execute("SELECT amount FROM cash_balances WHERE currency=? AND as_of<=? ORDER BY as_of DESC, created DESC, id DESC LIMIT 1",
                      (currency, str(date.today()))).fetchone()
        return None if r is None else int(r[0])

    @classmethod
    def _in_sandbox(cls, c, currency):
        """The sandbox holds a currency you have a balance in, or one you added to it yourself — nothing else."""
        return cls._latest_cash(c, currency) is not None or c.execute(
            "SELECT 1 FROM sandbox_currencies WHERE currency=?", (currency,)).fetchone() is not None

    def add_sandbox_currency(self, actor, currency, amount=None):
        """Put a currency you do not hold into the sandbox, starting from the test amount you give (or nothing)."""
        self.owner(actor)
        currency = (currency or "").upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise Denied("currency must be an ISO code", "currency_invalid")
        start = units(str(amount), decimals(currency)) if amount not in (None, "", "0") else 0
        if start > 10000 * 10 ** decimals(currency):
            raise Denied("test top-up limited to 10,000 per action", "fund_limit")
        with self.store.tx() as c:
            if self._in_sandbox(c, currency):
                raise Denied("this currency is already in the sandbox", "sandbox_currency_exists")
            c.execute("INSERT INTO sandbox_currencies VALUES (?,?)", (currency, now()))
            c.execute("INSERT INTO balances(currency,total) VALUES (?,?) ON CONFLICT(currency) DO UPDATE SET total=excluded.total",
                      (currency, str(start)))  # a fresh start, whatever an older version left there
            self.store.event(c, actor, "sandbox.currency_add", "ok", currency, units=str(start), label="simulated test funds")
        return self.balances()

    def remove_sandbox_currency(self, actor, currency):
        """Take an added currency out again; one you hold, or one with a payment on its way, stays."""
        self.owner(actor)
        currency = (currency or "").upper()
        with self.store.tx() as c:
            if self._latest_cash(c, currency) is not None:
                raise Denied("this is a currency you hold; clear its balance on the overview instead", "sandbox_currency_own")
            busy = any(json.loads(r[0])["source"] == currency
                       for r in c.execute("SELECT body FROM transfers WHERE status IN ('pending','unknown')"))
            if busy:
                raise Denied("a payment from this currency is still on its way", "sandbox_currency_busy")
            if not c.execute("DELETE FROM sandbox_currencies WHERE currency=?", (currency,)).rowcount:
                raise Denied("this currency is not in the sandbox", "currency_unknown")
            self.store.event(c, actor, "sandbox.currency_remove", "ok", currency)
        return self.balances()

    # what changes a balance inside DOT after a statement was taken: those a statement of the same day or older cannot undo
    MOVEMENTS = ("exchange", "transfer", "test_funds")

    @classmethod
    def _statement_check(cls, c, currency, minor, as_of):
        """Whether a bank statement's closing balance may become what you have now. None = yes; otherwise why not:
        'future' — dated after today; 'duplicate' — this exact snapshot is already recorded (a re-import changes nothing);
        'stale' — an exchange or payment was recorded on or after its date, which the statement cannot know about.
        Then the balance stays; you reconcile by entering the balance yourself."""
        if as_of > str(date.today()):
            return "future"
        if minor is not None and c.execute("SELECT 1 FROM cash_balances WHERE currency=? AND source='csv' AND as_of=? AND amount=?",
                                           (currency, as_of, int(minor))).fetchone():
            return "duplicate"
        if c.execute(f"SELECT 1 FROM cash_balances WHERE currency=? AND as_of>=? AND source IN ({','.join('?' * len(cls.MOVEMENTS))})",
                     (currency, as_of, *cls.MOVEMENTS)).fetchone():
            return "stale"
        return None

    def _sync_ledger(self, c, currency):
        """Payments draw on the balance you see on the overview, not on a separate pot of test money."""
        amount = self._latest_cash(c, currency)
        if amount is not None:
            c.execute("INSERT INTO balances(currency,total) VALUES (?,?) ON CONFLICT(currency) DO UPDATE SET total=excluded.total",
                      (currency, str(amount)))

    def _record_cash(self, c, actor, currency, amount, as_of, source, label=""):
        c.execute("INSERT INTO cash_balances(currency,amount,as_of,source,label,created) VALUES (?,?,?,?,?,?)",
                  (currency, int(amount), as_of, source, (label or "")[:120], now()))
        self.store.event(c, actor, "cash.record", "ok", currency, source=source, as_of=as_of)
        self._sync_ledger(c, currency)

    def set_cash(self, actor, currency, amount, label=""):
        self.owner(actor)
        currency = (currency or "").upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise Denied("currency must be an ISO code", "currency_invalid")
        text = str(amount).strip()
        negative = text.startswith("-")
        minor = units(text.lstrip("-"), decimals(currency)) if text.lstrip("-") not in ("", "0") else 0
        with self.store.tx() as c:
            self._record_cash(c, actor, currency, -minor if negative else minor, str(date.today()), "manual", label)
        return self.cash_position()

    def clear_cash(self, actor, currency):
        self.owner(actor)
        with self.store.tx() as c:
            if not c.execute("DELETE FROM cash_balances WHERE currency=?", ((currency or "").upper(),)).rowcount:
                raise Denied("no balance recorded for that currency", "cash_unknown")
            c.execute("UPDATE balances SET total='0' WHERE currency=?", (currency.upper(),))  # nothing left to pay from
            self.store.event(c, actor, "cash.clear", "ok", currency.upper())
        return self.cash_position()

    def cash_balances(self):
        """The latest known balance per currency (newest date wins, then the newest entry)."""
        with self.store.read() as c:
            rows = c.execute("SELECT * FROM cash_balances WHERE as_of<=? ORDER BY as_of, created, id", (str(date.today()),)).fetchall()
        latest = {}
        for r in rows:
            latest[r["currency"]] = dict(currency=r["currency"], amount=r["amount"], as_of=r["as_of"], source=r["source"], label=r["label"])
        return latest

    def _convert(self, minor, source, target):
        if source == target:
            return minor, None
        try:
            ref = self.rates.latest(source, target)
        except Denied:
            return None, None
        return to_minor(from_minor(minor, source) * Decimal(ref["rate"]), target), ref

    def cash_position(self, display=None):
        display = (display or self._currency_default()).upper()
        balances = self.cash_balances()
        items, total, missing = [], 0, []
        for cur, b in sorted(balances.items(), key=lambda kv: kv[0] != display):
            eq, ref = self._convert(b["amount"], cur, display)
            if eq is None:
                missing.append(cur)
            else:
                total += eq
            items.append(dict(b, equivalent=eq, rate=ref["rate"] if ref else None, observed=ref["observed"] if ref else None))
        sandbox = [dict(currency=x["currency"], amount=int(x["available"])) for x in self.balances() if x["rail"] == "sandbox" and int(x["available"])]
        return dict(display=display, total=total, currencies=items, unconverted=missing, sandbox=sandbox, has_cash=bool(balances),
                    note="latest balance per currency, entered by you or read from a bank CSV; conversions use daily reference rates")

    # ---------- what needs exchanging ----------
    def _needs_by_currency(self):
        today = date.today()
        horizon = today + timedelta(days=HORIZON)
        needs = {}

        def add(cur, amount, due, label, kind):
            if amount and amount > 0:
                needs.setdefault(cur, []).append(dict(amount=amount, date=due, label=label, kind=kind))
        for t in self.terms():
            due = date.fromisoformat(t["tuition_due"])
            if t["tuition"] and today <= due <= horizon:
                add(t["currency"], t["tuition"], str(due), t["name"], "tuition")
            start, end = max(today, date.fromisoformat(t["start"])), min(horizon, date.fromisoformat(t["end"]))
            if t["living"] and start <= end:
                add(t["currency"], t["living"] * ((end - start).days + 1) // 30, str(end), t["name"], "living")
        for o in self.obligations():
            if o["state"] in ("due_soon", "overdue", "upcoming") and o.get("due_date") and o["due_date"] <= str(horizon):
                add(o["currency"], o.get("amount") or 0, o["due_date"], o["title"], "bill")  # stored in minor units
        return needs  # exchange plans add their own purpose-only needs in the sandbox (plans.py)

    def _funding_currency(self, target, cash):
        """Pay from the currency you hold the most of (by reference value), other than the one you need."""
        home = self._currency_default()
        best, best_value = None, -1
        for cur, b in cash.items():
            if cur == target or b["amount"] <= 0:
                continue
            value, _ = self._convert(b["amount"], cur, home)
            if value is not None and value > best_value:
                best, best_value = cur, value
        return best

    def exchange_needs(self):
        cash = self.cash_balances()
        out = []
        for cur, items in self._needs_by_currency().items():
            need = sum(i["amount"] for i in items)
            have = max(0, cash.get(cur, {}).get("amount", 0))
            shortfall = need - have
            if shortfall <= 0:
                continue
            funding = self._funding_currency(cur, cash)
            out.append(self._need_view("shortfall", cur, need, have, shortfall, items, funding))
        for g in self.goals():
            if g["status"] == "active" and g["remaining"] > 0:
                out.append(self._need_view("goal", g["target"], g["target_amount"], g["completed"], g["remaining"],
                                           [dict(amount=g["remaining"], date=g["deadline"], label=g["title"], kind="goal")], g["source"]))
        return sorted(out, key=lambda n: n["due"] or "9999")

    def _need_view(self, kind, target, need, have, shortfall, items, funding):
        view = dict(kind=kind, target=target, need=need, have=have, shortfall=shortfall,
                    due=min((i["date"] for i in items if i["date"]), default=None), items=items, funding=funding,
                    rate=None, cost=None, verdict=None, judged_by=None)
        if funding:
            try:
                ref = self.rates.latest(funding, target)
                view.update(rate=ref["rate"], observed=ref["observed"],
                            cost=to_minor(from_minor(shortfall, target) / Decimal(ref["rate"]), funding))
            except Denied:
                return view
            try:  # the verdict is a bonus; the overview never fails without it
                w = self.watch(funding, target)
                adv = (w["last"] if w and w.get("last") else None) or self.exchange_advice(funding, target, use_model=False)
                view.update(verdict=adv["verdict"], judged_by=adv["judged_by"])
            except (Denied, KeyError, ValueError, ArithmeticError):
                pass
        return view

    def money_overview(self, display=None):
        pos = self.cash_position(display)
        gaps = self.currency_gaps(pos["display"])
        return dict(position=pos, needs=self.exchange_needs(), plans=self.exchange_plans(), suggestions=self.plan_suggestions(),
                    simulation=self.simulate(pos["display"]), gaps=gaps["gaps"], stress_pct=gaps["stress_pct"], horizon=gaps["horizon"],
                    ledger=self.virtual_ledger(), as_of=now(),
                    note="estimates on daily reference rates; fees are extra and nothing is exchanged automatically")

