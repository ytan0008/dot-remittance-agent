"""Payment habits, reminders and rate alerts. The habit indicator is internal and is never a credit score."""
import json
import re
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from .domain import Denied, canonical, now, units, decimals, from_minor
from .watch import EVENT_KINDS

CATEGORIES = ("rent", "tuition", "utility", "loan", "family", "subscription", "other")


def _parse(value, field):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise Denied(f"{field} must be YYYY-MM-DD", "date_invalid") from None


def _next_month(day):
    month = day.month % 12 + 1
    year = day.year + (day.month == 12)
    for d in (day.day, 30, 29, 28):
        try:
            return date(year, month, d)
        except ValueError:
            continue


class HabitsMixin:
    # ---------- obligations ----------
    def _validate_obligation(self, payload):
        title = (payload.get("title") or "").strip()
        currency = payload.get("currency", "")
        if not title or len(title) > 100 or not re.fullmatch(r"[A-Z]{3}", currency):
            raise Denied("obligation needs a title and ISO currency", "obligation_invalid")
        if payload.get("category", "other") not in CATEGORIES or payload.get("recurring", "none") not in ("none", "monthly"):
            raise Denied("invalid obligation category or recurrence", "obligation_invalid")
        return dict(title=title, category=payload.get("category", "other"), currency=currency,
                    amount=units(payload.get("amount"), decimals(currency)),
                    due_date=str(_parse(payload.get("due_date"), "due date")), recurring=payload.get("recurring", "none"))

    def add_obligation(self, actor, **payload):
        self.owner(actor)
        body = self._validate_obligation(payload)
        oid = str(uuid.uuid4())
        with self.store.tx() as c:
            c.execute("INSERT INTO obligations(id,body,status,created) VALUES (?,?,?,?)", (oid, canonical(body), "open", now()))
            self.store.event(c, actor, "obligation.add", "ok", oid, due=body["due_date"])
        return self.obligation(oid)

    def obligation(self, oid):
        with self.store.read() as c:
            r = c.execute("SELECT * FROM obligations WHERE id=?", (oid,)).fetchone()
        if not r:
            raise Denied("obligation not found", "obligation_unknown")
        return self._obligation_view(dict(r))

    def _obligation_view(self, r):
        body = json.loads(r["body"])
        due = _parse(body["due_date"], "due date")
        today = date.today()
        if r["paid_at"]:
            paid = datetime.fromtimestamp(r["paid_at"]).date()
            state = "paid_on_time" if paid <= due else "paid_late"
        elif today > due:
            state = "overdue"
        elif (due - today).days <= 3:
            state = "due_soon"
        else:
            state = "upcoming"
        return dict(id=r["id"], status=r["status"], paid_at=r["paid_at"], transfer_id=r["transfer_id"], created=r["created"],
                    state=state, days_until_due=(due - today).days,
                    evidence="sandbox demonstration record" if r["transfer_id"] else "user-recorded", **body)

    def obligations(self):
        with self.store.read() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM obligations WHERE status<>'archived' ORDER BY json_extract(body,'$.due_date')")]
        return [self._obligation_view(r) for r in rows]

    def mark_paid(self, actor, oid, paid_date=None, transfer_id=None):
        self.owner(actor)
        with self.store.tx() as c:
            r = c.execute("SELECT * FROM obligations WHERE id=?", (oid,)).fetchone()
            if not r:
                raise Denied("obligation not found", "obligation_unknown")
            if r["paid_at"]:
                raise Denied("obligation already recorded as paid", "obligation_paid")
            if transfer_id:
                t = c.execute("SELECT status,completed_at FROM transfers WHERE id=?", (transfer_id,)).fetchone()
                if not t or t["status"] != "completed":
                    raise Denied("only a completed payment can be linked", "obligation_transfer")
                paid_at = t["completed_at"]
            elif paid_date:
                paid_at = int(datetime.combine(_parse(paid_date, "paid date"), datetime.min.time()).timestamp()) + 43200
                if paid_at > now() + 86400:
                    raise Denied("paid date cannot be in the future", "date_invalid")
            else:
                paid_at = now()
            c.execute("UPDATE obligations SET paid_at=?,transfer_id=?,status='paid' WHERE id=?", (paid_at, transfer_id, oid))
            body = json.loads(r["body"])
            self.store.event(c, actor, "obligation.paid", "ok", oid, transfer_id=transfer_id)
            if body["recurring"] == "monthly":
                body["due_date"] = str(_next_month(_parse(body["due_date"], "due date")))
                c.execute("INSERT INTO obligations(id,body,status,created) VALUES (?,?,?,?)",
                          (str(uuid.uuid4()), canonical(body), "open", now()))
        return self.obligation(oid)

    def delete_obligation(self, actor, oid):
        self.owner(actor)
        with self.store.tx() as c:
            if not c.execute("UPDATE obligations SET status='archived' WHERE id=?", (oid,)).rowcount:
                raise Denied("obligation not found", "obligation_unknown")
            self.store.event(c, actor, "obligation.archive", "ok", oid)
        return {"archived": oid}

    def habits(self):
        items = self.obligations()
        resolved = sorted([o for o in items if o["paid_at"]], key=lambda o: o["due_date"], reverse=True)
        on_time = sum(o["state"] == "paid_on_time" for o in resolved)
        late = sum(o["state"] == "paid_late" for o in resolved)
        streak = 0
        for o in resolved:
            if o["state"] != "paid_on_time":
                break
            streak += 1
        recent = resolved[:12]
        return dict(label="internal payment-habit indicator, not an official credit score",
                    recorded=len(resolved), on_time=on_time, late=late,
                    overdue=sum(o["state"] == "overdue" for o in items), upcoming=sum(o["state"] in ("upcoming", "due_soon") for o in items),
                    on_time_pct=str(round(Decimal(on_time) * 100 / len(resolved), 1)) if resolved else None,
                    recent_on_time_pct=str(round(Decimal(sum(o["state"] == "paid_on_time" for o in recent)) * 100 / len(recent), 1)) if recent else None,
                    streak=streak, sandbox_linked=sum(bool(o["transfer_id"]) for o in resolved),
                    disclaimers=["Not reported to any credit bureau.", "Remittances do not automatically build credit.",
                                 "Sandbox payments are demonstration records and cannot establish credit history."])

    # ---------- rate alerts ----------
    def _validate_alert(self, payload):
        source, target = payload.get("source", ""), payload.get("target", "")
        if not re.fullmatch(r"[A-Z]{3}", source) or not re.fullmatch(r"[A-Z]{3}", target) or source == target:
            raise Denied("distinct uppercase ISO currency pair required", "pair_invalid")
        condition = payload.get("condition")
        if condition not in ("above", "below", "percentile", "date"):
            raise Denied("condition must be above, below, percentile or date", "alert_invalid")
        body = dict(source=source, target=target, condition=condition, note=str(payload.get("note") or "")[:120])
        if condition == "date":
            try:
                due = datetime.strptime(str(payload.get("due_date") or ""), "%Y-%m-%d").date()
            except ValueError:
                raise Denied("reminder date must be YYYY-MM-DD", "date_invalid") from None
            return dict(body, threshold="0", due_date=str(due))
        threshold = Decimal(str(payload.get("threshold", "0")))
        if not threshold.is_finite() or threshold <= 0 or (condition == "percentile" and not 50 <= threshold <= 99):
            raise Denied("threshold must be positive (percentile 50-99)", "alert_invalid")
        if condition == "percentile":
            return dict(body, threshold=str(threshold), window=str(payload.get("window") or "90"))
        return dict(body, threshold=str(threshold))

    def add_rate_alert(self, actor, **payload):
        self.owner(actor)
        body = self._validate_alert(payload)
        aid = str(uuid.uuid4())
        with self.store.tx() as c:
            c.execute("INSERT INTO rate_alerts(id,body,created) VALUES (?,?,?)", (aid, canonical(body), now()))
            self.store.event(c, actor, "rate_alert.add", "ok", aid, **body)
        return next(a for a in self.rate_alerts() if a["id"] == aid)

    def rate_alerts(self):
        with self.store.read() as c:
            return [dict(id=r["id"], active=bool(r["active"]), created=r["created"], last_rate=r["last_rate"],
                         last_checked=r["last_checked"], triggered_at=r["triggered_at"], **json.loads(r["body"]))
                    for r in c.execute("SELECT * FROM rate_alerts ORDER BY created DESC")]

    def update_rate_alert(self, actor, aid, active):
        self.owner(actor)
        with self.store.tx() as c:
            if not c.execute("UPDATE rate_alerts SET active=?,triggered_at=CASE WHEN ? THEN NULL ELSE triggered_at END WHERE id=?",
                             (int(active), int(active), aid)).rowcount:
                raise Denied("alert not found", "alert_unknown")
            self.store.event(c, actor, "rate_alert.update", "ok", aid, active=active)
        return next(a for a in self.rate_alerts() if a["id"] == aid)

    def check_rate_alerts(self):
        """One notification per crossing; the alert disarms until the owner re-arms it."""
        fired = []
        for alert in [a for a in self.rate_alerts() if a["active"]]:
            if alert["condition"] == "date":
                if date.today() >= date.fromisoformat(alert["due_date"]):
                    with self.store.tx() as c:
                        c.execute("UPDATE rate_alerts SET active=0,triggered_at=? WHERE id=?", (now(), alert["id"]))
                        self._remind(c, f"exchange:{alert['id']}", "exchange_due", alert["id"], "alert", dict(alert))
                        self.store.event(c, "system", "rate_alert.trigger", "ok", alert["id"], condition="date")
                    fired.append(alert["id"])
                continue
            try:
                ref = self.rates.latest(alert["source"], alert["target"])
                history = self.rates.fetch(alert["source"], alert["target"], alert.get("window", "90")) if alert["condition"] == "percentile" else None
            except Denied:
                continue
            rate, threshold = Decimal(ref["rate"]), Decimal(alert["threshold"])
            if alert["condition"] == "percentile":
                hit = Decimal(history["percentile"]) >= threshold
                ref = dict(ref, percentile=str(round(Decimal(history["percentile"]))))
            else:
                hit = rate >= threshold if alert["condition"] == "above" else rate <= threshold
            with self.store.tx() as c:
                c.execute("UPDATE rate_alerts SET last_rate=?,last_checked=? WHERE id=?", (ref["rate"], now(), alert["id"]))
                if hit:
                    c.execute("UPDATE rate_alerts SET active=0,triggered_at=? WHERE id=?", (now(), alert["id"]))
                    kind = "rate_favorable" if alert["condition"] == "percentile" else "rate_target"
                    self._remind(c, f"rate:{alert['id']}:{ref['observed']}", kind, alert["id"], "info",
                                 dict(alert, rate=ref["rate"], observed=ref["observed"], provider=ref["provider"], percentile=ref.get("percentile", "")))
                    self.store.event(c, "system", "rate_alert.trigger", "ok", alert["id"], rate=ref["rate"], observed=ref["observed"])
                    fired.append(alert["id"])
        return fired

    # ---------- reminders ----------
    @staticmethod
    def _remind(c, fingerprint, kind, ref, severity, data):
        cur = c.execute("INSERT OR IGNORE INTO reminders(fingerprint,kind,ref,severity,data,created) VALUES (?,?,?,?,?,?)",
                        (fingerprint, kind, ref, severity, canonical(data), now()))
        return cur.rowcount

    def refresh_reminders(self):
        """Derive reminders from real state. A condition that has not changed never notifies twice."""
        current = []
        today = date.today()
        for t in self.history(limit=300):
            b = t["details"]
            if t["status"] in ("draft", "approved"):
                left = b["expires"] - now()
                if left <= 0:
                    current.append((f"quote:{t['id']}:expired", "quote_expired", t["id"], "warn", dict(amount=b["amount"], source=b["source"])))
                elif left <= 120:
                    current.append((f"quote:{t['id']}:expiring", "quote_expiring", t["id"], "warn", dict(expires=b["expires"])))
            if t["status"] == "unknown" or (t["status"] == "pending" and (t["submitted"] or 0) < now() - 120):
                current.append((f"unresolved:{t['id']}:{t['status']}", "unresolved", t["id"], "alert", dict(status=t["status"])))
        balances = {b["currency"]: b for b in self.balances() if b["rail"] == "sandbox"}
        for t in self.history(limit=300):
            b = t["details"]
            if t["status"] in ("draft", "approved") and b["expires"] > now() and b.get("rail", "sandbox") == "sandbox":
                ledger = balances.get(b["source"])
                if ledger and int(ledger["available"]) < b["reserve"]:
                    current.append((f"funds:{t['id']}", "insufficient_funds", t["id"], "alert",
                                    dict(currency=b["source"], needed=str(b["reserve"]), available=ledger["available"])))
        for g in self.goals():
            if g["status"] != "active" or g["remaining"] <= 0:
                continue
            days = g["days_left"]
            stage = "overdue" if days < 0 else "1d" if days <= 1 else "7d" if days <= 7 else None
            if stage:
                current.append((f"goal:{g['id']}:{stage}", "goal_deadline", g["id"], "alert" if stage != "7d" else "warn",
                                dict(title=g["title"], deadline=g["deadline"], days_left=days)))
        for e in self.expenses(status="expected", limit=200):
            if e["date"] <= str(today + timedelta(days=1)):
                current.append((f"expected:{e['id']}", "expense_expected", e["id"], "warn",
                                dict(description=e["description"], date=e["date"], amount=str(from_minor(-e["amount"], e["currency"])), currency=e["currency"])))
        for o in self.obligations():
            if o["state"] in ("due_soon", "overdue"):
                current.append((f"obligation:{o['id']}:{o['state']}", "obligation_" + o["state"], o["id"],
                                "alert" if o["state"] == "overdue" else "warn",
                                dict(title=o["title"], due_date=o["due_date"], amount=str(o["amount"]), currency=o["currency"])))
        current.extend(self.student_reminders())
        current.extend(self.motivation_reminders())
        created = 0
        with self.store.tx() as c:
            for fingerprint, kind, ref, severity, data in current:
                created += self._remind(c, fingerprint, kind, ref, severity, data)
            live = {x[0] for x in current}
            for r in c.execute("SELECT id,fingerprint,kind FROM reminders WHERE resolved=0").fetchall():
                if r["kind"] in EVENT_KINDS:
                    continue
                if r["fingerprint"] not in live:
                    c.execute("UPDATE reminders SET resolved=1 WHERE id=?", (r["id"],))
        return created

    def reminders(self, include_dismissed=False):
        sql = "SELECT * FROM reminders WHERE resolved=0" + ("" if include_dismissed else " AND dismissed=0")
        with self.store.read() as c:
            return [dict(r, data=json.loads(r["data"])) for r in c.execute(sql + " ORDER BY created DESC LIMIT 100")]

    def dismiss(self, actor, reminder_id):
        if actor not in ("owner", "viewer"):
            raise Denied("only a person can dismiss reminders", "permission_denied")
        with self.store.tx() as c:
            if not c.execute("UPDATE reminders SET dismissed=1 WHERE id=?", (reminder_id,)).rowcount:
                raise Denied("reminder not found", "reminder_unknown")
            self.store.event(c, actor, "reminder.dismiss", "ok", str(reminder_id))
        return {"dismissed": reminder_id}
