import asyncio
import contextvars
import dataclasses
import hmac
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field
from .domain import Denied, new_request_id
from .service import Finance
from .agent import Agent
from .auth import Users
from .privacy import export_workspace
from . import worker

# The workspace (one person's database) this request works on, set from the session before the endpoint runs.
CURRENT = contextvars.ContextVar("workspace", default="default")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=4000)


class Draft(Model):
    amount: str | None = None
    receive_amount: str | None = None
    source: str
    target: str
    recipient_id: str
    purpose: str
    idempotency_key: str
    arrival_by: str | None = None
    goal_id: str | None = None


class Modify(Model):
    idempotency_key: str
    amount: str | None = None
    receive_amount: str | None = None
    purpose: str | None = None
    recipient_id: str | None = None


class Recipient(Model):
    recipient_id: str
    name: str
    address: str = ""
    enabled: bool = True
    currency: str = ""
    country: str = ""
    account: str = ""
    kind: str = "individual"
    bank: str = Field(default="", max_length=80)


class OwnAccount(Model):
    currency: str = Field(min_length=3, max_length=3)
    bank: str = Field(default="", max_length=80)
    account: str = Field(default="", max_length=34)
    country: str = Field(default="", max_length=2)


class Approval(Model):
    approval_digest: str
    note: str | None = None


class Execute(Model):
    mandate_id: str | None = None


class Mandate(Model):
    recipient_id: str
    per_payment: str
    total_budget: str
    expires: int


class Preference(Model):
    key: str
    value: str


class SignUp(Model):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)
    name: str = Field(default="", max_length=60)
    owner_token: str = Field(default="", max_length=200)  # claims the data already on this computer


class Claim(Model):
    owner_token: str = Field(min_length=1, max_length=200)


class SignIn(Model):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class Clear(Model):
    what: str


class Farewell(Model):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class FxRuleIn(Model):
    source: str
    target: str
    amount: str = Field(max_length=24)
    min_rate: str = Field(max_length=24)
    due: str | None = None
    mode: str = "confirm"
    bank: str | None = Field(default=None, max_length=40)


class MonthBudget(Model):
    currency: str
    amount: str | None = Field(default=None, max_length=24)


class Chat(Model):
    message: str = Field(min_length=1, max_length=4000)
    session: str = "default"
    language: str = "en"
    page: str = Field(default="", max_length=40)  # the screen the person is on, so "this" means something


class Login(Model):
    token: str = Field(min_length=24, max_length=256)


class Compare(Model):
    source: str
    target: str
    amount: str | None = None
    receive_amount: str | None = None
    rank: str = "receive"


class Scenario(Model):
    source: str
    target: str
    amount: str
    rate_change_pct: str


class RouteAdd(Model):
    send: str
    receive: str


class RouteUpdate(Model):
    enabled: bool | None = None
    payments_enabled: bool | None = None


class Fund(Model):
    currency: str
    amount: str


class Limit(Model):
    currency: str
    per_payment: str
    daily: str


class Goal(Model):
    title: str
    purpose: str = ""
    source: str
    target: str
    target_amount: str
    deadline: str
    recipient_id: str | None = None
    category: str = "family"


class GoalUpdate(Model):
    status: str


class BudgetEntry(Model):
    kind: str
    label: str
    currency: str
    amount: str
    date: str | None = None


class Obligation(Model):
    title: str
    category: str = "other"
    amount: str
    currency: str
    due_date: str
    recurring: str = "none"


class Paid(Model):
    paid_date: str | None = None
    transfer_id: str | None = None


class RateAlert(Model):
    source: str
    target: str
    condition: str
    threshold: str = "0"
    window: str | None = None
    due_date: str | None = None
    note: str | None = None


class AlertUpdate(Model):
    active: bool


class Decide(Model):
    accept: bool
    note: str = ""


class Note(Model):
    text: str = Field(min_length=1, max_length=300)
    kind: str = "fact"


class CsvImport(Model):
    filename: str = Field(default="statement.csv", max_length=200)
    content: str = Field(max_length=2_100_000)
    currency: str | None = None
    account_id: str | None = Field(default=None, max_length=64)


class AccountIn(Model):
    name: str = Field(min_length=1, max_length=60)
    type: str
    currency: str
    balance: str | None = Field(default=None, max_length=24)
    paid_by: str = "me"
    payer_name: str | None = Field(default=None, max_length=20)


class AccountPayer(Model):
    paid_by: str
    payer_name: str | None = Field(default=None, max_length=20)


class ExpenseIn(Model):
    date: str
    amount: int
    currency: str
    description: str = Field(min_length=1, max_length=200)
    category: str
    source: str = "manual"
    recurring: str | None = None


class SandboxCurrency(Model):
    currency: str = Field(min_length=3, max_length=3)
    amount: str | None = Field(None, max_length=20)


class ExpensePatch(Model):
    category: str | None = Field(None, max_length=40)
    amount: int | None = Field(None, ge=-10**12, le=10**12)
    description: str | None = Field(None, max_length=200)
    date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class QuickText(Model):
    text: str = Field(min_length=1, max_length=200)
    currency: str | None = None
    ai: bool = False


Image = Annotated[str, Field(max_length=6_000_000)]  # a data URL; the global 4000-character cap is for text fields


class Receipt(Model):
    model_config = ConfigDict(extra="forbid", str_max_length=6_000_000)
    image: Image | None = None
    images: list[Image] | None = Field(default=None, max_length=4)


class ReviewItem(Model):
    id: str = Field(max_length=64)
    include: bool = True
    category: str | None = Field(None, max_length=40)
    amount: int | None = Field(None, ge=-10**12, le=10**12)


class ReviewIn(Model):
    items: list[ReviewItem] = Field(min_length=1, max_length=5000)


class RecurringIn(Model):
    description: str
    amount: int
    currency: str
    category: str
    cadence: str
    last_date: str


class ScholarshipIn(Model):
    name: str
    provider: str = ""
    kind: str = "scholarship"
    status: str = "researching"
    amount: str = ""
    currency: str | None = None
    deadline: str | None = None
    payout_date: str | None = None
    url: str = ""
    notes: str = ""
    documents: list = Field(default_factory=list, max_length=20)


class ScholarshipPatch(Model):
    name: str | None = None
    provider: str | None = None
    kind: str | None = None
    status: str | None = None
    amount: str | None = None
    currency: str | None = None
    deadline: str | None = None
    payout_date: str | None = None
    url: str | None = None
    notes: str | None = None
    documents: list | None = Field(default=None, max_length=20)


class TermIn(Model):
    name: str
    currency: str | None = None
    start: str
    end: str
    tuition: str = ""
    tuition_due: str | None = None
    living: str = ""
    income: str = ""
    extras: list = Field(default_factory=list, max_length=12)


class AffordIn(Model):
    amount: str
    currency: str | None = None
    date: str | None = None
    label: str = Field(default="", max_length=80)
    payer: str = "me"


class EmailIn(Model):
    address: str = Field(default="", max_length=254)
    digest: str = "off"
    reminders: bool = False
    language: str = "en"
    weekday: int = 0
    skip_quiet: bool = True


class EmailSend(Model):
    period: str = "week"
    language: str | None = None


class MotivationIn(Model):
    enabled: bool = True
    celebrate: bool = True


class ChallengeIn(Model):
    kind: str
    amount: str | None = None
    currency: str | None = None


class SeenIn(Model):
    ids: list[int] = Field(max_length=50)


class WatchIn(Model):
    source: str
    target: str
    amount: str | None = None
    deadline: str | None = None
    min_rate: str | None = None
    note: str = Field(default="", max_length=200)
    active: bool = True


class TemplateIn(Model):
    name: str = Field(max_length=80)
    format: str
    fields: dict
    currency: str | None = None
    recipient_id: str | None = None
    amount: str | None = None
    purpose: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=300)


class TemplateCheck(Model):
    format: str
    fields: dict
    currency: str | None = None


class SheetIn(Model):
    amount: str | None = None


class PlanIn(Model):
    source: str
    target: str
    amount: str = Field(max_length=24)
    side: str = "receive"
    due: str | None = None
    purpose: str = Field(default="", max_length=120)
    kind: str = "custom"
    need_ref: str | None = Field(default=None, max_length=200)
    min_rate: str | None = Field(default=None, max_length=24)
    recipient_id: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=20)


class PlanStatus(Model):
    status: str


class Pretend(Model):
    currency: str
    amount: str = Field(max_length=24)


class SimulateIn(Model):
    display: str | None = None
    extra: list[Pretend] = Field(default_factory=list, max_length=12)
    rate_shift: str = Field(default="0", max_length=8)
    plan_ids: list[str] | None = Field(default=None, max_length=50)


class BankRefresh(Model):
    source: str
    target: str
    urls: list[str] | None = Field(default=None, max_length=3)


class BankPricing(Model):
    model_config = ConfigDict(extra="forbid", str_max_length=200)
    source: str
    target: str
    rate: str | None = None
    fee_send: dict | None = None
    fee_pct: str | None = None
    intermediary: dict | None = None
    fee_receive: dict | None = None
    notes: str = ""


class ScenarioIn(Model):
    source: str
    target: str
    amount: str = Field(max_length=24)
    mode: str = "send"
    send_bank: str | None = None
    receive_bank: str | None = None
    due: str | None = None


class TimelineIn(Model):
    display: str | None = None
    off: list[str] = Field(default_factory=list, max_length=200)
    scenario: dict | None = None
    days: int = 90
    extra: list[Pretend] = Field(default_factory=list, max_length=12)


class CashIn(Model):
    currency: str
    amount: str = Field(max_length=24)
    label: str = Field(default="", max_length=120)


class Recommendation(Model):
    subject: str
    detail: dict


def safe(value):
    """JavaScript numbers lose precision above 2^53; wei and large minor units travel as strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and abs(value) > 9007199254740991:
        return str(value)
    if isinstance(value, dict):
        return {k: safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    return value


class SafeJSONResponse(JSONResponse):
    def render(self, content):
        return super().render(safe(content))


def sse(event):
    return "data: " + json.dumps(safe(event), ensure_ascii=False, default=str) + "\n\n"


def create_app(finance=None, agent=None, background=None):
    @asynccontextmanager
    async def lifespan(app):
        owner, agent_token = os.getenv("OWNER_TOKEN", ""), os.getenv("AGENT_TOKEN", "")
        if len(owner) < 24 or len(agent_token) < 24 or owner == agent_token:
            raise RuntimeError("set distinct OWNER_TOKEN and AGENT_TOKEN (at least 24 characters)")
        if os.getenv("PUBLIC_DEPLOY") == "true" and (os.getenv("EVM_RPC_URL") or os.getenv("ENABLE_LIVE_PAYMENTS") == "true"):
            raise RuntimeError("PUBLIC_DEPLOY=true runs the simulation only: leave EVM_RPC_URL empty and ENABLE_LIVE_PAYMENTS false")
        viewer = os.getenv("VIEWER_TOKEN", "")
        if viewer and (len(viewer) < 24 or viewer in (owner, agent_token)):
            raise RuntimeError("VIEWER_TOKEN must be distinct and at least 24 characters")
        app.state.finance = finance or Finance()
        app.state.agent = agent or Agent(app.state.finance)
        app.state.finance.exchange_judge = app.state.agent.judge
        app.state.finance.page_reader = app.state.agent.judge  # reads public bank pages into rates and fees
        app.state.sessions = {}
        app.state.users = Users(os.path.join(os.path.dirname(os.path.abspath(app.state.finance.config.db)), "users.sqlite3"))
        app.state.workspaces = {"default": (app.state.finance, app.state.agent)}
        app.state.stop = stop = asyncio.Event()
        app.state.loop = asyncio.get_running_loop()
        app.state.run_worker = run_worker = background if background is not None else os.getenv("ENABLE_WORKER", "true") == "true"
        app.state.tasks = [asyncio.create_task(worker.run(app.state.finance, stop))] if run_worker else []
        app.state.demos = {}
        folder = os.path.join(os.path.dirname(os.path.abspath(app.state.finance.config.db)), "users")
        if os.path.isdir(folder):  # demo spaces never outlive the server
            for name in os.listdir(folder):
                if name.startswith("demo-"):
                    try:
                        os.remove(os.path.join(folder, name))
                    except OSError:
                        pass
        app.state.users.retry_deletions(os.remove)
        for ws in app.state.users.workspaces():  # reminders and digests keep running for every account
            open_workspace(ws)
        yield
        stop.set()
        for task in app.state.tasks:
            await task

    app = FastAPI(title="Remittance Agent", version="0.3.0", lifespan=lifespan, default_response_class=SafeJSONResponse,
                  description="Single-user prototype. Local sandbox simulation plus the agent's own EVM wallet. "
                              "Amount details use minor units.")
    bearer = HTTPBearer(auto_error=False)

    def token_role(token):
        for name in ("owner", "agent", "viewer"):
            expected = os.getenv(name.upper() + "_TOKEN", "")
            if expected and hmac.compare_digest(token, expected):
                return name
        raise HTTPException(401, "invalid credential")

    def role(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials:
            return token_role(credentials.credentials)
        session = app.state.sessions.get(request.cookies.get("finance_session", ""))
        if session and session["expires"] > time.time():
            return session["role"]
        raise HTTPException(401, "session required")

    @app.middleware("http")
    async def browser_guard(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.cookies.get("finance_session") or request.url.path.startswith(("/session", "/auth")):
                if request.headers.get("x-workspace-request") != "1":
                    return JSONResponse(status_code=403, content={"error": "same-origin request header required"})
        rid = new_request_id()
        session = app.state.sessions.get(request.cookies.get("finance_session", ""))
        CURRENT.set(session["ws"] if session and session["expires"] > time.time() else "default")  # bearer tokens: the default workspace
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-Id"] = rid
        return response

    def open_workspace(ws):
        """One person's own database and assistant; created on first use."""
        if ws in app.state.workspaces:
            return app.state.workspaces[ws]
        if not all(ch.isalnum() or ch == "-" for ch in ws):
            raise HTTPException(400, "invalid workspace")
        base = app.state.finance
        folder = os.path.join(os.path.dirname(os.path.abspath(base.config.db)), "users")
        config = dataclasses.replace(base.config, db=os.path.join(folder, ws + ".sqlite3"), rpc_url="", live=False, wallet_password="",
                                     wallet_path=os.path.join(folder, ws + ".keystore.json"))
        f = Finance(config, rates=base.rates)  # reference rates are shared; money, plans and memory are not
        a = Agent(f)
        f.exchange_judge = f.page_reader = a.judge
        app.state.workspaces[ws] = (f, a)
        if app.state.run_worker:
            app.state.loop.call_soon_threadsafe(lambda: app.state.tasks.append(asyncio.ensure_future(
                worker.run(f, app.state.stop, alive=lambda: app.state.workspaces.get(ws, (None,))[0] is f))))
        return f, a

    def service() -> Finance:
        return open_workspace(CURRENT.get())[0]

    def assistant() -> Agent:
        return open_workspace(CURRENT.get())[1]

    def demo_enabled():
        evm = service().evm
        live = bool(evm and evm.environment == "live_chain")
        return os.getenv("ENABLE_DEMO_LOGIN") == "true" and not live

    def session_response(response, actor, ws="default", user=None):
        stamp = time.time()
        app.state.sessions = {k: v for k, v in app.state.sessions.items() if v["expires"] > stamp}
        sid = secrets.token_urlsafe(32)
        app.state.sessions[sid] = {"role": actor, "expires": stamp + 28800, "ws": ws, "user": user}
        response.set_cookie("finance_session", sid, max_age=28800, httponly=True, samesite="strict",
                            secure=os.getenv("COOKIE_SECURE") == "true")
        return {"role": actor}

    @app.exception_handler(Denied)
    async def denied(request: Request, exc: Denied):
        # No credentials, request bodies, private keys or raw RPC errors in logs.
        params = {k: v for k, v in exc.params.items() if k in ("checks", "tier", "need", "places")}
        if not getattr(exc, "audited", False):
            service().audit_denial("api", request.url.path, None, str(exc), code=exc.code)
        return SafeJSONResponse(status_code=409, content={"error": str(exc), "code": exc.code, **params})

    # ---------- session ----------
    @app.post("/session")
    def login(body: Login, response: Response):
        return session_response(response, token_role(body.token))

    def client_of(request):
        return request.client.host if request.client else ""

    def owner_token_ok(token):
        expected = os.getenv("OWNER_TOKEN", "")
        return bool(token) and bool(expected) and hmac.compare_digest(token, expected)

    @app.post("/auth/register")
    def register(body: SignUp, request: Request, response: Response):
        claim = owner_token_ok(body.owner_token)
        if body.owner_token and not claim:
            raise Denied("that owner token is not right", "auth_token")
        if os.getenv("ALLOW_SIGNUP", "true") != "true" and not claim:  # closed means closed; only the owner may set up
            raise Denied("new accounts are closed on this instance", "auth_closed")
        user = app.state.users.register(body.email, body.password, body.name, client_of(request), claim_default=claim)
        open_workspace(user["workspace"])
        return dict(session_response(response, "owner", user["workspace"], user), user=dict(email=user["email"], name=user["name"]))

    @app.post("/auth/login")
    def sign_in(body: SignIn, request: Request, response: Response):
        user = app.state.users.verify(body.email, body.password, client_of(request))
        open_workspace(user["workspace"])
        return dict(session_response(response, "owner", user["workspace"], user), user=dict(email=user["email"], name=user["name"]))

    @app.post("/auth/claim")
    def claim_existing(body: Claim, request: Request, actor=Depends(role)):
        """A signed-in account takes over the data already on this computer — with the owner token from .env only."""
        s = app.state.sessions.get(request.cookies.get("finance_session", "")) or {}
        user = s.get("user")
        if not user:
            raise Denied("sign in with your account first", "auth_failed")
        if not owner_token_ok(body.owner_token):
            raise Denied("that owner token is not right", "auth_token")
        old = app.state.users.claim_default(user["id"])
        for v in app.state.sessions.values():
            if (v.get("user") or {}).get("id") == user["id"]:
                v["ws"] = "default"
                v["user"] = dict(v["user"], workspace="default")
        return {"claimed": True, "previous": old}

    def purge_demos(max_age=86400):
        for ws, born in list(app.state.demos.items()):
            if time.time() - born > max_age:
                app.state.demos.pop(ws, None)
                app.state.workspaces.pop(ws, None)
                folder = os.path.join(os.path.dirname(os.path.abspath(app.state.finance.config.db)), "users")
                for suffix in (".sqlite3", ".sqlite3-wal", ".sqlite3-shm"):
                    try:
                        os.remove(os.path.join(folder, ws + suffix))
                    except OSError:
                        pass

    @app.post("/session/demo")
    def demo_login(response: Response):
        if not demo_enabled():
            raise HTTPException(403, "demo login is available only for local use without a live chain")
        purge_demos()
        ws = "demo-" + secrets.token_hex(8)  # every visitor gets their own sandbox: nobody sees anyone else's entries
        app.state.demos[ws] = time.time()
        f, _ = open_workspace(ws)
        for currency, amount in (("AUD", "1000"), ("CNY", "5000"), ("USD", "500")):  # the demo shows test money from the start
            f.add_sandbox_currency("owner", currency, amount)
        return session_response(response, "owner", ws)

    @app.get("/session")
    def session(request: Request, actor=Depends(role)):
        a = assistant()
        s = app.state.sessions.get(request.cookies.get("finance_session", "")) or {}
        user = s.get("user")
        return {"role": actor, "model_configured": a.configured, "model": a.model if a.configured else None,
                "user": dict(email=user["email"], name=user["name"], original=s.get("ws") == "default") if user else None}

    @app.delete("/session")
    def logout(request: Request, response: Response):
        app.state.sessions.pop(request.cookies.get("finance_session", ""), None)
        response.delete_cookie("finance_session")
        return {"logged_out": True}

    # ---------- environment ----------
    @app.get("/health")
    def health():
        f = service()
        return {"status": "ok", "rails": {"sandbox": "local_simulation", "evm": f.evm.environment if f.evm else None},
                "evm_error": f.evm_error, "provider_sandbox_connected": False, "demo_login": demo_enabled(),
                "accounts": app.state.users.count() > 0, "signup": os.getenv("ALLOW_SIGNUP", "true") == "true" or app.state.users.count() == 0}

    @app.get("/capabilities")
    def capabilities(actor=Depends(role)):
        f = service()
        return {"sandbox": "local simulation of a provider sandbox (quotes, idempotent submit, async status)",
                "provider_sandbox_connected": False, "agent_wallet": f.evm.environment if f.evm else None,
                "reference_rates": "ECB via Frankfurter; blended composite only when ECB lacks the pair (labeled)",
                "forecast": "experimental 7-day drift model, backtested against an unchanged-rate baseline",
                "bridge": False, "fiat_on_off_ramp": False,
                "credit": "internal payment-habit indicator only; not a credit score; no bureau reporting"}

    @app.get("/economies")
    def economies(actor=Depends(role)):
        return service().economies()

    @app.get("/routes")
    def routes(actor=Depends(role)):
        return service().routes()

    @app.post("/routes")
    def add_route(body: RouteAdd, actor=Depends(role)):
        return service().add_route(actor, body.send, body.receive)

    @app.patch("/routes/{rid}")
    def update_route(rid: str, body: RouteUpdate, actor=Depends(role)):
        return service().update_route(actor, rid, body.enabled, body.payments_enabled)

    @app.post("/routes/{rid}/verify")
    def verify_route(rid: str, actor=Depends(role)):
        return service().verify_route(actor, rid)

    # ---------- funds ----------
    @app.post("/sandbox/currencies")
    def add_sandbox_currency(body: SandboxCurrency, actor=Depends(role)):
        return service().add_sandbox_currency(actor, body.currency, body.amount)

    @app.delete("/sandbox/currencies/{currency}")
    def remove_sandbox_currency(currency: str, actor=Depends(role)):
        return service().remove_sandbox_currency(actor, currency)

    @app.get("/balances")
    def balances(actor=Depends(role)):
        return service().balances()

    @app.get("/balances/equivalents")
    def equivalents(display: str = "AUD", actor=Depends(role)):
        return service().equivalents(display.upper())

    @app.post("/sandbox/fund")
    def fund(body: Fund, actor=Depends(role)):
        return service().fund(actor, body.currency, body.amount)

    @app.get("/wallet")
    def wallet(actor=Depends(role)):
        return service().wallet()

    # ---------- rates and analysis ----------
    @app.get("/rates")
    def rates(source: str, target: str, days: str = "0", actor=Depends(role)):
        return service().rates.fetch(source.upper(), target.upper(), days)

    @app.get("/rates/latest")
    def latest(source: str, target: str, actor=Depends(role)):
        return service().rates.latest(source.upper(), target.upper())

    @app.get("/rates/forecast")
    def forecast(source: str, target: str, actor=Depends(role)):
        return service().rates.forecast(source.upper(), target.upper())

    @app.post("/compare")
    def compare(body: Compare, actor=Depends(role)):
        return service().compare(actor, body.source.upper(), body.target.upper(), body.amount, body.receive_amount, body.rank)

    @app.post("/scenario")
    def scenario(body: Scenario, actor=Depends(role)):
        return service().scenario(actor, body.source.upper(), body.target.upper(), body.amount, body.rate_change_pct)

    # ---------- recipients and transfers ----------
    @app.get("/recipients")
    def recipients(actor=Depends(role)):
        return service().recipients()

    @app.post("/recipients")
    def recipient(body: Recipient, actor=Depends(role)):
        return service().add_recipient(actor, **body.model_dump())

    @app.post("/recipients/me")
    def own_account(body: OwnAccount, actor=Depends(role)):
        return service().add_own_account(actor, body.currency.upper(), body.bank, body.account.replace(" ", ""), body.country.upper())

    @app.delete("/recipients/me/{rid}")
    def remove_own_account(rid: str, actor=Depends(role)):
        return service().remove_own_account(actor, rid)

    @app.get("/transfers")
    def history(status: str | None = None, rail: str | None = None, actor=Depends(role)):
        return service().history(status, rail)

    @app.post("/transfers")
    def prepare(body: Draft, actor=Depends(role)):
        return service().prepare(actor, **body.model_dump())

    @app.get("/transfers/{tid}")
    def get(tid: str, actor=Depends(role)):
        return service().get(tid)

    @app.get("/transfers/{tid}/checks")
    def checks(tid: str, actor=Depends(role)):
        return service().checks(actor, tid)

    @app.get("/transfers/{tid}/trail")
    def trail(tid: str, actor=Depends(role)):
        return service().trail(actor, tid)

    @app.post("/transfers/{tid}/approve")
    def approve(tid: str, body: Approval, actor=Depends(role)):
        return service().approve(actor, tid, body.approval_digest, body.note)

    @app.post("/transfers/{tid}/execute")
    def execute(tid: str, body: Execute, actor=Depends(role)):
        return service().execute(actor, tid, body.mandate_id)

    @app.post("/transfers/{tid}/reconcile")
    def reconcile(tid: str, actor=Depends(role)):
        return service().reconcile(actor, tid)

    @app.post("/transfers/{tid}/cancel")
    def cancel(tid: str, actor=Depends(role)):
        return service().cancel(actor, tid)

    @app.post("/transfers/{tid}/modify")
    def modify(tid: str, body: Modify, actor=Depends(role)):
        return service().modify(actor, tid, body.idempotency_key, body.amount, body.receive_amount, body.purpose, body.recipient_id)

    # ---------- autonomy and settings ----------
    @app.get("/mandates")
    def mandates(actor=Depends(role)):
        return service().mandates()

    @app.post("/mandates")
    def grant(body: Mandate, actor=Depends(role)):
        return service().grant_mandate(actor, **body.model_dump())

    @app.post("/mandates/{mid}/revoke")
    def revoke(mid: str, actor=Depends(role)):
        return service().revoke(actor, mid)

    @app.get("/settings")
    def settings(actor=Depends(role)):
        return service().settings()

    @app.put("/settings/limits")
    def set_limit(body: Limit, actor=Depends(role)):
        return service().set_limit(actor, body.currency, body.per_payment, body.daily)

    @app.get("/memory")
    def memory(actor=Depends(role)):
        return service().memory()

    @app.put("/memory")
    def remember(body: Preference, actor=Depends(role)):
        return service().remember(actor, **body.model_dump())

    @app.get("/proposals")
    def proposals(actor=Depends(role)):
        return service().proposals()

    @app.post("/proposals/{pid}/decide")
    def decide(pid: str, body: Decide, actor=Depends(role)):
        return service().decide(actor, pid, body.accept, body.note)

    @app.get("/decisions")
    def decisions(actor=Depends(role)):
        return service().decisions()

    @app.post("/decisions")
    def accept(body: Recommendation, actor=Depends(role)):
        return service().accept_recommendation(actor, body.subject, body.detail)

    # ---------- planning and habits ----------
    @app.get("/goals")
    def goals(actor=Depends(role)):
        return service().goals()

    @app.post("/goals")
    def create_goal(body: Goal, actor=Depends(role)):
        return service().create_goal(actor, **body.model_dump())

    @app.patch("/goals/{gid}")
    def update_goal(gid: str, body: GoalUpdate, actor=Depends(role)):
        return service().update_goal(actor, gid, body.status)

    @app.get("/goals/{gid}/plan")
    def goal_plan(gid: str, installments: int = 3, actor=Depends(role)):
        return service().goal_plan(actor, gid, installments)

    @app.get("/budget")
    def budget(actor=Depends(role)):
        return service().budget()

    @app.post("/budget")
    def add_budget(body: BudgetEntry, actor=Depends(role)):
        return service().add_budget(actor, **body.model_dump())

    @app.delete("/budget/{bid}")
    def delete_budget(bid: str, actor=Depends(role)):
        return service().delete_budget(actor, bid)

    @app.get("/obligations")
    def obligations(actor=Depends(role)):
        return service().obligations()

    @app.post("/obligations")
    def add_obligation(body: Obligation, actor=Depends(role)):
        return service().add_obligation(actor, **body.model_dump())

    @app.post("/obligations/{oid}/paid")
    def paid(oid: str, body: Paid, actor=Depends(role)):
        return service().mark_paid(actor, oid, body.paid_date, body.transfer_id)

    @app.delete("/obligations/{oid}")
    def delete_obligation(oid: str, actor=Depends(role)):
        return service().delete_obligation(actor, oid)

    @app.get("/habits")
    def habits(actor=Depends(role)):
        return service().habits()

    @app.get("/reminders")
    def reminders(actor=Depends(role)):
        service().refresh_reminders()
        return service().reminders()

    @app.post("/reminders/{rid}/dismiss")
    def dismiss(rid: int, actor=Depends(role)):
        return service().dismiss(actor, rid)

    @app.get("/rate-alerts")
    def rate_alerts(actor=Depends(role)):
        return service().rate_alerts()

    @app.post("/rate-alerts")
    def add_alert(body: RateAlert, actor=Depends(role)):
        alert = service().add_rate_alert(actor, **body.model_dump(exclude_none=True))
        service().check_rate_alerts()  # fire immediately if the condition already holds
        return alert

    @app.patch("/rate-alerts/{aid}")
    def update_alert(aid: str, body: AlertUpdate, actor=Depends(role)):
        return service().update_rate_alert(actor, aid, body.active)

    # ---------- audit ----------
    @app.get("/audit")
    def audit(q: str | None = None, outcome: str | None = None, actor_filter: str | None = None, limit: int = 300,
              actor=Depends(role)):
        return service().audit(actor, q, outcome, actor_filter, limit)

    # ---------- spending ----------
    @app.get("/expenses")
    def list_expenses(status: str | None = None, month: str | None = None, actor=Depends(role)):
        return service().expenses(status=status, month=month)

    @app.get("/expenses/summary")
    def spending(month: str | None = None, actor=Depends(role)):
        return service().spending_summary(month)

    @app.post("/expenses/import")
    def import_csv(body: CsvImport, actor=Depends(role)):
        return service().import_csv(actor, body.filename, body.content, body.currency, body.account_id)

    @app.post("/expenses/{eid}/match")
    def confirm_match(eid: str, body: dict, actor=Depends(role)):
        return service().confirm_match(actor, eid, bool(body.get("accept")))

    @app.post("/expenses/{eid}/unmatch")
    def unmatch(eid: str, actor=Depends(role)):
        return service().unmatch(actor, eid)

    @app.get("/accounts")
    def accounts(actor=Depends(role)):
        return service().accounts()

    @app.post("/accounts")
    def add_account(body: AccountIn, actor=Depends(role)):
        return service().add_account(actor, body.name, body.type, body.currency, body.balance, body.paid_by, body.payer_name)

    @app.put("/accounts/{aid}/payer")
    def set_account_payer(aid: str, body: AccountPayer, actor=Depends(role)):
        return service().set_account_payer(actor, aid, body.paid_by, body.payer_name)

    @app.delete("/accounts/{aid}")
    def remove_account(aid: str, actor=Depends(role)):
        return service().remove_account(actor, aid)

    @app.post("/expenses/parse")
    def parse_quick(body: QuickText, actor=Depends(role)):
        # Rules first (instant, offline); the AI model reads what they cannot, when asked to.
        try:
            if not body.ai:
                return service().parse_quick(body.text, body.currency)
        except Denied:
            if not assistant().configured:
                raise
            return {"needs_ai": True, "items": []}
        service().require(actor, "prepare")
        return assistant().parse_expense_text(body.text, body.currency)

    @app.post("/expenses/receipt")
    def receipt(body: Receipt, actor=Depends(role)):
        service().owner(actor)
        return assistant().read_documents(body.images or [body.image])

    @app.post("/expenses")
    def add_expense(body: ExpenseIn, actor=Depends(role)):
        return service().add_expense(actor, body.date, body.amount, body.currency, body.description, body.category, body.source,
                                     recurring=body.recurring)

    @app.post("/expenses/review")
    def review(body: ReviewIn, actor=Depends(role)):
        return service().review(actor, [i.model_dump(exclude_none=True) for i in body.items])

    @app.patch("/expenses/{eid}")
    def patch_expense(eid: str, body: ExpensePatch, actor=Depends(role)):
        return service().update_expense(actor, eid, body.category, body.amount, body.description, body.date)

    @app.delete("/expenses/{eid}")
    def delete_expense(eid: str, actor=Depends(role)):
        return service().delete_expense(actor, eid)

    @app.get("/recurring")
    def recurring(actor=Depends(role)):
        return {"active": service().recurring_list(), "candidates": service().detect_recurring()}

    @app.post("/recurring")
    def add_recurring(body: RecurringIn, actor=Depends(role)):
        return service().add_recurring(actor, body.description, body.amount, body.currency, body.category, body.cadence, body.last_date)

    @app.delete("/recurring/{rid}")
    def stop_recurring(rid: str, actor=Depends(role)):
        return service().stop_recurring(actor, rid)

    # ---------- student money ----------
    @app.get("/scholarships")
    def scholarships(actor=Depends(role)):
        return service().scholarships()

    @app.post("/scholarships")
    def add_scholarship(body: ScholarshipIn, actor=Depends(role)):
        return service().add_scholarship(actor, **body.model_dump())

    @app.patch("/scholarships/{sid}")
    def patch_scholarship(sid: str, body: ScholarshipPatch, actor=Depends(role)):
        return service().update_scholarship(actor, sid, **body.model_dump(exclude_none=True))

    @app.delete("/scholarships/{sid}")
    def delete_scholarship(sid: str, actor=Depends(role)):
        return service().delete_scholarship(actor, sid)

    @app.get("/terms")
    def terms(actor=Depends(role)):
        return service().terms()

    @app.post("/terms")
    def add_term(body: TermIn, actor=Depends(role)):
        return service().add_term(actor, **body.model_dump())

    @app.put("/terms/{tid}")
    def update_term(tid: str, body: TermIn, actor=Depends(role)):
        return service().update_term(actor, tid, **body.model_dump())

    @app.delete("/terms/{tid}")
    def delete_term(tid: str, actor=Depends(role)):
        return service().delete_term(actor, tid)

    @app.get("/cashflow")
    def cashflow(currency: str | None = None, months: int = 6, actor=Depends(role)):
        return service().cashflow(currency, months)

    @app.post("/afford")
    def afford(body: AffordIn, actor=Depends(role)):
        return service().afford(actor, body.amount, body.currency, body.date, body.label, body.payer)

    @app.get("/insights")
    def insights(period: str = "month", lang: str = "en", currency: str | None = None, actor=Depends(role)):
        return service().spending_insights(period, lang, currency)

    @app.get("/email")
    def email_settings(actor=Depends(role)):
        service().owner(actor)
        return service().email_settings()

    @app.put("/email")
    def set_email(body: EmailIn, actor=Depends(role)):
        return service().set_email(actor, body.address, body.digest, body.reminders, body.language, body.weekday, body.skip_quiet)

    @app.post("/email/preview")
    def email_preview(body: EmailSend, actor=Depends(role)):
        service().owner(actor)
        r = service().report(body.period if body.period in ("day", "week", "month") else "week", body.language)
        return {"subject": r["subject"], "text": r["text"]}

    @app.post("/email/send")
    def email_send(body: EmailSend, actor=Depends(role)):
        service().owner(actor)
        return service().send_report(actor, body.period)

    # ---------- overview: cash position and exchange needs ----------
    @app.get("/overview/money")
    def overview_money(display: str | None = None, actor=Depends(role)):
        return service().money_overview(display)

    @app.put("/cash")
    def set_cash(body: CashIn, actor=Depends(role)):
        return service().set_cash(actor, body.currency, body.amount, body.label)

    @app.delete("/cash/{currency}")
    def clear_cash(currency: str, actor=Depends(role)):
        return service().clear_cash(actor, currency)

    # ---------- banks: public rates and fees read by AI, and exchange scenarios ----------
    @app.get("/banks")
    def banks(source: str | None = None, target: str | None = None, actor=Depends(role)):
        return service().banks(source, target)

    # ---------- deciding when: waiting in money, rules acted on later ----------
    @app.get("/decide/wait")
    def wait_value(source: str, target: str, amount: str, side: str = "spend", bank: str | None = None, due: str | None = None, actor=Depends(role)):
        return service().wait_value(source, target, amount, side, bank, due)

    @app.get("/fx-rules")
    def fx_rules(actor=Depends(role)):
        return service().fx_rules()

    @app.post("/fx-rules")
    def add_fx_rule(body: FxRuleIn, actor=Depends(role)):
        return service().add_fx_rule(actor, body.source, body.target, body.amount, body.min_rate, body.due, body.mode, body.bank)

    @app.post("/fx-rules/{rid}/execute")
    def execute_fx_rule(rid: str, actor=Depends(role)):
        return service().execute_fx_rule(actor, rid)

    @app.delete("/fx-rules/{rid}")
    def cancel_fx_rule(rid: str, actor=Depends(role)):
        return service().cancel_fx_rule(actor, rid)

    @app.get("/budget/month")
    def get_month_budget(actor=Depends(role)):
        return service().month_budget() or {}

    @app.put("/budget/month")
    def put_month_budget(body: MonthBudget, actor=Depends(role)):
        return service().set_month_budget(actor, body.currency, body.amount) or {}

    @app.post("/banks/auto")
    def banks_auto(body: BankRefresh, actor=Depends(role)):
        service().require(actor, "prepare")
        return service().auto_refresh_banks(body.source, body.target)

    @app.get("/banks/auto")
    def banks_auto_status(source: str, target: str, actor=Depends(role)):
        return service().auto_status(source, target)

    @app.post("/banks/{bank_id}/refresh")
    def refresh_bank(bank_id: str, body: BankRefresh, actor=Depends(role)):
        return service().refresh_bank(actor, bank_id, body.source, body.target, body.urls)

    @app.put("/banks/{bank_id}/pricing")
    def bank_pricing(bank_id: str, body: BankPricing, actor=Depends(role)):
        return service().set_bank_pricing(actor, bank_id, body.source, body.target, body.model_dump(exclude={"source", "target"}))

    @app.post("/exchange-scenarios")
    def exchange_scenarios(body: ScenarioIn, actor=Depends(role)):
        return service().exchange_scenarios(body.source, body.target, body.amount, body.mode, body.send_bank, body.receive_bank, body.due)

    # ---------- exchange plans, the what-if sandbox and gaps ----------
    @app.get("/exchange-plans")
    def exchange_plans(closed: bool = False, actor=Depends(role)):
        return service().exchange_plans(include_closed=closed)

    @app.get("/exchange-plans/suggestions")
    def plan_suggestions(actor=Depends(role)):
        return service().plan_suggestions()

    @app.post("/exchange-plans")
    def add_plan(body: PlanIn, actor=Depends(role)):
        return service().save_plan(actor, body.source, body.target, body.amount, body.side, body.due, body.purpose, body.kind,
                                   body.need_ref, body.min_rate, recipient_id=body.recipient_id, category=body.category)

    @app.put("/exchange-plans/{pid}")
    def update_plan(pid: str, body: PlanIn, actor=Depends(role)):
        return service().save_plan(actor, body.source, body.target, body.amount, body.side, body.due, body.purpose, body.kind,
                                   body.need_ref, body.min_rate, plan_id=pid, recipient_id=body.recipient_id, category=body.category)

    @app.post("/exchange-plans/{pid}/status")
    def plan_status(pid: str, body: PlanStatus, actor=Depends(role)):
        return service().set_plan_status(actor, pid, body.status)

    @app.delete("/exchange-plans/{pid}")
    def delete_plan(pid: str, actor=Depends(role)):
        return service().delete_plan(actor, pid)

    @app.post("/simulate")
    def simulate(body: SimulateIn, actor=Depends(role)):
        return service().simulate(body.display, [x.model_dump() for x in body.extra], body.rate_shift, body.plan_ids)

    @app.post("/sandbox/timeline")
    def sandbox_timeline(body: TimelineIn, actor=Depends(role)):
        return service().timeline(body.display, body.off, body.scenario, body.days, [x.model_dump() for x in body.extra])

    @app.get("/gaps")
    def gaps(display: str | None = None, actor=Depends(role)):
        return service().currency_gaps(display)

    @app.get("/sandbox/ledger")
    def sandbox_ledger(actor=Depends(role)):
        return service().virtual_ledger()

    # ---------- transfer templates (SWIFT and domestic bank instructions) ----------
    @app.get("/transfer-formats")
    def transfer_formats(actor=Depends(role)):
        return service().transfer_formats()

    @app.get("/transfer-templates")
    def transfer_templates(actor=Depends(role)):
        return service().transfer_templates()

    @app.get("/transfer-templates/{tid}")
    def transfer_template(tid: str, reveal: bool = False, actor=Depends(role)):
        return service().transfer_template(tid, actor, reveal)

    @app.post("/transfer-templates/validate")
    def validate_template(body: TemplateCheck, actor=Depends(role)):
        return service().validate_template(body.format, body.fields, body.currency)

    @app.post("/transfer-templates")
    def add_template(body: TemplateIn, actor=Depends(role)):
        return service().save_template(actor, body.name, body.format, body.fields, body.currency, body.recipient_id, body.amount,
                                       body.purpose, body.notes)

    @app.put("/transfer-templates/{tid}")
    def update_template(tid: str, body: TemplateIn, actor=Depends(role)):
        return service().save_template(actor, body.name, body.format, body.fields, body.currency, body.recipient_id, body.amount,
                                       body.purpose, body.notes, tid=tid)

    @app.post("/transfer-templates/{tid}/confirm")
    def confirm_template(tid: str, actor=Depends(role)):
        return service().confirm_template(actor, tid)

    @app.post("/transfer-templates/{tid}/sheet")
    def template_sheet(tid: str, body: SheetIn, actor=Depends(role)):
        return service().template_sheet(actor, tid, body.amount)

    @app.delete("/transfer-templates/{tid}")
    def delete_template(tid: str, actor=Depends(role)):
        return service().delete_template(actor, tid)

    # ---------- AI exchange watch ----------
    @app.get("/exchange-advice")
    def exchange_advice(source: str, target: str, lang: str | None = None, actor=Depends(role)):
        return service().exchange_advice(source, target, lang)

    @app.get("/watches")
    def watches(actor=Depends(role)):
        service().sync_watches()
        return service().watches()

    @app.put("/watches")
    def set_watch(body: WatchIn, actor=Depends(role)):
        return service().set_watch(actor, body.source, body.target, body.amount, body.deadline, body.min_rate, body.note, body.active)

    # ---------- motivation ----------
    @app.get("/motivation")
    def motivation(actor=Depends(role)):
        return service().motivation()

    @app.put("/motivation/settings")
    def motivation_settings(body: MotivationIn, actor=Depends(role)):
        return service().set_motivation(actor, body.enabled, body.celebrate)

    @app.post("/challenges")
    def start_challenge(body: ChallengeIn, actor=Depends(role)):
        return service().start_challenge(actor, body.kind, body.amount, body.currency)

    @app.post("/challenges/{cid}/done")
    def challenge_done(cid: str, actor=Depends(role)):
        return service().finish_challenge(actor, cid, True)

    @app.post("/challenges/{cid}/stop")
    def challenge_stop(cid: str, actor=Depends(role)):
        return service().finish_challenge(actor, cid, False)

    @app.get("/celebrations")
    def celebrations(actor=Depends(role)):
        if service().motivation_settings()["enabled"]:
            service().motivation_refresh()
        return service().celebrations()

    @app.post("/celebrations/seen")
    def celebrations_seen(body: SeenIn, actor=Depends(role)):
        return service().celebrations_seen(actor, body.ids)

    # ---------- agent memory ----------
    @app.get("/agent/memory")
    def agent_memory(actor=Depends(role)):
        mem = assistant().memory
        return {"notes": mem.notes(), "episodes": mem.episodes(limit=40), "preferences": service().memory(),
                "layers": {"conversation_turns": 12, "notes_limit": 200}}

    @app.post("/agent/memory")
    def add_note(body: Note, actor=Depends(role)):
        service().owner(actor)
        return assistant().memory.remember(actor, body.text, body.kind)

    @app.post("/agent/memory/clear")
    def clear_memory(body: Clear, actor=Depends(role)):
        return assistant().memory.clear(actor, body.what)

    # ---------- your data: take it with you, or close the account ----------
    @app.get("/account/export")
    def export_data(request: Request, actor=Depends(role)):
        f = service()
        f.owner(actor)
        s = app.state.sessions.get(request.cookies.get("finance_session", "")) or {}
        user = s.get("user") or {}
        data = dict(exported_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), account=dict(email=user.get("email"), name=user.get("name")),
                    note="everything this workspace holds; signed raw transactions are never exported", tables=export_workspace(f.store))
        with f.store.tx() as c:
            f.store.event(c, actor, "account.export", "ok", None)
        return Response(json.dumps(data, ensure_ascii=False, default=str, indent=1), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="dot-export.json"'})

    @app.post("/account/delete")
    def delete_account(body: Farewell, request: Request, response: Response, actor=Depends(role)):
        s = app.state.sessions.get(request.cookies.get("finance_session", "")) or {}
        user = s.get("user")
        if not user:
            raise Denied("sign in with your account to close it", "auth_failed")
        if user["workspace"] == "default":
            raise Denied("this account holds the data that was already on this computer; export it, or remove it on the server",
                         "account_default")
        if body.email.strip().lower() != user["email"]:
            raise Denied("type your own email to confirm", "auth_failed")
        app.state.users.verify(body.email, body.password, client_of(request))
        ws = user["workspace"]
        # 1) nobody can reach it any more: sessions revoked, the account gone, its background work stopped
        for sid in [k for k, v in app.state.sessions.items() if (v.get("user") or {}).get("id") == user["id"]]:
            app.state.sessions.pop(sid, None)
        app.state.users.delete(user["id"])
        app.state.workspaces.pop(ws, None)  # the worker's alive() turns false
        response.delete_cookie("finance_session")
        # 2) the files: each removal is checked; a failure is recorded, retried later, and said out loud
        folder = os.path.join(os.path.dirname(os.path.abspath(app.state.finance.config.db)), "users")
        failed = []
        for suffix in (".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".keystore.json"):
            path = os.path.join(folder, ws + suffix)
            for attempt in range(3):
                try:
                    os.remove(path)
                    break
                except FileNotFoundError:
                    break
                except OSError:
                    if attempt == 2:
                        failed.append(path)
                    else:
                        time.sleep(.2)
        if failed:
            app.state.users.remember_deletion(failed)
            return JSONResponse(status_code=202, content={"deleted": False, "account_closed": True, "pending_files": len(failed),
                                                          "code": "delete_pending",
                                                          "error": "your account is closed; some data files are still locked and will be deleted on retry"})
        return {"deleted": True}

    @app.delete("/agent/memory/{note_id}")
    def forget_note(note_id: int, actor=Depends(role)):
        service().owner(actor)
        return assistant().memory.forget(actor, note_id)

    # ---------- agent ----------
    @app.post("/chat")
    def chat(body: Chat, actor=Depends(role)):
        if actor not in ("owner", "agent"):
            raise Denied("chat runs as the agent and needs owner or agent access", "permission_denied")
        return assistant().chat(body.message, body.session, body.language)

    @app.post("/chat/stream")
    def chat_stream(body: Chat, actor=Depends(role)):
        if actor not in ("owner", "agent"):
            raise Denied("chat runs as the agent and needs owner or agent access", "permission_denied")
        a = assistant()
        a.pages[body.session] = body.page
        a.check(body.message, body.session)

        def events():
            try:
                for event in a.stream(body.message, body.session, body.language):
                    yield sse(event)
            except Denied as exc:
                yield sse({"type": "message", "text": str(exc), "code": exc.code})
                yield sse({"type": "done"})
        return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.get("/events")
    async def events(request: Request, actor=Depends(role)):
        """Pushes the audit high-water mark so every open screen refreshes when anything changes."""
        f = service()

        async def stream():
            last, idle = None, 0
            while not await request.is_disconnected():
                version = await asyncio.to_thread(f.version)
                if version != last:
                    last, idle = version, 0
                    yield sse({"type": "version", "version": version})
                else:
                    idle += 1
                    if idle % 15 == 0:
                        yield ": keep-alive\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    return app


app = create_app()
