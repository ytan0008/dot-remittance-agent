import contextvars
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR


class Denied(ValueError):
    """A rule refused the action. `code` is stable for UI translation; message stays English."""

    def __init__(self, message, code=None, **params):
        super().__init__(message)
        self.code = code or "denied"
        self.params = params


# Correlates every audit event written while serving one HTTP request or chat turn.
request_id = contextvars.ContextVar("request_id", default=None)


def new_request_id():
    value = uuid.uuid4().hex[:16]
    request_id.set(value)
    return value


def now() -> int:
    return int(time.time())


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


# ISO 4217 minor units for currencies that are not two-decimal; ETH uses wei.
DECIMALS = {"JPY": 0, "KRW": 0, "VND": 0, "CLP": 0, "PYG": 0, "ISK": 0, "ETH": 18}


def decimals(currency: str) -> int:
    return DECIMALS.get(currency, 2)


def units(value: str, places: int) -> int:
    try:
        d = Decimal(str(value))
        if not d.is_finite() or d <= 0 or d > Decimal("1000000000000"):
            raise Denied("amount must be finite, positive and within bounds", "amount_invalid")
        scaled = d * 10**places
        if scaled != scaled.to_integral_value():
            raise Denied(f"amount supports at most {places} decimal places", "amount_precision", places=places)
        return int(scaled)
    except (InvalidOperation, TypeError):
        raise Denied("invalid amount", "amount_invalid") from None


def to_minor(amount, currency, rounding=ROUND_CEILING) -> int:
    return int((Decimal(amount) * 10**decimals(currency)).to_integral_value(rounding=rounding))


def from_minor(value, currency) -> Decimal:
    return Decimal(int(value)) / 10**decimals(currency)


def floor_minor(amount, currency) -> int:
    return to_minor(amount, currency, ROUND_FLOOR)


def mask(text, keep=4) -> str:
    """Mask account numbers and addresses before they reach logs."""
    text = str(text or "")
    if len(text) <= keep + 2:
        return text
    return text[:2] + "…" + text[-keep:] if text.startswith("0x") else "•••• " + text[-keep:]


@dataclass(frozen=True)
class Config:
    db: str = "data/finance.sqlite3"
    chain_id: int = 11155111
    live: bool = False
    rpc_url: str = ""
    onchain: bool = False  # the legacy EVM wallet path: off unless ENABLE_ONCHAIN=true (never in the competition build)
    confirmations: int = 12
    max_gas_gwei: str = "30"
    max_eth: str = "0.01"
    daily_eth: str = "0.05"
    max_aud: str = "500"
    daily_aud: str = "1000"
    wallet_path: str = ""
    wallet_password: str = ""
    sandbox_settle_seconds: int = 8

    @classmethod
    def env(cls):
        db = os.getenv("FINANCE_DB", cls.db)
        return cls(
            db=db,
            chain_id=int(os.getenv("EVM_CHAIN_ID", "11155111")),
            live=os.getenv("ENABLE_LIVE_PAYMENTS") == "true",
            rpc_url=os.getenv("EVM_RPC_URL", ""),
            onchain=os.getenv("ENABLE_ONCHAIN") == "true",
            confirmations=int(os.getenv("EVM_CONFIRMATIONS", "3")),
            max_gas_gwei=os.getenv("EVM_MAX_GAS_PRICE_GWEI", "30"),
            max_eth=os.getenv("MAX_PAYMENT_ETH", "0.01"),
            daily_eth=os.getenv("DAILY_PAYMENT_ETH", "0.05"),
            max_aud=os.getenv("MAX_PAYMENT_AUD", "500"),
            daily_aud=os.getenv("DAILY_PAYMENT_AUD", "1000"),
            wallet_path=os.getenv("EVM_KEYSTORE_PATH", str(os.path.join(os.path.dirname(db) or ".", "agent.keystore.json"))),
            wallet_password=os.getenv("EVM_KEYSTORE_PASSWORD", "") or os.getenv("AGENT_WALLET_PASSWORD", ""),
            sandbox_settle_seconds=int(os.getenv("SANDBOX_SETTLE_SECONDS", "8")),
        )
