# Local Python worker integration test

This opt-in test joins the Python worker to the real Aave and Uniswap V3 contracts on
a selected supported EVM network fork. It creates deliberately mispriced test pools, signs a local
trade with a newly generated temporary account, and checks repayment, the 5%
merchant share, customer payout, gas accounting, treasury preservation, cleared
allowances, replay rejection, restart reconciliation, and report export.

## Run from Ubuntu / WSL

Keep your existing Anvil terminal running on `127.0.0.1:8547`, chain ID `31337`,
with the Prague hardfork. It must fork the selected source network. Node dependencies and
Python dependencies must already be installed. No production wallet or private
key is required. Do not run other local-fork transactions during this test:
restoring its snapshot also discards any concurrent local-fork transactions.

In a separate terminal:

```bash
cd /mnt/f/Arbitrary
git fetch origin codex/company-six-chain-readiness
git switch --track origin/codex/company-six-chain-readiness
uv run python scripts/test-worker-fork.py
```

The default `--chain 42161` tests Arbitrum. For the other networks, first restart
Anvil with the matching network RPC, then select one source ID per run:

```bash
uv run python scripts/test-worker-fork.py --chain 1
uv run python scripts/test-worker-fork.py --chain 8453
uv run python scripts/test-worker-fork.py --chain 10
uv run python scripts/test-worker-fork.py --chain 137
uv run python scripts/test-worker-fork.py --chain 43114
```

The harness checks only the local Anvil chain ID and identity before mutating its
state. Confirm that Anvil is connected to the requested source network before
running; the command does not infer the fork's source chain from chain ID 31337.

The command compiles its fixture through Forge. It uses only the local endpoint,
checks both Anvil identity and chain ID before mutations, uses temporary local
wallet balances, and restores the fork snapshot afterward. Your existing local
executor remains as it was before the test. It uses a temporary database and does
not change your dashboard database, `.env`, or chain registry files. Anvil may
still make upstream read requests to Alchemy while loading fork state.

On success it prints `LOCAL_WORKER_PASS` and saves
`data/local-worker-report-<chain ID>.json`. On a test failure it raises an error and attempts
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
- Local EVM gas accounting does not validate source-network fees, including Arbitrum Nitro L1 posting fees.
- This fixture uses test policy limits, a one-day oracle age limit, and one local
  confirmation. These settings are not copied into production configuration.
- Each pass covers the selected source network's Uniswap V3 integration only. It does not certify all six until each ID has its own recorded pass, and it does not test the newly configured Uniswap V2 routes.
- It does not provide a production authorization, security audit, production
  funding estimate, or certification for continuous operation.

The temporary live-mode gate file is scoped to chain `31337` and a synthetic
registry digest. It is deleted with the temporary directory. Never rename the
report to `fork-42161.json`, change its status to `PASS`, or use it to bypass the
production verification gate.

## Recorded desktop run

On 16 October 2026, the operator ran the harness on the desktop against a local
Anvil fork of Arbitrum One. It returned `LOCAL_WORKER_PASS` and
`"snapshot_restored": true`. The synthetic test reported a 26.223941 USDC
customer payout, a 1.380207 USDC merchant payout, a 0.005 USDC loan premium,
and 0.000511676888743318 ETH local EVM gas accounting. These figures are from
manufactured prices/liquidity and are not real market earnings or a live gas
quote. The 63 Python tests also passed at that checkpoint, including harness chain guards and
snapshot cleanup on failure.
