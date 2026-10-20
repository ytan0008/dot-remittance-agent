"""Student money: scholarships and grants, a term cash-flow planner, "can I afford this?", spending insights and email reports.

Everything here plans on the student's own figures and confirmed spending. Nothing moves money; every projection is an
estimate and says what it assumed.
"""
import calendar
import html
import json
import re
import uuid
from datetime import date, datetime, timedelta
from . import mailer
from .domain import Denied, canonical, digest, now, units, decimals, from_minor, mask
from .expenses import merchant_key
from .student_i18n import TIPS, EMAIL, REMINDERS, CATEGORIES, lang_of

SCHEMA = """
CREATE TABLE IF NOT EXISTS scholarships (id TEXT PRIMARY KEY, body TEXT NOT NULL, created INTEGER NOT NULL, updated INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS terms (id TEXT PRIMARY KEY, body TEXT NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS student_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS email_log (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, recipient TEXT NOT NULL,
    subject TEXT NOT NULL, status TEXT NOT NULL, error TEXT, created INTEGER NOT NULL);
"""
STAGES = ("researching", "preparing", "submitted", "interview", "awarded", "rejected")
OPEN_STAGES = ("researching", "preparing")
KINDS = ("scholarship", "grant", "bursary", "prize")
DIGESTS = ("off", "daily", "weekly", "monthly")
NOT_SPENDING = ("transfer", "income", "tuition")  # tuition is planned per term, not day-to-day spending
SEVERITY = {"alert": 0, "warn": 1, "info": 2, "good": 3}
WINDOW = 60  # days after a purchase that must stay covered


def _day(value, field="date"):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise Denied(f"{field} must be YYYY-MM-DD", "date_invalid") from None


def _minor(value, currency, allow_zero=True):
    if value in (None, "", 0, "0") and allow_zero:
        return 0
    return units(str(value), decimals(currency))


def _currency(value):
    value = (value or "").upper()
    if not re.fullmatch(r"[A-Z]{3}", value):
        raise Denied("currency must be an ISO code", "currency_invalid")
    return value


def _text(value, limit, field):
    value = str(value or "").strip()
    if not value or len(value) > limit:
        raise Denied(f"{field} must be 1-{limit} characters", "student_invalid", field=field)
    return value


def _add_months(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _share(monthly, d):
    """The part of a monthly amount that falls on day d; a whole month sums exactly to `monthly`."""
    dim = calendar.monthrange(d.year, d.month)[1]
    return monthly * d.day // dim - monthly * (d.day - 1) // dim


def money(minor, currency):
    places = decimals(currency)
    return f"{from_minor(minor, currency):,.{places}f} {currency}"


def reminder_text(templates, r):
    text = templates.get(r["kind"], r["kind"]).format_map(_Safe(r["data"]))
    return text + (" — " + r["data"]["why"] if r["data"].get("why") else "")


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


class StudentMixin:
    def _student_schema(self):
        with self.store.tx() as c:
            c.executescript(SCHEMA)

    # ---------- scholarships and grants ----------
    def _validate_scholarship(self, p, partial=False):
        out = {}
        if not partial or "name" in p:
            out["name"] = _text(p.get("name"), 120, "name")
        for key, limit in (("provider", 120), ("notes", 600)):
            if key in p or not partial:
                out[key] = str(p.get(key) or "").strip()[:limit]
        if "kind" in p or not partial:
            out["kind"] = p.get("kind") or "scholarship"
            if out["kind"] not in KINDS:
                raise Denied("unknown kind", "student_invalid", field="kind")
        if "status" in p or not partial:
            out["status"] = p.get("status") or "researching"
            if out["status"] not in STAGES:
                raise Denied("unknown status", "student_invalid", field="status")
        if "url" in p or not partial:
            url = str(p.get("url") or "").strip()
            if url and not re.fullmatch(r"https?://[^\s<>\"']{3,500}", url):
                raise Denied("link must start with http:// or https://", "student_invalid", field="url")
            out["url"] = url
        if "currency" in p or not partial:
            out["currency"] = _currency(p.get("currency") or self._currency_default())
        if "amount" in p or not partial:
            out["amount"] = _minor(p.get("amount"), out.get("currency") or p.get("currency") or self._currency_default())
        for key in ("deadline", "payout_date"):
            if key in p or not partial:
                out[key] = str(_day(p[key], key)) if p.get(key) else None
        if "documents" in p or not partial:
            docs = p.get("documents") or []
            if not isinstance(docs, list) or len(docs) > 20:
                raise Denied("up to 20 documents", "student_invalid", field="documents")
            out["documents"] = []
            for d in docs:
                d = d if isinstance(d, dict) else {"name": d}
                name = str(d.get("name") or "").strip()[:80]
                if name:
                    out["documents"].append({"name": name, "done": bool(d.get("done"))})
        return out

    def add_scholarship(self, actor, **payload):
        self.require(actor, "prepare")  # tracking is planning only; the agent may add one for the student
        body = self._validate_scholarship(payload)
        sid = str(uuid.uuid4())
        with self.store.tx() as c:
            c.execute("INSERT INTO scholarships VALUES (?,?,?,?)", (sid, canonical(body), now(), now()))
            self.store.event(c, actor, "scholarship.add", "ok", sid, status=body["status"])
        return self.scholarship(sid)

    def update_scholarship(self, actor, sid, **changes):
        self.owner(actor)
        with self.store.tx() as c:
            r = c.execute("SELECT body FROM scholarships WHERE id=?", (sid,)).fetchone()
            if not r:
                raise Denied("scholarship not found", "student_unknown")
            body = json.loads(r["body"])
            if "currency" in changes and "amount" not in changes:
                changes["amount"] = str(from_minor(body["amount"], body["currency"])) if body["amount"] else ""
            if "amount" in changes and "currency" not in changes:
                changes["currency"] = body["currency"]
            body.update(self._validate_scholarship(changes, partial=True))
            c.execute("UPDATE scholarships SET body=?, updated=? WHERE id=?", (canonical(body), now(), sid))
            self.store.event(c, actor, "scholarship.update", "ok", sid, fields=sorted(changes))
        return self.scholarship(sid)

    def delete_scholarship(self, actor, sid):
        self.owner(actor)
        with self.store.tx() as c:
            if not c.execute("DELETE FROM scholarships WHERE id=?", (sid,)).rowcount:
                raise Denied("scholarship not found", "student_unknown")
            self.store.event(c, actor, "scholarship.delete", "ok", sid)
        return {"deleted": sid}

    @staticmethod
    def _scholarship_view(r):
        body = json.loads(r["body"])
        docs = body.get("documents", [])
        days = (date.fromisoformat(body["deadline"]) - date.today()).days if body.get("deadline") else None
        return dict(id=r["id"], created=r["created"], updated=r["updated"], **body, days_left=days,
                    docs_done=sum(d["done"] for d in docs), docs_total=len(docs), open=body["status"] in OPEN_STAGES)

    def scholarship(self, sid):
        with self.store.read() as c:
            r = c.execute("SELECT * FROM scholarships WHERE id=?", (sid,)).fetchone()
        if not r:
            raise Denied("scholarship not found", "student_unknown")
        return self._scholarship_view(r)

    def scholarships(self):
        with self.store.read() as c:
            rows = [self._scholarship_view(r) for r in c.execute("SELECT * FROM scholarships")]
        # Open applications by nearest deadline first, then everything decided.
        return sorted(rows, key=lambda s: (not s["open"], s["deadline"] or "9999", s["name"].lower()))

    # ---------- terms ----------
    def _validate_term(self, p):
        currency = _currency(p.get("currency") or self._currency_default())
        start, end = _day(p.get("start"), "start"), _day(p.get("end"), "end")
        if end < start or (end - start).days > 400:
            raise Denied("a term ends after it starts and lasts at most 400 days", "term_invalid")
        extras = []
        for x in (p.get("extras") or [])[:12]:
            kind = x.get("kind") or "cost"
            if kind not in ("cost", "income"):
                raise Denied("extra items are a cost or an income", "term_invalid")
            extras.append(dict(label=_text(x.get("label"), 80, "label"), amount=_minor(x.get("amount"), currency, allow_zero=False),
                               date=str(_day(x.get("date"))), kind=kind))
        return dict(name=_text(p.get("name"), 80, "name"), currency=currency, start=str(start), end=str(end),
                    tuition=_minor(p.get("tuition"), currency),
                    tuition_due=str(_day(p.get("tuition_due"), "tuition_due")) if p.get("tuition_due") else str(start),
                    living=_minor(p.get("living"), currency), income=_minor(p.get("income"), currency), extras=extras)

    def add_term(self, actor, **payload):
        self.owner(actor)
        body = self._validate_term(payload)
        tid = str(uuid.uuid4())
        with self.store.tx() as c:
            c.execute("INSERT INTO terms VALUES (?,?,?)", (tid, canonical(body), now()))
            self.store.event(c, actor, "term.add", "ok", tid)
        return dict(id=tid, **body)

    def update_term(self, actor, tid, **payload):
        self.owner(actor)
        body = self._validate_term(payload)
        with self.store.tx() as c:
            if not c.execute("UPDATE terms SET body=? WHERE id=?", (canonical(body), tid)).rowcount:
                raise Denied("term not found", "student_unknown")
            self.store.event(c, actor, "term.update", "ok", tid)
        return dict(id=tid, **body)

    def delete_term(self, actor, tid):
        self.owner(actor)
        with self.store.tx() as c:
            if not c.execute("DELETE FROM terms WHERE id=?", (tid,)).rowcount:
                raise Denied("term not found", "student_unknown")
            self.store.event(c, actor, "term.delete", "ok", tid)
        return {"deleted": tid}

    def terms(self):
        with self.store.read() as c:
            rows = [dict(id=r["id"], created=r["created"], **json.loads(r["body"])) for r in c.execute("SELECT * FROM terms")]
        return sorted(rows, key=lambda t: t["start"])

    # ---------- spending baseline ----------
    def _spending(self, currency, start, end, own_only=False):
        """Confirmed day-to-day spending. own_only: only what left YOUR money — not what someone else paid by card."""
        sql = "SELECT * FROM expenses WHERE status='confirmed' AND amount<0 AND currency=? AND date BETWEEN ? AND ?"
        if own_only:
            sql += " AND (account_id IS NULL OR account_id NOT IN (SELECT id FROM accounts WHERE paid_by='other'))"
        with self.store.read() as c:
            rows = c.execute(sql, (currency, str(start), str(end))).fetchall()
        return [dict(r) for r in rows if r["category"] not in NOT_SPENDING]

    def _baseline_monthly(self, currency):
        """Average monthly day-to-day spending out of your own money over the last 90 days (or since the first entry),
        confirmed entries only: what someone else pays by card never lowers your projected cash."""
        today = date.today()
        rows = self._spending(currency, today - timedelta(days=89), today, own_only=True)
        if not rows:
            return 0
        span = max(30, (today - min(date.fromisoformat(r["date"]) for r in rows)).days + 1)
        return -sum(r["amount"] for r in rows) * 30 // min(90, span)

    # ---------- cash flow ----------
    def _plan_currency(self):
        preferred = self._currency_default()
        terms = self.terms()
        if terms and not any(t["currency"] == preferred for t in terms):
            return terms[0]["currency"]
        return preferred

    def cashflow(self, currency=None, months=6):
        currency = _currency(currency or self._plan_currency())
        months = max(1, min(int(months or 6), 24))
        today = date.today()
        all_terms = self.terms()
        terms = [t for t in all_terms if t["currency"] == currency]
        end = max([_add_months(today, months)] + [date.fromisoformat(t["end"]) for t in terms])
        end = min(end, today + timedelta(days=730))
        ledger = next((int(b["available"]) for b in self.balances() if b["currency"] == currency and b["rail"] == "sandbox"), 0)
        budget = self.budget()
        holdings = sum(e["amount"] for e in budget if e["kind"] == "holding" and e["currency"] == currency)
        buffer = sum(e["amount"] for e in budget if e["kind"] == "buffer" and e["currency"] == currency)
        baseline = self._baseline_monthly(currency)
        spans = [(date.fromisoformat(t["start"]), date.fromisoformat(t["end"]), t) for t in terms]
        points = []  # dated one-off flows, shown individually
        for t in terms:
            due = date.fromisoformat(t["tuition_due"])
            if t["tuition"] and today <= due <= end:
                points.append(dict(date=str(due), amount=-t["tuition"], kind="tuition", label=t["name"]))
            for x in t["extras"]:
                d = date.fromisoformat(x["date"])
                if today <= d <= end:
                    points.append(dict(date=x["date"], amount=x["amount"] if x["kind"] == "income" else -x["amount"],
                                       kind="extra_" + x["kind"], label=x["label"]))
        for e in budget:
            if e["kind"] in ("income", "expense") and e["currency"] == currency and e.get("date"):
                d = date.fromisoformat(e["date"])
                if today <= d <= end:
                    points.append(dict(date=e["date"], amount=e["amount"] if e["kind"] == "income" else -e["amount"],
                                       kind="budget_" + e["kind"], label=e["label"]))
        for s in self.scholarships():
            if s["status"] == "awarded" and s["amount"] and s["currency"] == currency and s.get("payout_date"):
                d = date.fromisoformat(s["payout_date"])
                if today <= d <= end:
                    points.append(dict(date=s["payout_date"], amount=s["amount"], kind="scholarship", label=s["name"]))
        by_day = {}
        for p in points:
            by_day[p["date"]] = by_day.get(p["date"], 0) + p["amount"]
        cash = self.cash_balances().get(currency)  # a real balance you entered or imported beats simulated funds
        opening = cash["amount"] if cash else ledger + holdings
        balance, daily, rows, lowest, first_negative = opening, [], {}, None, None
        used_baseline = False
        d = today
        while d <= end:
            covering = [t for s, e, t in spans if s <= d <= e]
            if covering:
                living = sum(_share(t["living"], d) for t in covering)
                income = sum(_share(t["income"], d) for t in covering)
            else:
                living, income = _share(baseline, d), 0
                used_baseline = used_baseline or baseline > 0
            point = by_day.get(str(d), 0)
            balance += income - living + point
            key = d.strftime("%Y-%m")
            row = rows.setdefault(key, dict(month=key, income=0, living=0, tuition=0, other_in=0, other_out=0, closing=0, low=None))
            row["income"] += income
            row["living"] += living
            for p in points:
                if p["date"] == str(d):
                    if p["kind"] == "tuition":
                        row["tuition"] += -p["amount"]
                    elif p["amount"] > 0:
                        row["other_in"] += p["amount"]
                    else:
                        row["other_out"] += -p["amount"]
            row["closing"] = balance
            row["low"] = balance if row["low"] is None else min(row["low"], balance)
            daily.append((str(d), balance))
            if lowest is None or balance < lowest[1]:
                lowest = (str(d), balance)
            if balance < 0 and first_negative is None:
                first_negative = str(d)
            d += timedelta(days=1)
        notes = (["cash_balance"] if cash else ["ledger_simulated"] + (["holdings_unverified"] if holdings else [])) + (["baseline_used"] if used_baseline else [])
        if not terms:
            notes.append("no_terms")
        return dict(currency=currency, start=str(today), end=str(end), opening=dict(ledger=ledger, holdings=holdings, cash=cash["amount"] if cash else None, cash_as_of=cash["as_of"] if cash else None, total=opening),
                    buffer=buffer, baseline_monthly=baseline, months=list(rows.values()), daily=daily,
                    events=sorted(points, key=lambda p: p["date"]), lowest=dict(date=lowest[0], amount=lowest[1]),
                    first_negative=first_negative, below_buffer=lowest[1] < buffer, terms=[t["name"] for t in terms],
                    other_currency_terms=[t["name"] for t in all_terms if t["currency"] != currency], notes=notes,
                    assumption="living costs and income are spread evenly over each month; tuition and extras land on their dates")

    def _month_budget(self, currency, d):
        """Planned day-to-day spending for d's month from the terms; 0 when no term covers it."""
        first = d.replace(day=1)
        last = first.replace(day=calendar.monthrange(d.year, d.month)[1])
        terms = [t for t in self.terms() if t["currency"] == currency]
        total, day_ = 0, first
        while day_ <= last:
            total += sum(_share(t["living"], day_) for t in terms if t["start"] <= str(day_) <= t["end"])
            day_ += timedelta(days=1)
        return total

    # ---------- can I afford this? ----------
    def afford(self, actor, amount, currency=None, day=None, label="", payer="me"):
        """payer "me": your cash, plan, buffer and this month's budget. payer "other" (e.g. a parent's card): not your money,
        so only this month's budget decides — it still counts as your spending."""
        self.require(actor, "view")
        if payer not in ("me", "other"):
            raise Denied("payer must be me or other", "student_invalid", field="payer")
        currency = _currency(currency or self._plan_currency())
        price = units(str(amount), decimals(currency))
        today = date.today()
        when = _day(day) if day else today
        if not today - timedelta(days=1) <= when <= today + timedelta(days=365):  # one day of slack for time zones
            raise Denied("choose a date from today up to a year ahead", "date_invalid")
        months = max(3, (when + timedelta(days=WINDOW) - today).days // 30 + 2)
        plan = self.cashflow(currency, months)
        series = [(date.fromisoformat(d), b) for d, b in plan["daily"]]
        horizon = when + timedelta(days=WINDOW)
        window = [(d, b) for d, b in series if when <= d <= horizon] or series[-1:]
        low_date, low_before = min(window, key=lambda x: x[1])
        low_after = low_before - price
        first_negative = next((str(d) for d, b in window if b - price < 0), None)
        buffer = plan["buffer"]
        month_budget = self._month_budget(currency, when)
        set_budget = self.month_budget()  # a monthly budget you set on the Spending page wins over the term's living costs
        if set_budget and set_budget["currency"] == currency:
            month_budget = set_budget["amount"]
        month_spent = 0
        if when.strftime("%Y-%m") == today.strftime("%Y-%m"):
            month_spent = -sum(r["amount"] for r in self._spending(currency, today.replace(day=1), today))
        remaining = month_budget - month_spent if month_budget else None
        if payer == "other":
            return self._afford_other(price, currency, when, label, month_budget, month_spent, remaining)
        if low_after < 0:
            verdict = "no"
        elif low_after < buffer or (remaining is not None and price > remaining):
            verdict = "careful"
        else:
            verdict = "yes"
        reasons = [dict(code="cash", amount=plan["opening"]["total"]),
                   dict(code="lowest", amount=low_after, date=str(low_date))]
        if first_negative:
            reasons.append(dict(code="negative", date=first_negative))
        elif buffer and low_after < buffer:
            reasons.append(dict(code="buffer", amount=buffer))
        if remaining is not None:
            reasons.append(dict(code="month_over" if price > remaining else "month_ok", remaining=max(0, remaining), budget=month_budget))
        big = sorted((e for e in plan["events"] if e["amount"] < 0 and str(when) <= e["date"] <= str(horizon)), key=lambda e: e["amount"])
        if big:
            reasons.append(dict(code="upcoming", label=big[0]["label"], kind=big[0]["kind"], amount=-big[0]["amount"], date=big[0]["date"]))
        if plan["opening"]["holdings"] == 0 and plan["opening"]["ledger"] == 0:
            reasons.append(dict(code="no_cash"))
        wait_until = None
        if verdict != "yes":
            floor = max(buffer, 0)
            for i, (d, _) in enumerate(series):
                if d <= when:
                    continue
                ahead = [b for d2, b in series[i:] if d2 <= d + timedelta(days=WINDOW)]
                if len(ahead) >= min(WINDOW, len(series) - i) and min(ahead) - price >= floor:
                    same_month = d.strftime("%Y-%m") == when.strftime("%Y-%m")
                    budget_then = remaining if same_month else self._month_budget(currency, d)
                    if budget_then is None or not (budget_then or same_month) or price <= budget_then:
                        wait_until = str(d)
                        break
        step = max(1, len(window) // 30)
        return dict(verdict=verdict, amount=price, currency=currency, date=str(when), label=str(label or "")[:80],
                    cash=plan["opening"]["total"], opening=plan["opening"], lowest_before=low_before, lowest_after=low_after,
                    lowest_date=str(low_date), buffer=buffer, month_budget=month_budget or None, month_spent=month_spent,
                    month_remaining=remaining, reasons=reasons, wait_until=wait_until,
                    shortfall=max(0, max(buffer, 0) - low_after) if verdict != "yes" else 0,
                    series=[(str(d), b, b - price) for d, b in window[::step]], notes=plan["notes"],
                    note="an estimate from your plan and confirmed spending, not advice; it never moves money")

    def _afford_other(self, price, currency, when, label, month_budget, month_spent, remaining):
        """Someone else pays (e.g. your parents' card): your own cash is untouched; the only question is your monthly budget."""
        reasons = [dict(code="other_pays")]
        wait_until = None
        if remaining is None:
            verdict = "yes"
            reasons.append(dict(code="other_no_budget"))
        elif price <= remaining:
            verdict = "yes"
            reasons.append(dict(code="month_ok", remaining=max(0, remaining), budget=month_budget))
        else:
            verdict = "careful"
            reasons.append(dict(code="month_over", remaining=max(0, remaining), budget=month_budget))
            nxt = (when.replace(day=1) + timedelta(days=32)).replace(day=1)
            if month_budget and price <= month_budget:  # a fresh month's budget would hold it
                wait_until = str(nxt)
        return dict(verdict=verdict, payer="other", amount=price, currency=currency, date=str(when), label=str(label or "")[:80],
                    cash=None, opening=None, lowest_before=None, lowest_after=None, lowest_date=None, buffer=None,
                    month_budget=month_budget or None, month_spent=month_spent, month_remaining=remaining, reasons=reasons,
                    wait_until=wait_until, shortfall=0, series=[], notes=["other_pays"],
                    note="paid by someone else: counted in your spending and budget, never taken from your cash")

    # ---------- insights ----------
    def spending_insights(self, period="month", language="en", currency=None):
        if period not in ("week", "month"):
            raise Denied("period must be week or month", "student_invalid", field="period")
        L = lang_of(language)
        T, cats = TIPS[L], CATEGORIES[L]
        today = date.today()
        if period == "week":
            # The calendar week: Monday until today, live every day, starting fresh each Monday. It is compared with the
            # same days of earlier weeks, so Wednesday is never measured against a whole week.
            start = today - timedelta(days=today.weekday())
            days = (today - start).days + 1
            windows = [(start - timedelta(days=7 * k), start - timedelta(days=7 * k - days + 1)) for k in (1, 2, 3)]
        else:
            days = 30
            start = today - timedelta(days=days - 1)
            windows = [(start - timedelta(days=30 * k), start - timedelta(days=30 * k - days + 1)) for k in (1, 2, 3)]
        (prev_start, prev_end), base_start = windows[0], windows[-1][0]
        with self.store.read() as c:
            spent = [dict(r) for r in c.execute("SELECT * FROM expenses WHERE status='confirmed' AND amount<0 AND date BETWEEN ? AND ?",
                                                (str(base_start), str(today))) if r["category"] not in NOT_SPENDING]
            pending = c.execute("SELECT COUNT(*) FROM expenses WHERE status='pending'").fetchone()[0]
        recent = [e for e in spent if e["date"] >= str(start)]
        currencies = sorted({e["currency"] for e in recent})
        preferred = self._currency_default()
        if currency:
            currency = _currency(currency)
        elif preferred in currencies or not currencies:
            currency = preferred
        else:
            currency = max(currencies, key=lambda cur: -sum(e["amount"] for e in recent if e["currency"] == cur))
        mine = [e for e in spent if e["currency"] == currency]

        def total(rows, a, b, cat=None):
            return -sum(e["amount"] for e in rows if str(a) <= e["date"] <= str(b) and (cat is None or e["category"] == cat))
        now_total = total(mine, start, today)
        prev_total = total(mine, prev_start, prev_end)
        base = lambda cat=None: sum(total(mine, a, b, cat) for a, b in windows) // 3  # noqa: E731
        base_avg = base()
        fmt = lambda m: money(m, currency)  # noqa: E731
        categories = []
        for cat in sorted({e["category"] for e in mine}):
            categories.append(dict(category=cat, amount=total(mine, start, today, cat), previous=total(mine, prev_start, prev_end, cat),
                                   baseline=base(cat)))
        categories = sorted([c for c in categories if c["amount"] or c["previous"]], key=lambda c: -c["amount"])
        merchants = {}
        for e in mine:
            if e["date"] >= str(start):
                key = merchant_key(e["description"]) or e["description"][:40]
                m = merchants.setdefault(key, dict(merchant=e["description"][:40], count=0, amount=0))
                m["count"] += 1
                m["amount"] += -e["amount"]
        top_merchants = sorted(merchants.values(), key=lambda m: (-m["count"], -m["amount"]))[:5]
        tips = []

        def tip(kind, severity, **params):
            template = T[kind]
            tips.append(dict(kind=kind, severity=severity, text=template.format_map(_Safe(params)),
                             params={k: v for k, v in params.items() if isinstance(v, (int, str))}))
        if pending:
            tip("pending", "info", n=pending)
        if not now_total:
            tip("no_data", "info")
        unit = 10 ** decimals(currency)
        plan_terms = [t for t in self.terms() if t["currency"] == currency]
        budget = sum(_share(t["living"], d) for d in (start + timedelta(days=i) for i in range(days))
                     for t in plan_terms if t["start"] <= str(d) <= t["end"])
        if budget and now_total:
            if now_total > budget * 105 // 100:
                month_budget = self._month_budget(currency, today)
                month_spent = total(mine, today.replace(day=1), today)
                left_days = calendar.monthrange(today.year, today.month)[1] - today.day + 1
                tip("budget_over", "warn", spent=fmt(now_total), days=days, over=fmt(now_total - budget), budget=fmt(budget),
                    per_day=fmt(max(0, month_budget - month_spent) // left_days))
            else:
                tip("budget_ok", "good", spent=fmt(now_total), budget=fmt(budget), days=days)
        rising = []
        for c in categories:
            reference = c["baseline"] or c["previous"]
            extra = c["amount"] - reference
            if reference and c["amount"] >= reference * 13 // 10 and extra >= max(now_total // 20, 10 * unit):
                rising.append((extra, c, reference))
        for extra, c, reference in sorted(rising, key=lambda x: -x[0])[:2]:
            advice = T["advice"].get(c["category"], T["advice"]["default"]).format(save=fmt(extra // 2))
            tip("category_up", "warn", category=cats.get(c["category"], c["category"]), pct=round((c["amount"] - reference) * 100 / reference),
                extra=fmt(extra), advice=advice)
        frequent = [m for m in top_merchants if m["count"] >= (4 if period == "week" else 6) and m["amount"] // m["count"] <= 20 * unit]
        if frequent:
            m = frequent[0]
            tip("frequent", "info", count=m["count"], merchant=m["merchant"], amount=fmt(m["amount"]),
                save=fmt(m["amount"] // 2 * 30 // days))
        subs = {}
        for e in mine:
            if e["category"] == "subscriptions" and e["date"] >= str(today - timedelta(days=29)):
                subs[merchant_key(e["description"])] = subs.get(merchant_key(e["description"]), 0) - e["amount"]
        if len(subs) >= 2:
            tip("subscriptions", "info", amount=fmt(sum(subs.values())), n=len(subs))
        if categories and now_total:
            top = categories[0]
            tip("top_category", "info", category=cats.get(top["category"], top["category"]), amount=fmt(top["amount"]),
                pct=round(top["amount"] * 100 / now_total))
        for t in self.terms():
            due = date.fromisoformat(t["tuition_due"])
            if t["tuition"] and 0 <= (due - today).days <= 30:
                tip("tuition_due", "warn", term=t["name"], amount=money(t["tuition"], t["currency"]), date=str(due), days=(due - today).days)
        for s in self.scholarships():
            if s["open"] and s["days_left"] is not None and 0 <= s["days_left"] <= 14:
                tip("scholarship_due", "warn", name=s["name"], date=s["deadline"], days=s["days_left"], missing=s["docs_total"] - s["docs_done"])
        try:
            plan = self.cashflow(currency)
            if plan["terms"] and plan["first_negative"]:
                tip("shortfall", "alert", amount=fmt(-plan["lowest"]["amount"]), month=plan["first_negative"][:7])
        except Denied:
            pass
        tips.sort(key=lambda x: SEVERITY[x["severity"]])
        return dict(period=period, days=days, start=str(start), end=str(today), currency=currency, total=now_total, previous=prev_total,
                    baseline=base_avg, change_pct=round((now_total - prev_total) * 100 / prev_total) if prev_total else None,
                    count=sum(1 for e in mine if e["date"] >= str(start)), daily_avg=now_total // days, budget=budget or None,
                    categories=categories, merchants=top_merchants, pending=pending, tips=tips[:7],
                    other_currencies=[c for c in currencies if c != currency], language=L)

    # ---------- reminders from the student plan ----------
    def student_reminders(self):
        today, out = date.today(), []
        for s in self.scholarships():
            days = s["days_left"]
            if not s["open"] or days is None or days < 0:
                continue
            stage = "1d" if days <= 1 else "3d" if days <= 3 else "7d" if days <= 7 else "14d" if days <= 14 else None
            if stage:
                out.append((f"scholarship:{s['id']}:{stage}", "scholarship_due", s["id"], "alert" if days <= 3 else "warn",
                            dict(name=s["name"], deadline=s["deadline"], days_left=days, missing=s["docs_total"] - s["docs_done"])))
        for t in self.terms():
            due = date.fromisoformat(t["tuition_due"])
            days = (due - today).days
            if t["tuition"] and 0 <= days <= 14:
                out.append((f"tuition:{t['id']}:{'3d' if days <= 3 else '14d'}", "tuition_due", t["id"], "alert" if days <= 3 else "warn",
                            dict(term=t["name"], amount=str(from_minor(t["tuition"], t["currency"])), currency=t["currency"], due_date=str(due))))
        return out

    # ---------- email reports ----------
    def _setting(self, key, default):
        with self.store.read() as c:
            r = c.execute("SELECT value FROM student_settings WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def _put_setting(self, c, key, value):
        c.execute("INSERT INTO student_settings VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
                  (key, canonical(value), now()))

    def email_settings(self):
        s = self._setting("email", {})
        with self.store.read() as c:
            log = [dict(r) for r in c.execute("SELECT id,kind,recipient,subject,status,error,created FROM email_log ORDER BY id DESC LIMIT 10")]
        return dict(configured=mailer.configured(), provider=mailer.provider(), address=s.get("address", ""), digest=s.get("digest", "off"),
                    weekday=int(s.get("weekday", 0)), skip_quiet=bool(s.get("skip_quiet", True)),
                    reminders=bool(s.get("reminders")), language=s.get("language", "en"), last_digest=s.get("last_digest"), log=log)

    def set_email(self, actor, address="", digest="off", reminders=False, language="en", weekday=0, skip_quiet=True):
        self.owner(actor)
        address = (address or "").strip()
        if address and not mailer.valid_address(address):
            raise Denied("enter a valid email address", "email_invalid")
        if digest not in DIGESTS:
            raise Denied("digest must be off, daily, weekly or monthly", "email_invalid")
        if weekday not in range(7):
            raise Denied("weekday must be 0 (Monday) to 6 (Sunday)", "email_invalid")
        s = self._setting("email", {})
        with self.store.tx() as c:
            if reminders and not s.get("reminders"):
                # Start from now: switching reminders on never mails the backlog.
                s["last_reminder_id"] = c.execute("SELECT COALESCE(MAX(id),0) FROM reminders").fetchone()[0]
            s.update(address=address, digest=digest if address else "off", reminders=bool(reminders and address), language=lang_of(language),
                     weekday=int(weekday), skip_quiet=bool(skip_quiet))
            self._put_setting(c, "email", s)
            self.store.event(c, actor, "email.settings", "ok", None, address=mask(address, 3) if address else "", digest=s["digest"],
                             reminders=s["reminders"])
        return self.email_settings()

    def _money_section(self, E):
        """Balances, gaps, plans and timing: the part of every digest that is about exchanging."""
        sections, fingerprint = [], []
        pos = self.cash_position()
        if pos["currencies"]:
            sections.append((E["assets"], [f"{c['currency']} {money(c['amount'], c['currency'])}" for c in pos["currencies"]]))
            fingerprint += [(c["currency"], c["amount"]) for c in pos["currencies"]]
        gaps = [g for g in self.currency_gaps()["gaps"] if g["known"] and g["gap_after"]]
        sections.append((E["gaps"], [E["gap_item"].format(cur=g["currency"], amount=money(g["gap_after"], g["currency"]),
                                                          due=f" · {g['due']}" if g["due"] else "",
                                                          stressed=money(g["gap_stressed"], g["currency"])) for g in gaps] or [E["no_gaps"]]))
        fingerprint += [(g["currency"], g["gap_after"]) for g in gaps]
        plans = self.exchange_plans()
        sections.append((E["plans"], [E["plan_item"].format(pair=f"{p['source']}→{p['target']}" + (f" · {p['purpose']}" if p["purpose"] else ""),
                                                            amount=money(p["amount"], p["amount_currency"]), due=p["due"] or "—") for p in plans[:8]]
                         or [E["no_plans"]]))
        fingerprint += [(p["id"], p["amount"], p["due"]) for p in plans]
        timing = []
        for pair in {(p["source"], p["target"]) for p in plans}:
            try:
                adv = self.exchange_advice(*pair, use_model=False)
                timing.append(f"{pair[0]}→{pair[1]} {adv['signals']['rate']} · {E.get('v_' + adv['verdict'], adv['verdict'])}" + (f" — {adv['explanation']}" if adv.get("explanation") else ""))
            except (Denied, KeyError, ValueError, ArithmeticError):  # timing is a bonus; the digest goes out without it
                continue
        if timing:
            sections.append((E["timing"], sorted(timing)))
        return sections, digest(fingerprint)

    def report(self, period="week", language=None):
        language = lang_of(language or self._setting("email", {}).get("language") or self.memory().get("language"))
        E, R = EMAIL[language], REMINDERS[language]
        daily = period == "day"
        ins = self.spending_insights("week" if daily else period, language)
        cur, cats = ins["currency"], CATEGORIES[language]
        today = date.today()
        subject = E["subject_" + period].format(date=str(today))
        lines = [E["title"], (E["period_day"].format(date=str(today)) if daily else E["period_" + period].format(start=ins["start"], end=ins["end"])), ""]
        change = (E["change"].format(sign="+" if ins["change_pct"] > 0 else "", pct=ins["change_pct"])
                  if ins["change_pct"] is not None else E["no_previous"])
        lines.append(E["spent"].format(total=money(ins["total"], cur)) + " · " + change)
        sections, money_print = self._money_section(E)
        if ins["categories"]:
            sections.append((E["categories"], [f"{cats.get(c['category'], c['category'])}: {money(c['amount'], cur)}"
                                               for c in ins["categories"][:6] if c["amount"]]))
        if ins["tips"]:
            sections.append((E["tips"], [t["text"] for t in ins["tips"]]))
        upcoming = []
        try:
            plan = self.cashflow(cur)
            if plan["terms"]:
                upcoming.append(E["cashflow_low"].format(amount=money(plan["lowest"]["amount"], cur), date=plan["lowest"]["date"]))
        except Denied:
            pass
        if upcoming:
            sections.append((E["upcoming"], upcoming))
        active = [r for r in self.reminders() if r["severity"] in ("warn", "alert")][:8]
        if active:
            sections.append((E["reminders"], [reminder_text(R, r) for r in active]))
        for title, items in sections:
            lines += ["", title] + ["· " + i for i in items]
        lines += ["", E["footer"]]
        return dict(subject=subject, text="\n".join(lines), html=self._html(E["title"], lines[1], lines[3], sections, E["footer"]),
                    fingerprint=digest([money_print, [r["id"] for r in active]]))

    @staticmethod
    def _html(title, period, headline, sections, footer):
        e = html.escape
        parts = [f'<div style="font-family:Inter,Segoe UI,Arial,sans-serif;max-width:560px;margin:0 auto;color:#111;background:#fff;padding:28px">',
                 f'<p style="font:600 11px monospace;letter-spacing:1px;color:#8a8a86;margin:0">{e(title)}</p>',
                 f'<h1 style="font-size:22px;font-weight:500;margin:10px 0 4px">{e(headline)}</h1>',
                 f'<p style="color:#8a8a86;font-size:13px;margin:0 0 18px">{e(period)}</p>']
        for name, items in sections:
            parts.append(f'<h2 style="font-size:13px;letter-spacing:.6px;text-transform:uppercase;border-top:1px solid #e3e3df;padding-top:14px">{e(name)}</h2>')
            parts.append('<ul style="padding-left:18px;font-size:14px;line-height:1.6">' + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>")
        parts.append(f'<p style="font-size:11px;color:#8a8a86;border-top:1px dashed #e3e3df;padding-top:12px">{e(footer)}</p></div>')
        return "".join(parts)

    def _log_email(self, kind, to, subject, status, error=None):
        with self.store.tx() as c:
            c.execute("INSERT INTO email_log(kind,recipient,subject,status,error,created) VALUES (?,?,?,?,?,?)",
                      (kind, mask(to, 3), subject[:200], status, error, now()))
            self.store.event(c, "system", "email.send", status, None, kind=kind)

    def send_report(self, actor, period="week"):
        self.require(actor, "prepare")  # only ever to the owner's own saved address
        s = self._setting("email", {})
        if not s.get("address"):
            raise Denied("save an email address first", "email_missing")
        with self.store.read() as c:
            last = c.execute("SELECT MAX(created) FROM email_log WHERE kind<>'reminders'").fetchone()[0]
        if last and now() - last < 60:
            raise Denied("wait a minute before sending another report", "email_rate")
        r = self.report(period if period in ("day", "week", "month") else "week")
        try:
            mailer.send(s["address"], r["subject"], r["text"], r["html"])
        except Denied as exc:
            self._log_email(period, s["address"], r["subject"], "failed", exc.code)
            raise
        self._log_email(period, s["address"], r["subject"], "sent")
        return {"sent": True, "subject": r["subject"], "to": mask(s["address"], 3)}

    def email_tick(self):
        """Called by the worker. Sends a due digest and new important reminders to the saved address."""
        s = self._setting("email", {})
        if not mailer.configured() or not s.get("address"):
            return []
        sent, today = [], date.today()
        last = s.get("last_digest")
        if s.get("digest") == "daily":
            due = datetime.fromtimestamp(last).date() != today if last else True
        elif s.get("digest") == "weekly":
            day = int(s.get("weekday", 0))
            # On the chosen weekday; or right away when a week has gone by without one (the app was not running that day).
            due = (today.weekday() == day and (not last or now() - last >= 6 * 86400)) or bool(last and now() - last >= 7 * 86400 + 3600)
        elif s.get("digest") == "monthly":
            due = datetime.fromtimestamp(last).strftime("%Y-%m") != today.strftime("%Y-%m") if last else today.day == 1
        else:
            due = False
        if due:
            period = {"daily": "day", "weekly": "week"}.get(s["digest"], "month")
            r = self.report(period)
            quiet = s.get("skip_quiet", True) and r["fingerprint"] == s.get("last_fingerprint")
            if quiet:  # nothing changed since the last digest: skip it rather than send the same email again
                s["last_digest"] = now()
                due = False
        if due:
            s["last_fingerprint"] = r["fingerprint"]
            try:
                mailer.send(s["address"], r["subject"], r["text"], r["html"])
                self._log_email("digest", s["address"], r["subject"], "sent")
                sent.append("digest")
            except Denied as exc:
                self._log_email("digest", s["address"], r["subject"], "failed", exc.code)
            s["last_digest"] = now()  # one attempt per period; failures are visible in the log
        if s.get("reminders"):
            fresh = [r for r in self.reminders() if r["id"] > s.get("last_reminder_id", 0) and
                     (r["severity"] in ("warn", "alert") or r["kind"] in ("rate_target", "rate_favorable", "exchange_due", "ai_good_time", "ai_deadline"))]
            if fresh:
                L = lang_of(s.get("language"))
                E, R = EMAIL[L], REMINDERS[L]
                items = [reminder_text(R, r) for r in fresh[:12]]
                subject = E["subject_reminders"].format(n=len(fresh))
                text = "\n".join([E["title"], "", E["reminders_intro"], *["· " + i for i in items], "", E["footer"]])
                try:
                    mailer.send(s["address"], subject, text, self._html(E["title"], E["reminders_intro"], subject, [(E["reminders"], items)], E["footer"]))
                    self._log_email("reminders", s["address"], subject, "sent")
                    sent.append("reminders")
                    s["last_reminder_id"] = max(r["id"] for r in fresh)
                except Denied as exc:
                    self._log_email("reminders", s["address"], subject, "failed", exc.code)
        with self.store.tx() as c:
            self._put_setting(c, "email", s)
        return sent
