"""Exchange plans, the what-if sandbox and currency gaps.

A plan says "I intend to exchange this much, from this currency into that one, by this date, for this purpose". It is the
student's own intent; nothing is exchanged. Plans feed three things:

- the sandbox: every planned exchange is applied, in numbers only, to the balances you hold (optionally with extra
  pretend money and a worse rate) so you see what each currency would have left;
- gaps: per currency, what you hold, plus what your plans bring in, minus what they take out, against the money you need
  in the next HORIZON days (tuition, a term's living costs, bills, purpose-only plans) and your safety buffer;
- the AI exchange watch: a pair's plans tell the watch how much is needed, by when, and the lowest acceptable rate.

Every figure is a reference estimate on daily rates, not a quote.
"""
import json
import math
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from .domain import Denied, canonical, now, decimals, from_minor, to_minor, floor_minor
from .money import HORIZON

SCHEMA = """
CREATE TABLE IF NOT EXISTS exchange_plans (id TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL, amount INTEGER NOT NULL,
    amount_currency TEXT NOT NULL, due TEXT, purpose TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'custom', need_ref TEXT,
    min_rate TEXT, status TEXT NOT NULL DEFAULT 'planned', origin TEXT NOT NULL, created INTEGER NOT NULL, updated INTEGER NOT NULL,
    done_at INTEGER);
CREATE INDEX IF NOT EXISTS exchange_plans_status ON exchange_plans(status, due);
"""
KINDS = ("tuition", "living", "bill", "goal", "custom")
CATEGORIES = ("family", "tuition", "rent", "living", "business", "other")
STATUSES = ("planned", "done", "cancelled")
STRESS_PCT = -3  # "what if the rate were 3% worse"
ISO = re.compile(r"[A-Z]{3}")


def _amount(text, currency):
    try:
        value = Decimal(str(text).replace(",", "").strip())
        if not value.is_finite() or value <= 0 or value > Decimal("1000000000000"):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise Denied("amount must be a positive number", "plan_invalid", field="amount") from None
    minor = to_minor(value, currency)
    if minor <= 0:
        raise Denied("amount must be a positive number", "plan_invalid", field="amount")
    return minor


class PlansMixin:
    def _plans_schema(self):
        with self.store.tx() as c:
            c.executescript(SCHEMA)
            cols = {r[1] for r in c.execute("PRAGMA table_info(exchange_plans)")}
            for col in ("recipient_id", "category"):
                if col not in cols:
                    c.execute(f"ALTER TABLE exchange_plans ADD COLUMN {col} TEXT")
        self._goals_to_plans()

    def _goals_to_plans(self):
        """Goals were "send this much by then" — exactly an exchange plan. Active ones become plans with the same id, so the
        payments already linked to them keep counting as progress; the goal itself is archived."""
        with self.store.tx() as c:
            for r in c.execute("SELECT * FROM goals WHERE status='active'").fetchall():
                g = json.loads(r["body"])
                if not c.execute("SELECT 1 FROM exchange_plans WHERE id=?", (r["id"],)).fetchone():
                    c.execute("INSERT INTO exchange_plans(id,source,target,amount,amount_currency,due,purpose,kind,need_ref,min_rate,status,origin,"
                              "created,updated,recipient_id,category) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (r["id"], g["source"], g["target"], g["target_amount"], g["target"], g["deadline"], g["title"][:120], "goal",
                               None, None, "planned", "user", r["created"], now(), g.get("recipient_id"), g.get("category") or "family"))
                c.execute("UPDATE goals SET status='archived' WHERE id=?", (r["id"],))
                self.store.event(c, "system", "goal.to_plan", "ok", r["id"])

    # ---------- plans ----------
    def _plan_row(self, plan_id):
        with self.store.read() as c:
            r = c.execute("SELECT * FROM exchange_plans WHERE id=?", (plan_id,)).fetchone()
        if not r:
            raise Denied("exchange plan not found", "plan_unknown")
        return dict(r)

    def save_plan(self, actor, source, target, amount, side="receive", due=None, purpose="", kind="custom", need_ref=None,
                  min_rate=None, plan_id=None, recipient_id=None, category=None):
        """Create or change a plan. The assistant may draft plans; only a person marks them done or deletes them."""
        self.require(actor, "prepare")
        source, target = (source or "").upper(), (target or "").upper()
        if not ISO.fullmatch(source) or not ISO.fullmatch(target) or source == target:
            raise Denied("distinct ISO currency pair required", "pair_invalid")
        if side not in ("receive", "spend"):
            raise Denied("amount side must be receive or spend", "plan_invalid", field="side")
        currency = target if side == "receive" else source
        minor = _amount(amount, currency)
        if due:
            try:
                due = str(date.fromisoformat(str(due)))
            except ValueError:
                raise Denied("date must be YYYY-MM-DD", "date_invalid") from None
        else:
            due = None
        if min_rate not in (None, ""):
            try:
                rate = Decimal(str(min_rate).replace(",", "."))
                if not rate.is_finite() or rate <= 0:
                    raise InvalidOperation
                min_rate = str(rate)
            except InvalidOperation:
                raise Denied("acceptable rate must be a positive number", "plan_invalid", field="min_rate") from None
        else:
            min_rate = None
        kind = kind if kind in KINDS else "custom"
        purpose = str(purpose or "").strip()[:120]
        category = category if category in CATEGORIES else None
        if recipient_id and not any(r["id"] == recipient_id for r in self.recipients()):
            raise Denied("recipient not found", "recipient_unknown")
        recipient_id = recipient_id or None
        with self.store.tx() as c:
            if plan_id:
                if not c.execute("SELECT 1 FROM exchange_plans WHERE id=?", (plan_id,)).fetchone():
                    raise Denied("exchange plan not found", "plan_unknown")
                c.execute("UPDATE exchange_plans SET source=?,target=?,amount=?,amount_currency=?,due=?,purpose=?,kind=?,need_ref=COALESCE(?,need_ref),"
                          "min_rate=?,updated=?,recipient_id=?,category=? WHERE id=?",
                          (source, target, minor, currency, due, purpose, kind, need_ref, min_rate, now(), recipient_id, category, plan_id))
            else:
                plan_id = str(uuid.uuid4())
                c.execute("INSERT INTO exchange_plans(id,source,target,amount,amount_currency,due,purpose,kind,need_ref,min_rate,status,origin,created,updated,"
                          "recipient_id,category) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (plan_id, source, target, minor, currency, due, purpose, kind, need_ref, min_rate, "planned",
                           "agent" if actor == "agent" else "user", now(), now(), recipient_id, category))
            self.store.event(c, actor, "plan.save", "ok", plan_id, pair=f"{source}-{target}", side=side, kind=kind, due=due)
        self._watch_pair(source, target)
        return self.exchange_plan(plan_id)

    def set_plan_status(self, actor, plan_id, status):
        self.owner(actor)
        if status not in STATUSES:
            raise Denied("unknown plan status", "plan_invalid", field="status")
        p = self._plan_row(plan_id)
        with self.store.tx() as c:
            c.execute("UPDATE exchange_plans SET status=?, done_at=?, updated=? WHERE id=?",
                      (status, now() if status == "done" else None, now(), plan_id))
            self.store.event(c, actor, "plan.status", "ok", plan_id, status=status)
        return self.exchange_plan(p["id"])

    def delete_plan(self, actor, plan_id):
        self.owner(actor)
        self._plan_row(plan_id)
        with self.store.tx() as c:
            c.execute("DELETE FROM exchange_plans WHERE id=?", (plan_id,))
            self.store.event(c, actor, "plan.delete", "ok", plan_id)
        return {"deleted": plan_id}

    def _rate(self, source, target):
        try:
            return self.rates.latest(source, target)
        except Denied:
            return None

    def _legs(self, p, rate):
        """(spend in source minor, receive in target minor) at a rate; None for the side a missing rate cannot price."""
        if p["amount_currency"] == p["target"]:
            receive = p["amount"]
            spend = to_minor(from_minor(receive, p["target"]) / rate, p["source"]) if rate else None
        else:
            spend = p["amount"]
            receive = floor_minor(from_minor(spend, p["source"]) * rate, p["target"]) if rate else None
        return spend, receive

    def _sent(self, plan_id):
        """What linked payments already delivered (completed) and what is on its way (drafts to pending), in target units."""
        with self.store.read() as c:
            rows = [dict(r) for r in c.execute("SELECT status, body FROM transfers WHERE goal_id=?", (plan_id,))]
        done = sum(json.loads(r["body"]).get("receive", 0) for r in rows if r["status"] == "completed")
        going = sum(json.loads(r["body"]).get("receive", 0) for r in rows if r["status"] in ("draft", "approved", "pending", "unknown"))
        return int(done), int(going)

    def _plan_view(self, p, verdicts=None, judge=True):
        ref = self._rate(p["source"], p["target"])
        rate = Decimal(ref["rate"]) if ref else None
        sent, on_way = self._sent(p["id"])
        if sent and p["amount_currency"] == p["target"]:
            p = dict(p, total=p["amount"], amount=max(0, p["amount"] - sent))  # only the rest still needs exchanging
        spend, receive = self._legs(p, rate) if p["amount"] else (0, 0)
        days = (date.fromisoformat(p["due"]) - date.today()).days if p["due"] else None
        verdict = None
        if judge and p["status"] == "planned" and ref:
            key = (p["source"], p["target"])
            if verdicts is not None and key in verdicts:
                verdict = verdicts[key]
            else:
                try:
                    adv = self.exchange_advice(p["source"], p["target"], use_model=False)
                    verdict = dict(verdict=adv["verdict"], judged_by=adv["judged_by"], explanation=adv.get("explanation"))
                except (Denied, KeyError, ValueError, ArithmeticError):
                    verdict = None
                if verdicts is not None:
                    verdicts[key] = verdict
        below = bool(p["min_rate"] and rate is not None and rate < Decimal(p["min_rate"]))
        total = p.get("total", p["amount"])
        return dict(p, total=total, sent=sent, on_way=on_way, progress_pct=round(sent * 100 / total) if total and p["amount_currency"] == p["target"] else 0,
                    side="receive" if p["amount_currency"] == p["target"] else "spend", spend=spend, receive=receive,
                    rate=ref["rate"] if ref else None, observed=ref["observed"] if ref else None, days_left=days,
                    below_min_rate=below, verdict=verdict["verdict"] if verdict else None,
                    judged_by=verdict["judged_by"] if verdict else None, why=verdict.get("explanation") if verdict else None)

    def exchange_plan(self, plan_id):
        return self._plan_view(self._plan_row(plan_id))

    def exchange_plans(self, include_closed=False, judge=True):
        sql = "SELECT * FROM exchange_plans" + ("" if include_closed else " WHERE status='planned'") + " ORDER BY COALESCE(due,'9999'), created"
        with self.store.read() as c:
            rows = [dict(r) for r in c.execute(sql)]
        verdicts = {}
        return [self._plan_view(p, verdicts, judge) for p in rows]

    def pair_plan_needs(self, source, target):
        """What a pair's plans tell the AI watch: total to receive, the earliest date, the strictest acceptable rate."""
        with self.store.read() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM exchange_plans WHERE status='planned' AND source=? AND target=?", (source, target))]
        if not rows:
            return {}
        ref = self._rate(source, target)
        rate = Decimal(ref["rate"]) if ref else None
        amounts = [self._legs(p, rate)[1] for p in rows]
        dues = [p["due"] for p in rows if p["due"] and p["due"] >= str(date.today())]
        floors = [Decimal(p["min_rate"]) for p in rows if p["min_rate"]]
        return dict(amount=sum(a for a in amounts if a) or None, deadline=min(dues) if dues else None,
                    min_rate=str(max(floors)) if floors else None, note=" · ".join(p["purpose"] for p in rows if p["purpose"])[:200], plans=len(rows))

    def _watch_pair(self, source, target):
        """A planned pair is always watched by the AI (a watch the student switched off stays off)."""
        with self.store.tx() as c:
            c.execute("INSERT OR IGNORE INTO rate_watches(id,source,target,body,origin,active,created) VALUES (?,?,?,?,?,?,?)",
                      (str(uuid.uuid4()), source, target, canonical(dict(amount=None, deadline=None, min_rate=None, note="")), "plan", 1, now()))

    # ---------- what is needed, per currency ----------
    def _buffers(self):
        out = {}
        for e in self.budget():
            if e["kind"] == "buffer":
                out[e["currency"]] = out.get(e["currency"], 0) + int(e["amount"])
        return out

    def _plan_needs(self, plans):
        """Money a plan exists for and that nothing else already counts: purpose-only plans are spent once received."""
        needs = {}
        horizon = str(date.today() + timedelta(days=HORIZON))
        for p in plans:
            if p["kind"] in ("custom", "goal") and p["receive"] and (not p["due"] or p["due"] <= horizon):
                needs.setdefault(p["target"], []).append(dict(amount=p["receive"], date=p["due"], label=p["purpose"] or f"{p['source']}→{p['target']}", kind="plan"))
        return needs

    def plan_suggestions(self):
        """Shortfalls the plans do not cover yet, as ready-made plans: one per need, in the order they fall due."""
        cash = self.cash_balances()
        plans = self.exchange_plans(judge=False)
        planned_in, refs = {}, {p["need_ref"] for p in plans if p["need_ref"]}
        for p in plans:
            if p["receive"]:
                planned_in[p["target"]] = planned_in.get(p["target"], 0) + p["receive"]
        buffers = self._buffers()
        out = []
        for cur, items in self._needs_by_currency().items():
            open_items = [i for i in items if f"{i['kind']}:{i['label']}:{i['date']}" not in refs]
            room = max(0, cash.get(cur, {}).get("amount", 0)) + planned_in.get(cur, 0) - buffers.get(cur, 0)
            for i in sorted(items, key=lambda x: x["date"] or "9999"):
                take = min(room, i["amount"])
                room -= take
                short = i["amount"] - take
                ref = f"{i['kind']}:{i['label']}:{i['date']}"
                if short > 0 and i in open_items:
                    funding = self._funding_currency(cur, cash)
                    out.append(dict(target=cur, source=funding, amount=short, due=i["date"], purpose=i["label"], kind=i["kind"], need_ref=ref,
                                    cost=self._cost(funding, cur, short)))
        return sorted(out, key=lambda s: s["due"] or "9999")

    def _cost(self, source, target, receive):
        if not source:
            return None
        ref = self._rate(source, target)
        return to_minor(from_minor(receive, target) / Decimal(ref["rate"]), source) if ref else None

    # ---------- the sandbox: apply the plans in numbers only ----------
    def simulate(self, display=None, extra=None, rate_shift=0, plan_ids=None):
        """What each currency would hold after the planned exchanges. Pretend money and a rate shift are for this call only."""
        display = (display or self._currency_default()).upper()
        try:
            shift = Decimal(str(rate_shift or 0))
            if not shift.is_finite() or not -50 <= shift <= 50:
                raise InvalidOperation
        except InvalidOperation:
            raise Denied("rate shift must be between -50 and 50 percent", "plan_invalid", field="rate_shift") from None
        base = {cur: b["amount"] for cur, b in self.cash_balances().items()}
        pretend = []
        for x in (extra or [])[:12]:
            cur = str(x.get("currency", "")).upper()
            if not ISO.fullmatch(cur):
                raise Denied("currency must be an ISO code", "currency_invalid")
            text = str(x.get("amount", "")).strip()
            minor = -_amount(text[1:], cur) if text.startswith("-") else _amount(text, cur)
            base[cur] = base.get(cur, 0) + minor
            pretend.append(dict(currency=cur, amount=minor))
        plans = [p for p in self.exchange_plans(judge=False) if plan_ids is None or p["id"] in plan_ids]
        moves, flows = [], {}
        for p in plans:
            ref = self._rate(p["source"], p["target"])
            if not ref:
                moves.append(dict(plan=p["id"], source=p["source"], target=p["target"], priced=False, purpose=p["purpose"], due=p["due"]))
                continue
            rate = Decimal(ref["rate"]) * (1 + shift / 100)
            spend, receive = self._legs(p, rate)
            flows[p["source"]] = flows.get(p["source"], 0) - spend
            flows[p["target"]] = flows.get(p["target"], 0) + receive
            moves.append(dict(plan=p["id"], source=p["source"], target=p["target"], spend=spend, receive=receive, rate=str(rate),
                              priced=True, purpose=p["purpose"], due=p["due"]))
        needs = self._needs_by_currency()
        for cur, items in self._plan_needs(plans).items():
            needs.setdefault(cur, []).extend(items)
        buffers = self._buffers()
        rows = []
        for cur in sorted(set(base) | set(flows) | set(needs) | set(buffers)):
            before = base.get(cur, 0)
            inflow = max(0, flows.get(cur, 0)) if flows.get(cur, 0) > 0 else 0
            outflow = -flows.get(cur, 0) if flows.get(cur, 0) < 0 else 0
            after = before + flows.get(cur, 0)
            need = sum(i["amount"] for i in needs.get(cur, []))
            buffer = buffers.get(cur, 0)
            due = min((i["date"] for i in needs.get(cur, []) if i["date"]), default=None)
            rows.append(dict(currency=cur, before=before, inflow=inflow, outflow=outflow, after=after, need=need, buffer=buffer, due=due,
                             items=needs.get(cur, []), gap_now=max(0, need + buffer - before), gap_after=max(0, need + buffer - after),
                             overdrawn=after < 0, known=cur in base or cur in flows, before_display=self._convert(before, cur, display)[0],
                             after_display=self._convert(after, cur, display)[0]))
        total = lambda key: sum(r[key] for r in rows if r[key] is not None)
        return dict(display=display, rate_shift=str(shift), horizon=HORIZON, rows=rows, moves=moves, pretend=pretend,
                    total_before=total("before_display"), total_after=total("after_display"),
                    unconverted=[r["currency"] for r in rows if r["before_display"] is None],
                    note="numbers only: nothing is exchanged or saved; daily reference rates, fees not included")

    def currency_gaps(self, display=None):
        """Gaps per currency, with how they would look if rates were STRESS_PCT worse."""
        base = self.simulate(display)
        stressed = {r["currency"]: r for r in self.simulate(display, rate_shift=STRESS_PCT)["rows"]}
        out = []
        for r in base["rows"]:
            s = stressed.get(r["currency"], r)
            if r["gap_now"] or r["gap_after"] or s["gap_after"] or r["overdrawn"]:
                out.append(dict(currency=r["currency"], have=r["before"], planned_in=r["inflow"], planned_out=r["outflow"], after=r["after"],
                                need=r["need"], buffer=r["buffer"], due=r["due"], items=r["items"], gap_now=r["gap_now"],
                                gap_after=r["gap_after"], gap_stressed=s["gap_after"], overdrawn=r["overdrawn"], known=r["known"]))
        return dict(display=base["display"], horizon=HORIZON, stress_pct=STRESS_PCT, gaps=out, rows=base["rows"])

    # ---------- the test-money ledger: what simulated payments did to the pretend balances ----------
    def virtual_ledger(self, limit=10):
        moves = []
        for t in self.history(limit=60):
            b = t["details"]
            if b.get("rail", "sandbox") != "sandbox" or t["status"] in ("superseded",) or t.get("test"):
                continue
            effect = "deducted" if t["status"] == "completed" else "none" if t["status"] in ("failed", "cancelled", "expired") else "open"
            moves.append(dict(id=t["id"], created=t["created"], status=t["status"], effect=effect, currency=b["source"],
                              amount=-int(b.get("reserve") or (b.get("value", 0) + b.get("fee", 0))), receive=b.get("receive"),
                              target=b["target"], recipient=(b.get("recipient") or {}).get("name"), purpose=b.get("purpose"),
                              by=t.get("created_by") or t.get("actor")))
            if len(moves) >= limit:
                break
        funds = [dict(currency=x["currency"], total=int(x["total"]), reserved=int(x["reserved"]), available=int(x["available"]))
                 for x in self.balances() if x["rail"] == "sandbox"]
        return dict(funds=funds, moves=moves, note="local simulation: pretend money; nothing real is spent or exchanged")

    # ---------- reminders that the plans and gaps raise ----------
    def plan_reminders(self):
        out, today = [], date.today()
        try:
            gaps = self.currency_gaps()["gaps"]
        except Denied:
            gaps = []
        for g in gaps:
            if not g["known"]:
                continue  # no balance recorded for this currency: a "gap" would only mean "unknown"
            if g["overdrawn"]:
                out.append((f"plan_short:{g['currency']}", "plan_short", g["currency"], "alert",
                            dict(currency=g["currency"], amount=str(from_minor(-g["after"], g["currency"])))))
            if g["gap_after"] > 0:
                days = (date.fromisoformat(g["due"]) - today).days if g["due"] else None
                urgent = days is not None and days <= 7
                size = int(math.log2(max(2, g["gap_after"])))  # a gap that doubles is news again
                out.append((f"gap:{g['currency']}:{size}:{'7d' if urgent else 'later'}", "currency_gap", g["currency"], "alert" if urgent else "info",
                            dict(currency=g["currency"], amount=str(from_minor(g["gap_after"], g["currency"])), due_date=g["due"] or str(today + timedelta(days=HORIZON)),
                                 days_left=days if days is not None else "")))
        for p in self.exchange_plans():
            if p["due"]:
                days = p["days_left"]
                stage = "overdue" if days < 0 else "3d" if days <= 3 else "7d" if days <= 7 else None
                if stage:
                    out.append((f"plan:{p['id']}:{stage}", "plan_due", p["id"], "warn" if stage == "7d" else "alert",
                                dict(source=p["source"], target=p["target"], purpose=p["purpose"], due_date=p["due"], days_left=days,
                                     amount=str(from_minor(p["receive"] or 0, p["target"])))))
            if p["below_min_rate"]:
                out.append((f"plan_rate:{p['id']}:{p['observed']}", "plan_below_rate", p["id"], "alert",
                            dict(source=p["source"], target=p["target"], rate=p["rate"], min_rate=p["min_rate"], purpose=p["purpose"])))
        return out


class TimelineMixin:
    """The dated sandbox: what each currency would hold, day by day, as plans, goals, bills, subscriptions, a term's
    costs and a scenario from the Send page happen. Every source can be switched off; nothing is saved or moved."""

    def _rate_or_none(self, source, target):
        try:
            return Decimal(self.rates.latest(source, target)["rate"])
        except Denied:
            return None

    def timeline_sources(self, days=90):
        """Everything that could move money in the next `days`, as dated events with a stable key each."""
        today, end = date.today(), date.today() + timedelta(days=days)
        events = []

        def add(key, group, label, day, cur, amount):
            if amount and today <= day <= end:
                events.append(dict(key=key, group=group, label=label, date=str(day), currency=cur, amount=int(amount)))
        for p in self.exchange_plans(judge=False):
            day = max(today, date.fromisoformat(p["due"])) if p["due"] else today
            if p["spend"] is not None and p["receive"] is not None:
                label = p["purpose"] or f"{p['source']}→{p['target']}"
                add(f"plan:{p['id']}", "plans", label, day, p["source"], -p["spend"])
                add(f"plan:{p['id']}", "plans", label, day, p["target"], p["receive"])
        for g in self.goals():
            if g["status"] == "active" and g["remaining"] > 0:
                rate = self._rate_or_none(g["source"], g["target"])
                if rate:
                    cost = to_minor(from_minor(g["remaining"], g["target"]) / rate, g["source"])
                    add(f"goal:{g['id']}", "goals", g["title"], max(today, date.fromisoformat(g["deadline"])), g["source"], -cost)
        for o in self.obligations():
            if not o.get("paid_at") and o.get("due_date") and o.get("amount"):
                add(f"bill:{o['id']}", "bills", o["title"], max(today, date.fromisoformat(o["due_date"])), o["currency"], -int(o["amount"]))
        for r in self.recurring_list():
            day = date.fromisoformat(r["next_date"])
            while day <= end:
                group = "subscriptions" if r["category"] in ("subscriptions", "phone") else "recurring"
                add(f"rec:{r['id']}", group, r["description"], day, r["currency"], -int(r["amount"]))
                day = self._advance(day, r["cadence"])
        for t in self.terms():
            cur = t["currency"]
            if t["tuition"] and t.get("tuition_due"):
                add(f"tuition:{t['id']}", "term", t["name"], date.fromisoformat(t["tuition_due"]), cur, -t["tuition"])
            start, stop = max(today, date.fromisoformat(t["start"])), min(end, date.fromisoformat(t["end"]))
            month = date(start.year, start.month, 1)
            while month <= stop:
                day = max(month, start)
                add(f"living:{t['id']}", "term", t["name"], day, cur, -t["living"]) if t["living"] else None
                add(f"income:{t['id']}", "term", t["name"], day, cur, t["income"]) if t["income"] else None
                month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        return events

    def timeline(self, display=None, off=None, scenario=None, days=90, extra=None):
        display = (display or self._currency_default()).upper()
        days = max(7, min(int(days or 90), 366))
        off = set(off or [])
        base = {cur: b["amount"] for cur, b in self.cash_balances().items()}
        events = [e for e in self.timeline_sources(days) if e["key"] not in off]
        today = date.today()
        for i, leg in enumerate((scenario or {}).get("legs") or []):
            try:
                day = max(today, date.fromisoformat(str(leg["date"])))
                spend, receive = int(leg["spend"]), int(leg["receive"])
            except (KeyError, ValueError, TypeError):
                raise Denied("invalid scenario", "plan_invalid") from None
            label = str((scenario or {}).get("label") or "")[:80]
            events.append(dict(key="scenario", group="scenario", label=label, date=str(day), currency=scenario["source"].upper(), amount=-spend))
            events.append(dict(key="scenario", group="scenario", label=label, date=str(day), currency=scenario["target"].upper(), amount=receive))
        for x in (extra or [])[:12]:  # pretend money, today
            cur = str(x.get("currency", "")).upper()
            if not ISO.fullmatch(cur):
                raise Denied("currency must be an ISO code", "currency_invalid")
            text = str(x.get("amount", "")).strip()
            minor = -_amount(text[1:], cur) if text.startswith("-") else _amount(text, cur)
            events.append(dict(key="pretend", group="pretend", label="", date=str(today), currency=cur, amount=minor))
        events.sort(key=lambda e: (e["date"], e["amount"] > 0))  # money leaves before it arrives on the same day: the cautious order
        balance, low = dict(base), {}
        for e in events:
            balance[e["currency"]] = balance.get(e["currency"], 0) + e["amount"]
            e["balance"] = balance[e["currency"]]
            if e["currency"] not in low or e["balance"] < low[e["currency"]]["amount"]:
                low[e["currency"]] = dict(amount=e["balance"], date=e["date"])
        equiv = lambda bal: sum(v for v in (self._convert(a, c, display)[0] for c, a in bal.items()) if v is not None)  # noqa: E731
        return dict(display=display, today=str(today), end=str(today + timedelta(days=days)), start=base, end_balances=balance,
                    total_start=equiv(base), total_end=equiv(balance), events=events,
                    lowest={c: v for c, v in low.items()}, negative=sorted(c for c, v in low.items() if v["amount"] < 0),
                    sources=self._timeline_groups(days, off),
                    note="numbers only, on daily reference rates; nothing is exchanged, paid or saved")

    def _timeline_groups(self, days, off):
        groups = {}
        for e in self.timeline_sources(days):
            g = groups.setdefault(e["key"], dict(key=e["key"], group=e["group"], label=e["label"], first=e["date"], count=0, on=e["key"] not in off,
                                                 amounts={}))
            g["count"] += 1
            g["amounts"][e["currency"]] = g["amounts"].get(e["currency"], 0) + e["amount"]
        return sorted(groups.values(), key=lambda g: (g["group"], g["first"]))
