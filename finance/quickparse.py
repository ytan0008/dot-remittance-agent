"""Read expenses out of one short line of text — the fast, offline first try before any AI model.

Handles what people actually type: numbers glued to Chinese text ("午饭40澳刀"), currency words and symbols in six
languages ("澳元", "刀", "A$", "円", "원", "đ"), decimal commas ("12,10"), dates ("2026年10月 19号", "10月19日", "19/10",
"昨天", "上周五", "last friday") and several expenses in one line ("午饭10澳元 打车25"). Anything it cannot read
confidently is left to the AI model (Agent.parse_expense_text).
"""
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

DOLLARS = ("AUD", "USD", "CAD", "NZD", "SGD", "HKD")
# Longest first, so "澳元" wins over "元" and "HK$" over "$".
SUFFIX = [("澳元", "AUD"), ("澳币", "AUD"), ("澳幣", "AUD"), ("澳刀", "AUD"), ("澳", "AUD"), ("美元", "USD"), ("美金", "USD"), ("美刀", "USD"),
          ("人民币", "CNY"), ("人民幣", "CNY"), ("块钱", "CNY"), ("塊錢", "CNY"), ("块", "CNY"), ("塊", "CNY"), ("日元", "JPY"), ("日币", "JPY"),
          ("日幣", "JPY"), ("円", "JPY"), ("韩元", "KRW"), ("韓元", "KRW"), ("원", "KRW"), ("越南盾", "VND"), ("盾", "VND"), ("đồng", "VND"),
          ("đ", "VND"), ("欧元", "EUR"), ("歐元", "EUR"), ("英镑", "GBP"), ("英鎊", "GBP"), ("港币", "HKD"), ("港幣", "HKD"), ("新币", "SGD"),
          ("新幣", "SGD"), ("加元", "CAD"), ("纽币", "NZD"), ("紐幣", "NZD"), ("元", "CNY"), ("刀", "$")]
CODES = ("AUD", "USD", "CNY", "RMB", "EUR", "GBP", "JPY", "KRW", "VND", "HKD", "SGD", "NZD", "CAD", "INR", "CHF")
PREFIX = [("AU$", "AUD"), ("A$", "AUD"), ("US$", "USD"), ("HK$", "HKD"), ("S$", "SGD"), ("NZ$", "NZD"), ("C$", "CAD"), ("￥", "CNY"),
          ("¥", "CNY"), ("€", "EUR"), ("£", "GBP"), ("₩", "KRW"), ("₫", "VND"), ("$", "$")]
WORDS = [("dollars", "$"), ("dollar", "$"), ("bucks", "$"), ("buck", "$"), ("yuan", "CNY"), ("yen", "JPY"), ("won", "KRW"), ("euros", "EUR"),
         ("euro", "EUR"), ("pounds", "GBP"), ("dong", "VND")]

_alt = lambda pairs: "|".join(re.escape(k) for k, _ in sorted(pairs, key=lambda kv: -len(kv[0])))
NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:[.,]\d{1,2})?"
AMOUNT = re.compile(
    rf"(?<![A-Za-z\d.,:])(?P<pre>{_alt(PREFIX)}|(?:{'|'.join(CODES)})\s?)?\s?(?P<num>{NUMBER})(?![\d:])\s?"
    rf"(?P<suf>{_alt(SUFFIX)}|(?:{'|'.join(CODES)})(?![A-Za-z])|(?:{_alt(WORDS)})(?![A-Za-z]))?", re.I)

WEEKDAYS = {  # Monday = 0
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    "月曜": 0, "火曜": 1, "水曜": 2, "木曜": 3, "金曜": 4, "土曜": 5, "日曜": 6,
    "월요일": 0, "화요일": 1, "수요일": 2, "목요일": 3, "금요일": 4, "토요일": 5, "일요일": 6,
    "thứ hai": 0, "thứ ba": 1, "thứ tư": 2, "thứ năm": 3, "thứ sáu": 4, "thứ bảy": 5, "chủ nhật": 6,
}
RELATIVE = [(r"大前天", 3), (r"前天|一昨日|그저께|hôm kia|day before yesterday", 2), (r"昨天|昨日|어제|hôm qua|yesterday", 1),
            (r"今天|今日|오늘|hôm nay|today", 0)]
FILLER = re.compile(r"(?i)(?:^|\s)(?:spent|paid|for|on|at|i|bought|花了|花|付了|付|买了|买|買了|買|用了|一共|共|总共|總共|大概|约|約)(?=\s|$)")


def _fullwidth(text):
    return text.translate({0xFF10 + i: ord("0") + i for i in range(10)} | {0xFF0C: ord(","), 0xFF0E: ord("."), 0xFF04: ord("$")})


def _date(text, today):
    """Find one date in the text; return (date or None, text without it)."""
    pats = [
        (r"(?P<y>\d{4})\s*[年/.\-]\s*(?P<m>\d{1,2})\s*[月/.\-]\s*(?P<d>\d{1,2})\s*[日号號]?", "ymd"),
        (r"(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*[日号號]?", "md"),
        (r"(?<![\d.,$])(?P<d>\d{1,2})/(?P<m>\d{1,2})(?:/(?P<y>\d{2,4}))?(?![\d/])", "dm"),
        (r"(?P<d>\d{1,2})\s*[日号號](?![\d])", "d"),
    ]
    for pat, kind in pats:
        m = re.search(pat, text)
        if not m:
            continue
        g = m.groupdict()
        y = int(g.get("y") or today.year)
        y = y + 2000 if y < 100 else y
        mon, dd = int(g.get("m") or today.month), int(g["d"])
        if kind == "dm" and mon > 12 >= dd:
            mon, dd = dd, mon  # "10/19" can only be month first
        try:
            d = date(y, mon, dd)
        except ValueError:
            continue
        if kind in ("md", "dm", "d") and not g.get("y") and d > today:
            d = d.replace(year=d.year - 1) if kind != "d" else (d.replace(month=mon - 1) if mon > 1 else d.replace(year=y - 1, month=12))
        return d, text[:m.start()] + " " + text[m.end():]
    for pat, back in RELATIVE:
        m = re.search(pat, text, re.I)
        if m:
            return today - timedelta(days=back), text[:m.start()] + " " + text[m.end():]
    m = re.search(r"(?i)(上上|上|this\s|last\s)?\s*(?:周|週|星期|礼拜|禮拜)([一二三四五六日天])|(上上|上|last\s)?\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
                  r"|(月曜|火曜|水曜|木曜|金曜|土曜|日曜)日?|([월화수목금토일]요일)|(thứ hai|thứ ba|thứ tư|thứ năm|thứ sáu|thứ bảy|chủ nhật)", text)
    if m:
        word = next(x for x in (m.group(2), m.group(4), m.group(5), m.group(6), m.group(7)) if x)
        wd = WEEKDAYS[word.lower()] if word.lower() in WEEKDAYS else WEEKDAYS[word]
        back = (today.weekday() - wd) % 7
        prefix = (m.group(1) or m.group(3) or "").strip().lower()
        if prefix in ("上", "last") and back == 0:
            back = 7
        if prefix == "上" and back < today.weekday() + 1 and back != 7:
            back += 7  # "上周五" on a Wednesday is the Friday of last week, not two days ago
        if prefix == "上上":
            back += 7 if back else 14
        return today - timedelta(days=back), text[:m.start()] + " " + text[m.end():]
    return None, text


def _number(raw):
    text = raw.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?", text):
        text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")  # "12,10" is a decimal comma
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value > 0 else None


def _currency(pre, suf, default):
    def code(token, table):
        if not token:
            return None
        token = token.strip()
        for k, v in table:
            if token.lower() == k.lower():
                return v
        up = token.upper()
        return "CNY" if up == "RMB" else up if up in CODES else None
    c = code(suf, SUFFIX + WORDS) or code(pre, PREFIX)
    if c == "$":
        return default if default in DOLLARS else "AUD"
    return c


def _clean(text):
    text = FILLER.sub(" ", " " + text + " ")
    text = re.sub(r"[,，;；、:：+＋&]|(?:\s|^)(?:和|还有|還有|and|plus)(?:\s|$)", " ", text)
    return re.sub(r"\s+", " ", text).strip(" .-·") or ""


def parse_text(raw, today=None, default="AUD"):
    """Items in a line of text: [{date, amount (Decimal, positive), currency, description, explicit_currency}]."""
    today = today or date.today()
    text = " ".join(_fullwidth(str(raw or "")).split())
    if not text:
        return []
    day, rest = _date(text, today)
    rest = re.sub(r"(?<!\d)\d{1,2}:\d{2}(?:\s?[ap]m)?(?![\d])", " ", rest, flags=re.I)  # times of day are not amounts
    matches = [m for m in AMOUNT.finditer(rest) if _number(m.group("num"))]
    # "iPhone 15 1299": a bare number right before another amount is part of the name, not a price.
    matches = [m for i, m in enumerate(matches)
               if not (i + 1 < len(matches) and not (m.group("pre") or m.group("suf")) and not rest[m.end():matches[i + 1].start()].strip())]
    items = []
    for i, m in enumerate(matches):
        start = matches[i - 1].end() if i else 0
        before = _clean(rest[start:m.start()])
        after = _clean(rest[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(rest)])
        # "午饭 10 打车 25": the words before an amount describe it; "12.50 lunch": a lone amount takes the words after.
        desc = before or (after if i + 1 == len(matches) or not _clean(rest[m.end():matches[i + 1].start()]) else "")
        if not before and i + 1 < len(matches):
            desc = after
        cur = _currency(m.group("pre"), m.group("suf"), default)
        items.append(dict(date=day or today, amount=_number(m.group("num")), currency=cur or default, description=desc or "",
                          explicit_currency=bool(cur)))
    # Words after the last amount that nobody claimed ("40 lunch") belong to it when it has none.
    if items and not items[-1]["description"]:
        items[-1]["description"] = _clean(rest[matches[-1].end():])
    for it in items:
        it["description"] = it["description"][:120] or "expense"
    return items
