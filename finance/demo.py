"""Offline demonstration: python -m finance.demo. Never broadcasts to a network."""
import json
import tempfile
from pathlib import Path
from .domain import Config, Denied
from .service import Finance


class FixtureRates:
    """The demo runs offline; quotes fall back to labeled synthetic fixture rates."""
    def latest(self, source, target):
        raise Denied("offline demo", "rates_unavailable")


def main():
    with tempfile.TemporaryDirectory() as folder:
        f = Finance(Config(db=str(Path(folder)/"demo.db"), sandbox_settle_seconds=0), rates=FixtureRates())
        f.add_sandbox_currency("owner", "AUD", "1000")
        f.add_sandbox_currency("owner", "CNY", "0")
        f.add_recipient("owner", "family", "Family demo recipient", currency="CNY", country="CN")
        f.remember("owner", "language", "zh-CN")
        draft = f.prepare("agent", "100", "AUD", "CNY", "family", "family support", "demo-001")
        try:
            f.execute("agent", draft["id"])
        except Denied as exc:
            print("Unauthorized execution blocked:", exc)
        f.approve("owner", draft["id"], draft["approval_digest"])
        receipt = f.execute("owner", draft["id"])
        retry = f.execute("owner", draft["id"])
        assert retry == receipt
        lost = f.prepare("agent", "12.57", "AUD", "CNY", "family", "timeout recovery test", "demo-002")
        f.approve("owner", lost["id"], lost["approval_digest"])
        unknown = f.execute("owner", lost["id"])
        recovered = f.reconcile("agent", lost["id"])
        print(json.dumps({"receipt": receipt, "timeout_case": [unknown["status"], recovered["status"]],
                          "balances": f.balances(), "audit_events": len(f.audit()),
                          "duplicate_protection": "passed"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
