import subprocess
import sys
import httpx
import pytest
from flasharb.storage.db import Store


def test_second_process_cannot_acquire_worker_lock(tmp_path):
    from flasharb.runtime import WorkerLock

    path = tmp_path / "worker.lock"
    with WorkerLock(path):
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                "from flasharb.runtime import WorkerLock; import sys; WorkerLock(sys.argv[1]).acquire()",
                str(path),
            ],
            capture_output=True,
        )
        assert child.returncode != 0
    with WorkerLock(path):
        pass


@pytest.mark.asyncio
async def test_rpc_quota_survives_client_and_database_restart(tmp_path):
    from flasharb.market.rpc import RpcClient, RpcError

    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"result": "0x1"}))
    db = tmp_path / "db"
    s = Store(db)
    r = RpcClient("https://example.test", 1, daily_calls=1, transport=transport, store=s)
    assert await r.call("eth_chainId", []) == "0x1"
    await r.close()
    s.close()
    s = Store(db)
    r = RpcClient("https://example.test", 1, daily_calls=1, transport=transport, store=s)
    with pytest.raises(RpcError, match="daily"):
        await r.call("eth_chainId", [])
    await r.close()
    s.close()


def test_backup_restores_pending_reservation_and_pause(tmp_path):
    from decimal import Decimal

    s = Store(tmp_path / "db")
    s.reserve("pending", 1, Decimal("0.1"), Decimal("1"), Decimal("1"), "2026-10-10")
    s.set_state("paused", True)
    s.backup(tmp_path / "backup")
    restored = Store(tmp_path / "backup")
    assert restored.reserved() == Decimal("0.1")
    assert restored.get_state("paused") is True
    restored.close()
    s.close()
