# Arbitrary

Python and Solidity flash-loan arbitrage system under active development.

**Status: implementation in progress; not ready for live funds.** See [build status](docs/BUILD_STATUS.md).

## Code

- [`contracts/src`](contracts/src): flash-loan executor and typed exchange adapters
- [`src/flasharb`](src/flasharb): configuration, market analysis, execution and storage
- [`tests`](tests) and [`contracts/test`](contracts/test): automated checks
- [`config/chains`](config/chains): Ethereum, Arbitrum, Base, Optimism, Polygon and Avalanche

## Local developer checks

Requires Python 3.12+, uv and Node.js/npm.

```sh
uv sync --locked
npm ci
uv run pytest -q
npm run contracts:build
npm run contracts:test
```

## Open the local dashboard

```sh
uv run flasharb init
uv run flasharb serve
```

Open http://127.0.0.1:8000 on the same computer. All networks start disabled. See [local operations and current limits](docs/LOCAL_OPERATIONS.md) before enabling a network.

## Project guides

- [MVP specification and implementation plan](docs/MVP_IMPLEMENTATION_PLAN.md)
- [Execution checklist](docs/EXECUTION_CHECKLIST.md)
- [Integration evidence](docs/INTEGRATION_MATRIX.md)

No private keys or RPC secrets belong in this repository. No profitability guarantee or independent security audit is claimed.
