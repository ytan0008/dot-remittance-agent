import asyncio
import hmac
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field
from .domain import Denied, new_request_id
from .service import Finance
from .agent import Agent
from . import worker


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


class Chat(Model):
    message: str = Field(min_length=1, max_length=4000)
    session: str = "default"
    language: str = "en"


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


class Tier(Model):
    tier: int


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
    threshold: str


class AlertUpdate(Model):
    active: bool


class Decide(Model):
    accept: bool
    note: str = ""


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
        viewer = os.getenv("VIEWER_TOKEN", "")
        if viewer and (len(viewer) < 24 or viewer in (owner, agent_token)):
            raise RuntimeError("VIEWER_TOKEN must be distinct and at least 24 characters")
        app.state.finance = finance or Finance()
        app.state.agent = agent or Agent(app.state.finance)
        app.state.sessions = {}
        stop = asyncio.Event()
        run_worker = background if background is not None else os.getenv("ENABLE_WORKER", "true") == "true"
        task = asyncio.create_task(worker.run(app.state.finance, stop)) if run_worker else None
        yield
        stop.set()
        if task:
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
            if request.cookies.get("finance_session") or request.url.path.startswith("/session"):
                if request.headers.get("x-workspace-request") != "1":
                    return JSONResponse(status_code=403, content={"error": "same-origin request header required"})
        rid = new_request_id()
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-Id"] = rid
        return response

    def service() -> Finance:
        return app.state.finance

    def demo_enabled():
        evm = service().evm
        live = bool(evm and evm.environment == "live_chain")
        return os.getenv("ENABLE_DEMO_LOGIN") == "true" and not live

    def session_response(response, actor):
        stamp = time.time()
        app.state.sessions = {k: v for k, v in app.state.sessions.items() if v["expires"] > stamp}
        sid = secrets.token_urlsafe(32)
        app.state.sessions[sid] = {"role": actor, "expires": stamp + 28800}
        response.set_cookie("finance_session", sid, max_age=28800, httponly=True, samesite="strict",
                            secure=os.getenv("COOKIE_SECURE") == "true")
        return {"role": actor}

    @app.exception_handler(Denied)
    async def denied(request: Request, exc: Denied):
        # No credentials, request bodies, private keys or raw RPC errors in logs.
        params = {k: v for k, v in exc.params.items() if k in ("checks", "tier", "need", "places")}
        if not getattr(exc, "audited", False):
            app.state.finance.audit_denial("api", request.url.path, None, str(exc), code=exc.code)
        return SafeJSONResponse(status_code=409, content={"error": str(exc), "code": exc.code, **params})

    # ---------- session ----------
    @app.post("/session")
    def login(body: Login, response: Response):
        return session_response(response, token_role(body.token))

    @app.post("/session/demo")
    def demo_login(response: Response):
        if not demo_enabled():
            raise HTTPException(403, "demo login is available only for local use without a live chain")
        return session_response(response, "owner")

    @app.get("/session")
    def session(actor=Depends(role)):
        a = app.state.agent
        return {"role": actor, "model_configured": a.configured, "model": a.model if a.configured else None,
                "agent_tier": service().agent_tier()}

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
                "evm_error": f.evm_error, "provider_sandbox_connected": False, "demo_login": demo_enabled()}

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

    @app.put("/settings/tier")
    def set_tier(body: Tier, actor=Depends(role)):
        return service().set_agent_tier(actor, body.tier)

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
        return service().add_rate_alert(actor, **body.model_dump())

    @app.patch("/rate-alerts/{aid}")
    def update_alert(aid: str, body: AlertUpdate, actor=Depends(role)):
        return service().update_rate_alert(actor, aid, body.active)

    # ---------- audit ----------
    @app.get("/audit")
    def audit(q: str | None = None, outcome: str | None = None, actor_filter: str | None = None, limit: int = 300,
              actor=Depends(role)):
        return service().audit(actor, q, outcome, actor_filter, limit)

    # ---------- agent ----------
    @app.post("/chat")
    def chat(body: Chat, actor=Depends(role)):
        if actor not in ("owner", "agent"):
            raise Denied("chat runs as the agent and needs owner or agent access", "permission_denied")
        return app.state.agent.chat(body.message, body.session, body.language)

    @app.post("/chat/stream")
    def chat_stream(body: Chat, actor=Depends(role)):
        if actor not in ("owner", "agent"):
            raise Denied("chat runs as the agent and needs owner or agent access", "permission_denied")
        app.state.agent.check(body.message, body.session)

        def events():
            try:
                for event in app.state.agent.stream(body.message, body.session, body.language):
                    yield sse(event)
            except Denied as exc:
                yield sse({"type": "message", "text": str(exc), "code": exc.code})
                yield sse({"type": "done"})
        return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.get("/events")
    async def events(request: Request, actor=Depends(role)):
        """Pushes the audit high-water mark so every open screen refreshes when anything changes."""
        async def stream():
            last, idle = None, 0
            while not await request.is_disconnected():
                version = await asyncio.to_thread(service().version)
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
