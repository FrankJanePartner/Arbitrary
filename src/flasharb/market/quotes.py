from ..models import Quote


class QuoteService:
    def __init__(self, config, rpc):
        self.config = config
        self.rpc = rpc
        self.quotes = 0

    async def quote_route(self, route, amount, block, detailed=True):
        self.quotes += 1
        if not detailed:
            return await self._quote_route_batched(route, amount, block)
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

    async def _quote_route_batched(self, route, amount, block):
        """Quote contiguous same-venue hops together for route-size search."""
        current = amount
        index = 0
        while index < len(route.hops):
            first = route.hops[index]
            venue = next(v for v in self.config.venues if v.router.lower() == first.router.lower())
            end = index + 1
            while (
                end < len(route.hops)
                and route.hops[end].router.lower() == first.router.lower()
                and route.hops[end].kind == first.kind
            ):
                end += 1
            segment = route.hops[index:end]
            if first.kind == 0:
                result = await self.rpc.contract_call(
                    venue.router,
                    "getAmountsOut(uint256,address[])",
                    ["uint256", "address[]"],
                    [current, [segment[0].token_in, *[hop.token_out for hop in segment]]],
                    ["uint256[]"],
                    block,
                )
                current = result[0][-1]
            else:
                if not venue.quoter:
                    raise ValueError("missing verified quoter")
                path = bytearray.fromhex(segment[0].token_in.removeprefix("0x"))
                for hop in segment:
                    path.extend(hop.fee.to_bytes(3, "big"))
                    path.extend(bytes.fromhex(hop.token_out.removeprefix("0x")))
                result = await self.rpc.contract_call(
                    venue.quoter,
                    "quoteExactInput(bytes,uint256)",
                    ["bytes", "uint256"],
                    [bytes(path), current],
                    ["uint256", "uint160[]", "uint32[]", "uint256"],
                    block,
                )
                current = result[0]
            if current <= 0:
                raise ValueError("zero quote")
            index = end
        return Quote(
            route=route,
            block_number=block,
            amount_in=amount,
            amount_out=current,
            hop_outputs=[],
        )
