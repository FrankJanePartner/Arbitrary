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
    for name in ["doctor", "serve", "run", "deploy-plan", "estimate-cost", "backup"]:
        assert name in r.output


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
