"""Opt-in Python worker integration on a local Arbitrum fork, never mainnet.

Uses real Aave/Uniswap contracts, synthetic liquidity, a random ephemeral signer,
local EVM fee accounting and test-only policy. Restores the Anvil snapshot on exit.
The resulting LOCAL_WORKER_PASS report is NOT a production authorization file.
"""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from eth_account import Account
from web3 import Web3
from web3.logs import DISCARD

from flasharb.config import load_config, verify_chain
from flasharb.deployment import verify_deployment
from flasharb.execution.abi import artifact, transaction
from flasharb.execution.signer import Signer
from flasharb.execution.simulation import simulate
from flasharb.market.quotes import QuoteService
from flasharb.market.rpc import RpcClient
from flasharb.models import Hop, Intent, Policy, Route, Token
from flasharb.storage.db import Store
from flasharb.storage.ledger import export_report
from flasharb.worker import Worker


def require_local(w3):
    if w3.eth.chain_id != 31337 or "anvil" not in w3.client_version.lower():
        raise ValueError("Refusing endpoint: requires Anvil chain 31337")


def rpc_method(w3, method, args):
    result = w3.provider.make_request(method, args)
    if "error" in result:
        raise RuntimeError(f"Local RPC method failed: {method}")
    return result["result"]


def compile_fixture():
    result = subprocess.run(
        ["node", "node_modules/@foundry-rs/forge/bin.mjs", "build", "--root", "contracts"],
        env=os.environ | {"FOUNDRY_PROFILE": "fork"},
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = result.stdout + result.stderr
    if result.returncode or "Error" in output:
        raise RuntimeError("Fixture build failed: " + output[-3000:])
    path = Path("contracts/out/WorkerFixture.sol/WorkerFixture.json")
    if not path.exists():
        raise RuntimeError("Fixture artifact missing")
    return json.loads(path.read_text())


async def exercise(w3, rpc, directory, fixture_artifact):
    config = load_config(Path("config/app.yaml"))
    source = next(c for c in config.chains if c.chain_id == 42161)
    loan = next(t for t in source.tokens if t.loan)
    venue = next(v for v in source.venues if v.kind == 2)
    owner, customer, merchant = w3.eth.accounts[:3]
    # Not an Anvil mnemonic or a real user's signing key. Never persisted or printed.
    signer = Signer(Account.create())
    rpc_method(w3, "anvil_setBalance", [signer.address, hex(100 * 10**18)])

    def send(fn, sender=owner):
        require_local(w3)
        tx_hash = fn.transact({"from": sender})
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status != 1:
            raise RuntimeError("Local fixture transaction reverted")
        return receipt

    def deploy(a, args, forge=False):
        bytecode = a["bytecode"]["object"] if forge else a["bytecode"]
        factory = w3.eth.contract(abi=a["abi"], bytecode=bytecode)
        receipt = send(factory.constructor(*args))
        return w3.eth.contract(address=receipt.contractAddress, abi=a["abi"])

    print("Creating synthetic pools on the local fork...", flush=True)
    fixture = deploy(fixture_artifact, [loan.address], forge=True)
    intermediate = fixture.functions.intermediate().call()
    reserve = await rpc.contract_call(
        source.pool,
        "getReserveData(address)",
        ["address"],
        [loan.address],
        [
            "(uint256,uint128,uint128,uint128,uint128,uint128,uint40,uint16,address,address,address,address,uint128,uint128,uint128)"
        ],
    )
    atoken = Web3.to_checksum_address(reserve[0][8])
    token_art = json.loads(Path("contracts/out/Executor.t.sol/Token.json").read_text())
    usdc = w3.eth.contract(address=loan.address, abi=token_art["abi"])
    executor = deploy(artifact(), [source.pool, owner, signer.address, customer, merchant, 500])
    rpc_method(w3, "anvil_setBalance", [atoken, hex(10**18)])
    rpc_method(w3, "anvil_impersonateAccount", [atoken])
    try:
        send(usdc.functions.transfer(fixture.address, 10**10), atoken)
        send(usdc.functions.transfer(executor.address, 77), atoken)
    finally:
        rpc_method(w3, "anvil_stopImpersonatingAccount", [atoken])
    send(fixture.functions.seed(Web3.to_checksum_address(venue.factory)))
    # Synthetic token first so deterministic discovery finds the synthetic cycle first.
    tokens = [loan, Token(address=intermediate, symbol="TEST", decimals=18)] + [
        t for t in source.tokens if t.address != loan.address
    ]
    for token in tokens:
        send(executor.functions.setToken(token.address, True, token.loan))
    send(executor.functions.setRouter(Web3.to_checksum_address(venue.router), 2, True))
    digest = hashlib.sha256(
        ("LOCAL-ONLY:" + source.registry_digest + executor.address + intermediate).encode()
    ).hexdigest()
    chain = source.model_copy(
        update={
            "chain_id": 31337,
            "name": "Local Arbitrum fixture",
            "enabled": True,
            "executor": executor.address,
            "executor_codehash": None,
            "owner": owner,
            "operator": signer.address,
            "recipient": customer,
            "merchant": merchant,
            "merchant_fee_bps": 500,
            "tokens": tokens,
            "venues": [venue.model_copy(update={"fee_tiers": [500, 3000]})],
            "confirmations": 1,
            "fee_model": "evm",
            "submission": "public",
            "registry_digest": digest,
        }
    )
    config.chains = [chain]
    config.data_dir = str(directory)
    config.policy = Policy(
        min_loan=10**6,
        max_loan=10**6,
        size_samples=2,
        min_profit_usd=Decimal("0.01"),
        safety_buffer_usd=Decimal("0.01"),
        max_tx_usd=Decimal("100"),
        daily_usd=Decimal("100"),
        global_daily_usd=Decimal("100"),
        low_balance_usd=Decimal("0"),
        price_max_age=86400,
        deadline_seconds=120,
    )
    # Mine at current time so a fork left open for hours does not fail head freshness.
    rpc_method(
        w3,
        "evm_setNextBlockTimestamp",
        [max(int(time.time()), w3.eth.get_block("latest").timestamp + 1)],
    )
    rpc_method(w3, "evm_mine", [])
    verification = await verify_chain(chain, rpc)
    assert verification.ok, verification.blockers
    await verify_deployment(chain, rpc)
    route = Route(
        chain_id=31337,
        hops=[
            Hop(
                kind=2,
                router=venue.router,
                pool=fixture.functions.first().call(),
                token_in=loan.address,
                token_out=intermediate,
                fee=500,
                min_out=1,
            ),
            Hop(
                kind=2,
                router=venue.router,
                pool=fixture.functions.second().call(),
                token_in=intermediate,
                token_out=loan.address,
                fee=3000,
                min_out=1,
            ),
        ],
    )
    block = w3.eth.block_number
    quote = await QuoteService(chain, rpc).quote_route(route, 10**6, block)
    preflight = Intent(
        id="01" * 32,
        chain_id=31337,
        operator=signer.address,
        nonce=0,
        executor=executor.address,
        asset=loan.address,
        amount=10**6,
        route=route,
        min_profit_token=1,
        deadline=min(int(time.time()) + 120, int(w3.eth.get_block(block).timestamp) + 120),
        block_number=block,
    )
    preflight_result = await simulate(preflight, rpc)
    if not preflight_result.ok:
        # The RPC client intentionally hides provider text because it can echo a
        # credential URL. This test is hard-limited to loopback Anvil, so a direct
        # diagnostic can safely report the local EVM's revert reason.
        raw = w3.provider.make_request(
            "eth_call", [transaction(preflight), hex(preflight.block_number)]
        )
        detail = raw.get("error", {}).get("message", "local EVM returned no revert detail")
        raise AssertionError(f"Real-protocol profitable preflight failed: {detail[:240]}")
    assert not (await simulate(preflight.model_copy(update={"min_profit_token": 10**12}), rpc)).ok
    assert quote.amount_out > quote.amount_in
    # Local gate evidence follows actual successful real-protocol simulation. Its
    # chain ID and synthetic digest cannot authorize a production registry/chain.
    evidence = directory / "fork-31337.json"
    evidence.write_text(
        json.dumps(
            {
                "status": "PASS",
                "registry_digest": digest,
                "chain_id": 31337,
                "scope": "LOCAL synthetic protocol preflight only",
                "production_authorized": False,
            }
        )
    )
    store = Store(directory / "worker.db")
    worker = Worker(config, store, signer=signer, mode="live")
    before = {
        a: usdc.functions.balanceOf(a).call()
        for a in [atoken, customer, merchant, executor.address]
    }
    gas_before = w3.eth.get_balance(signer.address)
    store.set_state("mode", "live")
    store.set_state("enabled:31337", True)
    print("Running Python worker discovery, quotes, simulation and signing...", flush=True)
    try:
        await worker.tick(chain, rpc)
        rows = store.rows("SELECT * FROM executions")
        assert len(rows) == 1, "Expected one submission; observations: " + str(
            store.rows("SELECT payload FROM observations")
        )
        row = rows[0]
        await worker.reconcile(chain, rpc)
        row = store.execution(row["id"])
        assert row["status"] == "confirmed", row["status"]
        receipt = json.loads(row["receipt"])
        accounting = receipt["accounting"]
        customer_delta = usdc.functions.balanceOf(customer).call() - before[customer]
        merchant_delta = usdc.functions.balanceOf(merchant).call() - before[merchant]
        assert customer_delta > 0 and merchant_delta > 0
        assert merchant_delta == (customer_delta + merchant_delta) * 500 // 10000
        assert int(accounting["profit_token"]) == customer_delta
        assert int(accounting["merchant_fee_token"]) == merchant_delta
        assert gas_before - w3.eth.get_balance(signer.address) == int(accounting["gas_native"])
        assert usdc.functions.balanceOf(executor.address).call() == before[executor.address]
        events = executor.events.Executed().process_receipt(
            w3.eth.get_transaction_receipt(row["tx_hash"]),
            errors=DISCARD,
        )
        assert len(events) == 1
        premium = events[0]["args"]["premium"]
        assert usdc.functions.balanceOf(atoken).call() - before[atoken] == premium
        assert usdc.functions.allowance(executor.address, source.pool).call() == 0
        assert usdc.functions.allowance(executor.address, venue.router).call() == 0
        test_token = w3.eth.contract(address=intermediate, abi=token_art["abi"])
        assert test_token.functions.allowance(executor.address, venue.router).call() == 0
        assert store.reserved() == 0
        # Restart reconciliation with a fresh Store; no duplicate settlement or payout.
        store.close()
        store = Store(directory / "worker.db")
        worker = Worker(config, store, signer=signer, mode="live")
        store.set_state("receipt-audit:31337", {"time": 0, "cursor": ""})
        await worker.reconcile(chain, rpc)
        assert store.execution(row["id"])["status"] == "confirmed" and store.reserved() == 0
        assert usdc.functions.balanceOf(customer).call() - before[customer] == customer_delta
        # Replay must fail with no token changes.
        replay = json.loads(row["metadata"])["intent"]
        assert executor.functions.usedIntents(bytes.fromhex(row["id"].removeprefix("0x"))).call()
        replay["block_number"] = w3.eth.block_number
        replay["deadline"] = w3.eth.get_block("latest").timestamp + 60
        assert not (await simulate(Intent(**replay), rpc)).ok
        export_path = directory / "export.json"
        export_report(store, export_path)
        exported = json.loads(export_path.read_text())
        assert exported["summary"]["finalized"] == 1
        return {
            "status": "LOCAL_WORKER_PASS",
            "production_authorized": False,
            "source_chain_id": 42161,
            "local_chain_id": 31337,
            "source_registry_digest": source.registry_digest,
            "customer_usdc": str(Decimal(customer_delta) / 10**loan.decimals),
            "merchant_usdc": str(Decimal(merchant_delta) / 10**loan.decimals),
            "premium_usdc": str(Decimal(premium) / 10**loan.decimals),
            "merchant_fee_bps": 500,
            "accounting": accounting,
            "checks": [
                "worker discovery and sizing",
                "real protocol simulation",
                "local signed submission",
                "repayment",
                "exact merchant split",
                "treasury preservation",
                "cleared allowances",
                "receipt accounting",
                "restart reconciliation",
                "replay rejection",
            ],
            "limitations": [
                "synthetic prices and liquidity",
                "local EVM fees, not Nitro L1 posting fees",
                "test oracle max-age 86400 seconds",
                "single confirmation on Anvil",
                "not evidence of available profit or production approval",
            ],
        }
    finally:
        store.close()


async def main(port):
    if not __debug__:
        raise RuntimeError("Run without Python optimization; test assertions are required")
    if port not in (8547, 18547):
        raise ValueError("Only designated local test ports are allowed")
    url = f"http://127.0.0.1:{port}"
    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 120}))
    require_local(w3)
    report_path = Path("data/local-worker-report.json")
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(json.dumps({"status": "BLOCKED", "production_authorized": False}))
    fixture = compile_fixture()
    snapshot = rpc_method(w3, "evm_snapshot", [])
    rpc = RpcClient(url, 31337, rps=15, daily_calls=5000)
    report = {"status": "BLOCKED", "production_authorized": False}
    try:
        with tempfile.TemporaryDirectory(prefix="arbitrary-local-worker-") as tmp:
            report = await exercise(w3, rpc, Path(tmp), fixture)
    finally:
        await rpc.close()
        restored = rpc_method(w3, "evm_revert", [snapshot])
        if not restored:
            raise RuntimeError("Local snapshot restore failed; restart Anvil before further tests")
        report["snapshot_restored"] = True
        Path("data").mkdir(exist_ok=True)
        Path("data/local-worker-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, choices=[8547, 18547], default=8547)
    args = parser.parse_args()
    asyncio.run(main(args.port))
