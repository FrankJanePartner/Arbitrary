"""Resumable, plan-keyed owner transactions. Invoke only under the worker lock."""

import hashlib
import json
from .execution.fees import estimate_fees


async def apply_transactions(plan, transactions, chain, rpc, signer, store, cap):
    if chain.fee_model == "op":
        raise ValueError("OP-stack deployment awaits fee ceiling certification")
    await rpc.check_chain()
    identity = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    prefix = f"deploy:{chain.chain_id}:{identity}:"
    results = []
    remaining = cap
    for index, tx in enumerate(transactions):
        key = prefix + str(index)
        record = store.get_state(key)
        if record is None:
            # Another interrupted plan with this signer must be resolved first.
            for state in store.rows("SELECT key,value FROM state WHERE key LIKE 'deploy:%'"):
                prior = json.loads(state["value"])
                if (
                    prior["chain_id"] == chain.chain_id
                    and prior["operator"] == signer.address
                    and prior["status"] != "confirmed"
                ):
                    raise ValueError("Another owner plan is unresolved; resume it first")
            fee = await estimate_fees(tx, chain, rpc)
            if fee.max_native_cost > remaining:
                raise ValueError("deployment fee cap exceeded")
            pending = int(
                await rpc.call("eth_getTransactionCount", [signer.address, "pending"]), 16
            )
            latest = int(await rpc.call("eth_getTransactionCount", [signer.address, "latest"]), 16)
            if pending != latest:
                raise ValueError("unresolved owner nonce")
            payload = dict(tx)
            payload.pop("from")
            payload.update(
                value=0,
                chainId=chain.chain_id,
                nonce=latest,
                type=2,
                gas=fee.gas_limit,
                maxFeePerGas=fee.max_fee_per_gas,
                maxPriorityFeePerGas=fee.priority_fee,
            )
            signed = signer.sign_transaction(payload)
            record = {
                "chain_id": chain.chain_id,
                "operator": signer.address,
                "nonce": latest,
                "hash": "0x" + signed.hash.hex(),
                "raw_tx": "0x" + signed.raw_transaction.hex(),
                "max_cost": fee.max_native_cost,
                "status": "signed",
            }
            store.set_state(key, record)  # SQLite commit before any broadcast
        remaining -= record["max_cost"]
        if remaining < 0:
            raise ValueError("resumed plan exceeds supplied cap")
        receipt = await rpc.call("eth_getTransactionReceipt", [record["hash"]])
        if receipt is None:
            latest = int(await rpc.call("eth_getTransactionCount", [signer.address, "latest"]), 16)
            if latest > record["nonce"]:
                raise ValueError("owner nonce consumed but journal receipt missing")
            returned = await rpc.call("eth_sendRawTransaction", [record["raw_tx"]])
            if returned.lower() != record["hash"].lower():
                raise ValueError("submission hash mismatch; journal retained")
            record["status"] = "submitted"
            store.set_state(key, record)
            receipt = await rpc.call("eth_getTransactionReceipt", [record["hash"]])
        if receipt is None:
            results.append(
                {
                    "hash": record["hash"],
                    "status": "pending",
                    "resume": "Run the same apply-plan command later",
                }
            )
            return results
        canonical = await rpc.call("eth_getBlockByNumber", [receipt["blockNumber"], False])
        head = int(await rpc.call("eth_blockNumber", []), 16)
        if (
            not canonical
            or canonical["hash"].lower() != receipt["blockHash"].lower()
            or head - int(receipt["blockNumber"], 16) + 1 < chain.confirmations
        ):
            results.append({"hash": record["hash"], "status": "provisional"})
            return results
        if int(receipt["status"], 16) != 1:
            raise ValueError("owner transaction reverted; plan requires investigation")
        record.update(status="confirmed", receipt=receipt)
        store.set_state(key, record)
        results.append(
            {
                "hash": record["hash"],
                "status": "confirmed",
                "contract": receipt.get("contractAddress"),
            }
        )
    return results
