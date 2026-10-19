"""Payment rails. Adapters never return private keys or signed raw transactions to the model."""
import uuid
from decimal import Decimal, ROUND_CEILING
from .domain import Denied, now, units, decimals, from_minor, floor_minor, to_minor

# Pairs the local simulated provider accepts. A route must also be enabled by the owner.
SANDBOX_PAIRS = {("AUD", "CNY"), ("AUD", "VND"), ("AUD", "PHP"), ("USD", "CNY"), ("USD", "VND"), ("USD", "PHP"),
                 ("USD", "MXN"), ("CNY", "AUD"), ("CNY", "USD"), ("CNY", "VND")}
# Used only when reference data is unreachable; always labeled synthetic.
FIXTURE_RATES = {("CNY", "AUD"): "0.215", ("CNY", "USD"): "0.14", ("CNY", "VND"): "3600", ("AUD", "CNY"): "4.70", ("AUD", "VND"): "17000", ("AUD", "PHP"): "38", ("USD", "CNY"): "7.10",
                 ("USD", "VND"): "26000", ("USD", "PHP"): "57", ("USD", "MXN"): "18"}
SPREAD = Decimal("0.005")
FIXED_FEE = Decimal("1")
PERCENT_FEE = Decimal("0.005")


class SandboxProvider:
    """Local simulation shaped like a provider sandbox: quotes, idempotent submission, async status.

    Test scenarios use magic cents, as many provider sandboxes do:
      x.13 -> provider rejects after processing (confirmed failure, funds released)
      x.57 -> submission response is lost (outcome unknown until status query)
    """
    name = "local_simulation"

    def __init__(self, store, rates, settle_seconds=8):
        self.store = store
        self.rates = rates
        self.settle_seconds = settle_seconds

    def supports(self, source, target):
        return (source, target) in SANDBOX_PAIRS

    def rate(self, source, target):
        try:
            ref = self.rates.latest(source, target)
            reference = dict(rate=ref["rate"], provider=ref["provider"], observed=ref["observed"], derived=ref["derived"])
            return Decimal(ref["rate"]), reference, "reference rate less simulated 0.5% spread"
        except Denied:
            rate = Decimal(FIXTURE_RATES[(source, target)])
            return rate, None, "synthetic fixture rate less simulated 0.5% spread (reference unavailable; not market data)"

    @staticmethod
    def fee(value, source):
        scale = 10**decimals(source)
        return int((FIXED_FEE * scale + Decimal(value) * PERCENT_FEE).to_integral_value(rounding=ROUND_CEILING))

    def quote(self, source, target, recipient, purpose, amount=None, receive_amount=None):
        if not self.supports(source, target):
            raise Denied("route not supported by the sandbox provider", "route_unsupported")
        reference_rate, reference, rate_kind = self.rate(source, target)
        applied = (reference_rate * (1 - SPREAD)).quantize(Decimal("0.000001"))
        if receive_amount is not None:
            wanted = units(receive_amount, decimals(target))
            # receive = (value - fee) * rate, fee = fixed + pct*value  =>  value = (receive/rate + fixed) / (1 - pct)
            need = (from_minor(wanted, target) / applied + FIXED_FEE) / (1 - PERCENT_FEE)
            value = to_minor(need, source)
            mode = "receive"
        else:
            value = units(amount, decimals(source))
            mode = "send"
        fee = self.fee(value, source)
        if value <= fee:
            raise Denied("amount must exceed the simulated fee", "amount_below_fee")
        receive = floor_minor(from_minor(value - fee, source) * applied, target)
        while mode == "receive" and receive < wanted:  # rounding: never deliver less than the target
            value += 1
            fee = self.fee(value, source)
            receive = floor_minor(from_minor(value - fee, source) * applied, target)
        return dict(rail="sandbox", environment=self.name, source=source, target=target,
                    amount=str(from_minor(value, source)), value=value, fee=fee, reserve=value, receive=receive,
                    fee_breakdown=dict(fixed=str(FIXED_FEE), percent=str(PERCENT_FEE * 100)),
                    rate=str(applied), reference=reference, spread_pct=str(SPREAD * 100), rate_kind=rate_kind,
                    mode=mode, target_receive=receive_amount,
                    unknown_charges="intermediary or receiving-bank charges are not modeled and may reduce the amount received",
                    eta=f"simulated settlement about {self.settle_seconds}s after submission", eta_seconds=self.settle_seconds,
                    expires=now() + 300, recipient=recipient, purpose=purpose)

    def submit(self, c, transfer_id, body):
        """Idempotent on transfer_id: a retry returns the original provider reference, never a new transfer."""
        row = c.execute("SELECT * FROM sandbox_provider WHERE transfer_id=?", (transfer_id,)).fetchone()
        if row:
            return row["ref"], False
        cents = body["value"] % 100 if decimals(body["source"]) == 2 else -1
        scenario = "reject" if cents == 13 else "lost_response" if cents == 57 else "complete"
        ref = "sbx_" + uuid.uuid4().hex[:20]
        c.execute("INSERT INTO sandbox_provider VALUES (?,?,?,?,?,?)",
                  (ref, transfer_id, "processing", scenario, now(), now() + self.settle_seconds))
        return ref, scenario == "lost_response"

    def find(self, c, transfer_id):
        row = c.execute("SELECT ref FROM sandbox_provider WHERE transfer_id=?", (transfer_id,)).fetchone()
        return row["ref"] if row else None

    def status(self, c, ref):
        row = c.execute("SELECT * FROM sandbox_provider WHERE ref=?", (ref,)).fetchone()
        if not row:
            return "unknown"
        if row["status"] == "processing" and row["settle_at"] <= now():
            final = "failed" if row["scenario"] == "reject" else "completed"
            c.execute("UPDATE sandbox_provider SET status=? WHERE ref=?", (final, ref))
            return final
        return row["status"]


class EvmProvider:
    """Native ETH transfers from the agent's own wallet on the configured EVM chain."""
    name = "evm"

    def __init__(self, config, web3=None, account=None, origin="injected"):
        from web3 import Web3
        self.config = config
        if config.chain_id != 11155111 and not config.live:
            raise Denied("non-Sepolia network requires ENABLE_LIVE_PAYMENTS=true", "live_blocked")
        if config.confirmations < 1:
            raise Denied("confirmation depth must be positive")
        self.w3 = web3 or Web3(Web3.HTTPProvider(config.rpc_url, request_kwargs={"timeout": 15}))
        if account is None:
            from .wallet import load_account
            account, origin = load_account(config)
        self.account = account
        self.origin = origin
        self._info = (0.0, None)

    @property
    def environment(self):
        return "sepolia_testnet" if self.config.chain_id == 11155111 else "live_chain"

    def check_chain(self):
        if self.w3.eth.chain_id != self.config.chain_id:
            raise Denied("RPC chain ID does not match configured chain", "chain_mismatch")

    def balance(self):
        self.check_chain()
        return self.w3.eth.get_balance(self.account.address)

    def invalidate(self):
        self._info = (0.0, None)

    def display_balance(self, max_age=15):
        """For display only; guardrails always call balance() for a fresh read."""
        return int(self.info(max_age)["balance"]) if self.info(max_age).get("connected") else self.balance()

    def info(self, max_age=15):
        import time
        stamp, cached = self._info
        if cached and time.time() - stamp < max_age:
            return dict(cached)
        info = dict(address=self.account.address, chain_id=self.config.chain_id, environment=self.environment,
                    key_origin=self.origin, confirmations=self.config.confirmations,
                    explorer={11155111: "https://sepolia.etherscan.io", 1: "https://etherscan.io"}.get(self.config.chain_id))
        try:
            self.check_chain()
            info.update(connected=True, balance=str(self.w3.eth.get_balance(self.account.address)),
                        nonce=self.w3.eth.get_transaction_count(self.account.address),
                        block=self.w3.eth.block_number, gas_price=str(self.w3.eth.gas_price))
        except Exception:
            info.update(connected=False)
            return info
        self._info = (time.time(), info)
        return dict(info)

    def quote(self, recipient, purpose, amount):
        self.check_chain()
        address = self.w3.to_checksum_address(recipient["address"])
        if address == self.account.address or int(address, 16) == 0:
            raise Denied("self or zero address not supported", "address_invalid")
        if self.w3.eth.get_code(address):
            raise Denied("only externally owned recipient accounts supported", "address_contract")
        value = units(amount, 18)
        gas_price = self.w3.eth.gas_price
        if gas_price > units(self.config.max_gas_gwei, 9):
            raise Denied("gas price exceeds configured ceiling", "gas_ceiling")
        gas = self.w3.eth.estimate_gas({"from": self.account.address, "to": address, "value": value})
        if gas != 21000:
            raise Denied("only plain native ETH transfers with 21000 gas supported", "gas_unexpected")
        return dict(rail="evm", environment=self.environment, source="ETH", target="ETH", amount=amount, value=value,
                    fee=gas * gas_price, reserve=value + gas * gas_price, receive=value, expires=now() + 120,
                    recipient=recipient, purpose=purpose, chain_id=self.config.chain_id, mode="send",
                    sender=self.account.address, gas=gas, gas_price=gas_price, rate="1", reference=None,
                    eta=f"{self.config.confirmations} confirmations", rate_kind="no FX conversion",
                    unknown_charges="none beyond network gas; recipient wallets may apply their own fees on withdrawal")

    def sign(self, body):
        self.check_chain()
        if body["sender"] != self.account.address or body["chain_id"] != self.config.chain_id:
            raise Denied("wallet or chain changed after quote", "chain_mismatch")
        to = self.w3.to_checksum_address(body["recipient"]["address"])
        if self.w3.eth.get_code(to):
            raise Denied("recipient is now a contract", "address_contract")
        nonce = self.w3.eth.get_transaction_count(self.account.address, "pending")
        if nonce != self.w3.eth.get_transaction_count(self.account.address, "latest"):
            raise Denied("wallet has an external pending transaction; reconcile first", "wallet_pending")
        signed = self.account.sign_transaction(dict(chainId=body["chain_id"], nonce=nonce,
                    to=to, value=body["value"], gas=body["gas"], gasPrice=body["gas_price"], data=b""))
        tx_hash = signed.hash.hex()
        return (tx_hash if tx_hash.startswith("0x") else "0x" + tx_hash), signed.raw_transaction.hex()

    def broadcast(self, raw):
        self.check_chain()
        return self.w3.eth.send_raw_transaction(bytes.fromhex(raw.removeprefix("0x"))).hex()

    def status(self, reference):
        from web3.exceptions import TransactionNotFound
        self.check_chain()
        try:
            receipt = self.w3.eth.get_transaction_receipt(reference)
        except TransactionNotFound:
            return "unknown", None
        if self.w3.eth.block_number - receipt.blockNumber + 1 < self.config.confirmations:
            return "pending", None
        block = self.w3.eth.get_block(receipt.blockNumber)
        if block.hash != receipt.blockHash:
            return "unknown", None
        fee = receipt.gasUsed * receipt.effectiveGasPrice
        return ("completed" if receipt.status == 1 else "failed"), fee
