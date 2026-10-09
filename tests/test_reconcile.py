import json
from decimal import Decimal as D
import pytest
from flasharb.storage.db import Store


@pytest.mark.asyncio
async def test_reorg_rolls_back_provisional_profit(tmp_path):
    from flasharb.storage.reconcile import reconcile_chain
    from flasharb.config import load_config

    s = Store(tmp_path / "db")
    c = load_config(__import__("pathlib").Path("config/app.yaml")).chains[0]
    s.reserve("x", 1, D(".7"), D("1"), D("1"), "2026-10-09")
    s.db.execute(
        "INSERT INTO executions(id,chain_id,operator,nonce,tx_hash,status,payload,metadata,receipt) VALUES('x',1,'0x1',0,'0xabc','provisional','{}','{}',?)",
        (json.dumps({"blockNumber": "0x1", "blockHash": "0xold"}),),
    )

    class RPC:
        async def call(self, m, p):
            return {"hash": "0xnew"} if m == "eth_getBlockByNumber" else None

    await reconcile_chain(s, c, RPC(), head_number=10)
    assert s.execution("x")["status"] == "unknown"
    assert s.reserved() == D(".7")


def test_export_never_leaks_signed_transaction(tmp_path):
    from flasharb.storage.ledger import export_report

    s = Store(tmp_path / "db")
    s.db.execute(
        "INSERT INTO executions(id,chain_id,raw_tx,status,metadata) VALUES('x',1,'privatebytes','unknown','{}')"
    )
    p = export_report(s, tmp_path / "report.json", "json")
    assert "privatebytes" not in p.read_text()


def test_receipt_event_recipient_matches_config():
    from flasharb.storage.reconcile import decode_profit
    from eth_abi import encode
    from web3 import Web3

    asset = "0x" + "11" * 20
    recipient = "0x" + "22" * 20
    executor = "0x" + "33" * 20
    id = "01" * 32
    log = {
        "address": executor,
        "topics": [
            "0x"
            + Web3.keccak(
                text="Executed(bytes32,address,address,uint256,uint256,uint256,bytes32)"
            ).hex(),
            "0x" + id,
            "0x" + "0" * 24 + asset[2:],
            "0x" + "0" * 24 + recipient[2:],
        ],
        "data": "0x"
        + encode(["uint256", "uint256", "uint256", "bytes32"], [1000, 10, 90, b"\0" * 32]).hex(),
    }
    meta = {"executor": executor, "asset": asset, "recipient": recipient, "amount": 1000}
    assert decode_profit({"logs": [log]}, id, meta) == 90
    meta["recipient"] = "0x" + "44" * 20
    with pytest.raises(ValueError, match="recipient"):
        decode_profit({"logs": [log]}, id, meta)
