# Build status — 15 October 2026

**Production release: BLOCKED.** Commercial wallet splitting and the listed reliability fixes are implemented. No mainnet funds have been spent. This status does not claim every original acceptance gate is complete.

## Implemented and locally tested

- Python market discovery, quotes, route sizing, profitability, simulation, signing and transaction journaling.
- Aave Solidity executor with V2/V3 adapters, role checks, allowlists, deadlines, pause and treasury preservation.
- Three commercial wallet roles: customer recipient, gas-paying operator, merchant recipient. Merchant rate is disclosed, defaults to the selected 5%, and is immutable per deployment (maximum 10%).
- Customer min-profit checks after merchant deduction; atomic customer/merchant payouts; separate merchant fee accounting.
- OS worker exclusion, persistent RPC quotas, pending-first receipt reconciliation and bounded historical audits.
- Explicit recovery/cancellation, pending/latest nonce checks, pause/deadline guard immediately before signing.
- Resumable deployment plans keyed to durable journal records; repeated plans do not blindly redeploy.
- Password/CSRF-protected dashboard, dashboard-only mode, CLI, CSV/JSON reports and backup preservation.
- Direct Chainlink feed configuration with L2 sequencer outage/grace checks, plus six network registries.

## Verification evidence

- **56 Python tests pass**, including signed local EVM execution, merchant/customer payouts, canonical receipt accounting and authenticated export.
- **15 Solidity unit tests pass**, including 256 randomized treasury-preservation runs, merchant split/minimum, failed merchant payout and router reentry.
- Python lint and format checks pass. Python distribution builds successfully and installs in a clean environment; the CLI help runs from that installation.
- Slither 0.11.3 completed with 13 findings (0 High); triage is in [SECURITY.md](SECURITY.md).
- Fresh-context AI code review completed; identified implementation defects were fixed with regression tests. This is not an independent security audit.
- **Two merchant-aware Solidity protocol fork tests pass on each of all six networks (12 cases)**. These are controlled synthetic-market tests, not naturally occurring profit.
- Protocol fork and read-only probe reports are in [evidence](evidence/). Each report records its scope, date and block. Forks use synthetic liquidity and prove specific Solidity protocol interactions only.

## Remaining before production

1. Complete the **Python worker running against each real protocol fork** acceptance workflow. The present signed Python/EVM integration uses mock pools/routers; separate real-protocol Solidity forks do not close this combined gate. No live-authorization PASS files have been manufactured.
2. Resolve the **Base/OP hard fee bound** requirement. L1/operator fees are buffered estimates, so funded execution, deployment and recovery on those chains remain blocked.
3. Validate Docker runtime and full desktop/mobile visual acceptance. Docker is unavailable in this environment; image/Compose files are supplied but not called tested.
4. Supply actual customer/operator/merchant addresses and administrative owner; configure RPC and local encrypted signing keys. The selected merchant rate is 5%; public addresses remain to be supplied during desktop setup.
5. Measure deployment costs, deploy/verify chosen networks, fund gas and perform explicit mainnet activation. Those are deployment steps, not completed work.

The baseline uses USDC loans/profits; merchant fees are USDC for those routes. Gas uses each chain's native currency. Price-feed interface probes use a wider freshness window to establish compatibility; live policy remains strict and may reject older feed rounds.

[Commercial wallet terms](COMMERCIAL_WALLETS.md) · [Local operations](LOCAL_OPERATIONS.md) · [Handover](HANDOVER.md) · [Master checklist](EXECUTION_CHECKLIST.md)
