from ..models import Quote


class QuoteService:
    def __init__(self, config, rpc):
        self.config = config
        self.rpc = rpc

    async def quote_route(self, route, amount, block):
        current = amount
        outputs = []
        for hop in route.hops:
            venue = next(v for v in self.config.venues if v.router.lower() == hop.router.lower())
            if venue.kind:
                if not venue.quoter:
                    raise ValueError("missing verified quoter")
                result = await self.rpc.contract_call(
                    venue.quoter,
                    "quoteExactInputSingle((address,address,uint256,uint24,uint160))",
                    ["(address,address,uint256,uint24,uint160)"],
                    [(hop.token_in, hop.token_out, current, hop.fee, 0)],
                    ["uint256", "uint160", "uint32", "uint256"],
                    block,
                )
                current = result[0]
            else:
                result = await self.rpc.contract_call(
                    venue.router,
                    "getAmountsOut(uint256,address[])",
                    ["uint256", "address[]"],
                    [current, [hop.token_in, hop.token_out]],
                    ["uint256[]"],
                    block,
                )
                current = result[0][-1]
            if current <= 0:
                raise ValueError("zero quote")
            outputs.append(current)
        return Quote(
            route=route,
            block_number=block,
            amount_in=amount,
            amount_out=current,
            hop_outputs=outputs,
        )
