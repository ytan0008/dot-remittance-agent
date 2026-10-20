"""Create local simulation settings without printing or replacing existing secrets."""
import argparse
from pathlib import Path
import secrets


def configure(path):
    template = Path(__file__).resolve().parents[1] / ".env.example"
    content = path.read_text(encoding="utf-8-sig") if path.exists() else template.read_text(encoding="utf-8")
    lines = content.splitlines()
    present = {}
    for i, line in enumerate(lines):
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            present[key.strip()] = (i, value.strip())
    defaults = dict(PUBLIC_DEPLOY="false", COOKIE_SECURE="false", ENABLE_ONCHAIN="false",
        ENABLE_LIVE_PAYMENTS="false", EVM_RPC_URL="", ALLOW_SIGNUP="true", ENABLE_DEMO_LOGIN="true",
        ENABLE_WORKER="true", FRONTEND_PORT="8787", FINANCE_DB="data/finance.sqlite3",
        OPENAI_API_KEY="", OPENAI_MODEL="gpt-6-luna", OPENAI_REASONING_EFFORT="none", OPENAI_BASE_URL="")
    for key in ("OWNER_TOKEN", "AGENT_TOKEN"):
        value = present.get(key, (-1, ""))[1].strip(chr(34) + chr(39))
        if not value or value.startswith("replace-with-"):
            new_line = f"{key}={secrets.token_urlsafe(32)}"
            if key in present:
                lines[present[key][0]] = new_line
            else:
                lines.append(new_line)
    for key, value in defaults.items():
        if key not in present:
            lines.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Configured {path.name}. Existing values preserved; blank/example tokens replaced. No secrets printed.")
    print("Local defaults use HTTP and simulation only. Review existing deployment settings before restart.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    configure(parser.parse_args().output)
