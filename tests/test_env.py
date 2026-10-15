import os
import shutil
import pytest
from typer.testing import CliRunner


def setup_env(tmp_path, monkeypatch, text):
    monkeypatch.setattr(os, "environ", dict(os.environ))
    for key in list(os.environ):
        if key.startswith("ARBITRARY_") or key == "RPC_42161":
            os.environ.pop(key)
    shutil.copytree("config", tmp_path / "config")
    (tmp_path / ".env").write_text(text)
    return tmp_path / "config/app.yaml"


def test_one_env_loads_wallets_fee_and_rpc_with_chain_override(tmp_path, monkeypatch):
    from flasharb.config import load_config

    path = setup_env(
        tmp_path,
        monkeypatch,
        "ARBITRARY_PROFIT_WALLET=0x"
        + "11" * 20
        + "\nARBITRARY_GAS_WALLET=0x"
        + "22" * 20
        + "\nARBITRARY_MERCHANT_WALLET=0x"
        + "33" * 20
        + "\nARBITRARY_PROFIT_WALLET_42161=0x"
        + "44" * 20
        + "\nRPC_42161=https://example.test/key\n",
    )
    cfg = load_config(path)
    chain = next(c for c in cfg.chains if c.chain_id == 42161)
    assert chain.recipient == "0x" + "44" * 20 and chain.operator == "0x" + "22" * 20
    assert chain.merchant == "0x" + "33" * 20 and chain.merchant_fee_bps == 500
    assert os.environ["RPC_42161"] == "https://example.test/key"
    assert "example.test" not in cfg.model_dump_json()
    assert cfg.mode == "observe" and not any(c.enabled for c in cfg.chains)


def test_invalid_env_wallet_rejected_without_echoing_value(tmp_path, monkeypatch):
    from flasharb.config import load_config

    path = setup_env(tmp_path, monkeypatch, "ARBITRARY_MERCHANT_WALLET=not-an-address\n")
    with pytest.raises(ValueError) as exc:
        load_config(path)
    assert "not-an-address" not in str(exc.value)


def test_deployment_plan_uses_env_wallets_and_five_percent(tmp_path, monkeypatch):
    from flasharb.cli import app

    keys = ["OWNER", "GAS", "PROFIT", "MERCHANT"]
    env = "\n".join(f"ARBITRARY_{key}_WALLET=0x" + str(i) * 40 for i, key in enumerate(keys, 1))
    cfg = setup_env(tmp_path, monkeypatch, env)
    r = CliRunner().invoke(
        app, ["deploy-plan", "42161", "--config", str(cfg), "--out", str(tmp_path / "plan.json")]
    )
    assert r.exit_code == 0, r.output
    import json

    plan = json.loads((tmp_path / "plan.json").read_text())
    assert plan["merchant_fee_bps"] == 500 and plan["merchant"] == "0x" + "4" * 40
    assert plan["broadcast"] is False
