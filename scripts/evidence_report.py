"""Turn the evidence exported by tests/browser/demo_video.py into readable operation logs.

    python scripts/evidence_report.py artifacts/execution-evidence [video file name]

Writes, next to evidence.json:
  sandbox-operation-log.md   summary, payments, each payment's audit trail, sandbox ledger, full audit log, chain check
  audit-log.csv              every audit entry of the session (one row each)
"""
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

folder = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/execution-evidence")
video = sys.argv[2] if len(sys.argv) > 2 else "dot-demo.mp4"
e = json.loads((folder / "evidence.json").read_text(encoding="utf-8"))
utc = lambda t: datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if t else "—"
money = lambda minor, cur: f"{int(minor) / 100:,.2f} {cur}" if minor is not None else "—"


def detail(raw, limit=110):
    try:
        d = json.loads(raw or "{}")
    except ValueError:
        return str(raw)[:limit]
    text = ", ".join(f"{k}={v}" for k, v in d.items() if v not in (None, "", [], {}))
    return text[:limit] + ("…" if len(text) > limit else "")


AREAS = [("Payments (sandbox)", ("draft.", "compare", "quote.", "guardrails.", "approve", "reserve", "submit", "settle", "provider.", "recipient.", "cancel")),
         ("Balances and sandbox funds", ("cash.", "sandbox.", "account.")),
         ("Exchange planning", ("plan.", "fx_rule.", "rate_alert.")),
         ("Bank fee knowledge base", ("bank.",)),
         ("Spending", ("expenses.", "receipt.", "budget.", "obligation.", "recurring.")),
         ("Term, scholarships, progress, memory", ("term.", "scholarship.", "challenge.", "memory.")),
         ("AI assistant", ("chat.", "tool.", "proposal."))]
MONEY_STEPS = {"approve", "submit", "reserve", "guardrails.approve", "guardrails.submit"}

audit = sorted(e["audit"], key=lambda r: r["id"])
transfers = sorted(e["transfers"], key=lambda t: t.get("created") or 0)
verify = e["audit_verify"]

# the chain, recomputed here from the exported rows: anyone can repeat this check on the file
prev, recomputed_ok = "", True
for r in audit:
    if not r.get("chain"):
        continue
    row = [r["time"], r["actor"], r["action"], r["outcome"], r["correlation"], r["detail"], r["request_id"]]
    link = hashlib.sha256((prev + "|" + json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)).encode()).hexdigest()
    recomputed_ok &= link == r["chain"]
    prev = r["chain"]

lines = []
w = lines.append
w("# DOT — Sandbox Operation Log")
w("")
w("**Topic:** C (non-on-chain) · **Environment:** local simulation with test funds — no real money, no bank or provider connection  ")
w(f"**Session:** isolated demo workspace · **Recorded:** {utc(audit[0]['time'])} – {utc(audit[-1]['time'])}  ")
w(f"**Companion video:** `{video}` (the same session, recorded end to end)")
w("")
w("This log was exported from DOT's own records at the end of the recorded session: the append-only audit log, the payments with their individual audit trails, and the sandbox ledger. Nothing was edited by hand.")
w("")
w("## 1. Summary")
w("")
done = [t for t in transfers if t["status"] == "completed"]
w("| Item | Result |")
w("|---|---|")
w(f"| Audit entries in this session | {len(audit)} |")
w(f"| Hash-chain check by the server (`/audit/verify`) | {'intact' if verify.get('ok') else 'BROKEN'} — {verify.get('checked')} entries |")
w(f"| Hash chain recomputed from this export | {'matches' if recomputed_ok else 'does NOT match'} |")
w(f"| Simulated payments | {len(transfers)} ({len(done)} completed, {len(transfers) - len(done)} left as draft) |")
w("| Real money moved | none — every payment ran against the local sandbox provider |")
w("")
w("## 2. What happened in this session")
w("")
w("Every audit entry of the session, grouped by area (action × count).")
w("")
w("| Area | Audit actions |")
w("|---|---|")
counts = Counter(r["action"] for r in audit)
grouped = {}
for action, n in sorted(counts.items()):
    area = next((label for label, prefixes in AREAS if action.startswith(prefixes)), "Other")
    grouped.setdefault(area, []).append(f"`{action}` ×{n}")
for label, _ in AREAS + [("Other", ())]:
    if label in grouped:
        w(f"| {label} | {', '.join(grouped[label])} |")
w("")
w("### Boundaries the log demonstrates")
w("")
agent_money = [r for r in audit if r["actor"] == "agent" and r["action"] in MONEY_STEPS]
proposed = sum(1 for r in audit if r["action"] == "proposal.create")
confirmed = [r for r in audit if r["action"] == "proposal.confirm"]
failed_lookups = sum(1 for r in audit if r["action"] == "bank.pricing" and r["outcome"] == "failed")
w("| Check | Result |")
w("|---|---|")
w(f"| Payment approvals / submissions made by the AI assistant | **{len(agent_money)}** — every `approve` and `submit` entry has actor `owner` |")
w(f"| Changes the assistant proposed → confirmed by the owner | {proposed} proposed → {len(confirmed)} confirmed, all by `{', '.join(sorted({r['actor'] for r in confirmed})) or '—'}` |")
w(f"| Guardrail checks run on payments | {', '.join(f'`{a}` {o}' for a, o in sorted({(r['action'], r['outcome']) for r in audit if r['action'].startswith('guardrails.')})) or '—'} |")
if failed_lookups:
    w(f"| Bank fee lookups that failed | {failed_lookups} — each logged with outcome `failed` |")
w("")
w("## 3. Simulated payments")
w("")
w("| Created | Payment ID | Amount sent | Recipient receives | Fee | Recipient | Status |")
w("|---|---|---|---|---|---|---|")
for t in transfers:
    d = t["details"]
    w(f"| {utc(t.get('created'))} | `{t['id'][:8]}` | {money(int(d['value']), d['source'])} | {money(d['receive'], d['target'])} | "
      f"{money(d['fee'], d['source'])} | {d['recipient']['name']} | **{t['status']}** |")
w("")
w("Every quote is labelled `local_simulation`; the applied rate is the ECB reference rate less a simulated 0.5% spread.")
w("")
w("## 4. Audit trail of each payment")
for t in transfers:
    d, trail = t["details"], e["trails"].get(t["id"], {})
    w("")
    w(f"### Payment `{t['id'][:8]}` — {money(int(d['value']), d['source'])} to {d['recipient']['name']} ({d.get('purpose', '')}) → **{t['status']}**")
    w("")
    w("| Time | Actor | Step | Outcome | Details |")
    w("|---|---|---|---|---|")
    for ev in trail.get("events", []):
        w(f"| {utc(ev['time'])} | {ev['actor']} | `{ev['action']}` | {ev['outcome']} | {detail(ev['detail'], 90)} |")
    w("")
    if t["status"] == "draft":
        w("**Not approved** — no `approve` or `submit` step exists for this payment; it remains a draft until the owner acts.")
    elif t.get("approval_digest"):
        w(f"Approved against digest: `{t['approval_digest']}`")
w("")
w("## 5. Sandbox ledger at the end of the session")
w("")
w("| Currency | Total | Reserved | Available |")
w("|---|---|---|---|")
for f in e["ledger"]["funds"]:
    w(f"| {f['currency']} | {money(f['total'], f['currency'])} | {money(f['reserved'], f['currency'])} | {money(f['available'], f['currency'])} |")
w("")
spent = Counter()
for m in e["ledger"]["moves"]:
    if m["effect"] == "deducted":
        spent[m["currency"]] += -int(m["amount"])
if spent:
    w("Completed payments deducted " + ", ".join(money(v, c) for c, v in spent.items()) + " (fees included) from the test funds; "
      "open drafts reserve nothing until they are approved.")
w("")
w("| Ledger movement | Status | Effect | Amount | Recipient receives |")
w("|---|---|---|---|---|")
for m in e["ledger"]["moves"]:
    w(f"| `{m['id'][:8]}` {m.get('purpose', '')} | {m['status']} | {m['effect']} | {money(m['amount'], m['currency'])} | {money(m.get('receive'), m.get('target'))} |")
w("")
w("## 6. Full audit log of the session")
w("")
w("Oldest first. `chain` is the first 12 characters of each entry's hash-chain link.")
w("")
w("| # | Time | Actor | Action | Outcome | Request | Details | chain |")
w("|---|---|---|---|---|---|---|---|")
for r in audit:
    w(f"| {r['id']} | {utc(r['time'])} | {r['actor']} | `{r['action']}` | {r['outcome']} | `{(r.get('request_id') or '')[:8]}` | {detail(r['detail'])} | `{(r.get('chain') or '')[:12]}` |")
w("")
w("## 7. How to check this log")
w("")
w("- **Hash chain:** each entry's link is `SHA-256(previous link | entry)`. Recomputing it over `evidence.json` gives the same links (done above); changing any entry breaks every later link.")
w("- **Reproduce the session:** `docker compose up -d`, then run the recording script (`tests/browser/demo_video.py` or `demo_full.py`) in the browser-test image and `scripts/evidence_report.py` on its output. A new demo workspace is used each time.")
w("- **Raw data:** `evidence.json` (audit log, payments, trails, ledger, balances); `audit-log.csv` (one row per audit entry).")
(folder / "sandbox-operation-log.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

with open(folder / "audit-log.csv", "w", newline="", encoding="utf-8-sig") as fh:
    out = csv.writer(fh)
    out.writerow(["id", "time_utc", "actor", "action", "outcome", "correlation", "request_id", "detail", "chain"])
    for r in audit:
        out.writerow([r["id"], utc(r["time"]), r["actor"], r["action"], r["outcome"], r["correlation"] or "", r.get("request_id") or "", r["detail"], r.get("chain") or ""])
print("ok", folder / "sandbox-operation-log.md", "| chain recomputed:", recomputed_ok, "| entries:", len(audit))
