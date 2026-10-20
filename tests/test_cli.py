from typer.testing import CliRunner


def test_status_without_rpc_and_no_broadcast(tmp_path):
    from flasharb.cli import app
    import shutil

    shutil.copytree("config", tmp_path / "config")
    cfg = tmp_path / "config/app.yaml"
    cfg.write_text(cfg.read_text().replace("data_dir: data", f"data_dir: {tmp_path}/data"))
    r = CliRunner().invoke(app, ["status", "--config", str(cfg)])
    assert r.exit_code == 0 and "pending" in r.output


def test_help_lists_required_commands():
    from flasharb.cli import app

    r = CliRunner().invoke(app, ["--help"])
    assert r.exit_code == 0
    for name in [
        "doctor",
        "serve",
        "run",
        "deploy-plan",
        "deploy-plans",
        "estimate-cost",
        "estimate-plans",
        "backup",
    ]:
        assert name in r.output


def test_deploy_plans_creates_unsigned_plan_for_each_chain(tmp_path):
    import json
    from typer.testing import CliRunner
    from flasharb.cli import app

    out_dir = tmp_path / "plans"
    addresses = ["0x" + char * 40 for char in ("1", "2", "3", "4")]
    result = CliRunner().invoke(
        app,
        [
            "deploy-plans",
            "--owner",
            addresses[0],
            "--operator",
            addresses[1],
            "--recipient",
            addresses[2],
            "--merchant",
            addresses[3],
            "--merchant-fee-bps",
            "500",
            "--out-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    plans = sorted(out_dir.glob("deploy-plan-*.json"))
    assert len(plans) == 6
    records = [json.loads(path.read_text()) for path in plans]
    assert {plan["chain_id"] for plan in records} == {1, 10, 137, 8453, 42161, 43114}
    assert all(plan["broadcast"] is False for plan in records)
    assert all(plan["merchant_fee_bps"] == 500 for plan in records)
    assert all(plan["owner"] == addresses[0] for plan in records)


def test_estimate_plans_reports_each_chain_without_broadcast(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from typer.testing import CliRunner
    from flasharb import cli

    chains = [
        SimpleNamespace(
            chain_id=chain_id,
            name=f"chain-{chain_id}",
            native_symbol="ETH",
            fee_model="op" if chain_id in (10, 8453) else "evm",
            registry_digest=f"digest-{chain_id}",
        )
        for chain_id in (1, 10, 137, 8453, 42161, 43114)
    ]
    monkeypatch.setattr(cli, "load_config", lambda _: SimpleNamespace(chains=chains))

    class FakeRpc:
        async def check_chain(self):
            return None

        async def close(self):
            return None

    monkeypatch.setattr(cli, "from_config", lambda *_: FakeRpc())

    async def fake_estimate(*_args):
        return SimpleNamespace(max_native_cost=10**15, components={"execution_max": 10**15})

    monkeypatch.setattr(cli, "estimate_fees", fake_estimate)
    for chain in chains:
        (tmp_path / f"deploy-plan-{chain.chain_id}.json").write_text(
            json.dumps(
                {
                    "chain_id": chain.chain_id,
                    "registry_digest": chain.registry_digest,
                    "broadcast": False,
                    "transaction": {"from": "0x" + "11" * 20, "data": "0x00"},
                }
            )
        )

    result = CliRunner().invoke(cli.app, ["estimate-plans", "--plans-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["broadcast"] is False
    assert len(report["results"]) == 6
    op_results = [row for row in report["results"] if row["chain_id"] in (10, 8453)]
    assert all(not row["funded_deployment_supported_by_fee_model"] for row in op_results)
    assert all(row["includes_configuration"] is False for row in report["results"])


def test_doctor_reports_sanitized_rpc_error(monkeypatch):
    from types import SimpleNamespace
    from typer.testing import CliRunner
    from flasharb import cli
    from flasharb.market.rpc import RpcError

    monkeypatch.setattr(
        cli, "load_config", lambda _: SimpleNamespace(chains=[SimpleNamespace(chain_id=42161)])
    )

    def fail_rpc(*args):
        raise RpcError("eth_chainId unavailable after 3 attempts")

    monkeypatch.setattr(cli, "from_config", fail_rpc)
    result = CliRunner().invoke(cli.app, ["doctor", "--chain", "42161"])
    assert result.exit_code == 0
    assert '"reason": "eth_chainId unavailable after 3 attempts"' in result.output
    assert "https://" not in result.output
