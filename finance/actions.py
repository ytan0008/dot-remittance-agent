"""Everything the assistant can get done for you, as actions you confirm with one click.

The assistant looks things up and prepares freely, but changes to your money records (balances, bills, subscriptions,
terms, budget, plans, templates, limits, routes, email, …) are proposed as an action: it appears in the chat with what
it will do, and only when you press "Confirm" does the server run it, as you. Payments are not in this list on purpose:
authorizing and submitting a payment stays a deliberate act in the payment screen.

Each action names its parameters (required ones first) so a proposal can be checked before you see it.
"""
from .domain import Denied

# name: (required params, optional params, how to run it on the service as the owner)
ACTIONS = {
    "set_cash": (("currency", "amount"), ("label",), lambda f, a, p: f.set_cash(a, p["currency"], p["amount"], p.get("label", ""))),
    "clear_cash": (("currency",), (), lambda f, a, p: f.clear_cash(a, p["currency"])),
    "add_bill": (("title", "amount", "currency", "due_date"), ("category", "recurring"),
                 lambda f, a, p: f.add_obligation(a, title=p["title"], category=p.get("category") or "other", amount=str(p["amount"]),
                                                  currency=p["currency"], due_date=p["due_date"], recurring=p.get("recurring") or "none")),
    "mark_bill_paid": (("bill_id",), ("paid_date",), lambda f, a, p: f.mark_paid(a, p["bill_id"], p.get("paid_date") or None, None)),
    "delete_bill": (("bill_id",), (), lambda f, a, p: f.delete_obligation(a, p["bill_id"])),
    "add_recurring": (("description", "amount", "currency", "cadence"), ("category", "last_date"),
                      lambda f, a, p: f.add_recurring(a, p["description"], _minor(p["amount"], p["currency"]), p["currency"].upper(),
                                                      p.get("category") or "subscriptions", p["cadence"], p.get("last_date") or "")),
    "stop_recurring": (("recurring_id",), (), lambda f, a, p: f.stop_recurring(a, p["recurring_id"])),
    "add_budget": (("kind", "label", "currency", "amount"), ("date",),
                   lambda f, a, p: f.add_budget(a, kind=p["kind"], label=p["label"], currency=p["currency"], amount=str(p["amount"]), date=p.get("date") or None)),
    "delete_budget": (("entry_id",), (), lambda f, a, p: f.delete_budget(a, p["entry_id"])),
    "add_term": (("name", "start", "end"), ("currency", "tuition", "tuition_due", "living", "income"),
                 lambda f, a, p: f.add_term(a, name=p["name"], currency=p.get("currency"), start=p["start"], end=p["end"],
                                            tuition=str(p.get("tuition") or ""), tuition_due=p.get("tuition_due") or None,
                                            living=str(p.get("living") or ""), income=str(p.get("income") or ""), extras=[])),
    "delete_term": (("term_id",), (), lambda f, a, p: f.delete_term(a, p["term_id"])),
    "add_scholarship": (("name",), ("provider", "amount", "currency", "deadline", "status"),
                        lambda f, a, p: f.add_scholarship(a, name=p["name"], provider=p.get("provider", ""), kind="scholarship",
                                                          status=p.get("status") or "researching", amount=str(p.get("amount") or ""),
                                                          currency=p.get("currency"), deadline=p.get("deadline") or None, payout_date=None,
                                                          url="", notes="", documents=[])),
    "set_scholarship_status": (("scholarship_id", "status"), (), lambda f, a, p: f.update_scholarship(a, p["scholarship_id"], status=p["status"])),
    "delete_scholarship": (("scholarship_id",), (), lambda f, a, p: f.delete_scholarship(a, p["scholarship_id"])),
    "set_plan_status": (("plan_id", "status"), (), lambda f, a, p: f.set_plan_status(a, p["plan_id"], p["status"])),
    "delete_plan": (("plan_id",), (), lambda f, a, p: f.delete_plan(a, p["plan_id"])),
    "confirm_expenses": (("expense_ids",), ("category",),
                         lambda f, a, p: f.review(a, [dict(id=i, include=True, **({"category": p["category"]} if p.get("category") else {}))
                                                      for i in _ids(p["expense_ids"])])),
    "recategorize_expense": (("expense_id", "category"), (), lambda f, a, p: f.update_expense(a, p["expense_id"], p["category"], None, None, None)),
    "delete_expense": (("expense_id",), (), lambda f, a, p: f.delete_expense(a, p["expense_id"])),
    "set_email": (("digest",), ("address", "weekday", "reminders", "skip_quiet"),
                  lambda f, a, p: _email(f, a, p)),
    "set_limit": (("currency", "per_payment", "daily"), (), lambda f, a, p: f.set_limit(a, p["currency"], str(p["per_payment"]), str(p["daily"]))),
    "add_route": (("send", "receive"), (), lambda f, a, p: f.add_route(a, p["send"], p["receive"])),
    "toggle_route": (("route_id", "enabled"), (), lambda f, a, p: f.update_route(a, p["route_id"], _bool(p["enabled"]), None)),
    "confirm_template": (("template_id",), (), lambda f, a, p: f.confirm_template(a, p["template_id"])),
    "set_bank_pricing": (("bank", "source", "target"), ("rate", "fee_send", "fee_pct", "intermediary", "fee_receive"),
                         lambda f, a, p: f.set_bank_pricing(a, p["bank"], p["source"], p["target"], {k: p.get(k) for k in ("rate", "fee_send", "fee_pct", "intermediary", "fee_receive")})),
    "set_motivation": (("enabled",), ("celebrate",), lambda f, a, p: f.set_motivation(a, _bool(p["enabled"]), _bool(p.get("celebrate", True)))),
    "dismiss_reminder": (("reminder_id",), (), lambda f, a, p: f.dismiss(a, int(p["reminder_id"]))),
    "fund_sandbox": (("currency", "amount"), (), lambda f, a, p: f.fund(a, p["currency"], str(p["amount"]))),
    "cancel_payment": (("transfer_id",), (), lambda f, a, p: f.cancel(a, p["transfer_id"])),
}


def _bool(v):
    return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")


def _ids(v):
    return [str(x) for x in (v if isinstance(v, list) else str(v).split(","))][:100]


def _minor(amount, currency):
    from decimal import Decimal, InvalidOperation
    from .domain import to_minor
    try:
        value = Decimal(str(amount).replace(",", ""))
    except InvalidOperation:
        raise Denied("amount must be a number", "action_invalid", field="amount") from None
    if not value.is_finite() or value <= 0:
        raise Denied("amount must be positive", "action_invalid", field="amount")
    return to_minor(value, currency.upper())


def _email(f, actor, p):
    s = f.email_settings()
    if p["digest"] != "off" and not (p.get("address") or s["address"]):
        raise Denied("add the email address the digest should go to", "email_address_needed")
    return f.set_email(actor, p.get("address") or s["address"], p["digest"], _bool(p.get("reminders", s["reminders"])), s["language"],
                       int(p.get("weekday", s.get("weekday", 0))), _bool(p.get("skip_quiet", s.get("skip_quiet", True))))


def check(action, params):
    """Shape check when the assistant proposes; the service validates the values again when you confirm."""
    if action not in ACTIONS or not isinstance(params, dict):
        raise Denied("unknown action", "action_invalid", action=str(action)[:40])
    required, optional, _ = ACTIONS[action]
    missing = [k for k in required if params.get(k) in (None, "", [])]
    if missing:
        raise Denied("missing details: " + ", ".join(missing), "action_invalid", fields=missing)
    extra = set(params) - set(required) - set(optional)
    if extra:
        raise Denied("unknown details: " + ", ".join(sorted(extra)), "action_invalid", fields=sorted(extra))
    return {k: params[k] for k in (*required, *optional) if k in params}


def run(finance, actor, action, params):
    return ACTIONS[action][2](finance, actor, params)


def catalog():
    return {name: dict(required=list(r), optional=list(o)) for name, (r, o, _) in ACTIONS.items()}
