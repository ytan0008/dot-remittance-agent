"""Student spending: bank CSV import, receipts, quick-add, recurring expenses and a fast review step.

Nothing connects to a bank. Every imported or extracted entry starts as `pending` and is saved only after the
user confirms it, so the student stays in control. Duplicates are flagged, never silently dropped.
"""
import csv
import io
import json
import re
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from .domain import Denied, canonical, now, decimals

CATEGORIES = ("rent", "groceries", "dining", "transport", "utilities", "phone", "subscriptions", "tuition", "shopping",
              "health", "entertainment", "travel", "transfer", "fees", "income", "other")
# Lowercase keyword -> category. Multilingual so imports and quick-add work in every UI language.
KEYWORDS = {
    "rent": ["rent", "lease", "landlord", "accommodation", "房租", "租金", "房东", "房東", "tiền nhà", "thuê nhà", "家賃", "월세", "임대"],
    "groceries": ["woolworths", "coles", "aldi", "iga", "supermarket", "grocer", "costco", "超市", "菜", "siêu thị", "スーパー", "마트"],
    "dining": ["lunch", "dinner", "breakfast", "cafe", "coffee", "restaurant", "mcdonald", "kfc", "uber eats", "doordash", "menulog",
               "starbucks", "pizza", "sushi", "午饭", "午餐", "晚饭", "晚餐", "早餐", "咖啡", "外卖", "餐", "ăn trưa", "cà phê", "quán",
               "ランチ", "コーヒー", "食事", "점심", "커피", "식당"],
    "transport": ["bus", "train", "tram", "metro", "opal", "myki", "uber", "didi", "taxi", "fuel", "petrol", "parking", "toll",
                  "公交", "地铁", "地鐵", "打车", "打車", "出租", "油费", "停车", "xe buýt", "xăng", "taxi", "バス", "電車", "タクシー", "버스", "지하철", "택시"],
    "utilities": ["electricity", "energy", "agl", "origin", "gas bill", "water", "电费", "水费", "燃气", "電費", "tiền điện", "tiền nước", "電気", "水道", "전기", "수도"],
    "phone": ["optus", "telstra", "vodafone", "mobile", "internet", "nbn", "phone plan", "话费", "話費", "宽带", "điện thoại", "携帯", "휴대폰", "인터넷"],
    "subscriptions": ["netflix", "spotify", "apple.com", "icloud", "youtube", "disney", "chatgpt", "openai", "subscription", "会员", "會員",
                      "订阅", "訂閱", "サブスク", "구독"],
    "tuition": ["tuition", "university", "uni ", "school fee", "course fee", "学费", "學費", "học phí", "学費", "등록금", "수업료"],
    "shopping": ["amazon", "kmart", "target", "big w", "ikea", "jb hi-fi", "taobao", "淘宝", "京东", "购物", "mua sắm", "買い物", "쇼핑"],
    "health": ["pharmacy", "chemist", "doctor", "medical", "dental", "medicare", "药", "藥", "医院", "醫院", "thuốc", "bệnh viện", "薬", "病院", "약국", "병원"],
    "entertainment": ["cinema", "movie", "steam", "game", "concert", "ticket", "电影", "電影", "游戏", "phim", "映画", "영화", "게임"],
    "travel": ["airline", "qantas", "jetstar", "virgin australia", "hotel", "airbnb", "booking.com", "flight", "机票", "機票", "酒店",
               "vé máy bay", "khách sạn", "航空", "ホテル", "항공", "호텔"],
    "transfer": ["transfer to", "remittance", "wise", "western union", "汇款", "匯款", "转账", "轉帳", "chuyển khoản", "送金", "송금", "이체"],
    "fees": ["fee", "charge", "interest", "手续费", "手續費", "phí", "手数料", "수수료"],
}
DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%m/%d/%y",
                "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%Y%m%d", "%Y年%m月%d日")
HEADERS = {
    "date": ["date", "transaction date", "posted", "posting date", "value date", "日期", "交易日期", "记账日期", "ngày", "日付", "날짜", "거래일"],
    "description": ["description", "details", "narrative", "memo", "transaction", "payee", "merchant", "reference", "particulars",
                    "摘要", "交易描述", "描述", "商户", "对方", "备注", "mô tả", "nội dung", "摘要欄", "内容", "적요", "내용"],
    "amount": ["amount", "value", "金额", "金額", "交易金额", "số tiền", "金額(円)", "금액"],
    "debit": ["debit", "withdrawal", "money out", "paid out", "支出", "借方", "chi", "出金", "출금"],
    "credit": ["credit", "deposit", "money in", "paid in", "收入", "贷方", "thu", "入金", "입금"],
    "balance": ["balance", "余额", "餘額", "số dư", "残高", "잔액"],
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (id TEXT PRIMARY KEY, date TEXT NOT NULL, amount INTEGER NOT NULL, currency TEXT NOT NULL,
    description TEXT NOT NULL, merchant TEXT, category TEXT NOT NULL, suggested TEXT, source TEXT NOT NULL, status TEXT NOT NULL,
    fingerprint TEXT NOT NULL, duplicate_of TEXT, recurring_id TEXT, import_id TEXT, created INTEGER NOT NULL, confirmed INTEGER);
CREATE INDEX IF NOT EXISTS expenses_fp ON expenses(fingerprint);
CREATE TABLE IF NOT EXISTS expense_imports (id TEXT PRIMARY KEY, filename TEXT NOT NULL, rows INTEGER NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS recurring (id TEXT PRIMARY KEY, description TEXT NOT NULL, amount INTEGER NOT NULL, currency TEXT NOT NULL,
    category TEXT NOT NULL, cadence TEXT NOT NULL, next_date TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS category_rules (pattern TEXT PRIMARY KEY, category TEXT NOT NULL, updated INTEGER NOT NULL);
"""


def normalize(text):
    text = re.sub(r"\d{4,}", " ", (text or "").lower())          # card numbers, receipt ids
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def merchant_key(text):
    words = [w for w in normalize(text).split() if len(w) > 1 and not w.isdigit()]
    return " ".join(words[:3])


def brand(merchant):
    """The first meaningful word of a merchant: one correction then covers every branch (WOOLWORTHS SYDNEY / MELBOURNE)."""
    words = [w for w in (merchant or "").split() if len(w) >= 3]
    return words[0] if words else (merchant or "")


def parse_amount(raw):
    text = str(raw or "").strip()
    if not text:
        return None
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")")) or text.upper().endswith(("DR", " D"))
    text = re.sub(r"(?i)\b(cr|dr)\b|[()\s]", "", text)
    text = re.sub(r"[^\d,.\-]", "", text).lstrip("-")
    if text.count(",") and text.count("."):
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else text.replace(".", "").replace(",", ".")
    elif text.count(",") == 1 and len(text.split(",")[1]) in (1, 2):
        text = text.replace(",", ".")  # European decimal comma
    else:
        text = text.replace(",", "")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return -value if negative else value


def parse_date(raw, day_first=True):
    text = str(raw or "").strip()
    if not text:
        return None
    formats = DATE_FORMATS if day_first else tuple(f for f in DATE_FORMATS if f.startswith("%m")) + DATE_FORMATS
    for fmt in formats:
        try:
            return datetime.strptime(text[:30], fmt).date()
        except ValueError:
            continue
    return None


def suggest_category(description, rules=None, amount=None):
    text = " " + (description or "").lower() + " "
    key = merchant_key(description)
    words = set(normalize(description).split())
    for pattern, category in (rules or {}).items():
        if pattern and (pattern == key or pattern in words or (" " in pattern and pattern in text)):
            return category, "learned"
    if amount is not None and amount > 0:
        return "income", "sign"
    for category, words in KEYWORDS.items():
        if any(w in text for w in words):
            return category, "keyword"
    return "other", "default"


class ExpensesMixin:
    def _expenses_schema(self):
        with self.store.tx() as c:
            c.executescript(SCHEMA)

    def _rules(self, c):
        return {r["pattern"]: r["category"] for r in c.execute("SELECT * FROM category_rules")}

    def _rules_snapshot(self):
        with self.store.read() as c:
            return self._rules(c)

    def _currency_default(self):
        return (self.memory().get("display_currency") or "AUD").upper()

    @staticmethod
    def fingerprint(day, amount, currency, description):
        return f"{day}|{amount}|{currency}|{merchant_key(description)}"

    def _dup(self, c, fp, day, amount, currency, description, exclude_import=None):
        """An existing entry with the same amount and merchant within two days counts as a likely duplicate."""
        row = c.execute("SELECT id FROM expenses WHERE fingerprint=? AND status<>'skipped' AND (import_id IS NULL OR import_id<>?)",
                        (fp, exclude_import or "")).fetchone()
        if row:
            return row["id"]
        d = date.fromisoformat(day)
        for r in c.execute("SELECT id, date, description FROM expenses WHERE amount=? AND currency=? AND status<>'skipped' "
                           "AND date BETWEEN ? AND ? AND (import_id IS NULL OR import_id<>?)",
                           (amount, currency, str(d - timedelta(days=2)), str(d + timedelta(days=2)), exclude_import or "")):
            if merchant_key(r["description"]) == merchant_key(description):
                return r["id"]
        return None

    # ---------- CSV import ----------
    def import_csv(self, actor, filename, content, currency=None):
        self.owner(actor)
        if not isinstance(content, str) or not content.strip():
            raise Denied("the file is empty", "csv_empty")
        if len(content) > 2_000_000:
            raise Denied("file too large (max 2 MB)", "csv_large")
        currency = (currency or self._currency_default()).upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise Denied("currency must be an ISO code", "csv_currency")
        text = content.lstrip("﻿")
        sample = text[:5000]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(cell.strip() for cell in r)]
        if not rows:
            raise Denied("no rows found", "csv_empty")
        header = [h.strip().lower() for h in rows[0]]
        cols = {}
        for field, names in HEADERS.items():
            for i, h in enumerate(header):
                if i not in cols.values() and any(h == n or h.startswith(n) for n in names):
                    cols[field] = i
                    break
        has_header = "date" in cols and ("amount" in cols or "debit" in cols or "credit" in cols)
        if not has_header:
            cols = self._guess_columns(rows)
            data = rows
        else:
            data = rows[1:]
        if "date" not in cols or not ({"amount", "debit", "credit"} & set(cols)):
            raise Denied("could not find date and amount columns", "csv_columns")
        if len(data) > 5000:
            raise Denied("too many rows (max 5000)", "csv_large")
        dates = [r[cols["date"]] for r in data if len(r) > cols["date"]]
        day_first = not any(re.match(r"^\s*\d{1,2}[/-](\d{1,2})[/-]", d) and int(re.match(r"^\s*\d{1,2}[/-](\d{1,2})", d).group(1)) > 12
                            for d in dates)
        imp = str(uuid.uuid4())
        created, skipped = [], 0
        with self.store.tx() as c:
            rules = self._rules(c)
            seen = {}
            for r in data:
                get = lambda f: r[cols[f]].strip() if f in cols and len(r) > cols[f] else ""
                day = parse_date(get("date"), day_first)
                if "amount" in cols:
                    value = parse_amount(get("amount"))
                else:
                    debit, credit = parse_amount(get("debit")), parse_amount(get("credit"))
                    value = -abs(debit) if debit else (abs(credit) if credit else None)
                description = get("description") or " ".join(cell for i, cell in enumerate(r) if i not in cols.values())[:200]
                if not day or value is None or value == 0:
                    skipped += 1
                    continue
                minor = int((abs(value) * 10 ** decimals(currency)).to_integral_value())
                signed = minor if value > 0 else -minor
                category, why = suggest_category(description, rules, signed)
                fp = self.fingerprint(str(day), signed, currency, description)
                dup = seen.get(fp) or self._dup(c, fp, str(day), signed, currency, description, imp)
                eid = str(uuid.uuid4())
                seen.setdefault(fp, eid)
                c.execute("INSERT INTO expenses(id,date,amount,currency,description,merchant,category,suggested,source,status,fingerprint,"
                          "duplicate_of,import_id,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (eid, str(day), signed, currency, description[:200], merchant_key(description), category, why, "csv",
                           "pending", fp, dup, imp, now()))
                created.append(eid)
            c.execute("INSERT INTO expense_imports VALUES (?,?,?,?)", (imp, (filename or "statement.csv")[:120], len(created), now()))
            self.store.event(c, actor, "expenses.import", "ok", imp, rows=len(created), skipped=skipped, filename=(filename or "")[:60])
        recurring = self.detect_recurring(imp)
        return dict(import_id=imp, rows=self.expenses(import_id=imp), skipped=skipped, recurring_candidates=recurring,
                    columns={k: header[v] if has_header and v < len(header) else f"#{v + 1}" for k, v in cols.items()},
                    date_order="day/month" if day_first else "month/day")

    @staticmethod
    def _guess_columns(rows):
        """Header-less exports: pick the column that parses as dates, the one that parses as money, the longest text."""
        width = max(len(r) for r in rows[:20])
        score = {i: {"date": 0, "amount": 0, "text": 0} for i in range(width)}
        for r in rows[:20]:
            for i, cell in enumerate(r):
                if parse_date(cell):
                    score[i]["date"] += 1
                elif parse_amount(cell) is not None:
                    score[i]["amount"] += 1
                else:
                    score[i]["text"] += len(cell)
        cols = {"date": max(score, key=lambda i: score[i]["date"]), "amount": max(score, key=lambda i: score[i]["amount"])}
        rest = [i for i in score if i not in cols.values()]
        if rest:
            cols["description"] = max(rest, key=lambda i: score[i]["text"])
        return cols

    def detect_recurring(self, import_id=None):
        """Same merchant and amount at roughly monthly intervals -> suggest a recurring expense (user confirms)."""
        with self.store.read() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM expenses WHERE amount<0 AND status<>'skipped'")]
            known = {(r["description"].lower(), r["amount"]) for r in c.execute("SELECT description, amount FROM recurring WHERE active=1")}
        groups = {}
        for r in rows:
            groups.setdefault((merchant_key(r["description"]), -r["amount"], r["currency"]), []).append(r)
        out = []
        for (key, amount, currency), items in groups.items():
            days = sorted({date.fromisoformat(i["date"]) for i in items})
            if len(days) < 2 or not key:
                continue
            gaps = [(b - a).days for a, b in zip(days, days[1:])]
            if all(26 <= g <= 35 for g in gaps):
                cadence = "monthly"
            elif all(6 <= g <= 8 for g in gaps):
                cadence = "weekly"
            else:
                continue
            description = items[-1]["description"]
            if (description.lower(), amount) in known:
                continue
            out.append(dict(description=description, amount=amount, currency=currency, category=items[-1]["category"],
                            cadence=cadence, last_date=str(days[-1]), occurrences=len(days)))
        return out

    # ---------- quick-add (text or voice) ----------
    def parse_quick(self, text, currency=None):
        raw = " ".join(str(text or "").split())
        if not raw or len(raw) > 200:
            raise Denied("type something like “lunch 12.50”", "quick_invalid")
        low = raw.lower()
        day = date.today()
        for words, delta in ((["yesterday", "昨天", "昨日", "hôm qua", "어제"], 1), (["前天", "一昨日", "그저께", "hôm kia"], 2)):
            if any(w in low for w in words):
                day -= timedelta(days=delta)
                for w in words:
                    raw = re.sub(re.escape(w), " ", raw, flags=re.I)
        m = re.search(r"(?<![\w.])(?:[$¥€£₫₩]|aud|usd|cny|rmb|vnd|jpy|krw)?\s*(\d{1,7}(?:[.,]\d{1,2})?)\s*(元|块|塊|đ|円|원|aud|usd|cny|vnd|jpy|krw)?(?![\w.])",
                      raw, re.I)
        if not m:
            raise Denied("add an amount, e.g. “bus pass 40”", "quick_amount")
        amount = Decimal(m.group(1).replace(",", "."))
        unit = (m.group(2) or "").lower()
        code = {"元": "CNY", "块": "CNY", "塊": "CNY", "rmb": "CNY", "đ": "VND", "円": "JPY", "원": "KRW"}.get(unit, unit.upper() or None)
        prefix = re.search(r"(aud|usd|cny|rmb|vnd|jpy|krw)\s*" + re.escape(m.group(1)), raw, re.I)
        if prefix:
            code = {"RMB": "CNY"}.get(prefix.group(1).upper(), prefix.group(1).upper())
        currency = (code or currency or self._currency_default()).upper()
        description = (raw[:m.start()] + " " + raw[m.end():]).strip(" ,.-:：，") or "expense"
        description = re.sub(r"\s+", " ", re.sub(r"(?i)\b(aud|usd|cny|rmb|vnd|jpy|krw)\b", " ", description)).strip() or "expense"
        with self.store.read() as c:
            category, why = suggest_category(description, self._rules(c))
        if category == "income":
            category = "other"
        minor = int((amount * 10 ** decimals(currency)).to_integral_value())
        return dict(date=str(day), amount=-minor, currency=currency, description=description[:200], category=category, suggested=why,
                    source="quick")

    # ---------- receipt (vision model, user checks before saving) ----------
    def receipt_prompt(self):
        return ("Extract this receipt as JSON with keys: date (YYYY-MM-DD or empty), total (number as string, the amount paid), "
                "currency (ISO code or empty), merchant, category (one of: " + ", ".join(CATEGORIES) + "). "
                "Reply with the JSON object only. If it is not a receipt, reply {\"error\": \"not a receipt\"}.")

    def receipt_result(self, raw_json):
        try:
            text = re.search(r"\{.*\}", raw_json or "", re.S).group(0)
            data = json.loads(text)
        except (AttributeError, ValueError):
            return dict(available=False, reason="could not read the receipt")
        if data.get("error"):
            return dict(available=False, reason=str(data["error"])[:120])
        currency = (data.get("currency") or self._currency_default()).upper()[:3]
        amount = parse_amount(data.get("total"))
        day = parse_date(data.get("date")) or date.today()
        merchant = str(data.get("merchant") or "")[:120]
        category = data.get("category") if data.get("category") in CATEGORIES else suggest_category(merchant)[0]
        minor = int((abs(amount) * 10 ** decimals(currency)).to_integral_value()) if amount is not None else None
        return dict(available=True, date=str(day), amount=-minor if minor is not None else None, currency=currency,
                    description=merchant or "receipt", merchant=merchant, category=category, source="receipt",
                    note="extracted by the AI model; check before saving")

    # ---------- save, review, learn ----------
    def add_expense(self, actor, day, amount, currency, description, category, source="manual", status="confirmed", recurring=None):
        if actor not in ("owner", "agent"):
            raise Denied("permission required", "permission_denied")
        if actor == "agent":
            status = "pending"  # the agent may suggest entries; only the student confirms them
        if category not in CATEGORIES:
            raise Denied("unknown category", "expense_invalid")
        currency = (currency or "").upper()
        if not re.fullmatch(r"[A-Z]{3}", currency) or not (description or "").strip():
            raise Denied("an expense needs an amount, currency and description", "expense_invalid")
        d = parse_date(day) if isinstance(day, str) else day
        if not d or d > date.today() + timedelta(days=400):
            raise Denied("invalid date", "date_invalid")
        amount = int(amount)
        if amount == 0 or abs(amount) > 10 ** 12:
            raise Denied("invalid amount", "expense_invalid")
        eid = str(uuid.uuid4())
        fp = self.fingerprint(str(d), amount, currency, description)
        with self.store.tx() as c:
            dup = self._dup(c, fp, str(d), amount, currency, description)
            c.execute("INSERT INTO expenses(id,date,amount,currency,description,merchant,category,source,status,fingerprint,duplicate_of,"
                      "recurring_id,created,confirmed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (eid, str(d), amount, currency, description.strip()[:200], merchant_key(description), category, source, status, fp,
                       dup, None, now(), now() if status == "confirmed" else None))
            self.store.event(c, actor, "expenses.add", status, eid, source=source, category=category)
        if recurring in ("monthly", "weekly") and actor == "owner":
            self.add_recurring(actor, description, abs(amount), currency, category, recurring, str(d))
        return self.expense(eid)

    def expense(self, eid):
        with self.store.read() as c:
            r = c.execute("SELECT * FROM expenses WHERE id=?", (eid,)).fetchone()
        if not r:
            raise Denied("expense not found", "expense_unknown")
        return dict(r)

    def expenses(self, status=None, import_id=None, month=None, limit=500):
        sql, args = "SELECT * FROM expenses WHERE 1=1", []
        if status:
            sql += " AND status=?"; args.append(status)
        if import_id:
            sql += " AND import_id=?"; args.append(import_id)
        if month:
            sql += " AND substr(date,1,7)=?"; args.append(month)
        with self.store.read() as c:
            return [dict(r) for r in c.execute(sql + " ORDER BY date DESC, created DESC LIMIT ?", (*args, min(int(limit), 5000)))]

    def review(self, actor, items):
        """Batch confirm or skip pending entries; a changed category becomes a rule for that merchant."""
        self.owner(actor)
        if not isinstance(items, list) or not items or len(items) > 5000:
            raise Denied("nothing to review", "review_invalid")
        confirmed = skipped = learned = 0
        with self.store.tx() as c:
            for item in items:
                r = c.execute("SELECT * FROM expenses WHERE id=? AND status IN ('pending','expected')", (str(item.get("id")),)).fetchone()
                if not r:
                    continue
                if not item.get("include", True):
                    c.execute("UPDATE expenses SET status='skipped' WHERE id=?", (r["id"],))
                    skipped += 1
                    continue
                category = item.get("category") or r["category"]
                if category not in CATEGORIES:
                    raise Denied("unknown category", "expense_invalid")
                amount = r["amount"]
                if item.get("amount") is not None:
                    amount = -abs(int(item["amount"])) if r["amount"] < 0 else abs(int(item["amount"]))
                c.execute("UPDATE expenses SET status='confirmed', category=?, amount=?, confirmed=? WHERE id=?",
                          (category, amount, now(), r["id"]))
                if category != r["category"] and r["merchant"]:
                    c.execute("INSERT INTO category_rules VALUES (?,?,?) ON CONFLICT(pattern) DO UPDATE SET category=excluded.category,"
                              "updated=excluded.updated", (brand(r["merchant"]), category, now()))
                    learned += 1
                if r["recurring_id"] and amount != r["amount"]:
                    c.execute("UPDATE recurring SET amount=? WHERE id=?", (abs(amount), r["recurring_id"]))  # "adjust" sticks
                confirmed += 1
            self.store.event(c, actor, "expenses.review", "ok", None, confirmed=confirmed, skipped=skipped, learned=learned)
        return dict(confirmed=confirmed, skipped=skipped, learned=learned)

    def update_expense(self, actor, eid, category=None, amount=None, description=None, day=None):
        self.owner(actor)
        with self.store.tx() as c:
            r = c.execute("SELECT * FROM expenses WHERE id=?", (eid,)).fetchone()
            if not r:
                raise Denied("expense not found", "expense_unknown")
            if category and category not in CATEGORIES:
                raise Denied("unknown category", "expense_invalid")
            c.execute("UPDATE expenses SET category=COALESCE(?,category), amount=COALESCE(?,amount), description=COALESCE(?,description),"
                      " date=COALESCE(?,date) WHERE id=?", (category, amount, description, day, eid))
            if category and category != r["category"] and r["merchant"]:
                c.execute("INSERT INTO category_rules VALUES (?,?,?) ON CONFLICT(pattern) DO UPDATE SET category=excluded.category,"
                          "updated=excluded.updated", (brand(r["merchant"]), category, now()))
            self.store.event(c, actor, "expenses.update", "ok", eid)
        return self.expense(eid)

    def delete_expense(self, actor, eid):
        self.owner(actor)
        with self.store.tx() as c:
            if not c.execute("UPDATE expenses SET status='skipped' WHERE id=?", (eid,)).rowcount:
                raise Denied("expense not found", "expense_unknown")
            self.store.event(c, actor, "expenses.delete", "ok", eid)
        return {"deleted": eid}

    # ---------- recurring ----------
    def add_recurring(self, actor, description, amount, currency, category, cadence, last_date):
        self.owner(actor)
        if cadence not in ("monthly", "weekly") or category not in CATEGORIES:
            raise Denied("invalid recurring expense", "expense_invalid")
        d = parse_date(last_date) or date.today()
        nxt = self._advance(d, cadence)
        rid = str(uuid.uuid4())
        with self.store.tx() as c:
            c.execute("INSERT INTO recurring VALUES (?,?,?,?,?,?,?,1,?)", (rid, description[:200], int(amount), currency.upper(), category,
                                                                         cadence, str(nxt), now()))
            self.store.event(c, actor, "recurring.add", "ok", rid, cadence=cadence)
        self.materialize_recurring()
        return self.recurring_list()[0] if self.recurring_list() else None

    @staticmethod
    def _advance(d, cadence):
        if cadence == "weekly":
            return d + timedelta(days=7)
        month = d.month % 12 + 1
        year = d.year + (d.month == 12)
        for day in (d.day, 30, 29, 28):
            try:
                return date(year, month, day)
            except ValueError:
                continue

    def recurring_list(self):
        with self.store.read() as c:
            return [dict(r) for r in c.execute("SELECT * FROM recurring WHERE active=1 ORDER BY created DESC")]

    def stop_recurring(self, actor, rid):
        self.owner(actor)
        with self.store.tx() as c:
            if not c.execute("UPDATE recurring SET active=0 WHERE id=?", (rid,)).rowcount:
                raise Denied("recurring expense not found", "expense_unknown")
            c.execute("UPDATE expenses SET status='skipped' WHERE recurring_id=? AND status='expected'", (rid,))
            self.store.event(c, actor, "recurring.stop", "ok", rid)
        return {"stopped": rid}

    def materialize_recurring(self, horizon_days=7):
        """Create the next expected entries a few days ahead; the student confirms, adjusts or skips them."""
        made = 0
        limit = date.today() + timedelta(days=horizon_days)
        with self.store.tx() as c:
            for r in c.execute("SELECT * FROM recurring WHERE active=1").fetchall():
                nxt = date.fromisoformat(r["next_date"])
                while nxt <= limit:
                    fp = self.fingerprint(str(nxt), -r["amount"], r["currency"], r["description"]) + "|expected"
                    if not c.execute("SELECT 1 FROM expenses WHERE fingerprint=?", (fp,)).fetchone():
                        c.execute("INSERT INTO expenses(id,date,amount,currency,description,merchant,category,source,status,fingerprint,"
                                  "recurring_id,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                  (str(uuid.uuid4()), str(nxt), -r["amount"], r["currency"], r["description"], merchant_key(r["description"]),
                                   r["category"], "recurring", "expected", fp, r["id"], now()))
                        made += 1
                    nxt = self._advance(nxt, r["cadence"])
                c.execute("UPDATE recurring SET next_date=? WHERE id=?", (str(nxt), r["id"]))
        return made

    # ---------- summary ----------
    def spending_summary(self, month=None):
        month = month or date.today().strftime("%Y-%m")
        first = date.fromisoformat(month + "-01")
        prev = (first - timedelta(days=1)).strftime("%Y-%m")
        def totals(m):
            out = {}
            for e in self.expenses(status="confirmed", month=m, limit=5000):
                if e["amount"] < 0 and e["category"] not in ("transfer", "income"):
                    key = (e["currency"], e["category"])
                    out[key] = out.get(key, 0) + -e["amount"]
            return out
        now_t, prev_t = totals(month), totals(prev)
        by_currency = {}
        for (cur, cat), v in now_t.items():
            by_currency.setdefault(cur, {"total": 0, "categories": {}})
            by_currency[cur]["total"] += v
            by_currency[cur]["categories"][cat] = v
        for cur, d in by_currency.items():
            d["previous"] = sum(v for (c2, _), v in prev_t.items() if c2 == cur)
        counts = {s: len(self.expenses(status=s, limit=5000)) for s in ("pending", "expected")}
        return dict(month=month, previous_month=prev, currencies=by_currency, pending=counts["pending"], expected=counts["expected"],
                    note="confirmed entries only; transfers and income are excluded from spending")
