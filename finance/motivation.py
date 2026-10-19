"""Encouraging, non-competitive motivation: milestone badges, a forgiving check-in streak, short opt-in challenges,
money-skill levels with clear criteria, and celebration moments.

Design rules: nothing compares students with each other or ranks anyone by how much money they have; nothing nudges
anyone to spend or to save beyond what fits their budget; nothing is shared. Everything is derived from the student's
own activity and can be switched off.
"""
import json
import uuid
from datetime import date, datetime, timedelta
from .domain import Denied, canonical, now, units, decimals

SCHEMA = """
CREATE TABLE IF NOT EXISTS badges (id TEXT PRIMARY KEY, earned INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS challenges (id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL,
    started TEXT NOT NULL, ends TEXT NOT NULL, finished INTEGER, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS celebrations (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, ref TEXT NOT NULL,
    data TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL, UNIQUE(kind, ref));
"""
# Things that count as looking after your money today. Viewing pages is never tracked.
CHECKIN = ("expenses.add", "expenses.review", "expenses.import", "expenses.update", "budget.add", "term.add", "term.update",
           "scholarship.add", "scholarship.update", "rate_alert.add", "goal.create", "goal.update", "recurring.add",
           "obligation.paid", "challenge.done")
REST = 2  # up to two days off in a row never break a streak
STREAK_MILESTONES = (7, 30, 100)

# (badge id, skill group, rule over facts)
BADGES = [
    ("first_log", "tracking", lambda f: f["entries"] >= 1),
    ("logging_week", "tracking", lambda f: f["best_week_days"] >= 5),
    ("first_import", "tracking", lambda f: f["imports"] >= 1),
    ("receipt", "tracking", lambda f: f["receipts"] >= 1),
    ("reviewer", "tracking", lambda f: f["confirmed"] >= 25),
    ("term_plan", "planning", lambda f: f["terms"] >= 1),
    ("buffer", "planning", lambda f: f["buffer"]),
    ("exchange_plan", "planning", lambda f: f["alerts"] >= 1),
    ("streak_7", "habits", lambda f: f["longest"] >= 7),
    ("streak_30", "habits", lambda f: f["longest"] >= 30),
    ("on_track", "habits", lambda f: f["on_track"]),
    ("first_challenge", "habits", lambda f: f["challenges_done"] >= 1),
    ("three_challenges", "habits", lambda f: f["challenges_done"] >= 3),
    ("goal_met", "goals", lambda f: f["goals_done"] >= 1),
    ("applied", "goals", lambda f: f["applied"]),
    ("docs_ready", "goals", lambda f: f["docs_ready"]),
]
BADGE_IDS = [b[0] for b in BADGES]
# Levels describe money skills, never money. Each needs every listed badge.
LEVELS = [(1, ["first_log"]), (2, ["logging_week", "term_plan"]), (3, ["buffer", "exchange_plan", "streak_7", "first_challenge"]),
          (4, ["reviewer", "on_track", "three_challenges"]), (5, ["streak_30", "goal_met"])]
# Short opt-in challenges. auto = measured from activity; self = the student marks it done (nothing to prove).
CHALLENGES = {
    "log_5_days": dict(mode="auto", target=5),
    "clear_review": dict(mode="auto", target=1),
    "plan_term": dict(mode="auto", target=1),
    "one_document": dict(mode="auto", target=1),
    "review_subs": dict(mode="self", target=1),
    "no_spend_day": dict(mode="self", target=1),
    "set_aside": dict(mode="self", target=1),
}
DAYS = 7
MAX_ACTIVE = 3


class MotivationMixin:
    def _motivation_schema(self):
        with self.store.tx() as c:
            c.executescript(SCHEMA)

    # ---------- settings ----------
    def motivation_settings(self):
        s = self._setting("motivation", {})
        return dict(enabled=s.get("enabled", True), celebrate=s.get("celebrate", True))

    def set_motivation(self, actor, enabled=True, celebrate=True):
        self.owner(actor)
        s = self._setting("motivation", {})
        s.update(enabled=bool(enabled), celebrate=bool(celebrate))
        with self.store.tx() as c:
            self._put_setting(c, "motivation", s)
            self.store.event(c, actor, "motivation.settings", "ok", None, enabled=s["enabled"], celebrate=s["celebrate"])
        return self.motivation_settings()

    # ---------- streak ----------
    def _checkin_days(self):
        zone = self.zone()
        since = now() - 400 * 86400
        marks = ",".join("?" * len(CHECKIN))
        with self.store.read() as c:
            rows = c.execute(f"SELECT time FROM audit WHERE actor IN ('owner','agent') AND outcome IN ('ok','pending','confirmed') "
                             f"AND action IN ({marks}) AND time>=?", (*CHECKIN, since)).fetchall()
        return sorted({datetime.fromtimestamp(r["time"], zone).date() for r in rows})

    def _today(self):
        return datetime.now(self.zone()).date()

    def streak(self):
        days, today = self._checkin_days(), self._today()
        runs, run = [], []
        for d in days:
            if run and (d - run[-1]).days > REST + 1:
                runs.append(run)
                run = []
            run.append(d)
        if run:
            runs.append(run)
        last = days[-1] if days else None
        alive = bool(last and (today - last).days <= REST + 1)
        current = runs[-1] if alive else []
        status = "none" if not days else "active" if last == today else "resting" if alive else "welcome_back"
        week0 = today - timedelta(days=today.weekday())
        weeks = []
        for i in range(7, -1, -1):
            start = week0 - timedelta(weeks=i)
            weeks.append(dict(start=str(start), days=sum(1 for d in days if start <= d < start + timedelta(days=7))))
        return dict(current=len(current), span=(today - current[0]).days + 1 if current else 0, longest=max((len(r) for r in runs), default=0),
                    status=status, last=str(last) if last else None, safe_until=str(last + timedelta(days=REST + 1)) if alive else None,
                    today=last == today, rest_days=REST, weeks=weeks)

    # ---------- facts ----------
    def _motivation_facts(self, streak):
        today = self._today()
        with self.store.read() as c:
            q = lambda sql, *a: c.execute(sql, a).fetchone()[0]  # noqa: E731
            entries = q("SELECT COUNT(*) FROM expenses WHERE status<>'skipped'")
            confirmed = q("SELECT COUNT(*) FROM expenses WHERE status='confirmed'")
            imports = q("SELECT COUNT(*) FROM expense_imports")
            receipts = q("SELECT COUNT(*) FROM expenses WHERE source='receipt' AND status<>'skipped'")
            alerts = q("SELECT COUNT(*) FROM rate_alerts")
            done = q("SELECT COUNT(*) FROM challenges WHERE status='completed'")
        log_days = sorted(d for d in self._checkin_days())
        best = 0
        for i, d in enumerate(log_days):
            best = max(best, sum(1 for x in log_days[i:] if (x - d).days < 7))
        scholarships = self.scholarships()
        goals = self.goals()
        budget = self.budget()
        on_track = False
        try:
            ins = self.spending_insights("month")
            on_track = bool(ins["budget"] and ins["count"] >= 10 and ins["total"] <= ins["budget"])
        except Denied:
            pass
        return dict(entries=entries, confirmed=confirmed, imports=imports, receipts=receipts, alerts=alerts, challenges_done=done,
                    best_week_days=best, terms=len(self.terms()), buffer=any(b["kind"] == "buffer" for b in budget),
                    longest=streak["longest"], on_track=on_track,
                    goals_done=sum(1 for g in goals if g["status"] == "done" or (g["remaining"] <= 0 and g["completed"] > 0)),
                    applied=any(s["status"] in ("submitted", "interview", "awarded", "rejected") for s in scholarships),
                    docs_ready=any(s["docs_total"] and s["docs_done"] == s["docs_total"] for s in scholarships),
                    pending=sum(1 for _ in self.expenses(status="pending", limit=5000)),
                    subscriptions=len({e["merchant"] for e in self.expenses(status="confirmed", limit=5000)
                                       if e["category"] == "subscriptions" and e["date"] >= str(today - timedelta(days=45))}),
                    open_docs=any(s["open"] and s["docs_done"] < s["docs_total"] for s in scholarships),
                    docs_done=sum(s["docs_done"] for s in scholarships), today=today)

    # ---------- challenges ----------
    def _challenge_view(self, r):
        body = json.loads(r["body"])
        ends = date.fromisoformat(r["ends"])
        return dict(id=r["id"], kind=r["kind"], status=r["status"], started=r["started"], ends=r["ends"], finished=r["finished"],
                    days_left=max(0, (ends - self._today()).days), mode=CHALLENGES[r["kind"]]["mode"], **body)

    def challenges(self, status=None):
        sql, args = "SELECT * FROM challenges", ()
        if status:
            sql, args = sql + " WHERE status=?", (status,)
        with self.store.read() as c:
            return [self._challenge_view(r) for r in c.execute(sql + " ORDER BY created DESC LIMIT 50", args)]

    def suggested_amount(self, currency=None):
        """A small, comfortable amount: at most 10 units, and never more than 5% of a week's planned living costs."""
        currency = currency or self._plan_currency()
        unit = 10 ** decimals(currency)
        weekly = self._month_budget(currency, self._today()) * 7 // 30
        cap = weekly * 5 // 100 if weekly else 10 * unit
        amount = min(10 * unit, max(unit, cap))
        return dict(amount=amount // unit * unit or unit, currency=currency, weekly_budget=weekly or None)

    def start_challenge(self, actor, kind, amount=None, currency=None):
        self.require(actor, "prepare")
        if kind not in CHALLENGES:
            raise Denied("unknown challenge", "challenge_invalid")
        active = self.challenges("active")
        if len(active) >= MAX_ACTIVE:
            raise Denied(f"at most {MAX_ACTIVE} challenges at a time", "challenge_limit")
        if any(x["kind"] == kind for x in active):
            raise Denied("this challenge is already running", "challenge_active")
        body = {"progress": 0, "target": CHALLENGES[kind]["target"]}
        if kind == "set_aside":
            hint = self.suggested_amount(currency)
            currency = hint["currency"]
            minor = units(str(amount), decimals(currency)) if amount not in (None, "") else hint["amount"]
            cap = max(hint["weekly_budget"] // 4 if hint["weekly_budget"] else 100 * 10 ** decimals(currency), hint["amount"])
            if minor > cap:  # never encourage saving beyond what fits
                raise Denied("choose a smaller amount that comfortably fits your budget", "challenge_amount", cap=cap)
            body.update(amount=minor, currency=currency)
        if kind == "one_document":
            body["baseline"] = sum(s["docs_done"] for s in self.scholarships())
        today = self._today()
        cid = str(uuid.uuid4())
        with self.store.tx() as c:
            c.execute("INSERT INTO challenges VALUES (?,?,?,?,?,?,?,?)",
                      (cid, kind, canonical(body), "active", str(today), str(today + timedelta(days=DAYS - 1)), None, now()))
            self.store.event(c, actor, "challenge.start", "ok", cid, kind=kind)
        self.motivation_refresh()
        return next(x for x in self.challenges() if x["id"] == cid)

    def finish_challenge(self, actor, cid, done=True):
        """Mark a self-reported challenge done, or stop any challenge early — stopping is never a failure."""
        self.owner(actor)
        with self.store.tx() as c:
            r = c.execute("SELECT * FROM challenges WHERE id=? AND status='active'", (cid,)).fetchone()
            if not r:
                raise Denied("challenge not found or already finished", "challenge_unknown")
            if done and CHALLENGES[r["kind"]]["mode"] != "self":
                raise Denied("this challenge completes by itself as you go", "challenge_auto")
            status = "completed" if done else "stopped"
            body = json.loads(r["body"])
            if done:
                body["progress"] = body["target"]
            c.execute("UPDATE challenges SET status=?, body=?, finished=? WHERE id=?", (status, canonical(body), now(), cid))
            self.store.event(c, actor, "challenge.done" if done else "challenge.stop", "ok", cid, kind=r["kind"])
            if done:
                self._celebrate(c, "challenge", cid, dict(kind=r["kind"]))
        self.motivation_refresh()
        return next(x for x in self.challenges() if x["id"] == cid)

    def _progress(self, ch, facts):
        kind, start = ch["kind"], date.fromisoformat(ch["started"])
        if kind == "log_5_days":
            with self.store.read() as c:
                rows = c.execute("SELECT time FROM audit WHERE action IN ('expenses.add','expenses.import') AND actor IN ('owner','agent') "
                                 "AND time>=?", (int(datetime.combine(start, datetime.min.time(), self.zone()).timestamp()),)).fetchall()
            return len({datetime.fromtimestamp(r["time"], self.zone()).date() for r in rows})
        if kind == "clear_review":
            with self.store.read() as c:
                reviewed = c.execute("SELECT COUNT(*) FROM audit WHERE action='expenses.review' AND time>=?",
                                     (int(datetime.combine(start, datetime.min.time(), self.zone()).timestamp()),)).fetchone()[0]
            return 1 if facts["pending"] == 0 and reviewed else 0
        if kind == "plan_term":
            return 1 if facts["terms"] else 0
        if kind == "one_document":
            return 1 if facts["docs_done"] > ch.get("baseline", 0) else 0
        return ch["progress"]

    def suggestions(self, facts=None):
        facts = facts or self._motivation_facts(self.streak())
        running = {x["kind"] for x in self.challenges("active")}
        recent = {x["kind"] for x in self.challenges() if x["status"] == "completed" and x["finished"] and x["finished"] > now() - 14 * 86400}
        order = []
        if facts["pending"]:
            order.append("clear_review")
        if facts["subscriptions"] >= 2:
            order.append("review_subs")
        if not facts["terms"]:
            order.append("plan_term")
        if facts["open_docs"]:
            order.append("one_document")
        order += ["log_5_days", "no_spend_day", "set_aside", "review_subs"]
        out = []
        for k in order:
            if k not in running and k not in recent and k not in out:
                out.append(k)
        return [dict(kind=k, mode=CHALLENGES[k]["mode"], **({"suggested": self.suggested_amount()} if k == "set_aside" else {}))
                for k in out[:4]]

    # ---------- evaluation and celebrations ----------
    @staticmethod
    def _celebrate(c, kind, ref, data):
        c.execute("INSERT OR IGNORE INTO celebrations(kind,ref,data,created) VALUES (?,?,?,?)", (kind, str(ref), canonical(data), now()))

    def motivation_refresh(self):
        streak = self.streak()
        facts = self._motivation_facts(streak)
        first_run = not self._setting("motivation_init", False)
        with self.store.tx() as c:
            for r in c.execute("SELECT * FROM challenges WHERE status='active'").fetchall():
                ch = self._challenge_view(r)
                body = json.loads(r["body"])
                body["progress"] = progress = min(body["target"], self._progress(ch, facts))
                if CHALLENGES[r["kind"]]["mode"] == "auto" and progress >= body["target"]:
                    c.execute("UPDATE challenges SET status='completed', body=?, finished=? WHERE id=?", (canonical(body), now(), r["id"]))
                    self.store.event(c, "system", "challenge.done", "ok", r["id"], kind=r["kind"])
                    self._celebrate(c, "challenge", r["id"], dict(kind=r["kind"]))
                elif self._today() > date.fromisoformat(r["ends"]):
                    c.execute("UPDATE challenges SET status='ended', body=?, finished=? WHERE id=?", (canonical(body), now(), r["id"]))
                else:
                    c.execute("UPDATE challenges SET body=? WHERE id=?", (canonical(body), r["id"]))
            facts["challenges_done"] = c.execute("SELECT COUNT(*) FROM challenges WHERE status='completed'").fetchone()[0]
            earned = {r["id"] for r in c.execute("SELECT id FROM badges")}
            for bid, group, rule in BADGES:
                if bid not in earned and rule(facts):
                    c.execute("INSERT INTO badges VALUES (?,?)", (bid, now()))
                    earned.add(bid)
                    self._celebrate(c, "badge", bid, dict(group=group))
            level = 0
            for n, needs in LEVELS:
                if all(b in earned for b in needs):
                    level = n
                else:
                    break
            if level > 1:
                self._celebrate(c, "level", level, dict(level=level))
            for m in STREAK_MILESTONES:
                if streak["longest"] >= m:
                    self._celebrate(c, "streak", m, dict(days=m))
            for g in self.goals():
                if g["status"] == "done" or (g["remaining"] <= 0 and g["completed"] > 0):
                    self._celebrate(c, "goal", g["id"], dict(title=g["title"]))
            for s in self.scholarships():
                if s["status"] == "awarded":
                    self._celebrate(c, "awarded", s["id"], dict(name=s["name"]))
            if first_run:
                # History before this feature existed is acknowledged quietly, not as a burst of pop-ups.
                c.execute("UPDATE celebrations SET seen=1")
                self._put_setting(c, "motivation_init", True)
        return facts, streak

    def motivation(self):
        facts, streak = self.motivation_refresh()
        with self.store.read() as c:
            earned = {r["id"]: r["earned"] for r in c.execute("SELECT * FROM badges")}
        level, nxt = 0, None
        for n, needs in LEVELS:
            if all(b in earned for b in needs):
                level = n
            else:
                nxt = dict(level=n, needs=[dict(badge=b, done=b in earned) for b in needs])
                break
        challenges = self.challenges()
        return dict(settings=self.motivation_settings(), level=level, max_level=LEVELS[-1][0], next=nxt,
                    levels=[dict(level=n, needs=needs, reached=n <= level) for n, needs in LEVELS],
                    badges=[dict(id=b, group=g, earned=earned.get(b)) for b, g, _ in BADGES],
                    streak=streak, active=[x for x in challenges if x["status"] == "active"],
                    history=[x for x in challenges if x["status"] != "active"][:8], suggestions=self.suggestions(facts),
                    celebrations=self.celebrations(), principles=["no_ranking", "no_pressure", "private"])

    def celebrations(self):
        s = self.motivation_settings()
        if not (s["enabled"] and s["celebrate"]):
            return []
        with self.store.read() as c:
            return [dict(id=r["id"], kind=r["kind"], ref=r["ref"], data=json.loads(r["data"]), created=r["created"])
                    for r in c.execute("SELECT * FROM celebrations WHERE seen=0 ORDER BY id LIMIT 5")]

    def celebrations_seen(self, actor, ids):
        if actor not in ("owner", "viewer"):
            raise Denied("only a person can dismiss celebrations", "permission_denied")
        ids = [int(i) for i in ids][:50]
        with self.store.tx() as c:
            c.executemany("UPDATE celebrations SET seen=1 WHERE id=?", [(i,) for i in ids])
        return {"seen": ids}

    def motivation_reminders(self):
        out, today = [], self._today()
        if not self.motivation_settings()["enabled"]:
            return out
        for ch in self.challenges("active"):
            if ch["ends"] == str(today) and ch["mode"] == "self":
                out.append((f"challenge:{ch['id']}:last", "challenge_ending", ch["id"], "info", dict(kind=ch["kind"])))
        return out
