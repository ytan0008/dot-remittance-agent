"""Agent tool registry. Each tool is declared once: schema, kind of action and implementation together.

Each tool declares whether it only looks things up (view) or prepares something (prepare). The assistant can never
submit or approve payments, raise limits or change recipients directly; the service enforces that again.
To add a tool: write a function below and decorate it with @tool(...).
"""
from dataclasses import dataclass
from .domain import digest, request_id

S = {"type": "string"}
PAIR = {"source": {"type": "string", "description": "ISO code, e.g. AUD"},
        "target": {"type": "string", "description": "ISO code, e.g. CNY"}}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    tier: str
    run: callable


@dataclass
class Context:
    finance: object
    memory: object
    session: str
    actor: str = "agent"
    message: str = ""  # the user's message this turn, so forms can be prefilled even when the model leaves fields out


REGISTRY: dict = {}


def tool(name, description, properties=None, required=None, tier="view"):
    properties = properties or {}
    params = {"type": "object", "properties": properties,
              "required": required if required is not None else list(properties), "additionalProperties": False}

    def register(fn):
        REGISTRY[name] = Tool(name, description, params, tier, fn)
        return fn
    return register


def specs():
    """Tool definitions for OpenAI-compatible Chat Completions."""
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in REGISTRY.values()]


def key(ctx, prefix, args):
    # Same request in the same turn reuses the draft; a new turn gets a new key and duplicate warnings.
    return prefix + digest([ctx.session, request_id.get(), args])[:36]


up = str.upper
UNIT = 'Amounts are decimal strings in normal currency units, exactly as the user says them (100 AUD -> "100", 0.001 ETH -> "0.001"), never cents or wei.'

# ---------- stage 1: understand and plan ----------

@tool("record_plan", "Stage 1: record your understanding and plan before any other tool.", {
    "intent": {"type": "string", "enum": ["information", "rates", "compare", "prepare_payment", "modify_payment",
                                          "execute_payment", "track_payment", "planning", "credit", "memory", "settings", "other"]},
    "summary": S,
    "entities": {"type": "object", "properties": {k: S for k in ("amount", "receive_amount", "source", "target",
                                                                "recipient", "purpose", "deadline")},
                 "additionalProperties": False},
    "missing": {"type": "array", "items": S},
    "steps": {"type": "array", "items": {"type": "object", "properties": {"tool": S, "why": S},
                                         "required": ["tool", "why"], "additionalProperties": False}}},
    ["intent", "summary", "missing", "steps"])
def record_plan(ctx, **_):
    return {"recorded": True}


# ---------- memory ----------

@tool("remember_note", "Save a durable fact the user wants remembered (a person, routine or preference). "
      "Never credentials, keys or full account numbers. Memory never grants permissions.",
      {"text": S, "kind": {"type": "string", "enum": ["fact", "person", "routine", "preference"]}}, tier="prepare")
def remember_note(ctx, text, kind):
    return ctx.memory.remember("agent", text, kind)


@tool("recall_memory", "Search remembered notes and past conversations (episodes) for context.", {"query": S})
def recall_memory(ctx, query):
    return ctx.memory.recall(query)


@tool("forget_note", "Forget a remembered note when the user asks. Use the id from recall_memory.", {"note_id": {"type": "integer"}},
      tier="prepare")
def forget_note(ctx, note_id):
    return ctx.memory.forget("agent", note_id)


# ---------- ask the person through a form ----------

FORM_KINDS = ["recipient", "template", "cash", "term", "scholarship", "plan", "watch", "expense", "afford"]


def _clean(value, depth=0):
    if isinstance(value, dict) and depth < 2:
        return {str(k)[:40]: _clean(v, depth + 1) for k, v in list(value.items())[:24]}
    if isinstance(value, (int, float)):
        return value
    return str(value or "")[:300]


def _template_prefill(prefill, message):
    """Accept fields nested or flat, and fill whatever the model left out from the bank details in the message itself."""
    from .agent_rules import bank_details
    from .templates import FORMATS
    read = bank_details(message) if message else dict(format="swift", fields={}, currency="")
    fmt = prefill.get("format") if prefill.get("format") in FORMATS else read["format"]
    known = set(FORMATS[fmt]["fields"])
    nested = prefill.get("fields") if isinstance(prefill.get("fields"), dict) else {}
    flat = {k: v for k, v in prefill.items() if k in known}
    ours = read["fields"] if read["format"] == fmt else {k: v for k, v in read["fields"].items() if k in known}
    fields = {k: v for k, v in {**ours, **flat, **nested}.items() if k in known and v}
    out = dict(format=fmt, fields=fields, currency=prefill.get("currency") or read["currency"])
    if prefill.get("name"):
        out["name"] = prefill["name"]
    return out


@tool("request_details", "When you need details only the user can give, call this instead of asking in text. The app pops up a "
      "form beside the chat, prefilled with what you already know; the user completes it and the conversation continues. "
      "kind: recipient (name, currency, country) | template (bank details: format swift|sepa|au_bsb|uk_fps|us_ach|cn_cnaps|in_neft, "
      "name, fields such as beneficiary_name, beneficiary_address, account, bic, bank_name, bsb, account_number, sort_code, "
      "routing_number, ifsc, cnaps, reference, purpose_code; currency) | cash (currency, amount) | term (name, currency, start, "
      "end, tuition, tuition_due, living, income) | scholarship (name, provider, amount, currency, deadline, documents) | "
      "plan (an exchange plan: source, target, amount, side receive|spend, due, purpose, min_rate; watch is an alias) | "
      "expense (text) | afford (amount, currency, label). "
      "Fill prefill with everything you can read from the conversation; leave unknown fields out. Changes nothing by itself.",
      {"kind": {"type": "string", "enum": FORM_KINDS}, "prefill": {"type": "object"}, "reason": S})
def request_details(ctx, kind, prefill, reason):
    if kind not in FORM_KINDS:
        raise ValueError("unknown form")
    extra = dict(existing=[r["id"] for r in ctx.finance.recipients()]) if kind == "recipient" else {}
    prefill = prefill if isinstance(prefill, dict) else {}
    if kind == "template":
        prefill = _template_prefill(prefill, ctx.message)
    return dict(form=kind, prefill=_clean(prefill), reason=str(reason or "")[:200], **extra,
                note="Form shown to the user. Do not ask for these details again in text; wait for their next message.")


# ---------- spending ----------

@tool("log_expense", "Log spending from short text such as 'lunch 12.50', '午饭40澳刀' or '午饭10澳元 打车25' (several at once). Saved as pending; "
      "the student confirms it on the Spending page.", {"text": S}, tier="prepare")
def log_expense(ctx, text):
    entry = ctx.finance.parse_quick(text)
    saved = [ctx.finance.add_expense(ctx.actor, e["date"], e["amount"], e["currency"], e["description"], e["category"], source="agent")
             for e in entry["items"]]
    return dict(saved[0], logged=len(saved)) if len(saved) == 1 else dict(saved[0], logged=len(saved), entries=saved)


@tool("spending_summary", "Confirmed spending by category for a month (YYYY-MM, empty for this month), versus last month.",
      {"month": S})
def spending_summary(ctx, month):
    return ctx.finance.spending_summary(month or None)


# ---------- student money ----------

def _lang(ctx):
    return ctx.finance.memory().get("language") or "en"


@tool("afford_check", "“Can I afford this?” — checks a purchase against cash, the term plan, upcoming costs (tuition, bills), the "
      "safety buffer and this month's budget. Verdict yes/careful/no with reasons and the earliest safer date. date: YYYY-MM-DD or "
      "empty for today. payer: me (own money, default) or other (someone else pays, e.g. a parent's card: only the monthly budget decides). " + UNIT,
      {"amount": S, "currency": S, "date": S, "label": S, "payer": S}, ["amount", "currency"])
def afford_check(ctx, amount, currency, date="", label="", payer="me"):
    r = ctx.finance.afford(ctx.actor, amount, up(currency) or None, date or None, label, payer if payer in ("me", "other") else "me")
    r.pop("series", None)
    return r


@tool("cashflow_plan", "Term-based cash-flow projection: opening cash, monthly income, living costs, tuition and extras, closing "
      "balance per month, the lowest point and any shortfall. currency empty = the plan's currency.", {"currency": S}, [])
def cashflow_plan(ctx, currency=""):
    r = ctx.finance.cashflow(up(currency) or None)
    r.pop("daily", None)
    return r


@tool("spending_insights", "Weekly or monthly spending summary with personalized, actionable suggestions (already written in the "
      "user's language).", {"period": {"type": "string", "enum": ["week", "month"]}})
def spending_insights(ctx, period):
    return ctx.finance.spending_insights(period, _lang(ctx))


@tool("list_scholarships", "Tracked scholarships and grants: status, deadline, days left and document checklist progress.")
def list_scholarships(ctx):
    return ctx.finance.scholarships()


@tool("track_scholarship", "Start tracking a scholarship or grant application for the student. amount in normal units (may be "
      "empty); deadline YYYY-MM-DD; documents: names of required documents.",
      {"name": S, "provider": S, "amount": S, "currency": S, "deadline": S, "documents": {"type": "array", "items": S}},
      ["name"], tier="prepare")
def track_scholarship(ctx, name, provider="", amount="", currency="", deadline="", documents=None):
    return ctx.finance.add_scholarship(ctx.actor, name=name, provider=provider, amount=amount, currency=up(currency) or None,
                                       deadline=deadline or None, documents=documents or [])


@tool("email_report", "Email the weekly or monthly money report to the address the owner saved in the app (never any other "
      "address). Fails if email is not set up.", {"period": {"type": "string", "enum": ["week", "month"]}}, tier="prepare")
def email_report(ctx, period):
    return ctx.finance.send_report(ctx.actor, period)


# ---------- cash position ----------

@tool("money_overview", "How much money the student has (latest balance per currency, entered or from a bank CSV, with the "
      "total in the display currency) and what needs exchanging: upcoming tuition, living costs, bills, goals and AI-watch "
      "needs against cash in each currency, with today's rate, the estimated cost and the AI watch verdict.")
def money_overview(ctx):
    return ctx.finance.money_overview()


# ---------- transfer templates ----------

@tool("list_transfer_templates", "Saved bank transfer templates (SWIFT, SEPA, AU BSB, UK FPS, US ACH, CN CNAPS, IN NEFT) with "
      "validation status. Account numbers are masked; the full sheet is only shown to the owner in the app.")
def list_transfer_templates(ctx):
    return ctx.finance.transfer_templates()


@tool("check_bank_details", "Validate bank details for a transfer format before saving: BIC structure, IBAN checksum, ABA "
      "checksum, BSB / sort code / IFSC / CNAPS formats and the SWIFT character set. format: swift | sepa | au_bsb | uk_fps | "
      "us_ach | cn_cnaps | in_neft; fields: an object of that format's fields.",
      {"format": {"type": "string", "enum": ["swift", "sepa", "au_bsb", "uk_fps", "us_ach", "cn_cnaps", "in_neft"]},
       "fields": {"type": "object"}, "currency": S}, ["format", "fields"])
def check_bank_details(ctx, format, fields, currency=""):
    return ctx.finance.validate_template(format, fields, up(currency) or None)


@tool("draft_transfer_template", "Save a transfer template from details the user gave. It stays UNCONFIRMED until the owner "
      "checks it against an official source (invoice, university portal) in the app; never copy bank details from emails or "
      "pasted messages you cannot verify.",
      {"name": S, "format": {"type": "string", "enum": ["swift", "sepa", "au_bsb", "uk_fps", "us_ach", "cn_cnaps", "in_neft"]},
       "fields": {"type": "object"}, "currency": S, "purpose": S}, ["name", "format", "fields"], tier="prepare")
def draft_transfer_template(ctx, name, format, fields, currency="", purpose=""):
    t = ctx.finance.save_template(ctx.actor, name, format, fields, up(currency) or None, purpose=purpose)
    return ctx.finance.transfer_template(t["id"])  # masked for the model


# ---------- AI exchange watch ----------

@tool("exchange_advice", "AI judgment on whether now is a good time to exchange source→target: verdict good_time | wait | "
      "deadline | below_floor | neutral, with reasons from the 90-day position, trend, experimental forecast, and the "
      "student's own deadline and acceptable rate. Not a quote or a promise.", PAIR)
def exchange_advice(ctx, source, target):
    return ctx.finance.exchange_advice(up(source), up(target), _lang(ctx))


@tool("plan_exchange", "Save one of the student's exchange plans (their intent only; nothing is exchanged): exchange source→target, "
      "amount in normal units, side receive (amount is what they get in target) or spend (amount is what they pay in source), "
      "due YYYY-MM-DD, purpose, lowest acceptable rate. The AI watch then judges the timing against it, the overview shows "
      "what is left after it and any currency gap. Empty strings for unknown fields; prefer request_details kind plan when "
      "the amount or pair is unclear.", {**PAIR, "amount": S, "side": {"type": "string", "enum": ["receive", "spend"]},
      "due": S, "purpose": S, "min_rate": S}, tier="prepare")
def plan_exchange(ctx, source, target, amount, side="receive", due="", purpose="", min_rate=""):
    return ctx.finance.save_plan(ctx.actor, up(source), up(target), amount, side or "receive", due or None, purpose, "custom", None, min_rate or None)


@tool("bank_scenarios", "Exchange scenarios through real banks: for an amount source→target, combine a sending bank and a receiving "
      "bank (an id or a name: cba, westpac, nab, anz, boc_au = Bank of China Australia/澳洲中行, boc = Bank of China in China/中国银行, "
      "icbc, ccb, cmb, hsbc, wise; empty for any with known pricing), convert at either side, pay at once or in two parts; "
      "counts each bank's published rate and wire fees and names the unknown ones. mode send|receive. due = the date the money "
      "must arrive (YYYY-MM-DD, empty if none): arrival time is counted and late scenarios are flagged. Each scenario has a tier: "
      "only tier 'sourced' with rank 1 may be called the best; 'partial' (fees unknown), 'estimate' (AI's own estimate) and "
      "'reference' are for reference only — say so. Fees are listed per currency; never add different currencies together. "
      "Public information, not a quote.",
      {**PAIR, "amount": S, "mode": {"type": "string", "enum": ["send", "receive"]}, "send_bank": S, "receive_bank": S, "due": S})
def bank_scenarios(ctx, source, target, amount, mode="send", send_bank="", receive_bank="", due=""):
    r = ctx.finance.exchange_scenarios(up(source), up(target), amount, mode, send_bank or None, receive_bank or None, due or None)
    return dict(r, scenarios=r["scenarios"][:5])


@tool("wait_or_now", "Is waiting worth it, in money? For an amount: side spend = the student converts this much of source; "
      "receive = they need this much of target. Returns the chance that waiting until the 7-day forecast date is better, the "
      "expected / best / worst outcome in the source currency (80% interval), where today sits in the last 90 days, and "
      "whether the forecast beats the unchanged-rate baseline (say so when it does not). bank: optional id or name for the "
      "bank's own rate; due: must-arrive date or empty. Not a promise.",
      {**PAIR, "amount": S, "side": {"type": "string", "enum": ["spend", "receive"]}, "bank": S, "due": S})
def wait_or_now(ctx, source, target, amount, side="spend", bank="", due=""):
    from .banks import find_bank
    return ctx.finance.wait_value(up(source), up(target), amount, side, find_bank(bank, up(source)) if bank else None, due or None)


@tool("simulate_exchange", "The sandbox: apply the student's exchange plans to their balances in numbers only and show what each "
      "currency would hold afterwards, the gaps against upcoming needs and the safety buffer, and optionally pretend money "
      "(extra: list of {currency, amount}, negative to take away) or a rate shift in percent (negative = worse). Nothing is "
      "exchanged or saved.", {"extra": {"type": "array", "items": {"type": "object", "properties": {"currency": S, "amount": S},
                                                                    "required": ["currency", "amount"], "additionalProperties": False}},
                              "rate_shift": S})
def simulate_exchange(ctx, extra=None, rate_shift="0"):
    clean = [dict(currency=str(x.get("currency", "")), amount=str(x.get("amount", ""))) for x in (extra or []) if isinstance(x, dict)]
    r = ctx.finance.simulate(None, clean, rate_shift or "0")
    return dict(r, gaps=[dict(currency=x["currency"], before=x["before"], after=x["after"], need=x["need"], buffer=x["buffer"],
                              gap_after=x["gap_after"], due=x["due"]) for x in r["rows"]])


# ---------- motivation ----------

@tool("progress_overview", "The student's encouraging progress: money-skill level and criteria for the next one, badges, the "
      "forgiving check-in streak, active challenges and suggested ones. Never compares students or ranks by money.")
def progress_overview(ctx):
    r = ctx.finance.motivation()
    r.pop("celebrations", None)
    return r


@tool("start_challenge", "Start a short, opt-in 7-day challenge the student asked for. kind: log_5_days | clear_review | plan_term | "
      "one_document | review_subs | no_spend_day | set_aside (amount in normal units, small and only if it fits the budget).",
      {"kind": {"type": "string", "enum": ["log_5_days", "clear_review", "plan_term", "one_document", "review_subs", "no_spend_day",
                                           "set_aside"]}, "amount": S}, ["kind"], tier="prepare")
def start_challenge(ctx, kind, amount=""):
    return ctx.finance.start_challenge(ctx.actor, kind, amount or None)


# ---------- read-only facts (T1) ----------

@tool("get_balances", "Ledger balances per currency: total, reserved, available. Sandbox is simulated test funds.")
def get_balances(ctx):
    return ctx.finance.balances()


@tool("reference_equivalents", "Reference equivalents of balances in a display currency. Not a conversion.", {"display": S})
def reference_equivalents(ctx, display):
    return ctx.finance.equivalents(up(display))


@tool("list_recipients", "Owner-managed recipients with their rail (sandbox/evm) and receiving currency.")
def list_recipients(ctx):
    return ctx.finance.recipients()


@tool("list_payments", "Payment history including drafts, approvals, submissions and outcomes.",
      {"status": {"type": "string", "enum": ["", "draft", "approved", "pending", "unknown", "completed", "failed", "cancelled"]}}, [])
def list_payments(ctx, status=""):
    return [{k: t[k] for k in ("id", "status", "rail", "created", "reference")} | {
        "amount": t["details"]["amount"], "source": t["details"]["source"], "target": t["details"]["target"],
        "recipient": t["details"]["recipient"]["id"], "purpose": t["details"]["purpose"]}
        for t in ctx.finance.history(status=status or None, limit=30)]


@tool("get_payment", "One payment with exact details, approval digest and guardrail results.", {"transfer_id": S})
def get_payment(ctx, transfer_id):
    return ctx.finance.get(transfer_id)


@tool("list_routes", "Regional routes and their verified capabilities.")
def list_routes(ctx):
    return ctx.finance.routes()


@tool("latest_rate", "Latest daily reference rate with source, observation date and recent change.", PAIR)
def latest_rate(ctx, source, target):
    return ctx.finance.rates.latest(up(source), up(target))


@tool("rate_history", "Historical statistics for 30/90/365 days: min, max, average, percentile, position.",
      {**PAIR, "days": {"type": "string", "enum": ["30", "90", "365"]}})
def rate_history(ctx, source, target, days):
    return ctx.finance.rates.fetch(up(source), up(target), days)


@tool("forecast_rate", "Experimental 7-day forecast with backtest errors vs unchanged-rate baseline, or unavailable.", PAIR)
def forecast_rate(ctx, source, target):
    return ctx.finance.rates.forecast(up(source), up(target))


@tool("compare_options", "Compare reference calculation, simulated options and the sandbox quote. Give amount OR receive_amount. " + UNIT,
      {**PAIR, "amount": S, "receive_amount": S, "rank": {"type": "string", "enum": ["receive", "speed"]}}, ["source", "target", "rank"])
def compare_options(ctx, source, target, rank, amount="", receive_amount=""):
    return ctx.finance.compare(ctx.actor, up(source), up(target), amount or None, receive_amount or None, rank)


@tool("scenario", "Hypothetical: effect of the rate moving by rate_change_pct (negative = less favorable). " + UNIT,
      {**PAIR, "amount": S, "rate_change_pct": S})
def scenario(ctx, source, target, amount, rate_change_pct):
    return ctx.finance.scenario(ctx.actor, up(source), up(target), amount, rate_change_pct)


@tool("goals_overview", "Payment goals with completed vs planned progress and deadlines.")
def goals_overview(ctx):
    return ctx.finance.goals()


@tool("goal_plan", "One-time vs installment plan and budget impact for a goal.", {"goal_id": S, "installments": {"type": "integer"}})
def goal_plan(ctx, goal_id, installments):
    return ctx.finance.goal_plan(ctx.actor, goal_id, installments)


@tool("habits_overview", "Obligations and the internal payment-habit indicator (not a credit score).")
def habits_overview(ctx):
    return dict(indicator=ctx.finance.habits(), obligations=ctx.finance.obligations())


@tool("reminders", "Active reminders: deadlines, quote expiry, unresolved payments, insufficient funds, rate targets.")
def reminders(ctx):
    ctx.finance.refresh_reminders()
    return ctx.finance.reminders()


# ---------- prepare and modify (T2) ----------

@tool("prepare_payment", "Create an immutable quote/draft. Does not authorize or spend. Give amount (what is sent) OR receive_amount "
      "(what the recipient must get). " + UNIT + " "
      "",
      {"amount": S, "receive_amount": S, **PAIR, "recipient_id": S, "purpose": S, "arrival_by": S, "goal_id": S},
      ["source", "target", "recipient_id", "purpose"], tier="prepare")
def prepare_payment(ctx, source, target, recipient_id, purpose, amount="", receive_amount="", arrival_by="", goal_id=""):
    args = dict(source=source, target=target, recipient_id=recipient_id, purpose=purpose, amount=amount,
                receive_amount=receive_amount, arrival_by=arrival_by, goal_id=goal_id)
    return ctx.finance.prepare(ctx.actor, amount or None, up(source), up(target), recipient_id, purpose, key(ctx, "agent-", args),
                               receive_amount or None, arrival_by or None, goal_id or None)


@tool("modify_payment", "Change a draft: creates a new draft, voids any approval on the old one. " + UNIT,
      {"transfer_id": S, "amount": S, "receive_amount": S, "purpose": S, "recipient_id": S}, ["transfer_id"], tier="prepare")
def modify_payment(ctx, transfer_id, amount="", receive_amount="", purpose="", recipient_id=""):
    args = dict(transfer_id=transfer_id, amount=amount, receive_amount=receive_amount, purpose=purpose, recipient_id=recipient_id)
    return ctx.finance.modify(ctx.actor, transfer_id, key(ctx, "agent-mod-", args), amount or None, receive_amount or None,
                              purpose or None, recipient_id or None)


@tool("reconcile_payment", "Query the outcome of a submitted payment. Never creates a second payment.", {"transfer_id": S},
      tier="prepare")
def reconcile_payment(ctx, transfer_id):
    return ctx.finance.reconcile(ctx.actor, transfer_id)


@tool("propose_change", "Propose a change the owner must confirm. kind: recipient|preference|obligation|rate_alert.",
      {"kind": {"type": "string", "enum": ["recipient", "preference", "obligation", "rate_alert"]},
       "payload": {"type": "object"}, "reason": S}, tier="prepare")
def propose_change(ctx, kind, payload, reason):
    return ctx.finance.propose(ctx.actor, kind, payload, reason)


def _action_help():
    from .actions import catalog
    return "; ".join(f"{k}({', '.join(v['required'])}{' | ' + ', '.join(v['optional']) if v['optional'] else ''})" for k, v in catalog().items())


@tool("do_action", "Get something done in the app for the user: it shows as an action card in the chat and runs only when the "
      "owner presses Confirm. Use it for every change to their records instead of telling them where to click. "
      "Actions (required | optional params): " + _action_help() + ". Ids come from read_records. Amounts are decimal strings in normal "
      "units; dates YYYY-MM-DD; cadence weekly|monthly; bill recurring none|monthly; budget kind income|expense|buffer; plan status "
      "done|cancelled; digest off|daily|weekly|monthly; expense_ids a comma-separated string. Payments are not actions: prepare a draft "
      "and the user authorizes and submits it in the payment screen.",
      {"action": {"type": "string", "enum": sorted(__import__("finance.actions", fromlist=["ACTIONS"]).ACTIONS)},
       "params": {"type": "object"}, "summary": S}, tier="prepare")
def do_action(ctx, action, params, summary):
    p = ctx.finance.propose(ctx.actor, "action", dict(action=action, params=params if isinstance(params, dict) else {}), summary)
    return dict(p, for_assistant="Shown to the user with a Confirm button; it runs only when they confirm. Do not claim it is done yet.")


RECORDS = ["fx_rules", "accounts", "bills", "recurring", "budget", "terms", "plans", "scholarships", "pending_expenses", "recent_expenses", "cash",
           "templates", "recipients", "reminders", "limits", "routes", "email", "banks"]


@tool("read_records", "Read the user's records with their ids, to answer questions or to refer to them in do_action. "
      "kind: " + "|".join(RECORDS) + ". For banks also give source and target currency (else empty).",
      {"kind": {"type": "string", "enum": RECORDS}, "source": S, "target": S})
def read_records(ctx, kind, source="", target=""):
    f = ctx.finance
    if kind == "bills":
        return [dict(id=o["id"], title=o["title"], amount=o["amount"], currency=o["currency"], due_date=o["due_date"], state=o["state"],
                     recurring=o.get("recurring")) for o in f.obligations()]
    if kind == "recurring":
        return f.recurring_list()
    if kind == "budget":
        return f.budget()
    if kind == "terms":
        return f.terms()
    if kind == "plans":
        return [{k: p[k] for k in ("id", "source", "target", "amount", "amount_currency", "due", "purpose", "status", "receive", "spend", "sent")
                 if k in p} for p in f.exchange_plans()]
    if kind == "scholarships":
        return [{k: s[k] for k in ("id", "name", "status", "deadline", "amount", "currency") if k in s} for s in f.scholarships()]
    if kind in ("pending_expenses", "recent_expenses"):
        rows = f.expenses(status="pending" if kind == "pending_expenses" else "confirmed", limit=40)
        return [{k: e[k] for k in ("id", "date", "amount", "currency", "description", "category") if k in e} for e in rows]
    if kind == "cash":
        return f.cash_position()
    if kind == "templates":
        return f.transfer_templates()
    if kind == "recipients":
        return f.recipients()
    if kind == "reminders":
        return [dict(id=r["id"], kind=r["kind"], data=r["data"], severity=r["severity"]) for r in f.reminders()[:30]]
    if kind == "limits":
        return f.limits()
    if kind == "routes":
        return [dict(id=r["id"], send=r["send"], receive=r["receive"], enabled=r["enabled"]) for r in f.routes()]
    if kind == "email":
        s = f.email_settings()
        return {k: s[k] for k in ("configured", "digest", "weekday", "reminders", "skip_quiet") if k in s}
    if kind == "banks":
        return f.banks(up(source) or None, up(target) or None)
    if kind == "accounts":
        return f.accounts()
    if kind == "fx_rules":
        return f.fx_rules()
    raise ValueError("unknown kind")


@tool("sandbox_timeline", "The dated sandbox: balances today, then day by day what plans, goals, bills, subscriptions, term costs "
      "would do over the next days (30-180). off: comma-separated source keys to leave out (from a previous result). Numbers only.",
      {"days": S, "off": S})
def sandbox_timeline(ctx, days="90", off=""):
    r = ctx.finance.timeline(None, [x for x in str(off or "").split(",") if x], None, int(days or 90))
    return dict(r, events=r["events"][:40])


