"""What leaves this machine for the AI model, and how you take your data with you or wipe it.

Before any text goes to an external model, account numbers, card numbers, IBANs and email addresses are replaced by
placeholders such as [ACCT_1 …2222]. The model can still talk about "the account ending 2222" and pass the placeholder to a
tool; the backend swaps the real value back in only inside tool arguments, on this machine. Images (receipts, bank app
screenshots) cannot be masked and are sent as they are — the screen says so before you upload.
"""
import json
import re

# Order matters: the more specific patterns first.
PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63})+")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")),
    # BSB + account (062-000 12345678), or a labelled account/card number of 6+ digits
    ("ACCT", re.compile(r"(?<!\d)\d{3}-?\d{3}[ -]\d{5,10}(?!\d)")),
    ("ACCT", re.compile(r"(?i)(?:account|acct|a/c|card|账号|帐号|卡号|账户|帳戶|帳號|số tài khoản|口座番号|계좌번호)\s*(?:no\.?|number|号码)?\s*[:：#]?\s*(\d[\d -]{4,}\d)")),
    # any long run of digits (cards, Chinese bank accounts): 10+ digits, spaces or dashes allowed between groups
    ("ACCT", re.compile(r"(?<![\w.,])\d(?:[ -]?\d){9,22}(?![\w.,])")),
]
TOKEN = re.compile(r"\[(EMAIL|IBAN|ACCT)_(\d+)[^\]]{0,24}\]")


class Redactor:
    """One per conversation turn: the same value always gets the same placeholder."""

    def __init__(self):
        self.values, self.tokens = {}, {}

    def _token(self, kind, value):
        key = value.strip()
        if key not in self.tokens:
            n = sum(1 for k in self.values if k.startswith(kind)) + 1
            digits = re.sub(r"\D", "", key)
            tail = f" …{digits[-4:]}" if kind != "EMAIL" and len(digits) >= 4 else (f" {key[0]}…@{key.split('@')[1]}" if kind == "EMAIL" else "")
            name = f"{kind}_{n}"
            self.values[name] = key
            self.tokens[key] = f"[{name}{tail}]"
        return self.tokens[key]

    def mask(self, text):
        if not isinstance(text, str) or not text:
            return text
        out = text
        for kind, rx in PATTERNS:
            def swap(m, kind=kind):
                if rx.groups:  # a labelled number: keep the label, mask the number
                    whole, num = m.group(0), m.group(1)
                    return whole[:m.start(1) - m.start(0)] + self._token(kind, num) + whole[m.end(1) - m.start(0):]
                return self._token(kind, m.group(0))
            out = rx.sub(swap, out)
        return out

    def unmask(self, value):
        """Real values back into tool arguments (a JSON string, dict, list or plain text)."""
        if isinstance(value, str):
            return TOKEN.sub(lambda m: self.values.get(f"{m.group(1)}_{m.group(2)}", m.group(0)), value)
        if isinstance(value, dict):
            return {k: self.unmask(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.unmask(v) for v in value]
        return value

    @property
    def count(self):
        return len(self.values)


SKIP_TABLES = {"secrets", "sqlite_sequence"}  # signed raw transactions never leave, even in an export


def export_workspace(store):
    """Everything this workspace holds, as plain JSON tables."""
    out = {}
    with store.read() as c:
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for name in names:
            if name in SKIP_TABLES:
                continue
            rows = []
            for r in c.execute(f'SELECT * FROM "{name}"'):
                row = dict(r)
                for k, v in row.items():
                    if isinstance(v, bytes):
                        row[k] = None
                    elif isinstance(v, str) and v[:1] in "{[":
                        try:
                            row[k] = json.loads(v)
                        except ValueError:
                            pass
                rows.append(row)
            out[name] = rows
    return out
