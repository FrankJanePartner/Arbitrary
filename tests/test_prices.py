from pathlib import Path
import pytest
from flasharb.config import load_config
from flasharb.market.prices import prices


@pytest.mark.asyncio
@pytest.mark.parametrize("answer,started", [(1, 1), (0, 0), (0, 9900)])
async def test_sequencer_outage_or_grace_blocks_prices(answer, started):
    chain = next(c for c in load_config(Path("config/app.yaml")).chains if c.chain_id == 42161)

    class RPC:
        async def contract_call(self, to, sig, *args):
            if to == chain.sequencer_feed:
                return (1, answer, started, started, 1)
            if sig == "decimals()":
                return (8,)
            return (1, 100000000, 9900, 9900, 1)

    with pytest.raises(ValueError, match="sequencer"):
        await prices(chain, RPC(), chain.tokens[0], 1, 10000, 300)
