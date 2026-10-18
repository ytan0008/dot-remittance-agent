"""Local owner's terminal. Shell access is trusted; model has no shell tool."""
import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
from decimal import Decimal
from .domain import Denied, now


def show(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def confirm_payment(payment):
    show(payment)
    b = payment["details"]
    divisor = Decimal(10)**(18 if b["source"] == "ETH" else 2)
    print(f"Environment: {b['environment']} | Recipient: {b['recipient']['name']} {b['recipient']['address']}")
    print(f"Maximum debit: {Decimal(b['reserve'])/divisor} {b['source']} | Fee: {Decimal(b['fee'])/divisor}")
    return input(f"Type APPROVE {payment['id']} to authorize these exact details: ") == "APPROVE "+payment["id"]


def main():
    parser = argparse.ArgumentParser(description="Finance agent local owner console")
    parser.add_argument("command", choices=["demo", "serve", "wallet-create", "wallet", "chat", "recipient", "approve", "mandate", "revoke", "reconcile", "history", "balances"])
    parser.add_argument("--id")
    parser.add_argument("--name")
    parser.add_argument("--address", default="")
    parser.add_argument("--currency", default="CNY")
    parser.add_argument("--path", default="data/agent.keystore.json")
    parser.add_argument("--per-payment", default="0.002")
    parser.add_argument("--budget", default="0.005")
    parser.add_argument("--hours", type=int, default=1)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.command == "demo":
        from .demo import main as demo
        return demo()
    if args.command == "wallet-create":
        from eth_account import Account
        password = getpass.getpass("New keystore password (12+ characters): ")
        if len(password) < 12 or password != getpass.getpass("Repeat password: "):
            raise Denied("password too short or does not match")
        account = Account.create()
        encrypted = Account.encrypt(account.key, password)
        path = Path(args.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as out:
            json.dump(encrypted, out)
        print("Wallet address:", account.address)
        print("Encrypted keystore:", path.resolve())
        print("Back up this keystore and its password separately. No funds have been transferred.")
        return
    if args.command == "serve":
        import uvicorn
        for role in ("OWNER", "AGENT"):
            if not os.getenv(role+"_TOKEN"):
                os.environ[role+"_TOKEN"] = secrets.token_urlsafe(32)
                print(f"Session-only {role}_TOKEN: {os.environ[role+'_TOKEN']}")
        print(f"Workspace: http://127.0.0.1:{args.port}/   API console: http://127.0.0.1:{args.port}/api/docs")
        uvicorn.run("finance.web:app", host="127.0.0.1", port=args.port, workers=1)
        return
    from .service import Finance
    from .agent import Agent
    f = Finance()
    if args.command == "recipient":
        if not args.id or not args.name:
            raise Denied("--id and --name required")
        show(f.add_recipient("owner", args.id, args.name, args.address, currency="" if args.address else args.currency))
    elif args.command == "approve":
        payment = f.get(args.id)
        if confirm_payment(payment):
            show(f.approve("owner", args.id, payment["approval_digest"]))
            print("Approved. Ask the agent to execute this ID, or call the execute API.")
    elif args.command == "mandate":
        print(f"Authorize the agent to spend ETH from its own wallet to recipient {args.id}, including fees.")
        show({"recipients": f.recipients(), "per_payment_ETH": args.per_payment,
              "total_budget_ETH": args.budget, "expires_in_hours": args.hours,
              "chain_id": f.config.chain_id, "agent_wallet": f.evm.account.address if f.evm else None})
        if input("Type GRANT to authorize this scope: ") == "GRANT":
            show(f.grant_mandate("owner", args.id, args.per_payment, args.budget, now()+args.hours*3600))
    elif args.command == "revoke":
        show(f.revoke("owner", args.id))
    elif args.command == "reconcile":
        show(f.reconcile("owner", args.id))
    elif args.command == "chat":
        agent = Agent(f)
        print("Type /exit to quit. Approve or grant scopes in a separate owner terminal. Never enter secrets here.")
        while True:
            message = input("You> ")
            if message == "/exit":
                break
            if message.strip():
                try:
                    reply = agent.chat(message, "terminal", os.getenv("AGENT_LANGUAGE", "en"))
                    show({"mode": reply["mode"], "plan": reply["plan"], "trace": [t["tool"] for t in reply["trace"]]})
                    print("Agent>", reply["message"])
                except Exception as exc:
                    print(str(exc) if isinstance(exc, Denied) else "Model/service request failed; check local configuration.")
    elif args.command == "wallet":
        show(f.wallet())
    else:
        show(getattr(f, args.command)())


if __name__ == "__main__":
    try:
        main()
    except Denied as exc:
        print("Blocked:", exc)
        raise SystemExit(1)
