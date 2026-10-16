"""Local integration harness must reject real chains before any mutation."""

import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

HARNESS = Path(__file__).resolve().parents[1] / "scripts/test-worker-fork.py"


@pytest.mark.parametrize("chain,client", [(42161, "anvil"), (1, "anvil"), (31337, "geth")])
def test_worker_fork_rejects_nonlocal_chain(chain, client):
    harness = runpy.run_path(str(HARNESS))
    endpoint = SimpleNamespace(eth=SimpleNamespace(chain_id=chain), client_version=client)
    with pytest.raises(ValueError, match="requires Anvil"):
        harness["require_local"](endpoint)


def test_worker_fork_accepts_local_anvil():
    harness = runpy.run_path(str(HARNESS))
    harness["require_local"](
        SimpleNamespace(eth=SimpleNamespace(chain_id=31337), client_version="anvil/v1.7")
    )


@pytest.mark.asyncio
async def test_worker_fork_restores_snapshot_on_failure(tmp_path, monkeypatch):
    harness = runpy.run_path(str(HARNESS))
    main = harness["main"]
    scope = main.__globals__
    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(scope, "require_local", lambda w3: None)
    monkeypatch.setitem(scope, "compile_fixture", lambda: {})

    def rpc(w3, method, args):
        calls.append(method)
        return "0x1" if method == "evm_snapshot" else True

    async def fail(*args):
        raise RuntimeError("fixture failed")

    monkeypatch.setitem(scope, "rpc_method", rpc)
    monkeypatch.setitem(scope, "exercise", fail)
    with pytest.raises(RuntimeError, match="fixture failed"):
        await main(8547)
    assert calls == ["evm_snapshot", "evm_revert"]
    import json

    report = json.loads((tmp_path / "data/local-worker-report.json").read_text())
    assert report == {
        "status": "BLOCKED",
        "production_authorized": False,
        "snapshot_restored": True,
    }
