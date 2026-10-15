from types import SimpleNamespace
import pytest
from eth_account import Account
from flasharb.execution.signer import Signer
from flasharb.storage.db import Store


@pytest.mark.asyncio
async def test_deployment_restart_reuses_signed_nonce_and_completed_receipt(tmp_path, monkeypatch):
    from flasharb.deployment_runner import apply_transactions

    signer = Signer(Account.create())
    s = Store(tmp_path / "db")
    raws = []

    class RPC:
        receipt = None

        async def check_chain(self):
            pass

        async def call(self, m, p):
            if m == "eth_getTransactionCount":
                return "0x0"
            if m == "eth_sendRawTransaction":
                from web3 import Web3

                raws.append(p[0])
                return "0x" + Web3.keccak(hexstr=p[0]).hex()
            if m == "eth_getTransactionReceipt":
                return self.receipt
            if m == "eth_getBlockByNumber":
                return {"hash": "0xblock"}
            if m == "eth_blockNumber":
                return "0x10"
            raise AssertionError(m)

    async def fee(*a):
        return SimpleNamespace(
            max_native_cost=42000, gas_limit=21000, max_fee_per_gas=2, priority_fee=1
        )

    monkeypatch.setattr("flasharb.deployment_runner.estimate_fees", fee)
    rpc = RPC()
    chain = SimpleNamespace(chain_id=1, fee_model="evm", confirmations=1)
    txs = [{"from": signer.address, "to": "0x" + "11" * 20, "value": "0x0", "data": "0x"}]
    first = await apply_transactions({"name": "plan"}, txs, chain, rpc, signer, s, 100000)
    assert first[-1]["status"] == "pending"
    await apply_transactions({"name": "plan"}, txs, chain, rpc, signer, s, 100000)
    assert len(raws) == 2 and raws[0] == raws[1]
    rpc.receipt = {
        "status": "0x1",
        "blockHash": "0xblock",
        "blockNumber": "0x1",
        "contractAddress": None,
    }
    final = await apply_transactions({"name": "plan"}, txs, chain, rpc, signer, s, 100000)
    assert final[-1]["status"] == "confirmed" and len(raws) == 2
