import json
import re
import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from functools import wraps
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .domain import Config, Denied, canonical, digest, now, units, decimals, mask
from .store import Store
from .providers import SandboxProvider, EvmProvider
from .rates import Rates
from .regions import SEED_ROUTES, ECONOMIES, route_body
from .planning import PlanningMixin
from .habits import HabitsMixin
from .expenses import ExpensesMixin
from .student import StudentMixin
from .motivation import MotivationMixin
from .watch import WatchMixin
from .templates import TemplatesMixin
from .money import MoneyMixin
from .plans import PlansMixin, TimelineMixin
from .banks import BanksMixin
from .bank_kb import BankKnowledgeMixin
from .decide import DecideMixin

ACTIVE = ("pending", "unknown")
FINAL = ("completed", "failed", "cancelled", "superseded")
LANGUAGES = ("en", "zh-CN", "zh-TW", "vi", "ja", "ko")
PREFERENCES = ("language", "display_currency", "payment_goal", "deadline", "home_region", "receive_region", "time_zone")


def audited(method):
    @wraps(method)
    def wrapped(self, actor, *args, **kwargs):
        try:
            return method(self, actor, *args, **kwargs)
        except Denied as exc:
            params = {k: v for k, v in exc.params.items() if k != "ref"}
            if not getattr(exc, "audited", False):
                self.audit_denial(actor, method.__name__, exc.params.get("ref"), str(exc), code=exc.code, **params)
                exc.audited = True
            raise
    return wrapped


TEST_RECIPIENTS = {"ui-acceptance"}


SELF_ID = re.compile(r"me(-[a-z]{3}(-\d{1,2})?)?")  # your own accounts: "me", "me-cny", "me-cny-2"

class Finance(PlanningMixin, HabitsMixin, ExpensesMixin, StudentMixin, MotivationMixin, WatchMixin, TemplatesMixin, MoneyMixin, PlansMixin, TimelineMixin, BanksMixin, BankKnowledgeMixin, DecideMixin):
    """Single-tenant service. Authorization is derived by the server, never taken from model input."""

    def __init__(self, config=None, provider=None, rates=None):
        self.config = config or Config.env()
        self.store = Store(self.config.db)
        self._money_schema()
        self._plans_schema()
        self._banks_schema()
        self._expenses_schema()
        self._student_schema()
        self._motivation_schema()
        self._watch_schema()
        self._templates_schema()
        self._decide_schema()
        self.rates = rates or Rates()
        self.sandbox = SandboxProvider(self.store, self.rates, self.config.sandbox_settle_seconds)
        self.evm, self.evm_error = provider, None
        if self.evm is None and self.config.rpc_url:
            try:
                self.evm = EvmProvider(self.config)
            except Denied as exc:
                self.evm_error = str(exc)
            except Exception:
                self.evm_error = "agent wallet could not be loaded; check keystore and password"
        with self.store.tx() as c:
            if self.evm:
                # A database is permanently bound to one agent wallet and chain.
                identity = canonical(dict(chain=self.config.chain_id, wallet=self.evm.account.address))
                existing = c.execute("SELECT value FROM memories WHERE key='_evm_identity'").fetchone()
                if existing and existing[0] != identity:
                    self.evm, self.evm_error = None, "this database is bound to a different wallet or chain; use a separate database"
                else:
                    c.execute("INSERT OR IGNORE INTO memories VALUES ('_evm_identity',?,?)", (identity, now()))
            # New seed routes appear on upgrade; routes the owner already configured keep their settings.
            for send, receive, payments in SEED_ROUTES:
                body = route_body(send, receive)
                c.execute("INSERT OR IGNORE INTO routes(id,body,payments_enabled) VALUES (?,?,?)", (body["id"], canonical(body), int(payments)))
            # Recipients from the first release were AUD->CNY sandbox payees or EVM addresses.
            for r in c.execute("SELECT * FROM recipients").fetchall():
                body = json.loads(r["body"])
                if "rail" not in body:
                    body.update(rail="evm" if body.get("address") else "sandbox")
                    if body["rail"] == "sandbox":
                        body.setdefault("currency", "CNY")
                    c.execute("UPDATE recipients SET body=? WHERE id=?", (canonical(body), r["id"]))

    # ---------- roles ----------
    @staticmethod
    def owner(actor):
        if actor != "owner":
            raise Denied("owner authorization required", "owner_required")

    def require(self, actor, need):
        """The assistant may look things up and prepare drafts; only a person ever submits a payment."""
        if actor in ("owner", "system"):
            return
        if actor == "viewer" and need == "view":
            return
        if actor == "agent":
            if need == "submit":
                raise Denied("the assistant never submits payments; you submit them yourself in the payment screen",
                             "agent_cannot_submit")
            return
        raise Denied(f"{need} permission required", "permission_denied", need=need)

    def audit_denial(self, actor, action, correlation, reason, **detail):
        with self.store.tx() as c:
            self.store.event(c, actor, action, "denied", correlation, reason=reason, **detail)

    # ---------- settings ----------
    def limit_defaults(self):
        return {"AUD": (units(self.config.max_aud, 2), units(self.config.daily_aud, 2)),
                "USD": (35000, 70000),
                "CNY": (250000, 500000),
                "ETH": (units(self.config.max_eth, 18), units(self.config.daily_eth, 18))}

    def limits(self, c=None):
        def build(c):
            out = {}
            for currency, (per, daily) in self.limit_defaults().items():
                stored = json.loads(self.store.setting(c, "limit." + currency, "null") or "null") or {}
                out[currency] = dict(per_payment=str(stored.get("per_payment", per)), daily=str(stored.get("daily", daily)),
                                     ceiling_per_payment=str(per), ceiling_daily=str(daily), decimals=decimals(currency))
            return out
        if c is not None:
            return build(c)
        with self.store.read() as c:
            return build(c)

    def settings(self):
        return dict(limits=self.limits(), assistant="looks up, explains and prepares; never submits payments")

    @audited
    def set_limit(self, actor, currency, per_payment, daily):
        """Owner may tighten limits; raising beyond server ceilings requires changing server configuration."""
        self.owner(actor)
        defaults = self.limit_defaults()
        if currency not in defaults:
            raise Denied("no limit configured for this currency", "limit_currency")
        per, total = units(per_payment, decimals(currency)), units(daily, decimals(currency))
        if per > defaults[currency][0] or total > defaults[currency][1] or per > total:
            raise Denied("limits must stay within server ceilings and per-payment <= daily", "limit_ceiling")
        with self.store.tx() as c:
            c.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      ("limit." + currency, canonical(dict(per_payment=per, daily=total))))
            self.store.event(c, actor, "settings.limit", "ok", currency, per_payment=str(per), daily=str(total))
        return self.settings()

    # ---------- routes ----------
    def routes(self):
        with self.store.read() as c:
            rows = c.execute("SELECT * FROM routes ORDER BY id").fetchall()
        out = []
        for r in rows:
            body = json.loads(r["body"])
            supported = self.sandbox.supports(body["source"], body["target"])
            reference = json.loads(r["reference"]) if r["reference"] else None
            out.append(dict(body, enabled=bool(r["enabled"]), payments_enabled=bool(r["payments_enabled"]),
                            provider_supported=supported, reference_check=reference,
                            capabilities=dict(reference_rates=reference["available"] if reference else None,
                                              historical_analysis=reference["available"] if reference else None,
                                              simulated_comparison=reference["available"] if reference else None,
                                              sandbox_payment=bool(r["enabled"] and r["payments_enabled"] and supported))))
        return out

    def economies(self):
        return [dict(code=k, currency=v[0], languages=v[1], time_zones=v[2]) for k, v in ECONOMIES.items()]

    def route_for(self, c, source, target):
        rows = c.execute("SELECT * FROM routes WHERE enabled=1").fetchall()
        for r in rows:
            body = json.loads(r["body"])
            if body["source"] == source and body["target"] == target and r["payments_enabled"]:
                return body
        return None

    @audited
    def add_route(self, actor, send, receive):
        self.owner(actor)
        if send == receive:
            raise Denied("sending and receiving economies must differ", "route_invalid")
        body = route_body(send, receive)
        with self.store.tx() as c:
            c.execute("INSERT OR IGNORE INTO routes(id,body,payments_enabled) VALUES (?,?,0)", (body["id"], canonical(body)))
            self.store.event(c, actor, "route.add", "ok", body["id"])
        return next(r for r in self.routes() if r["id"] == body["id"])

    @audited
    def update_route(self, actor, route_id, enabled=None, payments_enabled=None):
        self.owner(actor)
        with self.store.tx() as c:
            row = c.execute("SELECT * FROM routes WHERE id=?", (route_id,)).fetchone()
            if not row:
                raise Denied("route not found", "route_unknown")
            body = json.loads(row["body"])
            if payments_enabled and not self.sandbox.supports(body["source"], body["target"]):
                raise Denied("provider does not support payments on this route", "route_unsupported")
            if enabled is not None:
                c.execute("UPDATE routes SET enabled=? WHERE id=?", (int(enabled), route_id))
            if payments_enabled is not None:
                c.execute("UPDATE routes SET payments_enabled=? WHERE id=?", (int(payments_enabled), route_id))
            self.store.event(c, actor, "route.update", "ok", route_id, enabled=enabled, payments_enabled=payments_enabled)
        return next(r for r in self.routes() if r["id"] == route_id)

    def verify_route(self, actor, route_id):
        self.require(actor, "view")
        with self.store.read() as c:
            row = c.execute("SELECT body FROM routes WHERE id=?", (route_id,)).fetchone()
        if not row:
            raise Denied("route not found", "route_unknown")
        body = json.loads(row[0])
        try:
            ref = self.rates.latest(body["source"], body["target"])
            result = dict(available=True, provider=ref["provider"], derived=ref["derived"], observed=ref["observed"], checked=now())
        except Denied as exc:
            result = dict(available=False, reason=str(exc), checked=now())
        with self.store.tx() as c:
            c.execute("UPDATE routes SET reference=? WHERE id=?", (canonical(result), route_id))
            self.store.event(c, actor, "route.verify", "ok" if result["available"] else "unavailable", route_id)
        return next(r for r in self.routes() if r["id"] == route_id)

    # ---------- recipients ----------
    @audited
    def add_recipient(self, actor, recipient_id, name, address="", enabled=True, currency="", country="", account="", kind="individual",
                      bank=""):
        self.owner(actor)
        if kind == "self" or SELF_ID.fullmatch(recipient_id or ""):
            raise Denied("your own accounts are added as \"me\" (add_own_account)", "recipient_reserved")
        body = self._recipient_body(recipient_id, name, address, currency, country, account, kind, bank)
        with self.store.tx() as c:
            c.execute("INSERT INTO recipients VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body,enabled=excluded.enabled",
                      (recipient_id, canonical(body), int(enabled)))
            self.store.event(c, actor, "recipient.update", "ok", recipient_id, rail=body["rail"],
                             address=mask(address), account=mask(account), enabled=enabled)
        return body

    def add_own_account(self, actor, currency, bank="", account="", country=""):
        """One of YOUR accounts (e.g. Bank of China in China, and in Australia): a payment to it is a move between your own
        accounts. Its name is always "me" and its ID "me-<currency>" (a second one in that currency gets -2, -3…)."""
        self.owner(actor)
        currency = (currency or "").upper()
        with self.store.tx() as c:
            taken = {r[0] for r in c.execute("SELECT id FROM recipients WHERE id LIKE 'me-%'")}
            base = "me-" + currency.lower()
            rid = next(x for x in [base] + [f"{base}-{n}" for n in range(2, 100)] if x not in taken)
            body = self._recipient_body(rid, "me", "", currency, country, account, "self", bank)
            c.execute("INSERT INTO recipients VALUES (?,?,1)", (rid, canonical(body)))
            self.store.event(c, actor, "recipient.self_add", "ok", rid, account=mask(account), bank=body.get("bank", ""))
        return body

    def remove_own_account(self, actor, recipient_id):
        self.owner(actor)
        if not SELF_ID.fullmatch(recipient_id or ""):
            raise Denied("not one of your own accounts", "recipient_invalid")
        with self.store.tx() as c:
            if not c.execute("DELETE FROM recipients WHERE id=?", (recipient_id,)).rowcount:
                raise Denied("account not found", "recipient_missing")
            self.store.event(c, actor, "recipient.self_remove", "ok", recipient_id)
        return self.recipients()

    def _recipient_body(self, recipient_id, name, address="", currency="", country="", account="", kind="individual", bank=""):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", recipient_id or "") or not (name or "").strip():
            raise Denied("invalid recipient ID or name", "recipient_invalid")
        if kind not in ("individual", "business", "self"):
            raise Denied("recipient type must be individual or business", "recipient_invalid")
        bank = re.sub(r"\s+", " ", str(bank or "")).strip()[:80]
        if address:
            from web3 import Web3
            if not Web3.is_address(address):
                raise Denied("invalid EVM address", "address_invalid")
            return dict(id=recipient_id, name=name.strip()[:100], address=Web3.to_checksum_address(address), rail="evm", kind=kind)
        if not re.fullmatch(r"[A-Z]{3}", currency or ""):
            raise Denied("sandbox recipient needs a receiving currency", "recipient_currency")
        if country and country not in ECONOMIES:
            raise Denied("unknown economy", "economy_unknown")
        if account and not re.fullmatch(r"[A-Za-z0-9 -]{4,34}", account):
            raise Denied("account reference must be 4-34 letters or digits", "recipient_account")
        out = dict(id=recipient_id, name=name.strip()[:100], address="", rail="sandbox", currency=currency,
                   country=country, account=account, kind=kind)
        if bank:  # the bank it is held at, and which bank in DOT's list that is (for rates and fees)
            from .banks import find_bank
            out.update(bank=bank, bank_id=find_bank(bank, currency))
        return out

    def recipients(self):
        with self.store.read() as c:
            return [{**json.loads(r["body"]), "enabled": bool(r["enabled"])} for r in c.execute("SELECT * FROM recipients")]

    # ---------- transfers ----------
    @staticmethod
    def _get(c, transfer_id):
        row = c.execute("SELECT * FROM transfers WHERE id=?", (transfer_id,)).fetchone()
        if not row:
            raise Denied("transfer not found", "transfer_unknown")
        return dict(row)

    @staticmethod
    def is_test(body):
        """Payments made by the automated acceptance tests: kept for the audit trail, hidden from the history."""
        purpose = str(body.get("purpose") or "").lower()
        return (body.get("recipient") or {}).get("id") in TEST_RECIPIENTS or purpose.startswith(("ui acceptance", "ui test"))

    def public(self, row):
        body = json.loads(row["body"])
        explorer = None
        if body.get("rail") == "evm" and row.get("reference"):
            base = {11155111: "https://sepolia.etherscan.io", 1: "https://etherscan.io"}.get(body.get("chain_id"))
            explorer = f"{base}/tx/{row['reference']}" if base else None
        return dict(id=row["id"], rail=row.get("rail") or body.get("rail", "sandbox"), status=row["status"], details=body,
                    approval_digest=digest(body), authorized_by=row["approval_actor"], mandate_id=row["mandate_id"],
                    reference=row["reference"], actual_cost=row["actual_cost"], created=row["created"],
                    submitted=row["submitted"], approved_at=row.get("approved_at"), completed_at=row.get("completed_at"),
                    supersedes=row.get("supersedes"), goal_id=row.get("goal_id"),
                    checks=json.loads(row["checks"]) if row.get("checks") else None, explorer=explorer, test=self.is_test(body))

    def get(self, transfer_id):
        with self.store.read() as c:
            return self.public(self._get(c, transfer_id))

    def history(self, status=None, rail=None, limit=200):
        with self.store.read() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM transfers ORDER BY created DESC, rowid DESC LIMIT ?", (limit,))]
        return [self.public(r) for r in rows if (not status or r["status"] == status) and (not rail or r.get("rail") == rail)]

    @audited
    def prepare(self, actor, amount, source, target, recipient_id, purpose, idempotency_key,
                receive_amount=None, arrival_by=None, goal_id=None, supersedes=None):
        self.require(actor, "prepare")
        amount = amount or None
        receive_amount = receive_amount or None
        if (amount is None) == (receive_amount is None):
            raise Denied("give exactly one of a sending amount or a target receiving amount", "amount_mode")
        if not (purpose or "").strip() or len(purpose) > 200 or not 1 <= len(idempotency_key or "") <= 100:
            raise Denied("purpose and idempotency key required", "purpose_required")
        if arrival_by:
            try:
                datetime.strptime(arrival_by, "%Y-%m-%d")
            except ValueError:
                raise Denied("arrival date must be YYYY-MM-DD", "date_invalid") from None
        request = canonical(dict(amount=amount, receive_amount=receive_amount, source=source, target=target,
                                 recipient_id=recipient_id, purpose=purpose, arrival_by=arrival_by, goal_id=goal_id))
        with self.store.tx() as c:
            old = c.execute("SELECT * FROM transfers WHERE idem=?", (idempotency_key,)).fetchone()
            if old:
                if old["request"] != request:
                    raise Denied("idempotency key reused with different details", "idempotency_conflict")
                return self.public(dict(old))
            r = c.execute("SELECT * FROM recipients WHERE id=? AND enabled=1", (recipient_id,)).fetchone()
            if not r:
                raise Denied("recipient must first be enabled by owner", "recipient_missing")
            recipient = json.loads(r["body"])
            if source == "ETH" or target == "ETH":
                if (source, target) != ("ETH", "ETH"):
                    raise Denied("on-chain rail only sends native ETH; no bridge or fiat off-ramp is connected", "route_unsupported")
                if not self.evm:
                    raise Denied("agent wallet rail is not connected", "evm_unavailable")
                if recipient["rail"] != "evm" or receive_amount:
                    raise Denied("on-chain payments need an EVM recipient and a sending amount", "recipient_rail")
                try:
                    body = self.evm.quote(recipient, purpose, amount)
                except Denied:
                    raise
                except Exception:
                    raise Denied("agent wallet RPC unavailable", "evm_unavailable") from None
                route_id = "onchain-eth"
            else:
                route = self.route_for(c, source, target)
                if not route:
                    raise Denied("no enabled payment route for this currency pair", "route_disabled")
                if recipient["rail"] != "sandbox" or recipient.get("currency") != target:
                    raise Denied("recipient does not receive this currency", "recipient_currency")
                body = self.sandbox.quote(source, target, recipient, purpose, amount, receive_amount)
                route_id = route["id"]
            tid = str(uuid.uuid4())
            body.update(quote_id=str(uuid.uuid4()), route_id=route_id, arrival_by=arrival_by, goal_id=goal_id)
            c.execute("INSERT INTO transfers(id,idem,request,body,status,created,rail,supersedes,goal_id) VALUES(?,?,?,?,?,?,?,?,?)",
                      (tid, idempotency_key, request, canonical(body), "draft", now(), body["rail"], supersedes, goal_id))
            row = self._get(c, tid)
            checks = self._evaluate(c, row, "preview", actor)
            c.execute("UPDATE transfers SET checks=? WHERE id=?", (canonical(checks), tid))
            self.store.event(c, actor, "draft.create", "ok", tid, environment=body["environment"], route=route_id,
                             recipient=mask(recipient.get("address") or recipient.get("account") or recipient["id"]))
            self.store.event(c, actor, "quote.issue", "ok", tid, quote_id=body["quote_id"], expires=body["expires"],
                             rate=body.get("rate"), rate_kind=body.get("rate_kind"))
            self.store.event(c, actor, "guardrails.preview", self._outcome(checks), tid, checks=checks)
            return self.public(self._get(c, tid))

    @audited
    def modify(self, actor, transfer_id, idempotency_key, amount=None, receive_amount=None, purpose=None, recipient_id=None):
        """A change creates a new draft; the old one is superseded and any approval on it is void."""
        self.require(actor, "prepare")
        with self.store.read() as c:
            row = self._get(c, transfer_id)
        if row["status"] not in ("draft", "approved"):
            raise Denied("only drafts and approved, unsubmitted payments can be changed", "state_invalid", ref=transfer_id)
        b = json.loads(row["body"])
        request = json.loads(row["request"])
        changed = dict(amount=amount, receive_amount=receive_amount, purpose=purpose, recipient_id=recipient_id)
        if amount or receive_amount:
            request.update(amount=amount or None, receive_amount=receive_amount or None)
        new = self.prepare(actor, request["amount"], b["source"], b["target"], recipient_id or b["recipient"]["id"],
                           purpose or b["purpose"], idempotency_key, request.get("receive_amount"), b.get("arrival_by"),
                           b.get("goal_id"), supersedes=transfer_id)
        with self.store.tx() as c:
            current = self._get(c, transfer_id)
            if current["status"] in ("draft", "approved"):
                c.execute("UPDATE transfers SET status='superseded' WHERE id=?", (transfer_id,))
                self.store.event(c, actor, "draft.modify", "ok", transfer_id, replaced_by=new["id"],
                                 changed=[k for k, v in changed.items() if v], approval_voided=current["status"] == "approved")
        return new

    @staticmethod
    def _outcome(checks):
        statuses = {c["status"] for c in checks}
        return "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"

    def _limits_for(self, c, currency):
        limits = self.limits(c).get(currency)
        if not limits:
            raise Denied("no limit configured for this currency", "limit_currency")
        return int(limits["per_payment"]), int(limits["daily"])

    def _evaluate(self, c, row, phase, actor="system", mandate_id=None):
        """Run every guardrail and record each outcome. Checks run before approval and again before submission."""
        b = json.loads(row["body"])
        rail = b.get("rail", "sandbox")
        others = [dict(r) for r in c.execute("SELECT * FROM transfers WHERE id<>?", (row["id"],)).fetchall()]
        results = []

        def run(check_id, fn):
            try:
                outcome = fn()
                if outcome:
                    results.append(dict(id=check_id, status="warn", detail=outcome))
                else:
                    results.append(dict(id=check_id, status="pass"))
            except Denied as exc:
                results.append(dict(id=check_id, status="fail", code=exc.code, detail=str(exc)))

        def permission():
            if phase == "submit":
                self.require(actor, "submit")
            elif phase == "approve":
                self.owner(actor)

        def required():
            if not b.get("purpose") or not b.get("recipient") or b.get("value", 0) <= 0 or not b.get("source"):
                raise Denied("required payment fields missing", "fields_missing")

        def environment():
            if rail == "evm" and b.get("environment") == "live_chain" and not self.config.live:
                raise Denied("live payment environments are blocked in this release", "live_blocked")

        def route():
            if rail == "evm":
                if not self.evm or b.get("chain_id") != self.config.chain_id:
                    raise Denied("agent wallet rail unavailable or chain changed", "evm_unavailable")
                return None
            if not self.route_for(c, b["source"], b["target"]) or not self.sandbox.supports(b["source"], b["target"]):
                raise Denied("route is disabled or not supported by the provider", "route_disabled")

        def recipient():
            r = c.execute("SELECT * FROM recipients WHERE id=?", (b["recipient"]["id"],)).fetchone()
            if not r or not r["enabled"] or json.loads(r["body"]) != b["recipient"]:
                raise Denied("recipient changed or disabled; prepare a new draft", "recipient_changed")

        def expiry():
            if b["expires"] <= now():
                raise Denied("quote expired; prepare and authorize a new quote", "quote_expired")
            if b["expires"] - now() < 60:
                return "quote expires in under a minute"

        def per_payment():
            per, _ = self._limits_for(c, b["source"])
            if b["reserve"] > per:
                raise Denied("per-payment limit exceeded (including fee)", "limit_per_payment")

        def cumulative():
            _, daily = self._limits_for(c, b["source"])
            # Rolling 24h, plus every unresolved payment even if older than 24h.
            used = sum(int(r["actual_cost"]) if r["actual_cost"] is not None else json.loads(r["body"])["reserve"]
                       for r in others if r["submitted"] and json.loads(r["body"])["source"] == b["source"]
                       and (r["submitted"] > now() - 86400 or r["status"] in ACTIVE))
            if used + b["reserve"] > daily:
                raise Denied("rolling 24h budget exceeded", "limit_daily")

        def funds():
            reserved = sum(json.loads(r["body"])["reserve"] for r in others
                           if r["status"] in ACTIVE and json.loads(r["body"])["source"] == b["source"])
            if rail == "evm":
                available = self.evm.balance() - reserved
            else:
                if not self._in_sandbox(c, b["source"]):
                    raise Denied(f"{b['source']} is not in your sandbox — record your balance, or add it to the sandbox first",
                                 "sandbox_currency_missing")
                total = c.execute("SELECT total FROM balances WHERE currency=?", (b["source"],)).fetchone()
                available = (int(total[0]) if total else 0) - reserved
            if available < b["reserve"]:
                raise Denied("insufficient available funds", "funds_insufficient")

        def duplicate():
            for r in others:
                ob = json.loads(r["body"])
                if (r["status"] not in ("cancelled", "superseded", "failed") and r["created"] > now() - 600
                        and ob["recipient"]["id"] == b["recipient"]["id"] and ob["value"] == b["value"]
                        and ob["source"] == b["source"] and r["id"] != row.get("supersedes")):
                    return f"similar payment {r['id'][:8]} created in the last 10 minutes"

        def wallet_clear():
            if rail == "evm" and any(r["status"] in ACTIVE and r.get("rail") == "evm" for r in others):
                raise Denied("reconcile outstanding wallet transaction before another payment", "wallet_pending")

        def deadline():
            if not b.get("arrival_by"):
                return None
            due = datetime.strptime(b["arrival_by"], "%Y-%m-%d").replace(tzinfo=self.zone()) + timedelta(days=1)
            arrival = datetime.now(timezone.utc) + timedelta(seconds=b.get("eta_seconds") or 600)
            if arrival > due:
                return "estimated arrival is after the requested date"

        def authorization():
            if phase != "submit":
                return None
            if mandate_id:
                self._mandate(c, b, mandate_id)
            elif not (row["status"] == "approved" and row["approved_hash"] == digest(b)):
                raise Denied("exact owner approval or scoped owner mandate required", "approval_required")

        for check_id, fn in (("permission", permission), ("required_fields", required), ("environment", environment),
                             ("route", route), ("recipient", recipient), ("quote_expiry", expiry),
                             ("per_payment_limit", per_payment), ("cumulative_limit", cumulative),
                             ("available_funds", funds), ("duplicate", duplicate), ("wallet_clear", wallet_clear),
                             ("arrival_deadline", deadline), ("authorization", authorization)):
            if check_id == "permission" and phase == "preview":
                continue
            if check_id == "authorization" and phase != "submit":
                continue
            if check_id == "wallet_clear" and rail != "evm":
                continue
            try:
                run(check_id, fn)
            except Exception:
                results.append(dict(id=check_id, status="fail", code="check_error", detail="check could not be completed"))
        return results

    def _enforce(self, c, row, phase, actor, mandate_id=None):
        checks = self._evaluate(c, row, phase, actor, mandate_id)
        failed = [x for x in checks if x["status"] == "fail"]
        if failed:
            raise Denied(failed[0]["detail"], failed[0].get("code", "guardrail"), ref=row["id"], checks=checks)
        return json.loads(row["body"]), checks

    def checks(self, actor, transfer_id):
        self.require(actor, "view")
        with self.store.tx() as c:
            row = self._get(c, transfer_id)
            results = self._evaluate(c, row, "preview", actor)
            c.execute("UPDATE transfers SET checks=? WHERE id=?", (canonical(results), transfer_id))
        return results

    @audited
    def approve(self, actor, transfer_id, approval_digest, note=None):
        self.owner(actor)
        with self.store.tx() as c:
            row = self._get(c, transfer_id)
            if row["status"] not in ("draft", "approved"):
                raise Denied("transfer cannot be approved in this state", "state_invalid", ref=transfer_id)
            body, checks = self._enforce(c, row, "approve", actor)
            if approval_digest != digest(body):
                raise Denied("approval does not match exact displayed payment", "digest_mismatch", ref=transfer_id)
            c.execute("UPDATE transfers SET status='approved',approved_hash=?,approval_actor='owner',approved_at=?,checks=?,approval_note=? WHERE id=?",
                      (approval_digest, now(), canonical(checks), (note or "")[:200] or None, transfer_id))
            self.store.event(c, actor, "guardrails.approve", self._outcome(checks), transfer_id, checks=checks)
            self.store.event(c, actor, "approve", "ok", transfer_id, approved_digest=approval_digest,
                             approved=dict(amount=body["amount"], source=body["source"], target=body["target"],
                                           receive=str(body["receive"]), fee=str(body["fee"]), quote_id=body["quote_id"],
                                           expires=body["expires"], recipient=body["recipient"]["id"]))
            return self.public(self._get(c, transfer_id))

    # ---------- mandates (agent autonomy on its own wallet) ----------
    @audited
    def grant_mandate(self, actor, recipient_id, per_payment, total_budget, expires):
        self.owner(actor)
        if not self.evm:
            raise Denied("mandates apply only to the agent wallet rail; sandbox remittances need per-payment authorization",
                         "evm_unavailable")
        if not now() < expires <= now() + 86400 * 7:
            raise Denied("mandate must expire within seven days", "mandate_expiry")
        per, total = units(per_payment, 18), units(total_budget, 18)
        ceiling_per, ceiling_daily = self.limit_defaults()["ETH"]
        if per > ceiling_per or per > total or total > ceiling_daily:
            raise Denied("mandate exceeds server limits", "mandate_limits")
        with self.store.tx() as c:
            r = c.execute("SELECT body FROM recipients WHERE id=? AND enabled=1", (recipient_id,)).fetchone()
            if not r or json.loads(r[0]).get("rail") != "evm":
                raise Denied("enabled EVM recipient required", "recipient_rail")
            body = dict(recipient=json.loads(r[0]), per_payment=per, total_budget=total, expires=expires,
                        chain_id=self.config.chain_id, sender=self.evm.account.address, asset="ETH")
            mid = str(uuid.uuid4())
            c.execute("INSERT INTO mandates(id,body) VALUES (?,?)", (mid, canonical(body)))
            self.store.event(c, actor, "mandate.grant", "ok", mid, scope_digest=digest(body), recipient_id=recipient_id)
            return dict(id=mid, revoked=False, used="0", **body)

    def mandates(self):
        with self.store.read() as c:
            out = []
            for r in c.execute("SELECT * FROM mandates"):
                used = sum(json.loads(t[0])["reserve"] for t in
                           c.execute("SELECT body FROM transfers WHERE mandate_id=? AND submitted IS NOT NULL", (r["id"],)))
                out.append(dict(id=r["id"], revoked=bool(r["revoked"]), used=str(used), **json.loads(r["body"])))
            return out

    @audited
    def revoke(self, actor, mandate_id):
        self.owner(actor)
        with self.store.tx() as c:
            if not c.execute("UPDATE mandates SET revoked=1 WHERE id=?", (mandate_id,)).rowcount:
                raise Denied("mandate not found", "mandate_unknown")
            self.store.event(c, actor, "mandate.revoke", "ok", mandate_id)
        return {"revoked": mandate_id, "note": "already signed/broadcast payments cannot be recalled"}

    def _mandate(self, c, body, mandate_id):
        row = c.execute("SELECT * FROM mandates WHERE id=? AND revoked=0", (mandate_id,)).fetchone()
        if not row or body.get("rail") != "evm":
            raise Denied("active EVM mandate required", "mandate_required")
        m = json.loads(row["body"])
        if (m["expires"] <= now() or m["recipient"] != body["recipient"] or
                m["chain_id"] != body["chain_id"] or m["sender"] != body["sender"]):
            raise Denied("payment is outside mandate scope", "mandate_scope")
        rows = c.execute("SELECT body FROM transfers WHERE mandate_id=? AND submitted IS NOT NULL", (mandate_id,))
        # Lifetime commitment budget: even failed tx reservations count, conservative and non-resettable.
        used = sum(json.loads(r[0])["reserve"] for r in rows)
        if body["reserve"] > m["per_payment"] or used + body["reserve"] > m["total_budget"]:
            raise Denied("mandate budget exhausted", "mandate_budget")

    # ---------- submission and tracking ----------
    @audited
    def execute(self, actor, transfer_id, mandate_id=None):
        self.require(actor, "submit")
        with self.store.tx() as c:
            row = self._get(c, transfer_id)
            if row["status"] in (*ACTIVE, *FINAL):
                return self.public(row)  # retries cannot spend twice
            body, checks = self._enforce(c, row, "submit", actor, mandate_id)
            authorized = "owner_mandate" if mandate_id else "owner"
            status = "pending"
            if body.get("rail", "sandbox") == "evm":
                try:
                    reference, raw = self.evm.sign(body)
                except Denied as exc:
                    exc.params["ref"] = transfer_id
                    raise
                except Exception:
                    raise Denied("agent wallet RPC unavailable", "evm_unavailable", ref=transfer_id) from None
                c.execute("INSERT INTO secrets VALUES (?,?)", (transfer_id, raw))
            else:
                reference, lost = self.sandbox.submit(c, transfer_id, body)
                if lost:
                    reference, status = None, "unknown"
            c.execute("UPDATE transfers SET status=?,submitted=?,reference=?,mandate_id=?,approval_actor=?,checks=? WHERE id=?",
                      (status, now(), reference, mandate_id, authorized, canonical(checks), transfer_id))
            self.store.event(c, actor, "guardrails.submit", self._outcome(checks), transfer_id, checks=checks)
            self.store.event(c, actor, "reserve", "ok", transfer_id, units=str(body["reserve"]), currency=body["source"])
            self.store.event(c, actor, "submit", "accepted" if status == "pending" else "response_lost", transfer_id,
                             provider_reference=reference, rail=body.get("rail", "sandbox"), authorized_by=authorized, mandate_id=mandate_id)
            if status == "unknown":
                # The provider may or may not have the payment. Never retry with a new identifier;
                # a later status query looks it up by this transfer's own ID.
                return self.public(self._get(c, transfer_id))
        # Durable signed intent BEFORE network I/O; recovery never uses a new identifier or nonce.
        return self.reconcile(actor, transfer_id)

    @audited
    def reconcile(self, actor, transfer_id):
        self.require(actor, "prepare")
        with self.store.tx() as c:
            row = self._get(c, transfer_id)
            if row["status"] not in ACTIVE:
                return self.public(row)
            body = json.loads(row["body"])
            reference = row["reference"]
            if body.get("rail", "sandbox") == "sandbox":
                if not reference:
                    # Outcome unknown: look the payment up by our own identifier before any retry.
                    reference = self.sandbox.find(c, transfer_id)
                    recovery = "found_existing" if reference else "resubmitted_same_id"
                    if not reference:
                        reference, _ = self.sandbox.submit(c, transfer_id, body)
                    c.execute("UPDATE transfers SET reference=? WHERE id=?", (reference, transfer_id))
                    self.store.event(c, actor, "recovery", recovery, transfer_id, provider_reference=reference)
                provider_status = self.sandbox.status(c, reference)
                status = {"processing": "pending", "completed": "completed", "failed": "failed"}.get(provider_status, "unknown")
                cost = body["reserve"] if status == "completed" else 0 if status == "failed" else None
            else:
                try:
                    status, fee = self.evm.status(reference)
                    if status == "unknown":
                        raw = c.execute("SELECT raw_tx FROM secrets WHERE transfer_id=?", (transfer_id,)).fetchone()[0]
                        self.evm.broadcast(raw)
                        status, fee = self.evm.status(reference)
                    cost = (body["value"] if status == "completed" else 0) + fee if fee is not None else None
                except Exception:
                    # RPC exception strings may contain credentials. Do not persist or expose them.
                    status, cost = "unknown", None
            if status == row["status"] and status in ACTIVE:
                return self.public(self._get(c, transfer_id))
            if self.evm and body.get("rail") == "evm":
                self.evm.invalidate()
            if body.get("rail", "sandbox") == "sandbox" and status == "completed":
                cash = self._latest_cash(c, body["source"])
                if cash is not None:  # your overview balance goes down by what left, and the ledger follows it
                    self._record_cash(c, actor, body["source"], cash - cost, str(date.today()), "transfer",
                                      f"transfer {transfer_id[:8]}")
                else:
                    total = int(c.execute("SELECT total FROM balances WHERE currency=?", (body["source"],)).fetchone()[0])
                    c.execute("UPDATE balances SET total=? WHERE currency=?", (str(total - cost), body["source"]))
                # Money to someone else leaves you. Money to your OWN account (a move between your accounts) arrives in
                # your balance in that currency — the amount the quote said would arrive.
                if body.get("recipient", {}).get("kind") == "self" and body.get("receive") is not None:
                    got = int(body["receive"])
                    have = self._latest_cash(c, body["target"])
                    if have is not None or not self._in_sandbox(c, body["target"]):
                        self._record_cash(c, actor, body["target"], (have or 0) + got, str(date.today()), "transfer",
                                          f"from my {body['source']} account · {transfer_id[:8]}")
                    else:
                        total = int(c.execute("SELECT total FROM balances WHERE currency=?", (body["target"],)).fetchone()[0])
                        c.execute("UPDATE balances SET total=? WHERE currency=?", (str(total + got), body["target"]))
            c.execute("UPDATE transfers SET status=?,actual_cost=?,completed_at=? WHERE id=?",
                      (status, str(cost) if cost is not None else None, now() if status in ("completed", "failed") else None,
                       transfer_id))
            self.store.event(c, actor, "provider.status", status, transfer_id, provider_reference=reference)
            if status in ("completed", "failed"):
                self.store.event(c, actor, "settle" if status == "completed" else "release", "ok", transfer_id,
                                 actual_cost=str(cost), currency=body["source"])
            return self.public(self._get(c, transfer_id))

    def reconcile_open(self):
        """Background tracking of every submitted payment whose outcome is not yet final."""
        with self.store.read() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM transfers WHERE status IN ('pending','unknown')")]
        results = []
        for tid in ids:
            try:
                results.append(self.reconcile("system", tid))
            except Exception:
                pass
        return results

    @audited
    def cancel(self, actor, transfer_id):
        self.owner(actor)
        with self.store.tx() as c:
            row = self._get(c, transfer_id)
            if row["status"] not in ("draft", "approved"):
                raise Denied("cannot cancel a signed or submitted transaction", "state_invalid", ref=transfer_id)
            c.execute("UPDATE transfers SET status='cancelled' WHERE id=?", (transfer_id,))
            self.store.event(c, actor, "cancel", "ok", transfer_id, reservation="none held before submission")
            return self.public(self._get(c, transfer_id))

    def trail(self, actor, transfer_id):
        """Who authorized, what was approved, which checks ran, and what happened afterwards."""
        self.owner(actor)
        with self.store.read() as c:
            row = self._get(c, transfer_id)
            chain, cursor = [transfer_id], row
            while cursor.get("supersedes"):
                chain.append(cursor["supersedes"])
                cursor = dict(c.execute("SELECT * FROM transfers WHERE id=?", (cursor["supersedes"],)).fetchone() or {})
            marks = ",".join("?" * len(chain))
            events = [dict(r) for r in c.execute(f"SELECT * FROM audit WHERE correlation IN ({marks}) ORDER BY id", chain)]
        return dict(transfer=self.public(row), lineage=chain, events=events)

    # ---------- funds ----------
    def balances(self):
        with self.store.read() as c:
            active = [json.loads(r[0]) for r in c.execute("SELECT body FROM transfers WHERE status IN ('pending','unknown')")]
            out = []
            for r in c.execute("SELECT * FROM balances ORDER BY currency"):
                reserved = sum(b["reserve"] for b in active if b["source"] == r["currency"] and b.get("rail", "sandbox") == "sandbox")
                if not reserved and not self._in_sandbox(c, r["currency"]):
                    continue  # test money from an older version for a currency you never added: not shown, not spendable
                own = self._latest_cash(c, r["currency"]) is not None
                out.append(dict(currency=r["currency"], decimals=decimals(r["currency"]), total=r["total"], reserved=str(reserved),
                                available=str(int(r["total"]) - reserved), rail="sandbox", basis="cash" if own else "test_funds",
                                source="your overview balance" if own else "local simulation test funds, not provider funds"))
        if self.evm:
            reserved = sum(b["reserve"] for b in active if b.get("rail") == "evm")
            try:
                total = self.evm.display_balance()
                out.append({"currency": "ETH", "decimals": 18, "total": str(total), "reserved": str(reserved), "rail": "evm",
                            "available": str(max(0, total - reserved)),
                            "source": "RPC latest block; reservation held until confirmations"})
            except Exception:
                out.append({"currency": "ETH", "decimals": 18, "total": None, "reserved": str(reserved), "rail": "evm",
                            "available": None, "source": "RPC unreachable"})
        return out

    def equivalents(self, display):
        """Reference equivalents only. They do not imply that any conversion has occurred."""
        out = []
        for b in self.balances():
            if b["currency"] == display or b["total"] is None:
                out.append(dict(currency=b["currency"], display=display, total=b["total"], available=b["available"],
                                rate="1" if b["currency"] == display else None, kind="same currency" if b["currency"] == display else "unavailable"))
                continue
            try:
                ref = self.rates.latest(b["currency"], display)
                rate = ref["rate"]
                factor = Decimal(rate) * Decimal(10) ** (decimals(display) - b["decimals"])
                out.append(dict(currency=b["currency"], display=display, rate=rate, provider=ref["provider"],
                                observed=ref["observed"], derived=ref["derived"], kind="reference equivalent, not converted",
                                total=str(int(Decimal(b["total"]) * factor)), available=str(int(Decimal(b["available"]) * factor))))
            except Denied:
                out.append(dict(currency=b["currency"], display=display, rate=None, kind="unavailable", total=None, available=None))
        return out

    @audited
    def fund(self, actor, currency, amount):
        """Add simulated test funds to the local sandbox ledger."""
        self.owner(actor)
        value = units(amount, decimals(currency))
        if value > 10000 * 10**decimals(currency):
            raise Denied("test top-up limited to 10,000 per action", "fund_limit")
        with self.store.tx() as c:
            cash = self._latest_cash(c, currency)
            if cash is not None:  # you track this currency yourself: test money shows up in that balance
                self._record_cash(c, actor, currency, cash + value, str(date.today()), "test_funds", "test funds")
                self.store.event(c, actor, "sandbox.fund", "ok", currency, units=str(value), label="simulated test funds")
                return self.balances()
            row = c.execute("SELECT total FROM balances WHERE currency=?", (currency,)).fetchone()
            if not row or not self._in_sandbox(c, currency):
                raise Denied("add this currency to the sandbox first", "sandbox_currency_missing")
            c.execute("UPDATE balances SET total=? WHERE currency=?", (str(int(row[0]) + value), currency))
            self.store.event(c, actor, "sandbox.fund", "ok", currency, units=str(value), label="simulated test funds")
        return self.balances()

    def wallet(self):
        if not self.evm:
            return dict(available=False, reason=self.evm_error or "set EVM_RPC_URL and AGENT_WALLET_PASSWORD to give the agent a wallet")
        info = self.evm.info()
        info.update(available=True, mandates=[m for m in self.mandates() if not m["revoked"] and m["expires"] > now()])
        return info

    # ---------- memory and preferences ----------
    def memory(self):
        with self.store.read() as c:
            return {r["key"]: json.loads(r["value"]) for r in c.execute("SELECT * FROM memories") if not r["key"].startswith("_")}

    def zone(self):
        try:
            return ZoneInfo(self.memory().get("time_zone") or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            return timezone.utc

    @audited
    def remember(self, actor, key, value):
        self.owner(actor)
        if key not in PREFERENCES or not isinstance(value, str) or len(value) > 200:
            raise Denied("only bounded non-secret user preferences supported", "preference_invalid")
        if key == "language" and value and value not in LANGUAGES:
            raise Denied("unsupported language", "preference_invalid")
        if key in ("home_region", "receive_region") and value and value not in ECONOMIES:
            raise Denied("unknown economy", "economy_unknown")
        if key == "display_currency" and value and not re.fullmatch(r"[A-Z]{3}", value):
            raise Denied("currency must be an ISO code", "preference_invalid")
        if key == "time_zone" and value:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise Denied("unknown time zone", "preference_invalid") from None
        with self.store.tx() as c:
            c.execute("INSERT INTO memories VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated",
                      (key, canonical(value), now()))
            self.store.event(c, actor, "memory.update", "ok", key)
        return self.memory()

    # ---------- audit ----------
    def audit(self, actor="owner", q=None, outcome=None, actor_filter=None, limit=300):
        self.owner(actor)
        sql, args = "SELECT * FROM audit WHERE 1=1", []
        if q:
            sql += " AND (action LIKE ? OR correlation LIKE ? OR request_id LIKE ?)"
            args += [f"%{q}%"] * 3
        if outcome:
            sql += " AND outcome=?"
            args.append(outcome)
        if actor_filter:
            sql += " AND actor=?"
            args.append(actor_filter)
        with self.store.read() as c:
            return [dict(r) for r in c.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, min(int(limit), 1000)))]

    def version(self):
        with self.store.read() as c:
            return c.execute("SELECT COALESCE(MAX(id),0) FROM audit").fetchone()[0]
