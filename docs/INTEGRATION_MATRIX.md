# Integration evidence — 20 October 2026

Registry provenance and per-file digests are in `config/registry.lock.json`. Each configured chain now includes Uniswap V3 SwapRouter02/QuoterV2 and the official Uniswap V2 Router02/factory deployment. V2 addresses are sourced from [Uniswap's V2 deployment table](https://developers.uniswap.org/docs/protocols/v2/deployments); V3 remains checked against the [chain-specific deployment references](https://developers.uniswap.org/docs/protocols/v3/deployments). The addresses still require current on-chain `doctor` verification before use. This is two Uniswap protocol versions, not coverage of every DEX on each network.

The real-protocol Solidity fork tests below use the merchant-aware executor (5% test merchant share), real Aave loan/reserve and real Uniswap factory/router. Synthetic setup creates a new test token, transfers reserve tokens through local impersonation and seeds deliberately skewed pools. Each run checks profitable execution/repayment/payout and atomic rejection of an unprofitable execution. No mainnet transaction is sent.

| Network | ID | Pinned block | Protocol-only result | Evidence |
|---|---:|---:|---|---|
| Ethereum | 1 | 26199128 | PROTOCOLS_PASS | [report](evidence/fork-1.json) |
| Arbitrum | 42161 | 515115266 | PROTOCOLS_PASS | [report](evidence/fork-42161.json) |
| Base | 8453 | 52646319 | PROTOCOLS_PASS | [report](evidence/fork-8453.json) |
| OP Mainnet | 10 | 158241628 | PROTOCOLS_PASS | [report](evidence/fork-10.json) |
| Polygon | 137 | 95584510 | PROTOCOLS_PASS | [report](evidence/fork-137.json) |
| Avalanche | 43114 | 97632897 | PROTOCOLS_PASS | [report](evidence/fork-43114.json) |

These passes are not full Python-worker certification and do not authorize live trading. Python signed-EVM tests use mocked protocol contracts; combining these separate test results is not equivalent to testing the entire worker on each fork. Native fee certification is also separate; Base/OP funded operations remain blocked.

The protocol fork evidence above predates adding Uniswap V2 to the six registries and therefore does not certify the new V2 pools or routes. Re-run the read-only probes and add a controlled V2 execution/atomic-loss-revert test before treating V2 as verified on a network. A missing pair is a normal no-liquidity result; it does not indicate that the router is broken.

Read-only probes from 10 October are retained with dates and blocks. They verified registered code, flash-loan terms, pool discovery, quote interfaces and direct Chainlink feeds. Probe price freshness used 86,400 seconds to establish interface compatibility, **not** the default live policy (300 seconds). Strict runtime freshness may reject a valid but older Chainlink round. Review heartbeat/freshness policy before deployment; no USDC dollar peg is assumed.

To repeat: provide the six RPC environment variables locally and run `uv run python scripts/check-networks.py` and `uv run python scripts/run-forks.py`. Missing RPC inputs are BLOCKED, never success. The fork runner uses a modern fork EVM (Prague) for current protocol bytecode; deployable executor artifacts target Paris for compatibility.
