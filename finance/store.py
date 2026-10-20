import hashlib
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from .domain import canonical, now, request_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS transfers (
    id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, request TEXT NOT NULL,
    body TEXT NOT NULL, status TEXT NOT NULL, created INTEGER NOT NULL,
    submitted INTEGER, approved_hash TEXT, approval_actor TEXT,
    mandate_id TEXT, reference TEXT, actual_cost TEXT);
CREATE TABLE IF NOT EXISTS secrets (transfer_id TEXT PRIMARY KEY, raw_tx TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS balances (currency TEXT PRIMARY KEY, total TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recipients (id TEXT PRIMARY KEY, body TEXT NOT NULL, enabled INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS mandates (id TEXT PRIMARY KEY, body TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS memories (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, session TEXT NOT NULL, role TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY, time INTEGER NOT NULL, actor TEXT NOT NULL,
    action TEXT NOT NULL, outcome TEXT NOT NULL, correlation TEXT, detail TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
    BEGIN SELECT RAISE(ABORT, 'append only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
    BEGIN SELECT RAISE(ABORT, 'append only'); END;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS routes (id TEXT PRIMARY KEY, body TEXT NOT NULL, payments_enabled INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1, reference TEXT);
CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
    created_by TEXT NOT NULL, created INTEGER NOT NULL, decided_by TEXT, decided INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, detail TEXT NOT NULL,
    actor TEXT NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS goals (id TEXT PRIMARY KEY, body TEXT NOT NULL, status TEXT NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS budget (id TEXT PRIMARY KEY, body TEXT NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS obligations (id TEXT PRIMARY KEY, body TEXT NOT NULL, status TEXT NOT NULL,
    paid_at INTEGER, transfer_id TEXT, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
    ref TEXT, severity TEXT NOT NULL, data TEXT NOT NULL, created INTEGER NOT NULL,
    dismissed INTEGER NOT NULL DEFAULT 0, resolved INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS rate_alerts (id TEXT PRIMARY KEY, body TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
    created INTEGER NOT NULL, last_rate TEXT, last_checked INTEGER, triggered_at INTEGER);
CREATE TABLE IF NOT EXISTS sandbox_provider (ref TEXT PRIMARY KEY, transfer_id TEXT UNIQUE NOT NULL, status TEXT NOT NULL,
    scenario TEXT NOT NULL, created INTEGER NOT NULL, settle_at INTEGER NOT NULL);
"""

# Columns added after the first release; existing databases are upgraded in place.
COLUMNS = {
    "transfers": {"rail": "TEXT NOT NULL DEFAULT 'sandbox'", "supersedes": "TEXT", "approved_at": "INTEGER",
                  "completed_at": "INTEGER", "goal_id": "TEXT", "checks": "TEXT", "approval_note": "TEXT"},
    "audit": {"request_id": "TEXT", "chain": "TEXT"},
}


class Store:
    def __init__(self, path):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as c:
            c.executescript(SCHEMA)
            for table, columns in COLUMNS.items():
                present = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
                for name, kind in columns.items():
                    if name not in present:
                        c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")

    @contextmanager
    def tx(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    @contextmanager
    def read(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    @staticmethod
    def event(c, actor, action, outcome, correlation=None, **detail):
        """Append one audit entry, chained to the one before: chain = SHA-256(previous chain + this entry). Changing or
        removing any entry breaks every link after it (verify_audit finds where). Runs inside the caller's write
        transaction, so entries are chained in commit order."""
        row = (now(), actor, action, outcome, correlation, canonical(detail), request_id.get())
        prev = c.execute("SELECT chain FROM audit WHERE chain IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        link = hashlib.sha256(((prev[0] if prev else "") + "|" + canonical(list(row))).encode()).hexdigest()
        c.execute("INSERT INTO audit(time,actor,action,outcome,correlation,detail,request_id,chain) VALUES(?,?,?,?,?,?,?,?)", (*row, link))

    def verify_audit(self):
        """Walk the chain: ok, how many entries were checked, and the first entry whose link does not match (if any)."""
        prev, checked = "", 0
        with self.read() as c:
            for r in c.execute("SELECT id,time,actor,action,outcome,correlation,detail,request_id,chain FROM audit WHERE chain IS NOT NULL ORDER BY id"):
                row = [r["time"], r["actor"], r["action"], r["outcome"], r["correlation"], r["detail"], r["request_id"]]
                if hashlib.sha256((prev + "|" + canonical(row)).encode()).hexdigest() != r["chain"]:
                    return dict(ok=False, checked=checked, broken_at=r["id"])
                prev, checked = r["chain"], checked + 1
            last = c.execute("SELECT max(id) FROM audit WHERE chain IS NOT NULL").fetchone()[0]
        return dict(ok=True, checked=checked, head=prev, last_id=last)

    def setting(self, c, key, default=None):
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default
