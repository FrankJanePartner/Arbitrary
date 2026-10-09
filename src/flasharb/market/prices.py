from decimal import Decimal
from ..models import PricePoint


async def read_price(rpc, token, block, now, max_age):
    if not token.oracle:
        raise ValueError("missing verified price feed")
    rd = await rpc.contract_call(
        token.oracle,
        "latestRoundData()",
        [],
        [],
        ["uint80", "int256", "uint256", "uint256", "uint80"],
        block,
    )
    decimals = (await rpc.contract_call(token.oracle, "decimals()", [], [], ["uint8"], block))[0]
    if rd[1] <= 0 or rd[3] == 0 or rd[3] > now or now - rd[3] > max_age or rd[4] < rd[0]:
        raise ValueError("stale or invalid oracle round")
    if decimals > 36:
        raise ValueError("invalid price decimals")
    return Decimal(rd[1]) / 10**decimals, rd[3]


async def prices(config, rpc, loan, block, now, max_age):
    native = next(t for t in config.tokens if t.address.lower() == config.native_token.lower())
    np, nt = await read_price(rpc, native, block, now, max_age)
    lp, lt = await read_price(rpc, loan, block, now, max_age)
    return PricePoint(
        native_usd=np, loan_usd=lp, updated_at=min(nt, lt), loan_decimals=loan.decimals
    )


async def loan_terms(config, rpc, asset, block):
    premium = (
        await rpc.contract_call(
            config.pool, "FLASHLOAN_PREMIUM_TOTAL()", [], [], ["uint128"], block
        )
    )[0]
    configuration = (
        await rpc.contract_call(
            config.pool, "getConfiguration(address)", ["address"], [asset], ["uint256"], block
        )
    )[0]
    if not (configuration >> 56) & 1 or (configuration >> 60) & 1 or not (configuration >> 63) & 1:
        raise ValueError("reserve inactive, paused or flash loans disabled")
    # Aave V3 reserve tuple: aToken is the ninth ABI word, including packed configuration.
    result = await rpc.contract_call(
        config.pool,
        "getReserveData(address)",
        ["address"],
        [asset],
        [
            "(uint256,uint128,uint128,uint128,uint128,uint128,uint40,uint16,address,address,address,address,uint128,uint128,uint128)"
        ],
        block,
    )
    atoken = result[0][8]
    liquidity = (
        await rpc.contract_call(
            asset, "balanceOf(address)", ["address"], [atoken], ["uint256"], block
        )
    )[0]
    return premium, liquidity
