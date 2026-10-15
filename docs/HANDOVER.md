# Handover — 15 October 2026

The repository contains the local Python operator, Solidity executor, dashboard, reports, deployment tools, runtime recovery and commercial merchant splitting. This handover is a source/testing checkpoint, not permission to fund production trading.

## Demonstration without funds

```sh
uv sync --locked --python 3.12
npm ci
npm run contracts:build
npm run contracts:test
uv run pytest -q
uv run flasharb init
uv run flasharb serve
```

Open http://127.0.0.1:8000 on the same computer. Networks start disabled. RPC credentials are environment variables described in LOCAL_OPERATIONS.md. Observe mode discovers quotes without signing. A profitable quote is not a realized earning.

## Commercial setup decisions

Collect public customer-profit, operator/gas and merchant addresses for each intended network. The selected fee is 500 basis points (5%), with a contract maximum of 1,000. Put public addresses and RPC endpoints in the single local `.env` file described in [desktop setup](DESKTOP_SETUP.md). Select the administrative owner and who retains its key. The merchant and rate are immutable in the deployed contract. The operator needs an encrypted keystore locally; never request recipient or merchant private keys.

Use `flasharb deploy-plan --help` to generate an unsigned plan. Confirm addresses, network and fee in that plan. Deploying costs gas; the present checkpoint has not deployed anything on mainnet. The `apply-plan` command can resume the exact plan after interruption using its durable journal. Base/OP mainnet application remains blocked under the strict fee policy.

## Evidence and honest presentation

- Deterministic tests cover contract repayment, treasury protection, merchant/customer split, failed payouts, reentry, budgets, nonces, backup state, login/CSRF, reconciliation and report export.
- Protocol fork tests use real Aave/Uniswap deployments with a new synthetic token, impersonated reserve funding and deliberately different pool prices. They prove specific protocol interactions, not naturally available profits.
- Local Python/EVM integration signs a transaction and records its actual receipt and merchant/customer payouts. It uses mocked pool/router contracts, so it is not a substitute for full Python-worker integration against every real network.
- Review and static-analysis findings are recorded in SECURITY.md. An AI review is not an independent commercial audit.

Do not present this as a completed production release while BUILD_STATUS.md names open gates. Full worker-on-fork acceptance and Base/OP hard fee bounds are unresolved. Docker is supplied but has not been run in this environment. Deployment budget figures must be measured later from the finished plan and selected network; none are promised here.

## Source and operations

Each buyer/company instance needs separate data, credentials, wallets and budgets. There is no automatic subscription billing, tenant-hosting service or licence enforcement in this local architecture. Merchant terms are visible in the dashboard and generated deployment plan. Source recipients can change and redeploy source; immutable fees protect the terms of a particular deployed contract, not against source copying.

Maintain backups of the database and public configuration. Use `serve --dashboard-only` while running a separate worker. Stop the worker before `recover` or `apply-plan`. Never delete an unresolved nonce or reservation to bypass a failed check. Recalculate current fees and run exact transaction simulations before enabling any funded network.
