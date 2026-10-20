"""Accounts: sign up and sign in with an email and a password.

Passwords are stored only as salted scrypt hashes. Every account has its own workspace — its own database — so one
person never sees another's money. Signing up always creates a NEW, empty workspace: the data already on an instance
(the "default" workspace) is claimed only with the owner token from the server's .env, never by being first in line.
Repeated wrong passwords lock that email briefly; sign-ups are rate-limited per address. File deletions that fail are
recorded and retried, and never reported as done.
"""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from .domain import Denied

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, salt BLOB NOT NULL,
    hash BLOB NOT NULL, workspace TEXT NOT NULL, created INTEGER NOT NULL, last_login INTEGER);
CREATE TABLE IF NOT EXISTS signups (client TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS signups_client ON signups(client, at);
CREATE TABLE IF NOT EXISTS pending_deletions (path TEXT PRIMARY KEY, since INTEGER NOT NULL, tries INTEGER NOT NULL DEFAULT 0);
"""
SIGNUPS_PER_HOUR = 5
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$")
MAX_FAILS, LOCK_SECONDS = 5, 300


def _hash(password, salt):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


class Users:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.fails = {}  # key -> (count, first_failure_time)
        c = sqlite3.connect(self.path, timeout=30)
        try:
            c.executescript(SCHEMA)
        finally:
            c.close()

    @contextmanager
    def _db(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    def count(self):
        with self._db() as c:
            return c.execute("SELECT count(*) FROM users").fetchone()[0]

    def workspaces(self):
        with self._db() as c:
            return [r[0] for r in c.execute("SELECT workspace FROM users WHERE workspace<>'default'")]

    @staticmethod
    def public(row):
        return dict(id=row["id"], email=row["email"], name=row["name"], workspace=row["workspace"])

    def register(self, email, password, name="", client="", claim_default=False):
        email = (email or "").strip().lower()
        if not EMAIL.match(email):
            raise Denied("enter a valid email address", "auth_email")
        if not isinstance(password, str) or len(password) < 8 or len(password) > 200:
            raise Denied("the password needs at least 8 characters", "auth_password_short")
        if password.lower() in (email, email.split("@")[0]) or len(set(password)) < 4:
            raise Denied("choose a password that is harder to guess", "auth_password_weak")
        salt = secrets.token_bytes(16)
        uid = str(uuid.uuid4())
        who = hashlib.sha256(str(client).encode()).hexdigest()  # the limit needs to tell clients apart, not to know them
        with self._db() as c:  # BEGIN IMMEDIATE: counting and taking a place happen in one step, across threads and processes
            c.execute("DELETE FROM signups WHERE at<?", (time.time() - 3600,))
            if c.execute("SELECT count(*) FROM signups WHERE client=?", (who,)).fetchone()[0] >= SIGNUPS_PER_HOUR:
                raise Denied("too many new accounts from here — try again later", "auth_locked")
            if c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                raise Denied("an account with this email already exists — sign in instead", "auth_exists")
            if claim_default and c.execute("SELECT 1 FROM users WHERE workspace='default'").fetchone():
                raise Denied("the data on this computer already belongs to an account", "auth_claimed")
            workspace = "default" if claim_default else uid  # never by order: only a verified owner token claims existing data
            c.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?,?)", (uid, email, (name or "").strip()[:60] or email.split("@")[0],
                                                                    salt, _hash(password, salt), workspace, int(time.time()), int(time.time())))
            c.execute("INSERT INTO signups VALUES (?,?)", (who, time.time()))
            return self.public(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())

    def claim_default(self, uid):
        """Move a signed-in account onto the existing data (the caller has verified the owner token)."""
        with self._db() as c:
            if c.execute("SELECT 1 FROM users WHERE workspace='default'").fetchone():
                raise Denied("the data on this computer already belongs to an account", "auth_claimed")
            old = c.execute("SELECT workspace FROM users WHERE id=?", (uid,)).fetchone()
            if not old:
                raise Denied("sign in first", "auth_failed")
            c.execute("UPDATE users SET workspace='default' WHERE id=?", (uid,))
            return old[0]

    # ---------- deleting files: never claimed done when it is not ----------
    def remember_deletion(self, paths):
        with self._db() as c:
            for p in paths:
                c.execute("INSERT OR IGNORE INTO pending_deletions VALUES (?,?,0)", (p, int(time.time())))

    def retry_deletions(self, remove):
        with self._db() as c:
            rows = [r[0] for r in c.execute("SELECT path FROM pending_deletions")]
        left = []
        for p in rows:
            try:
                remove(p)
                done = True
            except FileNotFoundError:
                done = True
            except OSError:
                done = False
            with self._db() as c:
                if done:
                    c.execute("DELETE FROM pending_deletions WHERE path=?", (p,))
                else:
                    c.execute("UPDATE pending_deletions SET tries=tries+1 WHERE path=?", (p,))
                    left.append(p)
        return left

    def delete(self, uid):
        with self._db() as c:
            c.execute("DELETE FROM users WHERE id=?", (uid,))

    def verify(self, email, password, client=""):
        email = (email or "").strip().lower()
        key = f"{email}|{client}"
        count, since = self.fails.get(key, (0, 0))
        if count >= MAX_FAILS and time.time() - since < LOCK_SECONDS:
            raise Denied("too many attempts — wait a few minutes and try again", "auth_locked")
        with self._db() as c:
            row = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            # Hash even when the email is unknown, so timing does not reveal which emails have accounts.
            salt = row["salt"] if row else b"\0" * 16
            ok = hmac.compare_digest(_hash(str(password or "")[:200], salt), row["hash"] if row else b"\1" * 32)
            if not row or not ok:
                self.fails[key] = (count + 1 if time.time() - since < LOCK_SECONDS else 1, since if count and time.time() - since < LOCK_SECONDS else time.time())
                raise Denied("email or password is not right", "auth_failed")
            self.fails.pop(key, None)
            c.execute("UPDATE users SET last_login=? WHERE id=?", (int(time.time()), row["id"]))
            return self.public(row)
