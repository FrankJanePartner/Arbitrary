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
