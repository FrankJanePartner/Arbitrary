from pathlib import Path
import pytest
from flasharb.config import load_config
from flasharb.models import Policy
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


def test_observe_mode_has_bounded_quote_budget():
    from flasharb.worker import scan_quote_budget

    policy = Policy(max_route_quotes=24, size_samples=8)
    assert scan_quote_budget(policy, "observe") == (2, 2)
    assert scan_quote_budget(policy, "simulate") == (24, 8)


def test_live_trial_enforces_operator_approved_gas_caps():
    from decimal import Decimal
    from flasharb.worker import validate_live_policy

    validate_live_policy(Policy())
    with pytest.raises(ValueError, match="transaction gas budget"):
        validate_live_policy(Policy(max_tx_usd=Decimal("0.11")))
    with pytest.raises(ValueError, match="daily gas budget"):
        validate_live_policy(Policy(daily_usd=Decimal("1.01")))
    with pytest.raises(ValueError, match="daily gas budget"):
        validate_live_policy(Policy(global_daily_usd=Decimal("1.01")))


@pytest.mark.asyncio
async def test_pool_discovery_is_cached_and_refreshes_on_registry_change(tmp_path, monkeypatch):
    from flasharb.worker import Worker

    app = load_config(Path("config/app.yaml"))
    store = Store(tmp_path / "db")
    worker = Worker(app, store)
    chain = app.chains[0]
    calls = []

    async def discover(c, rpc, block):
        calls.append(block)
        return [block]

    monkeypatch.setattr("flasharb.worker.discover_pools", discover)
    assert await worker.load_pools(chain, object(), 100) == [100]
    assert await worker.load_pools(chain, object(), 101) == [100]
    chain.registry_digest = "changed-registry"
    assert await worker.load_pools(chain, object(), 102) == [102]
    assert calls == [100, 102]


@pytest.mark.asyncio
async def test_restart_requires_live_action(tmp_path):
    from flasharb.worker import Worker

    app = load_config(Path("config/app.yaml"))
    s = Store(tmp_path / "db")
    s.set_state("mode", "live")
    w = Worker(app, s)
    await w.run(once=True)
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


@pytest.mark.asyncio
async def test_disabled_network_with_pending_transaction_is_reconciled(tmp_path, monkeypatch):
    from flasharb.worker import Worker

    app = load_config(Path("config/app.yaml"))
    s = Store(tmp_path / "db")
    with s.atomic():
        s.db.execute("INSERT INTO executions(id,chain_id,status) VALUES('pending',1,'unknown')")

    class RPC:
        async def close(self):
            pass

    monkeypatch.setattr("flasharb.worker.from_config", lambda *a: RPC())
    seen = []
    w = Worker(app, s)

    async def reconcile(c, r):
        seen.append(c.chain_id)

    w.reconcile = reconcile
    await w.run(once=True)
    assert seen == [1]


def test_mid_scan_pause_blocks_submission(tmp_path):
    from flasharb.worker import Worker

    app = load_config(Path("config/app.yaml"))
    s = Store(tmp_path / "db")
    w = Worker(app, s)
    chain = app.chains[0]
    s.set_state("enabled:1", True)
    s.set_state("mode", "live")
    policy = app.policy
    assert w.submission_allowed(chain, policy)
    s.set_state("paused", True)
    assert not w.submission_allowed(chain, policy)
    s.set_state("paused", False)
    s.set_state("mode", "observe")
    assert not w.submission_allowed(chain, policy)
