# Flash Arbitrage — Build, Deployment and Operations Checklist

Date: 8 October 2026 (Africa/Lagos). Companion: [MVP specification and implementation plan](MVP_IMPLEMENTATION_PLAN.md).

This is the master progress record. Implementation has started; see [build status](BUILD_STATUS.md) for current evidence. Unchecked boxes remain unaccepted. Mark a box only with supporting commit, command result, report or operator record. No completion or profit claim follows from the existence of this checklist.

## A. Before application development

- [x] `FrankJanePartner/Arbitrary` repository verified under the correct personal account; existing public visibility recorded.
- [x] `docs/MVP_IMPLEMENTATION_PLAN.md` committed and content verified on GitHub.
- [x] `docs/EXECUTION_CHECKLIST.md` committed and content verified on GitHub.
- [x] User reviews the written plan; document scope corrections before implementing.
- [ ] Record execution approach and development environment.
- [ ] Preserve personal/company separation; ownership/reuse agreement handled separately before company handover.
- [ ] Do not add signing keys, RPC credentials or a licence granting public rights by default.

## B. Integration evidence and foundation — Task 1

- [ ] Pin Python dependencies, Solidity compiler, OpenZeppelin and Foundry revisions.
- [ ] Define shared interfaces and exact integer/Decimal conventions.
- [ ] Create private-by-default, observe-mode configuration.
- [ ] Confirm six chain IDs and correct RPC responses.
- [ ] Pin official Aave provider/Pool, exchange/quote/factory addresses and token metadata per chain.
- [ ] Verify router ABI variants, deployed code and flash-loan asset eligibility/liquidity.
- [ ] Publish `docs/INTEGRATION_MATRIX.md` and registry provenance.
- [ ] Config, secret-redaction, wrong-chain and stale-registry tests pass.

## C. Atomic execution contracts — Task 2

- [x] Implement executor, typed V2/V3 adapters and exported ABI.
- [ ] Operator/owner/recipient roles are separate and tested.
- [ ] Only verified provider and current execution context can invoke callback.
- [x] Existing contract balance cannot subsidize losing execution.
- [x] Principal plus premium remains reserved; only incremental surplus is paid.
- [ ] Allowlists, min outputs, route continuity, deadline and pause enforced.
- [ ] Reentrancy/replay/payout-failure/unauthorized-withdrawal tests pass.
- [ ] Fuzz/invariant tests and allowance lifecycle checks pass.

## D. Market data and opportunity engine — Tasks 3–4

- [ ] Block/event streaming reconnects and backfills safely.
- [ ] Pools/tokens are allowlisted and discovery workload is bounded.
- [ ] Quotes use consistent block context and exact token units.
- [ ] Two/three-hop routes close in the borrowed token.
- [ ] Loan-size search respects liquidity and configured limits.
- [ ] Exchange fees/price impact are included without double-counting.
- [ ] Actual flash premium and conservative gas conversion are included.
- [ ] Stale quotes/prices/provider data block live decisions.
- [ ] No-opportunity condition produces a clear no-trade result.
- [ ] RPC quotas/backoff and all strategy tests pass.

## E. Simulation, signing and budget controls — Tasks 5–6

- [ ] Simulate exact executor payload, sender, loan and min-profit threshold.
- [ ] Model complete fees for each chain; reject missing cost bounds.
- [ ] Daily/per-transaction limits reserve pending maximum gas liability.
- [ ] Failed transactions and cancellation gas remain in spending totals.
- [ ] Midnight, retries and replacement transactions cannot reset/bypass limits.
- [ ] Encrypted keystore unlock implemented; no key in `.env`, Git, UI or logs.
- [ ] Intent, signed hash, nonce and budget persisted before broadcasting.
- [ ] Timeout/restart recovery does not create duplicate transactions.
- [ ] Public/private submission capability and fallback policy explicit.
- [ ] Low balance and fee ceiling cause pause/skip; relevant tests pass.

## F. Accounting, lifecycle and dashboard — Tasks 7–9

- [ ] SQLite migrations, WAL and backup/restore tested.
- [ ] Receipts tracked through pending/provisional/final/replaced/failed/unknown states.
- [ ] Reorgs and duplicate receipts reconcile without false profit.
- [ ] Actual payout and all fee components recorded by network/token.
- [ ] Estimated opportunity and realized net earnings displayed separately.
- [x] CSV/JSON exports and daily local report implemented.
- [ ] Sleep/crash/restart reconciles transactions before new submissions.
- [x] Startup does not unexpectedly enable live trading.
- [x] One chain failure does not corrupt another chain's worker/accounting.
- [x] Local dashboard authentication/CSRF/secret-redaction tests pass.
- [ ] Mobile/desktop controls, six network panels and emergency pause checked.

## G. Packaging and full-system verification — Tasks 10–11

- [ ] Clean local installation works with documented commands.
- [ ] Optional Docker packaging builds and runs.
- [ ] Deployment plan/cost estimator produces unsigned, chain-specific output.
- [ ] Deployment verifier checks chain, bytecode and owner/operator/recipient.
- [ ] Unit, integration, fuzz/invariant, lint/type and static-analysis checks pass.
- [ ] Critical/high findings resolved; remaining issues documented.
- [ ] Offline CI does not claim fork checks passed when RPC secrets are missing.
- [ ] Complete local UI → quote → simulation → executor → ledger → export flow demonstrated.
- [ ] Audit/review status stated accurately; automated testing is not called an independent audit.

### Six-network verification tracker

All rows start `NOT RUN`. Replace status only with evidence paths and pinned block/address information.

| Network | ID | Registry/ABI verified | Full fork execution | Loss reverts | Repayment/payout | Fee model | Deployment tools | Evidence/status |
| --- | ---: | --- | --- | --- | --- | --- | --- | --- |
| Ethereum | 1 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | NOT RUN |
| Arbitrum One | 42161 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | NOT RUN |
| Base | 8453 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | NOT RUN |
| OP Mainnet | 10 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | NOT RUN |
| Polygon PoS | 137 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | NOT RUN |
| Avalanche C-Chain | 43114 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | NOT RUN |

- [ ] Each row has controlled profitable execution and an unprofitable revert on actual pinned protocol forks.
- [ ] Synthetic price/liquidity changes used in tests explicitly disclosed.
- [ ] No chain marked supported merely because its YAML exists.
- [ ] Final source readiness report names every blocked verification accurately.

## H. Before spending real funds — Task 12

- [ ] Choose which networks to activate; all six need not be funded together.
- [ ] Check current deployment and transaction fees from finished bytecode/payloads.
- [ ] Include funding/withdrawal/bridge charges for the chosen funding route.
- [ ] Set network-native gas balance and conservative budget in token units and reporting currency.
- [ ] Set per-transaction, per-day, pending liability, low-balance and minimum-net-profit limits.
- [ ] Do not reuse provisional $20–$50 or earlier multi-chain budgets as measured quotations.
- [ ] Configure verified recipient public address; recipient signing key stays off bot.
- [ ] Owner/operator signers and recovery procedures established securely.
- [ ] Operator explicitly authorizes mainnet deployment/funding/signing locally.

## I. Mainnet deployment and activation — repeat per funded network

- [ ] Confirm chain ID and source/ABI/compiler/dependency revisions.
- [ ] Review unsigned deployment/configuration transactions and fresh fee estimates.
- [ ] Deploy executor/adapters and record receipts/addresses/bytecode hash.
- [ ] Verify source where supported and confirm bytecode, owner, operator, recipient and allowlists.
- [ ] Confirm flash-loan eligibility/liquidity and live router behavior again.
- [ ] Fund operator gas wallet on the correct chain and set spending limits.
- [ ] Run doctor, observe and exact full-call simulation on deployed contracts.
- [ ] Explicitly enable live; no natural opportunity means wait, not fabricate a trade.
- [ ] Reconcile first included receipt; confirm actual gas and any payout.
- [ ] Check no-trade, failed-transaction, low-balance and emergency-pause behavior.
- [ ] Record network live status independently of other networks.

## J. Daily operation and safe shutdown

- [ ] Check RPC usage, chain heads, native gas balance and pending transactions.
- [ ] Review actual net results including failures and infrastructure expense.
- [ ] Preserve outstanding fee reservations and unresolved nonce records.
- [ ] Investigate repeated losses/reverts; pause before raising limits.
- [ ] Back up database, configuration and public deployment records; encrypt sensitive backups.
- [ ] Pause/stop worker cleanly before planned shutdown when possible.
- [ ] After restart/sleep, reconcile pending transactions, refresh quotes and unlock signer locally.
- [ ] Keep live activation deliberate; retain off-chain observe capability without spending gas.

## K. Scaling and company handover

- [ ] Confirm operating results justify paid RPC/hosting before subscribing.
- [ ] Activate extra networks individually after funding and verification.
- [ ] Retest after dependency/provider/contract changes; no silent registry replacement.
- [ ] Company instance uses separate keys, recipients, budgets and data directory.
- [ ] Confirm company source-use agreement and chosen distribution/licence terms.
- [ ] Deliver complete source, integration evidence, installation and emergency runbooks.
- [ ] Document real costs, remaining risks and known limitations without guaranteed-income claims.
- [ ] Tag software release only after applicable completion gates pass.

## Progress log

Append entries in this form: `date/time | task/checklist section | commit | tests/report | result | remaining blocker`. Never include credentials or private signing material.

## Stop conditions

Wrong chain or bytecode, stale/missing fee conversion, unverified router/token, failed simulation, insufficient gas, exceeded budget, unknown pending nonce, RPC quota exhaustion or unresolved high-risk contract finding must prevent new live submissions. Receipt reconciliation remains available while paused.

## Evidence for checked implementation items

9 October checkpoint: `uv run pytest -q` — 36 passed; `npm run contracts:test` — 9 passed, including 256 fuzz runs. `tests/test_worker.py` covers non-live restart, pause preservation and chain failure isolation; `tests/test_web.py` covers authentication/CSRF and exports; `contracts/test/Executor.t.sol` covers treasury preservation and incremental payouts. These are scoped local tests; the broader unchecked integration/recovery requirements still apply.
