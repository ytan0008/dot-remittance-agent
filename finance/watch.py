"""AI exchange watch: the assistant judges by itself when exchanging looks timely and reminds the student; the student
can add their own needs (amount, deadline, an acceptable rate, a note) that every judgment must respect.

The model (when configured) decides from computed signals; a transparent rule engine is the fallback and the guard:
a rate below the student's acceptable rate is never called a good time, and a close deadline is never told to wait.
Custom rules (target rate, favorable level, date) stay available on top. Nothing here exchanges or moves money.
"""
import json
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from .domain import Denied, canonical, now, decimals

SCHEMA = """
CREATE TABLE IF NOT EXISTS rate_watches (id TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL, body TEXT NOT NULL,
    origin TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created INTEGER NOT NULL, verdict TEXT, checked INTEGER,
    UNIQUE(source, target));
"""
VERDICTS = ("good_time", "deadline", "wait", "below_floor", "neutral")
REMIND = ("good_time", "deadline")  # verdicts worth a reminder when the judgment changes into them
CONFIDENCE = ("low", "medium", "high")
EVENT_KINDS = ("rate_target", "rate_favorable", "exchange_due", "ai_good_time", "ai_deadline")  # one-off events, not live states


def _pct(a, b):
    return float((Decimal(a) / Decimal(b) - 1) * 100) if b and Decimal(b) else 0.0


def judge_prompt(signals, prefs, language):
    return ("You decide whether a student should exchange currency now. Data (JSON): "
            + json.dumps(dict(signals=signals, student_needs=prefs), ensure_ascii=False)
            + "\nHigher rate = more target currency per source unit = better for the student. Reply with JSON only: "
              '{"verdict": "good_time|wait|deadline|neutral", "confidence": "low|medium|high", "reason": "..."} '
              f"where reason is at most two short sentences in language code {language}, speaking to the user directly as \"you\", "
              "plain words, citing the numbers. "
              "Rules: forecasts are experimental, never promise future rates; if the deadline is within 5 days prefer "
              "'deadline'; never answer 'good_time' when the rate is below the student's acceptable rate; when unsure say 'neutral'.")


def parse_judgment(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    verdict, conf = data.get("verdict"), data.get("confidence", "medium")
    if verdict not in VERDICTS or conf not in CONFIDENCE:
        return None
    return dict(verdict=verdict, confidence=conf, reason=str(data.get("reason") or "")[:400])


class WatchMixin:
    exchange_judge = None  # set by the API to the agent's model call: (prompt) -> text or None

    def _watch_schema(self):
        with self.store.tx() as c:
            c.executescript(SCHEMA)

    # ---------- watches and the student's needs ----------
    @staticmethod
    def _watch_view(r):
        return dict(id=r["id"], source=r["source"], target=r["target"], origin=r["origin"], active=bool(r["active"]),
                    created=r["created"], checked=r["checked"], **json.loads(r["body"]),
                    last=json.loads(r["verdict"]) if r["verdict"] else None)

    def watches(self):
        with self.store.read() as c:
            return [self._watch_view(r) for r in c.execute("SELECT * FROM rate_watches ORDER BY created")]

    def watch(self, source, target):
        with self.store.read() as c:
            r = c.execute("SELECT * FROM rate_watches WHERE source=? AND target=?", (source, target)).fetchone()
        return self._watch_view(r) if r else None

    def _validate_needs(self, source, target, amount, deadline, min_rate, note):
        out = dict(amount=None, deadline=None, min_rate=None, note=str(note or "").strip()[:200])
        if amount not in (None, ""):
            try:
                value = Decimal(str(amount))
                if not value.is_finite() or value <= 0:
                    raise InvalidOperation
                out["amount"] = int(value * 10 ** decimals(target))  # what the student needs to receive
            except InvalidOperation:
                raise Denied("amount must be a positive number", "watch_invalid") from None
        if deadline:
            try:
                d = date.fromisoformat(str(deadline))
            except ValueError:
                raise Denied("deadline must be YYYY-MM-DD", "date_invalid") from None
            if d < date.today():
                raise Denied("the deadline has already passed", "date_invalid")
            out["deadline"] = str(d)
        if min_rate not in (None, ""):
            try:
                rate = Decimal(str(min_rate))
                if not rate.is_finite() or rate <= 0:
                    raise InvalidOperation
                out["min_rate"] = str(rate)
            except InvalidOperation:
                raise Denied("acceptable rate must be a positive number", "watch_invalid") from None
        return out

    def set_watch(self, actor, source, target, amount=None, deadline=None, min_rate=None, note="", active=True):
        """Human-assisted: the student (or the agent on the student's words) states what they need; the AI respects it."""
        self.require(actor, "prepare")
        source, target = (source or "").upper(), (target or "").upper()
        if not re.fullmatch(r"[A-Z]{3}", source) or not re.fullmatch(r"[A-Z]{3}", target) or source == target:
            raise Denied("distinct uppercase ISO currency pair required", "pair_invalid")
        body = self._validate_needs(source, target, amount, deadline, min_rate, note)
        with self.store.tx() as c:
            c.execute("INSERT INTO rate_watches(id,source,target,body,origin,active,created) VALUES (?,?,?,?,?,?,?) "
                      "ON CONFLICT(source,target) DO UPDATE SET body=excluded.body, origin='user', active=excluded.active, verdict=NULL",
                      (str(uuid.uuid4()), source, target, canonical(body), "user", int(bool(active)), now()))
            self.store.event(c, actor, "watch.set", "ok", f"{source}-{target}", active=bool(active),
                             deadline=body["deadline"], has_floor=body["min_rate"] is not None)
        return self.watch(source, target)

    def sync_watches(self):
        """Watch the pairs the student actually uses: active goals and recent transfers. A watch turned off stays off."""
        pairs = {}
        for g in self.goals():
            if g["status"] == "active" and g["remaining"] > 0:
                pairs.setdefault((g["source"], g["target"]), dict(amount=g["remaining"], deadline=g["deadline"], min_rate=None,
                                                                  note=g["title"][:200]))
        for t in self.history(limit=60):
            b = t["details"]
            if t["created"] > now() - 60 * 86400 and b.get("rail", "sandbox") == "sandbox":
                pairs.setdefault((b["source"], b["target"]), dict(amount=None, deadline=None, min_rate=None, note=""))
        with self.store.tx() as c:
            for (s, t), body in pairs.items():
                if body["deadline"] and body["deadline"] < str(date.today()):
                    body["deadline"] = None
                c.execute("INSERT OR IGNORE INTO rate_watches(id,source,target,body,origin,active,created) VALUES (?,?,?,?,?,?,?)",
                          (str(uuid.uuid4()), s, t, canonical(body), "auto", 1, now()))
        return len(pairs)

    # ---------- signals and judgment ----------
    def exchange_signals(self, source, target, needs=None):
        needs = needs or {}
        latest = self.rates.latest(source, target)
        h90 = self.rates.fetch(source, target, "90")
        h30 = self.rates.fetch(source, target, "30")
        fc = self.rates.forecast(source, target)
        rate = latest["rate"]
        series = h90.get("series") or []
        recent = [r["rate"] for r in series[-6:]]
        sig = dict(rate=rate, observed=latest["observed"], provider=latest.get("provider"),
                   percentile_90d=round(float(h90["percentile"]), 1), percentile_30d=round(float(h30["percentile"]), 1),
                   average_90d=h90["average"], vs_average_pct=round(_pct(rate, h90["average"]), 2),
                   high_90d=h90["maximum"], low_90d=h90["minimum"],
                   trend_5obs_pct=round(_pct(recent[-1], recent[0]), 2) if len(recent) > 1 else 0.0,
                   forecast_available=bool(fc.get("available")))
        if fc.get("available"):
            sig.update(forecast_change_pct=round(_pct(fc["point"], rate), 2), forecast_interval=fc["interval_80"],
                       forecast_beats_baseline=bool(fc["beats_baseline"]))
        days_left = (date.fromisoformat(needs["deadline"]) - date.today()).days if needs.get("deadline") else None
        sig.update(days_left=days_left, acceptable_rate=needs.get("min_rate"),
                   below_acceptable=bool(needs.get("min_rate") and Decimal(rate) < Decimal(needs["min_rate"])))
        return sig

    @staticmethod
    def rule_verdict(sig):
        """Transparent fallback, and the reasons shown with every judgment."""
        p, days = sig["percentile_90d"], sig["days_left"]
        fc_up = sig.get("forecast_beats_baseline") and sig.get("forecast_change_pct", 0) > 0.5
        reasons = [dict(code="percentile", p=p), dict(code="vs_average", pct=sig["vs_average_pct"])]
        if sig["trend_5obs_pct"]:
            reasons.append(dict(code="trend", pct=sig["trend_5obs_pct"]))
        if sig.get("forecast_available"):
            reasons.append(dict(code="forecast" if sig.get("forecast_beats_baseline") else "forecast_weak",
                                pct=sig.get("forecast_change_pct", 0)))
        if days is not None:
            reasons.append(dict(code="deadline", days=days))
        if sig["acceptable_rate"]:
            reasons.append(dict(code="below_floor" if sig["below_acceptable"] else "above_floor", rate=sig["acceptable_rate"]))
        if sig["below_acceptable"]:
            verdict = "deadline" if days is not None and days <= 5 else "below_floor"
        elif days is not None and days <= 5:
            verdict = "deadline"
        elif p >= 75 and not (fc_up and (days is None or days > 7)):
            verdict = "good_time"
        elif p <= 35 and (days is None or days > 14):
            verdict = "wait"
        else:
            verdict = "neutral"
        confidence = "high" if sig.get("forecast_beats_baseline") and (p >= 85 or p <= 15) else "medium" if sig.get("forecast_available") else "low"
        return verdict, confidence, reasons

    def exchange_advice(self, source, target, language=None, use_model=True):
        source, target = (source or "").upper(), (target or "").upper()
        if not re.fullmatch(r"[A-Z]{3}", source) or not re.fullmatch(r"[A-Z]{3}", target) or source == target:
            raise Denied("distinct uppercase ISO currency pair required", "pair_invalid")
        language = language or self.memory().get("language") or "en"
        w = self.watch(source, target)
        needs = {k: w[k] for k in ("amount", "deadline", "min_rate", "note")} if w else {}
        planned = self.pair_plan_needs(source, target)  # the student's exchange plans for this pair are needs too
        if planned:
            dates = [d for d in (needs.get("deadline"), planned["deadline"]) if d]
            floors = [Decimal(r) for r in (needs.get("min_rate"), planned["min_rate"]) if r]
            needs = dict(amount=planned["amount"] or needs.get("amount"), deadline=min(dates) if dates else None,
                         min_rate=str(max(floors)) if floors else None,
                         note=" · ".join(x for x in (needs.get("note"), planned["note"]) if x)[:200], plans=planned["plans"])
        sig = self.exchange_signals(source, target, needs)
        key = canonical([sig["observed"], sig["rate"], needs, language, bool(use_model and self.exchange_judge)])
        if w and w["last"] and w["last"].get("key") == key:
            return w["last"]  # same data, same needs: no second model call
        cache = getattr(self, "_advice_cache", None)
        if cache is None:
            cache = self._advice_cache = {}
        if not w and key in cache:
            return cache[key]
        verdict, confidence, reasons = self.rule_verdict(sig)
        judged_by, explanation = "rules", None
        if use_model and self.exchange_judge:
            try:
                judged = parse_judgment(self.exchange_judge(judge_prompt(sig, needs, language)))
            except Exception:
                judged = None
            if judged:
                verdict, confidence, explanation, judged_by = judged["verdict"], judged["confidence"], judged["reason"], "model"
        # The student's needs are hard limits, whoever judged.
        if sig["below_acceptable"] and verdict == "good_time":
            verdict = "below_floor"
        if sig["days_left"] is not None and sig["days_left"] <= 2 and verdict == "wait":
            verdict = "deadline"
        out = dict(source=source, target=target, verdict=verdict, confidence=confidence, judged_by=judged_by, explanation=explanation,
                   reasons=reasons, signals=sig, needs=needs, watching=bool(w and w["active"]), origin=w["origin"] if w else None,
                   observed=sig["observed"], checked_at=now(), key=key,
                   note="a judgment on daily reference rates, not a quote or a promise; nothing is exchanged automatically")
        if w:
            with self.store.tx() as c:
                c.execute("UPDATE rate_watches SET verdict=?, checked=? WHERE id=?", (canonical(out), now(), w["id"]))
        else:
            cache[key] = out
        return out

    def check_watches(self):
        """Worker: keep watches in sync, judge each active pair, remind when the judgment turns actionable."""
        self.sync_watches()
        fired = []
        for w in self.watches():
            if not w["active"]:
                continue
            before = (w["last"] or {}).get("verdict")
            try:
                adv = self.exchange_advice(w["source"], w["target"])
            except Denied:
                continue
            if adv["verdict"] in REMIND and adv["verdict"] != before:
                sig = adv["signals"]
                data = dict(source=w["source"], target=w["target"], rate=sig["rate"], percentile=sig["percentile_90d"],
                            deadline=sig["days_left"] is not None and w.get("deadline") or "", days_left=sig["days_left"],
                            why=adv["explanation"] or "", judged_by=adv["judged_by"])
                with self.store.tx() as c:
                    if self._remind(c, f"watch:{w['id']}:{adv['verdict']}:{sig['observed']}", "ai_" + adv["verdict"], w["id"], "warn", data):
                        self.store.event(c, "system", "watch.remind", "ok", f"{w['source']}-{w['target']}", verdict=adv["verdict"],
                                         judged_by=adv["judged_by"])
                        fired.append(w["id"])
        return fired
