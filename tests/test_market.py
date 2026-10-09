import pytest
from decimal import Decimal
from flasharb.models import Hop, Route, Quote, FeeEstimate, PricePoint, Policy


def route():
    a = "0x" + "11" * 20
    b = "0x" + "22" * 20
    r = "0x" + "33" * 20
    return Route(
        chain_id=1,
        hops=[
            Hop(kind=2, router=r, pool="0x" + "44" * 20, token_in=a, token_out=b, fee=500),
            Hop(kind=2, router=r, pool="0x" + "55" * 20, token_in=b, token_out=a, fee=3000),
        ],
    )


def test_fees_not_double_counted():
    from flasharb.strategy.economics import evaluate_profit

    q = Quote(
        route=route(), block_number=10, amount_in=1000, amount_out=1100, hop_outputs=[1000, 1100]
    )
    fees = FeeEstimate(
        gas_limit=1,
        max_fee_per_gas=20,
        priority_fee=0,
        max_native_cost=20,
        expected_native_cost=20,
        components={},
    )
    price = PricePoint(native_usd=Decimal(10) ** 18, loan_usd=1, updated_at=100, loan_decimals=0)
    p = Policy(min_profit_usd=0, safety_buffer_usd=5, max_tx_usd=100)
    decision = evaluate_profit(q, 10, fees, price, p, now=101)
    assert decision.expected_net_usd == 65
    assert decision.min_profit_token == 25
    assert decision.eligible


def test_stale_conversion_blocks_trade():
    from flasharb.strategy.economics import evaluate_profit

    q = Quote(
        route=route(), block_number=10, amount_in=1000, amount_out=1100, hop_outputs=[1000, 1100]
    )
    fees = FeeEstimate(
        gas_limit=1,
        max_fee_per_gas=1,
        priority_fee=0,
        max_native_cost=1,
        expected_native_cost=1,
        components={},
    )
    d = evaluate_profit(
        q,
        1,
        fees,
        PricePoint(native_usd=1, loan_usd=1, updated_at=1, loan_decimals=6),
        Policy(),
        now=1000,
    )
    assert not d.eligible and "stale_price" in d.reasons


@pytest.mark.asyncio
async def test_size_within_liquidity_limit():
    from flasharb.strategy.sizing import optimize_size

    seen = []

    async def quote(r, n, b):
        seen.append(n)
        return Quote(
            route=r, block_number=b, amount_in=n, amount_out=n + 10, hop_outputs=[n, n + 10]
        )

    await optimize_size(route(), Policy(min_loan=100, max_loan=10000), 100, quote, liquidity=500)
    assert all(100 <= n <= 500 for n in seen)


@pytest.mark.asyncio
async def test_quotes_share_block():
    from flasharb.market.quotes import QuoteService

    class RPC:
        blocks = []

        async def contract_call(self, to, sig, types, args, out, block):
            self.blocks.append(block)
            return (1200, 0, 0, 0)

    from flasharb.config import load_config
    from pathlib import Path

    cfg = load_config(Path("config/app.yaml")).chains[0]
    r = route()
    for h in r.hops:
        h.router = cfg.venues[0].router
    rpc = RPC()
    result = await QuoteService(cfg, rpc).quote_route(r, 1000, 123)
    assert rpc.blocks == [123, 123] and result.amount_out == 1200


@pytest.mark.asyncio
async def test_stale_head_rejected():
    from flasharb.market.rpc import validate_head

    with pytest.raises(ValueError, match="stale"):
        validate_head({"timestamp": "0x1"}, 60, now=1000)


def test_only_two_or_three_hop_closed_cycles():
    from flasharb.strategy.cycles import find_cycles
    from flasharb.models import Pool, Venue

    r = route()
    v = Venue(
        name="v", kind=2, factory="0x" + "66" * 20, router=r.hops[0].router, quoter="0x" + "77" * 20
    )
    pools = [
        Pool(
            address=h.pool,
            token0=r.hops[0].token_in,
            token1=r.hops[0].token_out,
            venue=v,
            fee=h.fee,
        )
        for h in r.hops
    ]
    cycles = find_cycles(pools)
    assert len(cycles) == 4
    assert all(len(c.hops) == 2 and len({h.pool for h in c.hops}) == 2 for c in cycles)
