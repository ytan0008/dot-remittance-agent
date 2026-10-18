"""The agent's own EVM wallet. The private key lives only in this process; never in the model, UI or logs."""
import json
import os
from pathlib import Path
from .domain import Denied


def load_account(config):
    """Returns (account, origin). Creates an encrypted keystore on first start when a password is configured."""
    from eth_account import Account
    if os.getenv("EVM_PRIVATE_KEY"):
        return Account.from_key(os.environ["EVM_PRIVATE_KEY"]), "environment key"
    password = config.wallet_password
    if not password:
        raise Denied("agent wallet password not configured (AGENT_WALLET_PASSWORD)", "wallet_unconfigured")
    if len(password) < 12:
        raise Denied("agent wallet password must be at least 12 characters", "wallet_unconfigured")
    path = Path(config.wallet_path)
    if path.exists():
        key = Account.decrypt(json.loads(path.read_text(encoding="utf-8")), password)
        account = Account.from_key(key)
        del key
        return account, "encrypted keystore"
    account = Account.create()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as out:  # never overwrite an existing wallet
        json.dump(Account.encrypt(account.key, password), out)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return account, "encrypted keystore (created)"
