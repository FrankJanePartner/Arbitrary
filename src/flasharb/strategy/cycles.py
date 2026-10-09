from ..models import Hop, Route


def find_cycles(pools, max_hops=3, chain_id=1):
    edges = {}
    for p in pools:
        for a, b in [(p.token0, p.token1), (p.token1, p.token0)]:
            edges.setdefault(a.lower(), []).append(
                Hop(
                    kind=p.venue.kind,
                    router=p.venue.router,
                    pool=p.address,
                    token_in=a,
                    token_out=b,
                    fee=p.fee,
                )
            )
    result = []

    def visit(start, current, path):
        if len(path) >= max_hops:
            return
        for hop in edges.get(current, []):
            if any(h.pool.lower() == hop.pool.lower() for h in path):
                continue
            nxt = path + [hop]
            if hop.token_out.lower() == start:
                if len(nxt) >= 2:
                    result.append(Route(chain_id=chain_id, hops=nxt))
            elif hop.token_out.lower() not in {h.token_in.lower() for h in path}:
                visit(start, hop.token_out.lower(), nxt)

    for start in edges:
        visit(start, start, [])
    return result
