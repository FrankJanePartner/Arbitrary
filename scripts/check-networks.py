"""Read-only integration probes; never certify execution from successful probes."""

import asyncio
import json
import os
import time
from pathlib import Path
from flasharb.config import load_config, verify_chain
from flasharb.market.rpc import RpcClient
from flasharb.market.prices import loan_terms, prices
from flasharb.market.pools import discover_pools
from flasharb.market.quotes import QuoteService
from flasharb.strategy.cycles import find_cycles


async def check(chain):
    result = {
        "chain_id": chain.chain_id,
        "registry_digest": chain.registry_digest,
        "checks": {},
        "execution_certified": False,
        "checked_at": int(time.time()),
    }
    url = os.environ.get(chain.rpc_env)
    if not url:
        return result | {"status": "BLOCKED", "reason": f"Missing {chain.rpc_env}"}
    rpc = RpcClient(url, chain.chain_id, rps=5)
    try:
        verification = await verify_chain(chain, rpc)
        result["registry"] = verification.model_dump()
        block = verification.block_number
        result["block"] = block
        if not verification.ok:
            return result | {"status": "BLOCKED", "reason": "registry verification failed"}
        loan = next(t for t in chain.tokens if t.loan)
        for name, action in {
            "loan_terms": lambda: loan_terms(chain, rpc, loan.address, block),
            "prices": lambda: prices(chain, rpc, loan, block, int(time.time()), 86400),
            "pools": lambda: discover_pools(chain, rpc, block),
        }.items():
            try:
                value = await action()
                if name == "pools":
                    result["checks"][name] = {"status": "PASS", "count": len(value)}
                    routes = find_cycles(value, chain_id=chain.chain_id)
                    route = next(
                        (r for r in routes if r.hops[0].token_in.lower() == loan.address.lower()),
                        None,
                    )
                    if route:
                        quote = await QuoteService(chain, rpc).quote_route(
                            route, 100 * 10**loan.decimals, block
                        )
                        result["checks"]["quote"] = {
                            "status": "PASS",
                            "value": quote.model_dump(mode="json"),
                        }
                    else:
                        result["checks"]["quote"] = {
                            "status": "BLOCKED",
                            "reason": "no closed route",
                        }
                else:
                    result["checks"][name] = {
                        "status": "PASS",
                        "value": value.model_dump(mode="json")
                        if hasattr(value, "model_dump")
                        else value,
                    }
            except Exception as error:
                result["checks"][name] = {
                    "status": "BLOCKED",
                    "reason": str(error) if isinstance(error, ValueError) else type(error).__name__,
                }
        result["status"] = (
            "PROBES_PASS"
            if all(x["status"] == "PASS" for x in result["checks"].values())
            else "BLOCKED"
        )
    except Exception as error:
        result.update(status="BLOCKED", reason=type(error).__name__)
    finally:
        await rpc.close()
    return result


async def main():
    config = load_config(Path("config/app.yaml"))

    async def run(chain):
        result = await check(chain)
        Path("docs/evidence").mkdir(parents=True, exist_ok=True)
        Path(f"docs/evidence/probes-{chain.chain_id}.json").write_text(
            json.dumps(result, indent=2, default=str)
        )
        print(
            json.dumps(
                {
                    "chain_id": chain.chain_id,
                    "status": result["status"],
                    "checks": result.get("checks", {}),
                },
                default=str,
            ),
            flush=True,
        )

    await asyncio.gather(*(run(c) for c in config.chains))


if __name__ == "__main__":
    asyncio.run(main())
