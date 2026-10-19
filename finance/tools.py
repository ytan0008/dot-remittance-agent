"""Agent tool registry. Each tool is declared once: schema, permission tier and implementation together.

Tiers: view (T1), prepare (T2), submit (T3). The service enforces them again server-side; a tool can never
approve payments, grant mandates, raise limits or change recipients directly.
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


@tool("wallet_info", "The agent's own on-chain wallet: address, chain, balance and active mandates.")
def wallet_info(ctx):
    return ctx.finance.wallet()


@tool("list_mandates", "Owner-granted spending scopes for the agent wallet. Never grants anything.")
def list_mandates(ctx):
    return ctx.finance.mandates()


# ---------- prepare and modify (T2) ----------

@tool("prepare_payment", "Create an immutable quote/draft. Does not authorize or spend. Give amount (what is sent) OR receive_amount "
      "(what the recipient must get). " + UNIT + " "
      "Use source=target=ETH for the agent wallet.",
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


@tool("propose_change", "Propose a change the owner must confirm. kind: recipient|preference|goal|obligation|rate_alert.",
      {"kind": {"type": "string", "enum": ["recipient", "preference", "goal", "obligation", "rate_alert"]},
       "payload": {"type": "object"}, "reason": S}, tier="prepare")
def propose_change(ctx, kind, payload, reason):
    return ctx.finance.propose(ctx.actor, kind, payload, reason)


# ---------- submit (T3) ----------

@tool("execute_payment", "Submit a payment the owner approved, or an agent-wallet payment covered by mandate_id.",
      {"transfer_id": S, "mandate_id": S}, ["transfer_id"], tier="submit")
def execute_payment(ctx, transfer_id, mandate_id=""):
    return ctx.finance.execute(ctx.actor, transfer_id, mandate_id or None)
