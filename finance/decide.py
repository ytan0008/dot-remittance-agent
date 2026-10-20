"""Deciding when to exchange — in money, not in percentages — and acting on rules you set in advance.

wait_value()   "Is waiting worth it?" for YOUR amount: with the experimental 7-day forecast and its 80% interval, how
               much more or less you would get in your own currency if you wait, and the chance waiting turns out better.
               It says plainly when the forecast does not beat the unchanged-rate baseline.
fx rules       Conditional exchange: "when 1 CNY buys at least 0.2150 AUD, exchange up to 60,000 CNY, before 10 Nov".
               mode "confirm": the app tells you and prepares it, you confirm with one tap. mode "auto": it converts
               on its own — in this simulation that moves your own recorded balances; a real bank would need an
               authorised connection. Never more than the rule's cap, never twice, never after its date; a rule that
               has not triggered by its date only warns you, it does not exchange at a bad rate.
savings()      What an exchange gained against the 30-day average rate — the "I saved this much" card for your parents.
month budget   One monthly spending budget; reminders as you near and pass it, and a nudge after a week without entries.
bank rates     Every bank rate read is kept by day, so "near a recent low" can be judged on the rate your bank gives.
"""
import json
import math
import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from .domain import Denied, canonical, now, decimals, from_minor, to_minor, floor_minor, units

SCHEMA = """
CREATE TABLE IF NOT EXISTS fx_rules (id TEXT PRIMARY KEY, body TEXT NOT NULL, status TEXT NOT NULL, created INTEGER NOT NULL,
    updated INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS bank_rates (bank TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, day TEXT NOT NULL,
    rate TEXT NOT NULL, PRIMARY KEY (bank, source, target, day));
"""
MODES = ("confirm", "auto")
RULE_EVENTS = ("fx_rule_ready", "fx_rule_done", "fx_rule_blocked")
Z80 = 1.2815515655  # 80% interval half-width in standard deviations


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _dec(v, what="amount"):
    try:
        d = Decimal(str(v).replace(",", "").strip())
        if not d.is_finite() or d <= 0:
            raise InvalidOperation
        if d > Decimal(10) ** 12:
            raise Denied("that amount is too large", "amount_too_large")
        return d
    except (InvalidOperation, ValueError):
        raise Denied(f"enter a positive {what}", "amount_invalid") from None


class DecideMixin:
    def _decide_schema(self):
        with self.store.tx() as c:
            c.executescript(SCHEMA)

    # ---------- bank rate history ----------
    def bank_rate_history(self, bank, source, target, days=90):
        with self.store.read() as c:
            return [dict(day=r["day"], rate=r["rate"]) for r in c.execute(
                "SELECT day, rate FROM bank_rates WHERE bank=? AND source=? AND target=? AND day>=? ORDER BY day",
                (bank, source.upper(), target.upper(), str(date.today() - timedelta(days=days))))]

    def _bank_now(self, bank, source, target):
        if not bank:
            return None
        b = next((x for x in self.banks(source, target) if x["id"] == bank), None)
        p = (b or {}).get("pricing") or {}
        return Decimal(p["rate"]) if p.get("status") == "ok" and p.get("rate") else None

    # ---------- is waiting worth it? ----------
    def wait_value(self, source, target, amount, side="spend", bank=None, due=None):
        source, target = source.upper(), target.upper()
        value = _dec(amount)
        if side not in ("spend", "receive"):
            raise Denied("side must be spend or receive", "amount_mode")
        ref_now = Decimal(self.rates.latest(source, target)["rate"])
        fc = self.rates.forecast(source, target)
        bank_now = self._bank_now(bank, source, target)
        now_rate = bank_now or ref_now
        out = dict(source=source, target=target, amount=str(value), side=side, bank=bank if bank_now else None,
                   rate_now=str(now_rate), rate_basis="bank" if bank_now else "reference", available=bool(fc.get("available")))
        # where today sits: against your bank's own history once it has enough days, else the reference series
        hist = self.bank_rate_history(bank, source, target) if bank_now else []
        series = [Decimal(h["rate"]) for h in hist] if len(hist) >= 10 else [Decimal(str(r["rate"])) for r in fc.get("recent") or []]
        if series:
            out["position_pct"] = round(100 * sum(1 for r in series if r < now_rate) / len(series))  # higher = better than more days
            out["position_basis"] = "bank" if len(hist) >= 10 else "reference"
            out["position_days"] = len(series)
        if not fc.get("available"):
            out["reason"] = fc.get("reason") or "no forecast for this pair"
            return out
        scale = now_rate / ref_now  # the bank's margin is assumed to stay the same over a week
        point = Decimal(str(fc["point"])) * scale
        lo, hi = (Decimal(str(x)) * scale for x in fc["interval_80"])
        sd = float(hi - lo) / (2 * Z80) or 1e-9
        p_better = 1 - _phi((float(now_rate) - float(point)) / sd)

        def gain(r):
            """In the currency you hold (source): more AUD for the same CNY, or fewer CNY for the same AUD — as CNY."""
            if side == "spend":
                return value * (r / now_rate - 1)
            return value / now_rate - value / r

        unit = source
        day = date.fromisoformat(fc["data_cutoff"]) + timedelta(days=int(fc.get("horizon_days") or 7))
        out.update(horizon=str(day), p_better=round(p_better * 100), expected=str(gain(point).quantize(Decimal("0.01"))),
                   best=str(gain(hi).quantize(Decimal("0.01"))), worst=str(gain(lo).quantize(Decimal("0.01"))), unit=unit,
                   beats_baseline=bool(fc.get("beats_baseline")), point=str(point.quantize(Decimal("0.000001"))),
                   interval=[str(lo.quantize(Decimal("0.000001"))), str(hi.quantize(Decimal("0.000001")))])
        if due:
            try:
                due_day = date.fromisoformat(str(due)[:10])
            except ValueError:
                raise Denied("the date must be YYYY-MM-DD", "date_invalid") from None
            from .banks import latest_start
            out["latest_start"] = str(latest_start(due_day, 3))
            out["can_wait"] = day <= date.fromisoformat(out["latest_start"])  # the forecast date still leaves time for a wire
        return out

    # ---------- what an exchange gained ----------
    def savings(self, source, target, rate, amount_src):
        """Against the average of the last 30 observed reference rates, in the currency you exchanged from."""
        try:
            fc = self.rates.forecast(source, target)
            recent = [Decimal(str(r["rate"])) for r in (fc.get("recent") or [])][-30:]
        except Denied:
            recent = []
        if not recent:
            return None
        avg = sum(recent) / len(recent)
        rate, amount = Decimal(str(rate)), Decimal(str(amount_src))
        extra_target = amount * (rate - avg)
        return dict(average=str(avg.quantize(Decimal("0.000001"))), days=len(recent), rate=str(rate),
                    saved=str((extra_target / rate).quantize(Decimal("0.01"))), currency=source.upper(),
                    extra_target=str(extra_target.quantize(Decimal("0.01"))), target=target.upper())

    # ---------- conditional exchange rules ----------
    def fx_rules(self):
        with self.store.read() as c:
            return [dict(json.loads(r["body"]), id=r["id"], status=r["status"], created=r["created"], updated=r["updated"])
                    for r in c.execute("SELECT * FROM fx_rules ORDER BY created DESC LIMIT 50")]

    def add_fx_rule(self, actor, source, target, amount, min_rate, due=None, mode="confirm", bank=None):
        self.owner(actor)  # a rule spends your money later: only you set one
        source, target = source.upper(), target.upper()
        if source == target:
            raise Denied("pick two different currencies", "pair_invalid")
        if mode not in MODES:
            raise Denied("mode must be confirm or auto", "fx_rule_invalid")
        cap = units(str(_dec(amount)), decimals(source))
        floor = _dec(min_rate, "rate")
        self.rates.latest(source, target)  # the pair must have reference data
        if due:
            try:
                if date.fromisoformat(str(due)[:10]) < date.today():
                    raise Denied("the date is in the past", "date_invalid")
            except ValueError:
                raise Denied("the date must be YYYY-MM-DD", "date_invalid") from None
        rid = str(uuid.uuid4())
        body = dict(source=source, target=target, amount=cap, min_rate=str(floor), due=str(due)[:10] if due else None, mode=mode,
                    bank=bank or None)
        with self.store.tx() as c:
            c.execute("INSERT INTO fx_rules VALUES (?,?,?,?,?)", (rid, canonical(body), "active", now(), now()))
            self.store.event(c, actor, "fx_rule.add", "ok", rid, pair=f"{source}-{target}", mode=mode)
        return next(r for r in self.fx_rules() if r["id"] == rid)

    def cancel_fx_rule(self, actor, rid):
        self.owner(actor)
        with self.store.tx() as c:
            if not c.execute("UPDATE fx_rules SET status='cancelled', updated=? WHERE id=? AND status IN ('active','triggered')", (now(), rid)).rowcount:
                raise Denied("rule not found or already finished", "fx_rule_unknown")
            self.store.event(c, actor, "fx_rule.cancel", "ok", rid)
        return self.fx_rules()

    def _rule_rate(self, r):
        return self._bank_now(r.get("bank"), r["source"], r["target"]) or Decimal(self.rates.latest(r["source"], r["target"])["rate"])

    def execute_fx_rule(self, actor, rid, _auto=False):
        """Convert within the rule (simulation: your recorded balances change). Everything that decides whether it may run —
        status, date, balance — is read again inside ONE write transaction, and the rule moves to done only if it was
        still waiting: two requests at once cannot both credit, an expired rule cannot run, and an unknown balance is
        never treated as enough."""
        if not _auto:
            self.owner(actor)
        r = next((x for x in self.fx_rules() if x["id"] == rid), None)
        if not r:
            raise Denied("rule not found or already finished", "fx_rule_unknown")
        rate = self._rule_rate(r)  # network reads stay outside the transaction
        per_unit = self.savings(r["source"], r["target"], rate, 1000000)  # against the 30-day average (scaled below)
        who = "agent" if _auto else actor
        if r.get("due") and date.today() > date.fromisoformat(r["due"]):
            with self.store.tx() as c:  # committed first, so the refusal and what you then read agree
                c.execute("UPDATE fx_rules SET status='expired', updated=? WHERE id=? AND status IN ('active','triggered')", (now(), rid))
            raise Denied("this rule's date has passed", "fx_rule_expired")
        with self.store.tx() as c:  # BEGIN IMMEDIATE: one writer at a time
            row = c.execute("SELECT body, status FROM fx_rules WHERE id=?", (rid,)).fetchone()
            if not row or row["status"] not in ("active", "triggered"):
                raise Denied("rule not found or already finished", "fx_rule_unknown")
            body = json.loads(row["body"])
            if body.get("due") and date.today() > date.fromisoformat(body["due"]):
                raise Denied("this rule's date has passed", "fx_rule_expired")  # passed midnight since the check above
            if rate < Decimal(body["min_rate"]):
                raise Denied("the rate is below your rule now", "fx_rule_below")
            src, tgt = body["source"], body["target"]
            have = self._latest_cash(c, src)
            if have is None or have <= 0:
                self._remind(c, f"fxrule:{rid}:blocked", "fx_rule_blocked", rid, "alert", dict(source=src, target=tgt))
                raise Denied(f"record your {src} balance first — DOT does not exchange money it cannot see", "funds_insufficient")
            amount = min(body["amount"], have)
            received = floor_minor(from_minor(amount, src) * rate, tgt)
            if not c.execute("UPDATE fx_rules SET status='done', updated=? WHERE id=? AND status IN ('active','triggered')", (now(), rid)).rowcount:
                raise Denied("rule not found or already finished", "fx_rule_unknown")
            self._record_cash(c, who, src, have - amount, str(date.today()), "exchange", f"rule {rid[:8]}")
            self._record_cash(c, who, tgt, (self._latest_cash(c, tgt) or 0) + received, str(date.today()), "exchange", f"rule {rid[:8]}")
            saved_guess = None
            if per_unit:
                k = from_minor(amount, src) / 1000000
                saved_guess = dict(per_unit, saved=str((Decimal(per_unit["saved"]) * k).quantize(Decimal("0.01"))),
                                   extra_target=str((Decimal(per_unit["extra_target"]) * k).quantize(Decimal("0.01"))))
            body["result"] = dict(rate=str(rate), spent=amount, received=received, at=now(), saved=saved_guess, auto=_auto)
            c.execute("UPDATE fx_rules SET body=? WHERE id=?", (canonical(body), rid))
            self.store.event(c, who, "fx_rule.execute", "ok", rid, auto=_auto, simulated=True)
            self._remind(c, f"fxrule:{rid}:done", "fx_rule_done", rid, "info",
                         dict(source=src, target=tgt, amount=str(from_minor(amount, src)), received=str(from_minor(received, tgt)),
                              rate=str(rate), saved=(saved_guess or {}).get("saved", ""), auto=_auto))
        return next(x for x in self.fx_rules() if x["id"] == rid)

    def check_fx_rules(self):
        """The worker: act on rules whose condition holds; warn about rules running out of time."""
        done = 0
        today = date.today()
        for r in self.fx_rules():
            if r["status"] not in ("active", "triggered"):
                continue
            due = date.fromisoformat(r["due"]) if r.get("due") else None
            if due and today > due:
                with self.store.tx() as c:
                    c.execute("UPDATE fx_rules SET status='expired', updated=? WHERE id=?", (now(), r["id"]))
                continue
            try:
                rate = self._rule_rate(r)
            except Denied:
                continue
            if rate >= Decimal(r["min_rate"]):
                if r["mode"] == "auto":
                    try:
                        self.execute_fx_rule("agent", r["id"], _auto=True)
                        done += 1
                    except Denied:
                        pass
                elif r["status"] == "active":
                    with self.store.tx() as c:
                        c.execute("UPDATE fx_rules SET status='triggered', updated=? WHERE id=?", (now(), r["id"]))
                        self._remind(c, f"fxrule:{r['id']}:ready", "fx_rule_ready", r["id"], "alert",
                                     dict(source=r["source"], target=r["target"], amount=str(from_minor(r["amount"], r["source"])), rate=str(rate)))
        return done

    def rule_reminders(self):
        """Live states for refresh_reminders: a rule close to its date that has not triggered."""
        out, today = [], date.today()
        for r in self.fx_rules():
            if r["status"] == "active" and r.get("due"):
                left = (date.fromisoformat(r["due"]) - today).days
                if 0 <= left <= 3:
                    out.append((f"fxrule:{r['id']}:due", "fx_rule_due", r["id"], "warn",
                                dict(source=r["source"], target=r["target"], due=r["due"], days_left=left, min_rate=r["min_rate"])))
        return out

    # ---------- one monthly budget ----------
    def month_budget(self):
        return self._setting("month_budget", None)

    def set_month_budget(self, actor, currency, amount, others=None):
        """Two budgets for the month in one currency: mine (what I pay) and others (what others pay for me, e.g. my parents'
        card). Either may be empty; both empty removes the budget."""
        self.owner(actor)
        currency = (currency or "").upper()
        old = self.month_budget() or {}
        if old.get("currency") == currency:  # a value left out (None) keeps that budget; "" or 0 clears it
            amount = old.get("amount") and str(from_minor(old["amount"], currency)) if amount is None else amount
            others = old.get("others_amount") and str(from_minor(old["others_amount"], currency)) if others is None else others
        blank = lambda v: v in (None, "", "0", 0)
        if blank(amount) and blank(others):
            with self.store.tx() as c:
                c.execute("DELETE FROM student_settings WHERE key='month_budget'")
            return None
        value = 0 if blank(amount) else units(str(_dec(amount)), decimals(currency))
        theirs = 0 if blank(others) else units(str(_dec(others)), decimals(currency))
        with self.store.tx() as c:
            self._put_setting(c, "month_budget", dict(currency=currency, amount=value, others_amount=theirs))
            self.store.event(c, actor, "budget.month", "ok", currency)
        return self.month_budget()

    def budget_reminders(self):
        out, b = [], self.month_budget()
        month = date.today().strftime("%Y-%m")
        if b:
            d = self.spending_summary(month)["currencies"].get(b["currency"]) or {}
            for who, spent, limit in (("", d.get("mine", 0), b.get("amount", 0)),
                                      ("_others", sum((d.get("others") or {}).values()), b.get("others_amount", 0))):
                if not limit:
                    continue
                pct = spent * 100 // max(1, limit)
                if pct >= 100:
                    out.append((f"budget{who}:{month}:over", f"budget{who}_over", month, "alert", dict(currency=b["currency"],
                                spent=str(from_minor(spent, b["currency"])), budget=str(from_minor(limit, b["currency"])))))
                elif pct >= 85:
                    out.append((f"budget{who}:{month}:near", f"budget{who}_near", month, "warn", dict(currency=b["currency"], pct=int(pct),
                                budget=str(from_minor(limit, b["currency"])))))
        # a week without any entry (when you have used spending before): one gentle nudge per week
        with self.store.read() as c:
            any_ever = c.execute("SELECT 1 FROM expenses LIMIT 1").fetchone()
            recent = c.execute("SELECT 1 FROM expenses WHERE created>=? LIMIT 1", (now() - 7 * 86400,)).fetchone()
        if any_ever and not recent:
            week = date.today().isocalendar()
            out.append((f"lognudge:{week[0]}-{week[1]}", "log_nudge", "spending", "info", {}))
        return out
