"""Opt-in read-only forks. No real transactions; all impersonation is inside Forge."""

import asyncio
import json
import os
import time
from pathlib import Path
from flasharb.config import load_config
from flasharb.market.rpc import RpcClient


async def run(chain):
    result = {
        "chain_id": chain.chain_id,
        "registry_digest": chain.registry_digest,
        "checked_at": int(time.time()),
        "scope": "Real Aave + Uniswap V3 Solidity integration, not complete Python worker certification",
        "synthetic_setup": "Impersonated aToken transfers 10,000 USDC to test; new test token and two deliberately skewed real-factory pools",
        "status": "BLOCKED",
    }
    url = os.environ.get(chain.rpc_env)
    if not url:
        result["reason"] = f"Missing {chain.rpc_env}"
    else:
        rpc = RpcClient(url, chain.chain_id)
        try:
            await rpc.check_chain()
            block = int(await rpc.call("eth_blockNumber", []), 16)
            loan = next(t for t in chain.tokens if t.loan)
            reserve = await rpc.contract_call(
                chain.pool,
                "getReserveData(address)",
                ["address"],
                [loan.address],
                [
                    "(uint256,uint128,uint128,uint128,uint128,uint128,uint40,uint16,address,address,address,address,uint128,uint128,uint128)"
                ],
                block,
            )
            venue = next(v for v in chain.venues if v.kind == 2)
            env = os.environ.copy()
            env.update(
                FOUNDRY_PROFILE="fork",
                FORK_RPC=url,
                FORK_BLOCK=str(block),
                FORK_LOAN=loan.address,
                FORK_POOL=chain.pool,
                FORK_ATOKEN=reserve[0][8],
                FORK_FACTORY=venue.factory,
                FORK_ROUTER=venue.router,
            )
            proc = await asyncio.create_subprocess_exec(
                "node_modules/.bin/forge",
                "test",
                "--root",
                "contracts",
                "--match-contract",
                "ProtocolForkTest",
                "-vvvv",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                output, _ = await asyncio.wait_for(proc.communicate(), 180)
                log = output.decode(errors="replace").replace(url, "<RPC_ENDPOINT>")
                result.update(
                    block=block,
                    exit_code=proc.returncode,
                    status="PROTOCOLS_PASS"
                    if proc.returncode == 0 and "2 passed" in log
                    else "BLOCKED",
                    log=log[-10000:],
                )
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                result["reason"] = "Fork test exceeded 180 seconds"
        except Exception as e:
            result["reason"] = type(e).__name__
        finally:
            await rpc.close()
    Path("docs/evidence").mkdir(parents=True, exist_ok=True)
    Path(f"docs/evidence/fork-{chain.chain_id}.json").write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in ("log", "synthetic_setup", "scope", "registry_digest")
            }
        ),
        flush=True,
    )


async def main():
    # Sequential runs avoid compiler/cache races and shared public endpoint bursts.
    for chain in load_config(Path("config/app.yaml")).chains:
        await run(chain)


if __name__ == "__main__":
    asyncio.run(main())
