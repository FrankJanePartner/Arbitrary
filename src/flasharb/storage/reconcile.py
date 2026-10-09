import json
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from eth_abi import decode
from web3 import Web3
from ..execution.fees import actual_cost

EVENT = (
    "0x"
    + Web3.keccak(text="Executed(bytes32,address,address,uint256,uint256,uint256,bytes32)").hex()
)


def decode_profit(receipt, id, metadata):
    logs = [
        log
        for log in receipt.get("logs", [])
        if log["address"].lower() == metadata["executor"].lower()
        and log.get("topics")
        and log["topics"][0].lower() == EVENT.lower()
    ]
    if len(logs) != 1:
        raise ValueError("expected exactly one execution event")
    log = logs[0]
    if log["topics"][1].removeprefix("0x").lower() != id.removeprefix("0x").lower():
        raise ValueError("intent event mismatch")
    if log["topics"][2][-40:].lower() != metadata["asset"][-40:].lower():
        raise ValueError("asset event mismatch")
    if log["topics"][3][-40:].lower() != metadata["recipient"][-40:].lower():
        raise ValueError("recipient event mismatch")
    amount, premium, profit, _ = decode(
        ["uint256", "uint256", "uint256", "bytes32"], bytes.fromhex(log["data"][2:])
    )
    if amount != metadata["amount"]:
        raise ValueError("amount event mismatch")
    return profit


async def reconcile_chain(store, chain, rpc, head_number, timezone="Africa/Lagos"):
    # Retain a recent finalized audit window to detect deeper-than-confirmation reorganizations.
    rows = store.rows(
        "SELECT * FROM executions WHERE chain_id=? ORDER BY created DESC LIMIT 500",
        (chain.chain_id,),
    )
    for row in rows:
        old = json.loads(row["receipt"]) if row["receipt"] else None
        if old:
            canonical = await rpc.call("eth_getBlockByNumber", [old["blockNumber"], False])
            if not canonical or canonical["hash"].lower() != old["blockHash"].lower():
                with store.atomic():
                    store.reopen(row["id"])
                    store.db.execute(
                        "UPDATE executions SET receipt=NULL,status='unknown' WHERE id=?",
                        (row["id"],),
                    )
                continue
        found = None
        winning = None
        for tx in store.rows("SELECT * FROM tx_hashes WHERE intent_id=?", (row["id"],)):
            receipt = await rpc.call("eth_getTransactionReceipt", [tx["hash"]])
            if receipt:
                found = receipt
                winning = tx
                break
        if not found:
            continue
        canonical = await rpc.call("eth_getBlockByNumber", [found["blockNumber"], False])
        if not canonical or canonical["hash"].lower() != found["blockHash"].lower():
            continue
        metadata = json.loads(row["metadata"])
        success = int(found["status"], 16) == 1
        cancelled = winning["kind"] == "cancel"
        profit = decode_profit(found, row["id"], metadata) if success and not cancelled else 0
        cost = await actual_cost(found, chain, rpc)
        native_usd = Decimal(metadata["native_usd"])
        loan_usd = Decimal(metadata["loan_usd"])
        decimals = int(metadata["loan_decimals"])
        gas_usd = Decimal(cost) * native_usd / 10**18
        profit_usd = Decimal(profit) * loan_usd / 10**decimals
        finalized = head_number - int(found["blockNumber"], 16) + 1 >= chain.confirmations
        status = (
            ("cancelled" if cancelled else ("confirmed" if success else "failed"))
            if finalized
            else "provisional"
        )
        day = (
            datetime.fromtimestamp(int(canonical["timestamp"], 16), ZoneInfo(timezone))
            .date()
            .isoformat()
        )
        found.update(
            {
                "accounting": {
                    "profit_token": str(profit),
                    "gas_native": str(cost),
                    "gas_usd": str(gas_usd),
                    "profit_usd": str(profit_usd),
                    "net_usd": str(profit_usd - gas_usd),
                    "valuation_basis": "submission price snapshot",
                    "valuation_timestamp": metadata.get("price_timestamp"),
                    "finalized": finalized,
                }
            }
        )
        with store.atomic():
            store.db.execute(
                "UPDATE executions SET receipt=?,status=? WHERE id=?",
                (json.dumps(found), status, row["id"]),
            )
            if finalized:
                store.settle(row["id"], gas_usd, day)
