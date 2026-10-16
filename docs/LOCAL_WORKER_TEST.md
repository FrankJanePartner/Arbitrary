# Local Python worker integration test

This opt-in test joins the Python worker to the real Aave and Uniswap contracts on
an Arbitrum fork. It creates deliberately mispriced test pools, signs a local
trade with a newly generated temporary account, and checks repayment, the 5%
merchant share, customer payout, gas accounting, treasury preservation, cleared
allowances, replay rejection, restart reconciliation, and report export.

## Run from Ubuntu / WSL

Keep your existing Anvil terminal running on `127.0.0.1:8547`, chain ID `31337`,
with the Prague hardfork. It must be a recent Arbitrum fork. Node dependencies and
Python dependencies must already be installed. No production wallet or private
key is required. Do not run other local-fork transactions during this test:
restoring its snapshot also discards any concurrent local-fork transactions.

In a separate terminal:

```bash
cd /mnt/f/Arbitrary
git pull --ff-only
uv run python scripts/test-worker-fork.py
```

The command compiles its fixture through Forge. It uses only the local endpoint,
checks both Anvil identity and chain ID before mutations, uses temporary local
wallet balances, and restores the fork snapshot afterward. Your existing local
executor remains as it was before the test. It uses a temporary database and does
not change your dashboard database, `.env`, or chain registry files. Anvil may
still make upstream read requests to Alchemy while loading fork state.

On success it prints `LOCAL_WORKER_PASS` and saves
`data/local-worker-report.json`. On a test failure it raises an error and attempts
to restore the snapshot. If restoration fails or the process is forcibly killed,
restart Anvil before continuing. A compiler or connection failure does not mean
the integration passed. Run without Python's `-O` optimization flag.

## What a pass establishes

The worker discovered a synthetic opportunity, quoted and simulated it, submitted
one signed transaction on the local chain, and reconciled its receipt. Assertions
compare actual token/native balances with the recorded accounting. Reconciliation
is repeated after reopening the database to check that it does not duplicate
settlement. The merchant receives 5% of trading surplus after the flash-loan
premium; gas is paid separately by the operator.

## What remains outside this test

- The opportunity and liquidity are deliberately manufactured; they do not prove
  that profitable opportunities exist on mainnet.
- Local EVM gas accounting does not validate Arbitrum Nitro L1 posting fees.
- This fixture uses test policy limits, a one-day oracle age limit, and one local
  confirmation. These settings are not copied into production configuration.
- This tests Arbitrum protocol integrations only, not all six networks.
- It does not provide a production authorization, security audit, production
  funding estimate, or certification for continuous operation.

The temporary live-mode gate file is scoped to chain `31337` and a synthetic
registry digest. It is deleted with the temporary directory. Never rename the
report to `fork-42161.json`, change its status to `PASS`, or use it to bypass the
production verification gate.

## Validation at introduction

The Solidity fixture compiled with Solc 0.8.30 (Prague), lint passed, and all 63
Python tests passed, including rejection of nonlocal chains and snapshot cleanup
on failure. The full upstream-backed worker test could not be run in the authoring
environment because its public Arbitrum RPC was unreachable. Its result must be
verified on the desktop's working fork; no end-to-end pass is claimed yet.
