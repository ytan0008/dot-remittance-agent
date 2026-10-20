import pytest
from web3 import Web3, EthereumTesterProvider
from finance.domain import Config, Denied
from finance.service import Finance
from finance.providers import EvmProvider

RATES = {("AUD", "CNY"): "4.64", ("USD", "AUD"): "1.44", ("USD", "CNY"): "7.10", ("AUD", "USD"): "0.69",
         ("CNY", "AUD"): "0.2155", ("USD", "PHP"): "57.2", ("AUD", "VND"): "17900"}


class FakeRates:
    """Deterministic reference data for tests; unknown pairs are unavailable, never invented."""
    def __init__(self, table=None):
        self.table = dict(RATES if table is None else table)

    def latest(self, source, target):
        rate = self.table.get((source, target))
        if not rate:
            raise Denied("reference data unavailable or unsupported; no synthetic fallback", "rates_unavailable")
        return dict(kind="reference", rate=rate, provider="test reference", observed="2026-10-16", derived=False,
                    source=source, target=target)

    def fetch(self, source, target, days="0"):
        return dict(self.latest(source, target), series=[{"date": "2026-10-16", "rate": self.latest(source, target)["rate"]}])

    def forecast(self, source, target, horizon_days=7):
        return dict(available=False, reason="test")


def seed_sandbox(f):
    """The test money most tests pay from: 1,000 AUD, 5,000 CNY, 500 USD in the sandbox."""
    for currency, amount in (("AUD", "1000"), ("CNY", "5000"), ("USD", "500")):
        f.add_sandbox_currency("owner", currency, amount)


@pytest.fixture
def local(tmp_path):
    f = Finance(Config(db=str(tmp_path / "local.db"), sandbox_settle_seconds=0), rates=FakeRates())
    seed_sandbox(f)
    f.add_recipient("owner", "family", "Family", currency="CNY", country="CN", account="6222000011112222")
    return f


@pytest.fixture
def evm(tmp_path):
    w3 = Web3(EthereumTesterProvider())
    account = w3.eth.account.from_key(w3.provider.ethereum_tester.backend.account_keys[0])
    config = Config(db=str(tmp_path / "evm.db"), chain_id=w3.eth.chain_id, live=True, confirmations=1)
    f = Finance(config, EvmProvider(config, w3, account), rates=FakeRates())
    f.add_recipient("owner", "family", "Recipient", w3.eth.accounts[1])
    return f


def draft(f, amount="100", key="one"):
    on_chain = f.evm is not None
    return f.prepare("agent", amount, "ETH" if on_chain else "AUD", "ETH" if on_chain else "CNY", "family", "support", key)


def approved(f, amount="100", key="one"):
    t = draft(f, amount, key)
    f.approve("owner", t["id"], t["approval_digest"])
    return t
