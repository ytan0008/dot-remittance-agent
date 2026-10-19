"""Agent memory in three layers. Memory is context, never authority: it cannot grant permissions or prove payments.

1. Conversation  - recent turns per session (short-term).
2. Notes         - durable facts the user wants kept: people, routines, preferences (long-term, owner can forget).
3. Episodes      - one record per agent turn: what was asked, which tools ran, what happened (recallable history).

Facts about money always come from the ledger and the chain, not from memory.
"""
import json
import re
from .domain import Denied, canonical, now

KINDS = ("fact", "person", "routine", "preference")
LIMIT = 200
# Credentials, keys and full account or card numbers never enter memory.
SENSITIVE = re.compile(r"\b(?:0x)?[0-9a-fA-F]{64}\b|sk-[A-Za-z0-9_-]{15,}|(?<!\d)(?:\d[ -]?){12,19}(?!\d)|password|passwort|密码|密碼|mật khẩu|パスワード|비밀번호", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_notes (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active', created INTEGER NOT NULL, last_used INTEGER, uses INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS episodes (id INTEGER PRIMARY KEY, session TEXT NOT NULL, time INTEGER NOT NULL, mode TEXT NOT NULL,
    request TEXT NOT NULL, intent TEXT, tools TEXT NOT NULL, refs TEXT NOT NULL, outcome TEXT NOT NULL);
"""


def tokens(text):
    """Words for Latin scripts, character bigrams for CJK, so recall works in every UI language."""
    text = (text or "").lower()
    out = set(re.findall(r"[^\W\d_]{2,}|\d{2,}", re.sub(r"[぀-ヿ㐀-鿿가-힯]+", " ", text)))
    for run in re.findall(r"[぀-ヿ㐀-鿿가-힯]+", text):
        out.update(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return out


class Memory:
    def __init__(self, store):
        self.store = store
        with store.tx() as c:
            c.executescript(SCHEMA)

    # ---------- layer 1: conversation ----------
    def conversation(self, session, limit=12):
        with self.store.read() as c:
            rows = list(c.execute("SELECT role,body FROM messages WHERE session=? AND role IN ('user','assistant') "
                                  "ORDER BY id DESC LIMIT ?", (session, limit)))
        return [{"role": r["role"], "content": r["body"]} for r in reversed(rows)]

    def save_turn(self, session, message, answer):
        with self.store.tx() as c:
            c.executemany("INSERT INTO messages(session,role,body) VALUES (?,?,?)",
                          [(session, "user", message), (session, "assistant", answer)])

    # ---------- layer 2: notes ----------
    def remember(self, actor, text, kind="fact"):
        if actor not in ("owner", "agent"):
            raise Denied("only the owner or the agent can write memory", "permission_denied")
        text = " ".join(str(text or "").split())
        if kind not in KINDS or not 3 <= len(text) <= 300:
            raise Denied("a memory note needs 3-300 characters and a known kind", "memory_invalid")
        if SENSITIVE.search(text):
            raise Denied("memory never stores credentials, keys or full account numbers", "memory_sensitive")
        with self.store.tx() as c:
            same = c.execute("SELECT id FROM agent_notes WHERE status='active' AND lower(text)=lower(?)", (text,)).fetchone()
            if same:
                return self.note(same[0], c)
            if c.execute("SELECT count(*) FROM agent_notes WHERE status='active'").fetchone()[0] >= LIMIT:
                raise Denied("memory is full; forget some notes first", "memory_full")
            nid = c.execute("INSERT INTO agent_notes(kind,text,source,created) VALUES (?,?,?,?)",
                            (kind, text, actor, now())).lastrowid
            self.store.event(c, actor, "memory.remember", "ok", str(nid), kind=kind, length=len(text))
            return self.note(nid, c)

    def forget(self, actor, note_id):
        if actor not in ("owner", "agent"):
            raise Denied("only the owner or the agent can change memory", "permission_denied")
        with self.store.tx() as c:
            if not c.execute("UPDATE agent_notes SET status='forgotten' WHERE id=? AND status='active'", (int(note_id),)).rowcount:
                raise Denied("memory note not found", "memory_unknown")
            self.store.event(c, actor, "memory.forget", "ok", str(note_id))
        return {"forgotten": int(note_id)}

    @staticmethod
    def note(note_id, c):
        return dict(c.execute("SELECT * FROM agent_notes WHERE id=?", (note_id,)).fetchone())

    def notes(self):
        with self.store.read() as c:
            return [dict(r) for r in c.execute("SELECT * FROM agent_notes WHERE status='active' ORDER BY id DESC")]

    # ---------- layer 3: episodes ----------
    def record_episode(self, session, mode, request, intent, tools, refs, outcome):
        with self.store.tx() as c:
            c.execute("INSERT INTO episodes(session,time,mode,request,intent,tools,refs,outcome) VALUES (?,?,?,?,?,?,?,?)",
                      (session, now(), mode, request[:500], intent, canonical(tools), canonical(sorted(set(refs))), (outcome or "")[:500]))

    def episodes(self, session=None, limit=30):
        sql, args = "SELECT * FROM episodes", []
        if session:
            sql, args = sql + " WHERE session=?", [session]
        with self.store.read() as c:
            rows = [dict(r) for r in c.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))]
        for r in rows:
            r["tools"], r["refs"] = json.loads(r["tools"]), json.loads(r["refs"])
        return rows

    # ---------- recall ----------
    def recall(self, query, limit=5):
        want = tokens(query)
        scored = lambda text: len(want & tokens(text)) / (len(want) or 1)
        notes = sorted(((scored(n["text"]), n) for n in self.notes()), key=lambda x: (-x[0], -x[1]["id"]))
        episodes = sorted(((scored(e["request"] + " " + e["outcome"]), e) for e in self.episodes(limit=200)),
                          key=lambda x: (-x[0], -x[1]["id"]))
        hit_notes = [n for s, n in notes if s > 0][:limit]
        hit_episodes = [e for s, e in episodes if s > 0][:limit]
        self._used([n["id"] for n in hit_notes])
        return dict(kind="memory recall (user-provided context, not ledger facts)", query=query,
                    notes=hit_notes, episodes=hit_episodes)

    def context(self, message, session, limit=8):
        """What the model sees each turn: the most relevant notes, then the newest, plus recent episodes."""
        want = tokens(message)
        notes = self.notes()
        ranked = sorted(notes, key=lambda n: (-len(want & tokens(n["text"])), -n["id"]))[:limit]
        self._used([n["id"] for n in ranked if want & tokens(n["text"])])
        recent = [dict(time=e["time"], request=e["request"][:160], intent=e["intent"], tools=e["tools"], outcome=e["outcome"][:160])
                  for e in self.episodes(session, limit=3)]
        return dict(notes=[dict(id=n["id"], kind=n["kind"], text=n["text"], source=n["source"]) for n in ranked],
                    recent_episodes=recent)

    def _used(self, ids):
        if not ids:
            return
        with self.store.tx() as c:
            c.executemany("UPDATE agent_notes SET uses=uses+1,last_used=? WHERE id=?", [(now(), i) for i in ids])
