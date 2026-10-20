"""Opt-in read-only forks. No real transactions; all impersonation is inside Forge."""

import asyncio
import argparse
import json
import os
import time
from pathlib import Path
from flasharb.config import load_config
from flasharb.market.rpc import RpcClient

FORGE_COMMAND = ("node", "node_modules/@foundry-rs/forge/bin.mjs")


async def run(chain):
    result = {
        "chain_id": chain.chain_id,
        "registry_digest": chain.registry_digest,
        "checked_at": int(time.time()),
        "scope": "Real Aave + Uniswap V2/V3 Solidity adapter integration, not complete Python worker certification",
        "synthetic_setup": "Impersonated aToken funds test; new test token and deliberately skewed pools",
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
            venue_v2 = next(v for v in chain.venues if v.kind == 0)
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
                *FORGE_COMMAND,
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
                v3_status = "V3_PASS" if proc.returncode == 0 and "2 passed" in log else "BLOCKED"
                result.update(
                    block=block,
                    exit_code=proc.returncode,
                    v3_status=v3_status,
                    status="BLOCKED",
                    log=log[-10000:],
                )
                v2_env = env | {
                    "FORK_V2_FACTORY": venue_v2.factory,
                    "FORK_V2_ROUTER": venue_v2.router,
                }
                v2_proc = await asyncio.create_subprocess_exec(
                    *FORGE_COMMAND,
                    "test",
                    "--root",
                    "contracts",
                    "--match-contract",
                    "ProtocolV2ForkTest",
                    "-vvvv",
                    env=v2_env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                try:
                    v2_output, _ = await asyncio.wait_for(v2_proc.communicate(), 180)
                    v2_log = v2_output.decode(errors="replace").replace(url, "<RPC_ENDPOINT>")
                    result["v2_exit_code"] = v2_proc.returncode
                    result["v2_status"] = (
                        "V2_PASS" if v2_proc.returncode == 0 and "2 passed" in v2_log else "BLOCKED"
                    )
                    result["v2_log"] = v2_log[-10000:]
                    if v3_status == "V3_PASS" and result["v2_status"] == "V2_PASS":
                        result["status"] = "PROTOCOLS_AND_V2_PASS"
                except TimeoutError:
                    v2_proc.kill()
                    await v2_proc.communicate()
                    result["v2_status"] = "BLOCKED"
                    result["v2_reason"] = "V2 fork test exceeded 180 seconds"
                    result["status"] = "BLOCKED"
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
                if k not in ("log", "v2_log", "synthetic_setup", "scope", "registry_digest")
            }
        ),
        flush=True,
    )


def select_chains(chains, chain_id=None):
    if chain_id is None:
        return list(chains)
    selected = [chain for chain in chains if chain.chain_id == chain_id]
    if not selected:
        raise ValueError(f"Chain {chain_id} is not configured")
    return selected


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run read-only Solidity protocol forks for configured networks."
    )
    parser.add_argument(
        "--chain",
        type=int,
        choices=(1, 42161, 8453, 10, 137, 43114),
        help="Run only this network (recommended when RPC quotas are limited).",
    )
    return parser.parse_args()


async def main(chain_id=None):
    # Sequential runs avoid compiler/cache races and shared public endpoint bursts.
    chains = select_chains(load_config(Path("config/app.yaml")).chains, chain_id)
    for chain in chains:
        await run(chain)


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args.chain))
