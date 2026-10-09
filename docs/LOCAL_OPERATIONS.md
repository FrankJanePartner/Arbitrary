# Local operation and current limits

Status: development checkpoint, not approved for funded operation. The six network registries exist; none has passed full fork certification. Base and OP Mainnet live execution is explicitly blocked pending a defensible L1/operator fee ceiling. Do not create a fake PASS evidence file to bypass a gate.

## Install and open the dashboard

From the repository root, with Python 3.12+, uv and Node/npm installed:

```sh
uv sync --locked
npm ci
npm run contracts:build
uv run flasharb init
uv run flasharb serve
```

Choose a dashboard password of at least 12 characters at the local prompt. Open http://127.0.0.1:8000 on the same computer. The server listens only on loopback. It starts in observe mode and cannot enable live signing through a browser. Do not expose it to the public internet. Stop with Ctrl+C; starting again preserves an emergency pause.

All networks start disabled. To observe Arbitrum, set an HTTPS RPC endpoint in your terminal's `RPC_42161` environment variable, then run:

```sh
uv run flasharb doctor --chain 42161
uv run flasharb enable 42161
uv run flasharb serve
```

RPC environment names are `RPC_1`, `RPC_42161`, `RPC_8453`, `RPC_10`, `RPC_137` and `RPC_43114`. Supply your actual endpoint locally; do not commit credentials. `.env` is ignored by Git but is not automatically loaded. A dashboard without configured RPC endpoints still opens and displays disconnected networks.

Use **one worker process at a time**. `serve`, `observe`, `simulate` and `run` each start a worker. Do not run the dashboard worker alongside a CLI worker against the same database. Cross-process locking and full restart recovery acceptance tests remain outstanding. RPC request quotas currently reset on process restart; account-level provider quotas still apply.

## Controls and reports

```sh
uv run flasharb status
uv run flasharb pause
uv run flasharb resume
uv run flasharb observe --once
uv run flasharb report --out data/report.json
uv run flasharb report --format csv --out data/report.csv
uv run flasharb backup data/backup.db
```

The dashboard provides network toggles, policy limits, pause/resume, observations, transactions and exports. Observations are quotes, not earnings. Reports distinguish provisional receipts from finalized results; USD values use stored submission-time price snapshots. Emergency pause stops new trading attempts while continuing receipt reconciliation. Already-broadcast transactions cannot be undone by pausing.

## Deployment preparation

`flasharb deploy-plan` creates unsigned deployment payloads; `configure-plan` creates owner configuration payloads; `estimate-cost` estimates fees; `verify-deployment` checks runtime bytecode and roles. Run `uv run flasharb <command> --help` for their arguments. Owner, operator and payout recipient are separate roles. Existing external wallets supply addresses; this application does not invent a wallet or embed a recipient private key.

`apply-plan` can spend gas after a local encrypted-keystore unlock and explicit confirmation. Its fee figures are estimates, particularly on OP-stack chains; this command is not certified for deployment yet. Do not use it for funded deployment until the remaining checklist gates are resolved. No keys or funding are needed to inspect the code, run unit tests or open the disconnected dashboard.

The live worker requires deployment verification, local signer unlock and matching fork evidence. Those checks do not constitute an independent security audit, and the current implementation has not passed full release review. Trading can lose gas even when the flash loan and swaps revert. Profitability has not been demonstrated.

## Local data and recovery

The `data/` directory contains the SQLite database, dashboard password hash, reports and transaction/deployment journals. Keep it private and back it up. Never delete the database to clear a stuck transaction: pending nonces and budget reservations are financial state. Stop the worker before restoring a backup, retain the latest database, and reconcile against the chain before any new signing. Backup creation is tested; full restore/recovery acceptance is outstanding.

No licence has been added that grants public reuse rights. Repository access and source possession do not by themselves settle ownership or employment agreements; personal/company handover remains a separate documented step.
