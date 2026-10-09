# Integration evidence

Six networks are configured from the pinned official Aave address book and Uniswap deployment documentation. Revisions and per-file SHA-256 digests are in `config/registry.lock.json`; addresses, tokens, feeds, routers, quoters and factories are in `config/chains/`.

Baseline venue is Uniswap V3 SwapRouter02 + QuoterV2. Distinct fee-tier pools form two/three-hop cycles; their existence and liquidity must be discovered on-chain. The V2 and original V3 adapters are implemented for explicitly verified additional venue configurations, but no unverified second exchange is enabled by default.

| Network | Chain ID | Registry source | RPC/code/ABI evidence | Fork execution |
|---|---:|---|---|---|
| Ethereum | 1 | pinned | pending doctor | not run |
| Arbitrum One | 42161 | pinned | pending doctor | not run |
| Base | 8453 | pinned | pending doctor | not run |
| OP Mainnet | 10 | pinned | pending doctor | not run |
| Polygon PoS | 137 | pinned | pending doctor | not run |
| Avalanche C-Chain | 43114 | pinned | pending doctor | not run |

Registry presence is not live support certification. `flasharb doctor` performs RPC checks; fork evidence must pass before marking a chain ready. Oracle adapter compatibility and freshness are checked at runtime; an adapter lacking timestamped round data blocks live valuation rather than assuming a dollar peg.
