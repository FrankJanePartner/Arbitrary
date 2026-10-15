import pytest
from eth_account import Account
from decimal import Decimal


def test_keystore_requires_unlock(tmp_path):
    from flasharb.execution.signer import Signer

    a = Account.create()
    p = tmp_path / "key.json"
    p.write_text(
        __import__("json").dumps(
            Account.encrypt(a.key, "test password", kdf="pbkdf2", iterations=1000)
        )
    )
    with pytest.raises(ValueError):
        Signer.unlock(p, "wrong")
    s = Signer.unlock(p, "test password")
    assert s.address == a.address
    assert a.key.hex() not in repr(s)


@pytest.mark.asyncio
async def test_ambiguous_timeout_reuses_hash(tmp_path):
    from flasharb.execution.transactions import TransactionManager
    from flasharb.execution.signer import Signer
    from flasharb.storage.db import Store

    class RPC:
        raws = []

        async def call(self, m, p):
            if m == "eth_sendRawTransaction":
                self.raws.append(p[0])
                raise RuntimeError("timeout")
            if m == "eth_getTransactionReceipt":
                return None
            if m == "eth_getTransactionCount":
                return "0x0"
            if m == "eth_chainId":
                return "0x1"

    rpc = RPC()
    s = Store(tmp_path / "db")
    signer = Signer(Account.create())
    tm = TransactionManager(s, rpc, signer, 1)
    tx = {
        "chainId": 1,
        "nonce": 0,
        "to": "0x" + "11" * 20,
        "value": 0,
        "data": "0x",
        "gas": 21000,
        "maxFeePerGas": 2,
        "maxPriorityFeePerGas": 1,
        "type": 2,
    }
    result = await tm.submit_transaction(
        "a", tx, Decimal(".1"), Decimal("1"), Decimal("1"), "2026-10-09", {}
    )
    assert result.status == "unknown"
    row = s.execution("a")
    assert row["tx_hash"] == result.tx_hash and row["raw_tx"] == rpc.raws[0]
    await tm.rebroadcast("a")
    assert rpc.raws[0] == rpc.raws[1]
    with pytest.raises(ValueError, match="unresolved"):
        await tm.submit_transaction(
            "b", tx, Decimal(".1"), Decimal("1"), Decimal("1"), "2026-10-09", {}
        )


@pytest.mark.asyncio
async def test_pre_sign_guard_is_checked_after_network_wait(tmp_path):
    from flasharb.execution.transactions import TransactionManager
    from flasharb.storage.db import Store

    class RPC:
        async def call(self, *args):
            return "0x1"

    class Signer:
        def sign_transaction(self, *args):
            raise AssertionError("must not sign")

    store = Store(tmp_path / "db")
    tm = TransactionManager(store, RPC(), Signer(), 1)
    with pytest.raises(ValueError, match="stopped or stale"):
        await tm.submit_transaction(
            "x",
            {"chainId": 1},
            Decimal(".1"),
            Decimal(1),
            Decimal(1),
            "2026-10-10",
            {},
            can_submit=lambda: False,
        )
    assert store.reserved() == 0


@pytest.mark.asyncio
async def test_recovery_rebroadcasts_only_unexpired_same_payload(tmp_path):
    import json
    import time
    from flasharb.execution.transactions import TransactionManager
    from flasharb.storage.db import Store

    class RPC:
        sends = []

        async def call(self, method, params):
            if method == "eth_sendRawTransaction":
                self.sends.append(params[0])
                return "0xabc"

    s = Store(tmp_path / "db")
    rpc = RPC()
    tm = TransactionManager(s, rpc, None, 1)
    meta = {"intent": {"deadline": int(time.time()) - 1}}
    with s.atomic():
        s.db.execute(
            "INSERT INTO executions(id,chain_id,raw_tx,tx_hash,status,metadata) VALUES('x',1,'0x123','0xabc','signed',?)",
            (json.dumps(meta),),
        )
    with pytest.raises(ValueError, match="expired"):
        await tm.recover("x")
    assert not rpc.sends
    meta["intent"]["deadline"] = int(time.time()) + 60
    s.db.execute("UPDATE executions SET metadata=?", (json.dumps(meta),))
    result = await tm.recover("x")
    assert result.status == "submitted" and rpc.sends == ["0x123"]


@pytest.mark.asyncio
async def test_external_pending_nonce_blocks_new_intent(tmp_path):
    from flasharb.execution.transactions import TransactionManager
    from flasharb.execution.signer import Signer
    from flasharb.storage.db import Store

    class RPC:
        async def call(self, method, params):
            if method == "eth_chainId":
                return "0x1"
            return "0x1" if params[1] == "pending" else "0x0"

    store = Store(tmp_path / "db")
    tm = TransactionManager(store, RPC(), Signer(Account.create()), 1)
    with pytest.raises(ValueError, match="nonce"):
        await tm.submit_transaction(
            "new",
            {"chainId": 1, "nonce": 1},
            Decimal(".1"),
            Decimal(1),
            Decimal(1),
            "2026-10-10",
            {},
        )
    assert store.reserved() == 0
