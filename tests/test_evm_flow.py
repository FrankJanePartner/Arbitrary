"""Signed local EVM execution through simulation, durable journal, ledger and web export.
Liquidity and prices are synthetic. This is not a real-chain profitability test.
"""

import json
import re
from pathlib import Path
from decimal import Decimal
import pytest
from web3 import Web3, EthereumTesterProvider
from eth_account import Account
from fastapi.testclient import TestClient
from flasharb.models import Intent, Route, Hop
from flasharb.config import load_config
from flasharb.execution.abi import artifact, transaction
from flasharb.execution.simulation import simulate
from flasharb.execution.signer import Signer
from flasharb.execution.transactions import TransactionManager
from flasharb.storage.db import Store
from flasharb.storage.reconcile import reconcile_chain
from flasharb.web.app import create_app
from flasharb.web.auth import password_hash


def normalize(value):
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return hex(value)
    if isinstance(value, dict) or hasattr(value, "items"):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(x) for x in value]
    return value


@pytest.mark.asyncio
async def test_signed_evm_execution_reconciliation_and_authenticated_export(tmp_path):
    w3 = Web3(EthereumTesterProvider())
    owner = w3.eth.accounts[0]
    recipient = w3.eth.accounts[1]

    def deploy(name, *args):
        if name == "FlashArbitrageExecutor":
            a = artifact()
            bytecode = a["bytecode"]
        else:
            a = json.loads(Path(f"contracts/out/Executor.t.sol/{name}.json").read_text())
            bytecode = a["bytecode"]["object"]
        c = w3.eth.contract(abi=a["abi"], bytecode=bytecode)
        receipt = w3.eth.wait_for_transaction_receipt(
            c.constructor(*args).transact({"from": owner})
        )
        return w3.eth.contract(address=receipt.contractAddress, abi=a["abi"])

    a = deploy("Token")
    b = deploy("Token")
    pool = deploy("PoolMock")
    r1 = deploy("RouterMock", 0)
    r2 = deploy("RouterMock", 100)
    executor = deploy(
        "FlashArbitrageExecutor", pool.address, owner, owner, recipient, w3.eth.accounts[2], 1000
    )
    for fn in [
        executor.functions.setToken(a.address, True, True),
        executor.functions.setToken(b.address, True, False),
        executor.functions.setRouter(r1.address, 0, True),
        executor.functions.setRouter(r2.address, 0, True),
        a.functions.mint(pool.address, 10**9),
        b.functions.mint(r1.address, 10**9),
        a.functions.mint(r2.address, 10**9),
        a.functions.mint(executor.address, 77),
    ]:
        fn.transact({"from": owner})

    class RPC:
        async def call(self, method, params):
            if method == "eth_chainId":
                return hex(w3.eth.chain_id)
            if method == "eth_call":
                tx = dict(params[0])
                tx["value"] = int(tx.get("value", "0x0"), 16)
                return normalize(w3.eth.call(tx, int(params[1], 16)))
            if method == "eth_getTransactionCount":
                return hex(w3.eth.get_transaction_count(params[0], params[1]))
            if method == "eth_sendRawTransaction":
                return normalize(w3.eth.send_raw_transaction(params[0]))
            if method == "eth_getTransactionReceipt":
                return normalize(w3.eth.get_transaction_receipt(params[0]))
            if method == "eth_getBlockByNumber":
                return normalize(w3.eth.get_block(int(params[0], 16)))
            raise AssertionError(method)

    route = Route(
        chain_id=w3.eth.chain_id,
        hops=[
            Hop(
                kind=0,
                router=r1.address,
                pool=r1.address,
                token_in=a.address,
                token_out=b.address,
                min_out=1,
            ),
            Hop(
                kind=0,
                router=r2.address,
                pool=r2.address,
                token_in=b.address,
                token_out=a.address,
                min_out=1,
            ),
        ],
    )
    intent = Intent(
        id="01" * 32,
        chain_id=w3.eth.chain_id,
        operator=owner,
        nonce=w3.eth.get_transaction_count(owner),
        executor=executor.address,
        asset=a.address,
        amount=1000,
        route=route,
        min_profit_token=50,
        deadline=w3.eth.get_block("latest").timestamp + 30,
        block_number=w3.eth.block_number,
    )
    rpc = RPC()
    assert (await simulate(intent, rpc)).ok
    losing = intent.model_copy(update={"min_profit_token": 1000})
    assert not (await simulate(losing, rpc)).ok
    s = Store(tmp_path / "db")
    signer = Signer(Account.from_key(w3.provider.ethereum_tester.backend.account_keys[0]))
    tx = transaction(intent)
    tx.pop("from")
    tx.update(
        value=0,
        chainId=w3.eth.chain_id,
        nonce=intent.nonce,
        gas=1000000,
        maxFeePerGas=10**10,
        maxPriorityFeePerGas=10**9,
        type=2,
    )
    meta = {
        "executor": executor.address,
        "asset": a.address,
        "recipient": recipient,
        "merchant": w3.eth.accounts[2],
        "merchant_fee_bps": 1000,
        "amount": 1000,
        "native_usd": "1",
        "loan_usd": "1",
        "loan_decimals": 0,
    }
    manager = TransactionManager(s, rpc, signer, w3.eth.chain_id)
    result = await manager.submit_transaction(
        intent.id, tx, Decimal(".01"), Decimal("1"), Decimal("1"), "2026-10-10", meta
    )
    assert result.status == "submitted"
    cfg = load_config(Path("config/app.yaml"))
    cfg.data_dir = str(tmp_path)
    chain = cfg.chains[0].model_copy(update={"chain_id": w3.eth.chain_id, "confirmations": 1})
    await reconcile_chain(s, chain, rpc, w3.eth.block_number)
    await reconcile_chain(s, chain, rpc, w3.eth.block_number)
    assert s.execution(intent.id)["status"] == "confirmed" and s.reserved() == 0
    assert a.functions.balanceOf(recipient).call() == 81
    assert a.functions.balanceOf(w3.eth.accounts[2]).call() == 9
    assert a.functions.balanceOf(executor.address).call() == 77
    app = create_app(cfg, s, password_hash("long-test-password"), launch_worker=False)
    with TestClient(app) as client:
        page = client.get("/login")
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)[1]
        assert (
            client.post("/login", data={"csrf": csrf, "password": "long-test-password"}).status_code
            == 200
        )
        exported = client.get("/export/json")
        assert exported.status_code == 200
        assert "confirmed" in exported.text and "raw_tx" not in exported.text
    s.close()
