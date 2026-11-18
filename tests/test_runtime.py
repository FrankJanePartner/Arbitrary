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
    from flasharb.market.rpc import RpcClient, RpcQuotaExceeded

    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"result": "0x1"}))
    db = tmp_path / "db"
    s = Store(db)
    r = RpcClient("https://example.test", 1, daily_calls=1, transport=transport, store=s)
    assert await r.call("eth_chainId", []) == "0x1"
    assert r.usage_snapshot()["used"] == 1
    assert r.usage_snapshot()["remaining"] == 0
    await r.close()
    s.close()
    s = Store(db)
    r = RpcClient("https://example.test", 1, daily_calls=1, transport=transport, store=s)
    with pytest.raises(RpcQuotaExceeded, match="daily"):
        await r.call("eth_chainId", [])
    await r.close()
    s.close()


@pytest.mark.asyncio
async def test_rpc_429_retry_after_is_counted_and_chain_check_is_cached(monkeypatch):
    from flasharb.market import rpc as rpc_module
    from flasharb.market.rpc import RpcClient

    methods = []
    responses = [
        httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {"code": 429}}),
        httpx.Response(200, json={"result": "0x1"}),
    ]

    def handler(request):
        methods.append(request.content)
        return responses.pop(0)

    monkeypatch.setattr(rpc_module, "_retry_delay", lambda *args, **kwargs: 0)
    transport = httpx.MockTransport(handler)
    client = RpcClient("https://example.test", 1, transport=transport)
    await client.check_chain()
    await client.check_chain()
    assert len(methods) == 2  # one 429 attempt plus success; second check uses cache
    usage = client.usage_snapshot()
    assert usage["provider_rate_limits"] == 1
    assert usage["retries"] == 1
    assert usage["successful"] == 1
    await client.close()


def test_activity_reporter_persists_structured_events_and_summary(tmp_path):
    import json
    from flasharb.observability import ActivityReporter

    path = tmp_path / "logs" / "worker.jsonl"
    reporter = ActivityReporter(path)
    reporter.emit("opportunity_rejected", network="Polygon PoS", chain_id=137, reasons=["insufficient_profit"])
    reporter.emit("scan_complete", network="Polygon PoS", chain_id=137, block=10, routes_considered=2, rpc_attempts=4)
    reporter.session_summary()
    reporter.close()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[0]["event"] == "opportunity_rejected"
    assert rows[-1]["rejection_reasons"] == {"insufficient_profit": 1}
    assert path.stat().st_mode & 0o777 == 0o600


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
