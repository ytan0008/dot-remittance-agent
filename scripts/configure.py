"""Create or upgrade the local Docker configuration without printing or overwriting credentials."""
from pathlib import Path
import secrets

path = Path(__file__).resolve().parents[1] / ".env"
defaults = {
    "OWNER_TOKEN": lambda: secrets.token_urlsafe(32),
    "AGENT_TOKEN": lambda: secrets.token_urlsafe(32),
    "ENABLE_DEMO_LOGIN": lambda: "true",
    "OPENAI_API_KEY": lambda: "",
    "OPENAI_MODEL": lambda: "gpt-6-luna",
    "OPENAI_REASONING_EFFORT": lambda: "none",
    "OPENAI_BASE_URL": lambda: "",
    # The agent's own wallet on the Sepolia test network. Remove EVM_RPC_URL to run the sandbox only.
    "EVM_RPC_URL": lambda: "",  # on-chain payments are paused; leave empty
    "EVM_CHAIN_ID": lambda: "11155111",
    "EVM_CONFIRMATIONS": lambda: "3",
    "AGENT_WALLET_PASSWORD": lambda: secrets.token_urlsafe(24),
    "ENABLE_LIVE_PAYMENTS": lambda: "false",
}
present = {}
if path.exists():
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            present[line.split("=", 1)[0].strip()] = True
missing = [k for k in defaults if k not in present]
if not path.exists():
    with path.open("x", encoding="utf-8") as f:
        f.write("\n".join(f"{k}={defaults[k]()}" for k in defaults) + "\n")
    print("Created .env (local sandbox + Sepolia agent wallet). Credentials were not printed.")
elif missing:
    with path.open("a", encoding="utf-8") as f:
        f.write("\n# Added by scripts/configure.py\n" + "\n".join(f"{k}={defaults[k]()}" for k in missing) + "\n")
    print("Existing .env preserved; added missing keys:", ", ".join(missing))
else:
    print("Existing .env preserved.")
