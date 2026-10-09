from pathlib import Path
import pytest
from flasharb.config import load_config
from flasharb.storage.db import Store


@pytest.mark.asyncio
async def test_pause_keeps_reconciliation(tmp_path):
    from flasharb.worker import Worker

    app = load_config(Path("config/app.yaml"))
    app.data_dir = str(tmp_path)
    store = Store(tmp_path / "db")
    w = Worker(app, store)
    store.set_state("paused", True)
    seen = []

    async def reconcile(c, r):
        seen.append("reconcile")

    async def scan(c, r, m):
        seen.append("scan")

    w.reconcile = reconcile
    w.scan = scan
    await w.tick(app.chains[0], object())
    assert seen == ["reconcile"]


def test_restart_requires_live_action(tmp_path):
    from flasharb.worker import Worker

    app = load_config(Path("config/app.yaml"))
    s = Store(tmp_path / "db")
    s.set_state("mode", "live")
    w = Worker(app, s)
    assert w.mode == "observe" and s.get_state("mode") == "observe"


@pytest.mark.asyncio
async def test_one_chain_failure_isolated(tmp_path):
    from flasharb.worker import Worker

    app = load_config(Path("config/app.yaml"))
    s = Store(tmp_path / "db")
    w = Worker(app, s)

    async def broken(c, r):
        raise ValueError("bad node")

    w.reconcile = broken
    await w.safe_tick(app.chains[0], object())
    assert s.get_state("health:1")["status"] == "error"


def test_restart_preserves_emergency_pause(tmp_path):
    from flasharb.worker import Worker

    app = load_config(Path("config/app.yaml"))
    s = Store(tmp_path / "db")
    s.set_state("paused", True)
    Worker(app, s)
    assert s.get_state("paused") is True
