"""Comparison, scenarios, goals, budgets, decisions and proposals. Planning never moves funds."""
import json
import re
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from .domain import Denied, canonical, now, units, decimals, from_minor, to_minor, floor_minor

# Simulated market options for comparison only. They are illustrations, never real offers.
SIMULATED_OPTIONS = [
    dict(id="sim-bank-wire", fixed_usd="25", percent="0", spread="0.025", eta_hours=72,
         eta="2-4 business days", intermediary="correspondent-bank charges possible and unknown"),
    dict(id="sim-online", fixed_usd="3", percent="0.0045", spread="0.004", eta_hours=24,
         eta="same or next business day", intermediary="receiving-bank charges unknown"),
    dict(id="sim-instant", fixed_usd="5", percent="0.012", spread="0.015", eta_hours=0.25,
         eta="minutes (cash pickup / wallet)", intermediary="pickup-agent charges unknown"),
]
PROPOSAL_KINDS = ("recipient", "preference", "goal", "obligation", "rate_alert", "action")
BUDGET_KINDS = ("income", "expense", "buffer", "holding")


def _date(value, field="date"):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise Denied(f"{field} must be YYYY-MM-DD", "date_invalid") from None


class PlanningMixin:
    # ---------- comparison ----------
    def _fixed_fee(self, fixed_usd, source):
        fixed = Decimal(fixed_usd)
        if source == "USD" or fixed == 0:
            return fixed
        return fixed * Decimal(self.rates.latest("USD", source)["rate"])

    def compare(self, actor, source, target, amount=None, receive_amount=None, rank="receive"):
        self.require(actor, "view")
        if (not amount) == (not receive_amount):
            raise Denied("give exactly one of a sending amount or a target receiving amount", "amount_mode")
        if rank not in ("receive", "speed"):
            raise Denied("rank by receive or speed", "rank_invalid")
        mode = "receive" if receive_amount else "send"
        send_minor = units(amount, decimals(source)) if amount else None
        want_minor = units(receive_amount, decimals(target)) if receive_amount else None
        options, notes = [], []
        try:
            ref = self.rates.latest(source, target)
            ref_rate = Decimal(ref["rate"])
        except Denied:
            ref, ref_rate = None, None
            notes.append("reference rate unavailable for this pair; only the sandbox option can be calculated")

        if ref_rate:
            if mode == "send":
                ideal = floor_minor(from_minor(send_minor, source) * ref_rate, target)
                options.append(dict(id="reference", kind="reference_calculation", send=send_minor, receive=ideal, fee=0,
                                    applied_rate=str(ref_rate), spread_pct="0", eta=None, eta_hours=None,
                                    note="benchmark at the reference rate with no fees; not an available offer"))
            else:
                need = to_minor(from_minor(want_minor, target) / ref_rate, source)
                options.append(dict(id="reference", kind="reference_calculation", send=need, receive=want_minor, fee=0,
                                    applied_rate=str(ref_rate), spread_pct="0", eta=None, eta_hours=None,
                                    note="benchmark at the reference rate with no fees; not an available offer"))
            for opt in SIMULATED_OPTIONS:
                try:
                    fixed = self._fixed_fee(opt["fixed_usd"], source)
                except Denied:
                    notes.append(f"{opt['id']}: fixed fee could not be converted to {source}; omitted")
                    continue
                pct, spread = Decimal(opt["percent"]), Decimal(opt["spread"])
                applied = ref_rate * (1 - spread)
                if mode == "send":
                    send = send_minor
                else:
                    send = to_minor((from_minor(want_minor, target) / applied + fixed) / (1 - pct), source)
                fee = to_minor(fixed + from_minor(send, source) * pct, source)
                receive = floor_minor(from_minor(send - fee, source) * applied, target) if send > fee else 0
                options.append(dict(id=opt["id"], kind="simulated_option", send=send, receive=receive, fee=fee,
                                    fee_breakdown=dict(fixed=str(round(fixed, 2)), percent=str(pct * 100)),
                                    applied_rate=str(applied.quantize(Decimal("0.000001"))), spread_pct=str(spread * 100),
                                    eta=opt["eta"], eta_hours=opt["eta_hours"], unknown_charges=opt["intermediary"],
                                    executable=False, note="illustrative simulated option, not a real provider offer"))
        with self.store.read() as c:
            route = self.route_for(c, source, target)
        if self.sandbox.supports(source, target):
            try:
                q = self.sandbox.quote(source, target, None, "comparison", amount=amount or None, receive_amount=receive_amount or None)
                options.append(dict(id="sandbox", kind="sandbox_quote", send=q["value"], receive=q["receive"], fee=q["fee"],
                                    fee_breakdown=q["fee_breakdown"], applied_rate=q["rate"], spread_pct=q["spread_pct"],
                                    eta=q["eta"], eta_hours=q["eta_seconds"] / 3600, unknown_charges=q["unknown_charges"],
                                    executable=bool(route), route_id=route["id"] if route else None, rate_kind=q["rate_kind"],
                                    note="local simulation quote; a quote ID and expiry are issued when a draft is prepared"))
            except Denied as exc:
                notes.append(f"sandbox: {exc}")
        else:
            notes.append("the sandbox provider does not support payments on this pair")
        ranked = [o for o in options if o["kind"] != "reference_calculation"]
        if rank == "speed":
            ranked.sort(key=lambda o: (o["eta_hours"], -o["receive"] if mode == "send" else o["send"]))
            basis = "fastest estimated delivery first; ties broken by amount received (or sent)"
        elif mode == "send":
            ranked.sort(key=lambda o: -o["receive"])
            basis = "highest net amount received for the same sending amount"
        else:
            ranked.sort(key=lambda o: o["send"])
            basis = "lowest sending amount needed for the target received amount"
        for i, o in enumerate(ranked, 1):
            o["rank"] = i
            if ref_rate and mode == "send":
                ideal = options[0]["receive"]
                o["cost_vs_reference_pct"] = str(round((Decimal(ideal - o["receive"]) / ideal * 100), 3)) if ideal else None
        bench = [o for o in options if o["kind"] == "reference_calculation"]
        result = dict(kind="comparison", source=source, target=target, mode=mode, rank=rank, basis=basis,
                      amount=amount, receive_amount=receive_amount, reference=ref, options=bench + ranked, notes=notes,
                      disclaimer="Simulated options illustrate fee and spread structures. A sandbox quote is not a live offer.")
        with self.store.tx() as c:
            self.store.event(c, actor, "compare", "ok", None, pair=f"{source}/{target}", mode=mode, rank=rank,
                             options=[o["id"] for o in ranked])
        return result

    # ---------- scenarios ----------
    def scenario(self, actor, source, target, amount, rate_change_pct):
        self.require(actor, "view")
        change = Decimal(str(rate_change_pct))
        if not change.is_finite() or abs(change) >= 100:
            raise Denied("rate change must be between -100 and 100 percent", "scenario_invalid")
        send = units(amount, decimals(source))
        if self.sandbox.supports(source, target):
            q = self.sandbox.quote(source, target, None, "scenario", amount=amount)
            rate, fee = Decimal(q["rate"]), q["fee"]
            fixed, pct = Decimal(q["fee_breakdown"]["fixed"]), Decimal(q["fee_breakdown"]["percent"]) / 100
            basis = "sandbox fee model and applied rate"
        else:
            rate, fee, fixed, pct = Decimal(self.rates.latest(source, target)["rate"]), 0, Decimal(0), Decimal(0)
            basis = "reference rate with no fees (no quote available for this pair)"
        base_receive = floor_minor(from_minor(send - fee, source) * rate, target)
        new_rate = rate * (1 + change / 100)
        new_receive = floor_minor(from_minor(send - fee, source) * new_rate, target)
        required = to_minor((from_minor(base_receive, target) / new_rate + fixed) / (1 - pct), source)
        with self.store.read() as c:
            row = c.execute("SELECT total FROM balances WHERE currency=?", (source,)).fetchone()
            reserved = sum(json.loads(r[0])["reserve"] for r in
                           c.execute("SELECT body FROM transfers WHERE status IN ('pending','unknown')")
                           if json.loads(r[0])["source"] == source)
        available = int(row[0]) - reserved if row else None
        return dict(kind="hypothetical scenario, not a forecast", source=source, target=target, basis=basis,
                    send=send, fee=fee, rate=str(rate), rate_change_pct=str(change), scenario_rate=str(new_rate),
                    receive_now=base_receive, receive_scenario=new_receive, receive_difference=new_receive - base_receive,
                    required_send_for_same_receive=required, extra_needed=required - send, available=available,
                    shortfall=max(0, required - available) if available is not None else None,
                    assumptions=["fees follow the stated fee model", "rate moves by exactly the stated percentage",
                                 "no intermediary charges", "this is arithmetic, not a prediction"])

    # ---------- goals and budget ----------
    def _validate_goal(self, payload):
        title = (payload.get("title") or "").strip()
        source, target = payload.get("source", ""), payload.get("target", "")
        if not title or len(title) > 100 or not re.fullmatch(r"[A-Z]{3}", source) or not re.fullmatch(r"[A-Z]{3}", target):
            raise Denied("goal needs a title and ISO currencies", "goal_invalid")
        target_minor = units(payload.get("target_amount"), decimals(target))
        deadline = _date(payload.get("deadline"), "deadline")
        return dict(title=title, purpose=(payload.get("purpose") or title)[:200], source=source, target=target,
                    target_amount=target_minor, deadline=str(deadline), recipient_id=payload.get("recipient_id") or None,
                    category=payload.get("category") or "family")

    def create_goal(self, actor, **payload):
        self.owner(actor)
        body = self._validate_goal(payload)
        gid = str(uuid.uuid4())
        with self.store.tx() as c:
            c.execute("INSERT INTO goals VALUES (?,?,?,?)", (gid, canonical(body), "active", now()))
            self.store.event(c, actor, "goal.create", "ok", gid, deadline=body["deadline"])
        return self.goal(gid)

    def update_goal(self, actor, goal_id, status):
        self.owner(actor)
        if status not in ("active", "done", "archived"):
            raise Denied("invalid goal status", "goal_invalid")
        with self.store.tx() as c:
            if not c.execute("UPDATE goals SET status=? WHERE id=?", (status, goal_id)).rowcount:
                raise Denied("goal not found", "goal_unknown")
            self.store.event(c, actor, "goal.update", "ok", goal_id, status=status)
        return self.goal(goal_id)

    def goal(self, goal_id):
        with self.store.read() as c:
            row = c.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
            if not row:
                raise Denied("goal not found", "goal_unknown")
            transfers = [dict(r) for r in c.execute("SELECT * FROM transfers WHERE goal_id=?", (goal_id,))]
        body = json.loads(row["body"])
        # Completed and planned payments are kept apart to avoid double counting.
        completed = sum(json.loads(t["body"])["receive"] for t in transfers if t["status"] == "completed")
        planned = sum(json.loads(t["body"])["receive"] for t in transfers if t["status"] in ("draft", "approved", "pending", "unknown"))
        days_left = (_date(body["deadline"]) - date.today()).days
        return dict(id=row["id"], status=row["status"], created=row["created"], **body, completed=completed, planned=planned,
                    remaining=max(0, body["target_amount"] - completed), days_left=days_left,
                    transfers=[t["id"] for t in transfers])

    def goals(self):
        with self.store.read() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM goals WHERE status<>'archived' ORDER BY created DESC")]
        return [self.goal(i) for i in ids]

    def add_budget(self, actor, kind, label, currency, amount, date=None):
        self.owner(actor)
        if kind not in BUDGET_KINDS or not (label or "").strip() or not re.fullmatch(r"[A-Z]{3}", currency or ""):
            raise Denied("budget entry needs a kind, label and ISO currency", "budget_invalid")
        body = dict(kind=kind, label=label.strip()[:100], currency=currency, amount=units(amount, decimals(currency)),
                    date=str(_date(date)) if date else None, verified=False)
        bid = str(uuid.uuid4())
        with self.store.tx() as c:
            c.execute("INSERT INTO budget VALUES (?,?,?)", (bid, canonical(body), now()))
            self.store.event(c, actor, "budget.add", "ok", bid, kind=kind)
        return dict(id=bid, **body)

    def delete_budget(self, actor, entry_id):
        self.owner(actor)
        with self.store.tx() as c:
            if not c.execute("DELETE FROM budget WHERE id=?", (entry_id,)).rowcount:
                raise Denied("budget entry not found", "budget_unknown")
            self.store.event(c, actor, "budget.delete", "ok", entry_id)
        return {"deleted": entry_id}

    def budget(self):
        with self.store.read() as c:
            return [dict(id=r["id"], created=r["created"], **json.loads(r["body"])) for r in c.execute("SELECT * FROM budget ORDER BY created")]

    def goal_plan(self, actor, goal_id, installments=3):
        self.require(actor, "view")
        if not 1 <= int(installments) <= 12:
            raise Denied("installments must be between 1 and 12", "plan_invalid")
        installments = int(installments)
        g = self.goal(goal_id)
        source, target, remaining = g["source"], g["target"], g["remaining"]
        assumptions = ["the current rate stays unchanged until every installment", "fees follow the stated model per transfer",
                       "future rates and fees are unknown until a valid quote is issued"]

        def cost(receive_minor):
            if receive_minor <= 0:
                return 0, 0
            text = str(from_minor(receive_minor, target))
            if self.sandbox.supports(source, target):
                q = self.sandbox.quote(source, target, None, "plan", receive_amount=text)
                return q["value"], q["fee"]
            rate = Decimal(self.rates.latest(source, target)["rate"])
            return to_minor(from_minor(receive_minor, target) / rate, source), 0

        try:
            one_send, one_fee = cost(remaining)
            each = -(-remaining // installments)
            part_send, part_fee = cost(each)
            basis = "sandbox fee model" if self.sandbox.supports(source, target) else "reference rate, fees unknown"
        except Denied as exc:
            return dict(goal=g, available=False, reason=str(exc))
        deadline = _date(g["deadline"])
        today = date.today()
        span = max(0, (deadline - today).days)
        schedule = [str(today + timedelta(days=span * i // max(1, installments - 1))) if installments > 1 else str(today)
                    for i in range(installments)]
        entries = self.budget()
        in_window = [e for e in entries if e["currency"] == source and (not e["date"] or today <= _date(e["date"]) <= deadline)]
        income = sum(e["amount"] for e in in_window if e["kind"] == "income")
        expense = sum(e["amount"] for e in in_window if e["kind"] == "expense")
        buffer = sum(e["amount"] for e in entries if e["kind"] == "buffer" and e["currency"] == source)
        holdings = sum(e["amount"] for e in entries if e["kind"] == "holding" and e["currency"] == source)
        ledger = next((b for b in self.balances() if b["currency"] == source and b["rail"] == "sandbox"), None)
        available = int(ledger["available"]) if ledger else 0
        capacity = available + income - expense - buffer
        return dict(goal=g, available=True, basis=basis, assumptions=assumptions,
                    one_time=dict(send=one_send, fee=one_fee),
                    installments=dict(count=installments, each_receive=each, each_send=part_send, each_fee=part_fee,
                                      total_send=part_send * installments, total_fee=part_fee * installments, schedule=schedule),
                    extra_fees_for_installments=part_fee * installments - one_fee,
                    funds=dict(ledger_available=available, planned_income=income, planned_expense=expense, safety_buffer=buffer,
                               user_entered_holdings=holdings, capacity=capacity, shortfall=max(0, one_send - capacity),
                               note="ledger funds are simulated; user-entered holdings are unverified and excluded from capacity"))

    # ---------- decisions: accepting a recommendation is not a payment ----------
    def accept_recommendation(self, actor, subject, detail):
        self.owner(actor)
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", subject or "") or not isinstance(detail, dict):
            raise Denied("recommendation subject required", "decision_invalid")
        did = str(uuid.uuid4())
        snapshot = {k: detail[k] for k in list(detail)[:20]}
        with self.store.tx() as c:
            c.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?)", (did, "recommendation", subject, canonical(snapshot), actor, now()))
            self.store.event(c, actor, "recommendation.accept", "ok", did, subject=subject, balances_changed=False)
        return dict(id=did, kind="recommendation", subject=subject, detail=snapshot, actor=actor, created=now(),
                    note="accepting a recommendation does not prepare, authorize or move any funds")

    def decisions(self):
        with self.store.read() as c:
            return [dict(r, detail=json.loads(r["detail"])) for r in c.execute("SELECT * FROM decisions ORDER BY created DESC LIMIT 100")]

    # ---------- proposals: agent-suggested changes the owner confirms ----------
    def propose(self, actor, kind, payload, reason=""):
        self.require(actor, "prepare")
        if kind not in PROPOSAL_KINDS or not isinstance(payload, dict):
            raise Denied("unsupported proposal kind", "proposal_invalid")
        # Validate now so the owner reviews exactly what would be applied.
        if kind == "recipient":
            self._recipient_body(payload.get("recipient_id"), payload.get("name"), payload.get("address", ""),
                                 payload.get("currency", ""), payload.get("country", ""), payload.get("account", ""),
                                 payload.get("kind", "individual"))
        elif kind == "preference":
            from .service import PREFERENCES
            if payload.get("key") not in PREFERENCES or len(str(payload.get("value", ""))) > 200:
                raise Denied("only bounded non-secret user preferences supported", "preference_invalid")
        elif kind == "goal":
            self._validate_goal(payload)
        elif kind == "obligation":
            self._validate_obligation(payload)
        elif kind == "rate_alert":
            self._validate_alert(payload)
        elif kind == "action":
            from . import actions
            payload = dict(action=payload.get("action"), params=actions.check(payload.get("action"), payload.get("params")))
        pid = str(uuid.uuid4())
        with self.store.tx() as c:
            c.execute("INSERT INTO proposals(id,kind,payload,status,created_by,created,note) VALUES (?,?,?,?,?,?,?)",
                      (pid, kind, canonical(payload), "pending", actor, now(), (reason or "")[:300]))
            self.store.event(c, actor, "proposal.create", "pending", pid, kind=kind)
        return self.proposal(pid)

    def proposal(self, pid):
        with self.store.read() as c:
            r = c.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
        if not r:
            raise Denied("proposal not found", "proposal_unknown")
        return dict(r, payload=json.loads(r["payload"]))

    def proposals(self):
        with self.store.read() as c:
            return [dict(r, payload=json.loads(r["payload"])) for r in c.execute("SELECT * FROM proposals ORDER BY created DESC LIMIT 100")]

    def decide(self, actor, pid, accept, note=""):
        self.owner(actor)
        p = self.proposal(pid)
        if p["status"] != "pending":
            raise Denied("proposal already decided", "proposal_decided")
        if accept:
            payload = p["payload"]
            if p["kind"] == "recipient":
                self.add_recipient(actor, **{k: payload[k] for k in ("recipient_id", "name", "address", "currency",
                                                                     "country", "account", "kind") if k in payload})
            elif p["kind"] == "preference":
                self.remember(actor, payload["key"], str(payload["value"]))
            elif p["kind"] == "goal":
                self.create_goal(actor, **payload)
            elif p["kind"] == "obligation":
                self.add_obligation(actor, **payload)
            elif p["kind"] == "rate_alert":
                self.add_rate_alert(actor, **payload)
            elif p["kind"] == "action":
                from . import actions
                actions.run(self, actor, payload["action"], payload["params"])
        with self.store.tx() as c:
            c.execute("UPDATE proposals SET status=?,decided_by=?,decided=?,note=COALESCE(?,note) WHERE id=?",
                      ("confirmed" if accept else "rejected", actor, now(), note or None, pid))
            self.store.event(c, actor, "proposal.confirm" if accept else "proposal.reject", "ok", pid, kind=p["kind"])
        return self.proposal(pid)
