from ..models import FeeEstimate

OP_ORACLE = "0x420000000000000000000000000000000000000F"


async def estimate_fees(tx, chain, rpc, block="latest"):
    gas = int(
        await rpc.call("eth_estimateGas", [tx, hex(block) if isinstance(block, int) else block]), 16
    )
    gas = (gas * 125 + 99) // 100
    price = int(await rpc.call("eth_gasPrice", []), 16)
    tip = int(await rpc.call("eth_maxPriorityFeePerGas", []), 16)
    max_fee = max(1, price * 2 + tip)
    components = {"execution_max": gas * max_fee}
    # Arbitrum eth_estimateGas already includes the L1 posting charge in gas units.
    if chain.fee_model == "op":
        # Oracle size upper bound includes unsigned envelope overhead and signature bytes.
        length = len(bytes.fromhex(tx.get("data", "0x")[2:])) + 256
        l1 = (
            await rpc.contract_call(
                OP_ORACLE, "getL1FeeUpperBound(uint256)", ["uint256"], [length], ["uint256"], block
            )
        )[0]
        operator = (
            await rpc.contract_call(
                OP_ORACLE, "getOperatorFee(uint256)", ["uint256"], [gas], ["uint256"], block
            )
        )[0]
        components["l1_estimate_buffered"] = l1 * 2
        components["operator_estimate_buffered"] = operator * 2
    return FeeEstimate(
        gas_limit=gas,
        max_fee_per_gas=max_fee,
        priority_fee=min(tip, max_fee),
        max_native_cost=sum(components.values()),
        expected_native_cost=gas * price
        + sum(v for k, v in components.items() if k != "execution_max"),
        components=components,
    )


async def actual_cost(receipt, chain, rpc):
    gas = int(receipt["gasUsed"], 16)
    total = gas * int(receipt["effectiveGasPrice"], 16)
    if chain.fee_model == "op":
        if "l1Fee" not in receipt:
            raise ValueError("missing L1 receipt cost")
        total += int(receipt["l1Fee"], 16)
        # Historical oracle call accounts for the chain's active operator fee formula.
        fee = (
            await rpc.contract_call(
                OP_ORACLE,
                "getOperatorFee(uint256)",
                ["uint256"],
                [gas],
                ["uint256"],
                int(receipt["blockNumber"], 16),
            )
        )[0]
        total += fee
    return total
