"""The documented bootstrap must not expose or replace existing user secrets."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("configure_script", Path(__file__).resolve().parents[1] / "scripts/configure.py")
configure_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure_script)


def values(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))


def test_bootstrap_creates_distinct_tokens_and_simulation_settings(tmp_path, capsys):
    path = tmp_path / ".env"
    configure_script.configure(path)
    data = values(path)
    assert len(data["OWNER_TOKEN"]) >= 24 and data["OWNER_TOKEN"] != data["AGENT_TOKEN"]
    assert data["ENABLE_ONCHAIN"] == data["ENABLE_LIVE_PAYMENTS"] == data["PUBLIC_DEPLOY"] == "false"
    assert data["EVM_RPC_URL"] == data["OPENAI_API_KEY"] == ""
    assert data["OWNER_TOKEN"] not in capsys.readouterr().out
    original = path.read_bytes()
    configure_script.configure(path)
    assert path.read_bytes() == original


def test_bootstrap_preserves_existing_values_and_fills_blank_tokens(tmp_path):
    path = tmp_path / ".env"
    path.write_text("OWNER_TOKEN=existing-owner-token-that-must-be-kept\nAGENT_TOKEN=\nPUBLIC_DEPLOY=true\nOPENAI_API_KEY=example-local-value\n")
    configure_script.configure(path)
    data = values(path)
    assert data["OWNER_TOKEN"] == "existing-owner-token-that-must-be-kept"
    assert len(data["AGENT_TOKEN"]) >= 24
    assert data["PUBLIC_DEPLOY"] == "true"
    assert data["OPENAI_API_KEY"] == "example-local-value"
