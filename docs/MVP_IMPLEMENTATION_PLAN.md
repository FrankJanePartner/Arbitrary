# Flash Arbitrage — MVP Specification and Implementation Plan

Date: 8 October 2026 (Africa/Lagos). Status: planning deliverable; implementation has not started.

> For agentic workers: use `superpowers:executing-plans` to implement this plan task by task. Read this complete document and `EXECUTION_CHECKLIST.md` before changing application code. Checkboxes require recorded evidence, not merely a claim of completion.

**Goal:** Deliver a complete, locally runnable Python/Solidity flash-loan arbitrage system with independently verified support for six EVM networks, automatic token-profit payouts, secure controls, accounting, tests and deployment tools.

**Architecture:** A Python service discovers and quotes allowlisted swap routes, estimates all execution costs, simulates a Solidity flash-loan transaction and submits it only when configured conditions pass. One immutable executor is deployed per network; borrowing, swaps, repayment reservation and payout are atomic within that network. A local authenticated dashboard controls workers and shows reconciled results.

**Tech stack:** Python 3.12+, web3.py, Pydantic, FastAPI, Jinja2/HTMX, SQLite with WAL, pytest; Solidity 0.8.x, OpenZeppelin contracts, Foundry; Docker Compose optional. Pin exact compatible Python dependency versions, Solidity compiler and contract dependencies in Task 1; retain lockfiles and reproducible build evidence.

**Spec:** Sections 1–9 of this document are the product specification. Sections 10–12 are its implementation plan. The companion checklist tracks the entire lifecycle.

## Global constraints

- Repository owner: `FrankJanePartner`; repository name: `Arbitrary`; user-provided repository is public. Keep secrets and company-specific confidential data out of commits; visibility changes require a separate user decision.
- Core business logic is Python; blockchain executor and exchange adapters are Solidity. HTML/CSS and minimal JavaScript are only for the dashboard.
- Network scope: Ethereum (1), Arbitrum One (42161), Base (8453), OP Mainnet (10), Polygon PoS (137), Avalanche C-Chain (43114).
- Every network must pass actual chain-specific integration checks. A configuration file alone is not completed support.
- Every flash-loan route starts and ends in the same borrowed ERC-20 token on one chain; no bridging inside a loan.
- Default startup mode is observe; live mode requires explicit local configuration, verified contracts, an unlocked signer and sufficient gas funding.
- No private keys, recovery phrases, credentials or funded wallet material enter Git, reports, browser responses or logs.
- All token quantities use integer base units; monetary reporting uses Decimal; floating-point arithmetic is prohibited in financial decisions.
- No income guarantees. The ₦500,000 monthly goal is context, not an acceptance criterion or forecast.
- Build the full agreed feature set before handover. Test sequencing and individual network activation are verification/funding steps, not postponed features.
- Deployment estimates and USD/NGN conversions must be measured at deployment time; earlier conversation budgets are provisional.

## Review focus

1. Computer sleep/crash after submission: recover the persisted nonce and transaction, then reconcile before another submission (Tasks 6, 7).
2. RPC returns stale data or the wrong network: reject the route and stop affected live submissions (Tasks 1, 3, 5).
3. Token has unusual transfer behavior or decimals: reject unapproved/nonstandard assets and preserve exact unit arithmetic (Tasks 1, 2, 4).
4. Pending transactions consume the budget: reserve their maximum fee liability before sending, including replacements (Tasks 5, 6).
5. A successful-looking receipt is later reorganized: distinguish provisional/final results and rebuild accounting (Tasks 6, 7).

## 1. Intended use and completion definition

The user can run the complete system on their own computer while it is awake and connected. It must restart safely after a stop, crash or sleep. No custom domain, external database or paid hosting is required for local operation. Free RPC plans may be used within their limits; the system must not assume free unlimited throughput.

The company can operate a separate installation of the same code with independent wallets, keys, settings and records. Keeping code in the user's repository does not establish employer/IP rights; a separate written agreement is needed for ownership and company use. Do not apply an open-source licence automatically; record third-party licences and leave distribution rights private pending the user's decision.

Completion means all six networks have verified deployments/integrations, supported route types, passing fork evidence, deployment procedures and readiness reports. Actual production deployment on each network requires its RPC configuration, signer, destination address and funding. If any integration fails, report that network as blocked; do not label all six complete.

## 2. Networks and integration policy

| Network | Chain ID | Gas currency | Flash-loan integration | Operational policy |
| --- | ---: | --- | --- | --- |
| Ethereum | 1 | ETH | Aave V3 Pool, verified market | Supported; independently enabled and funded |
| Arbitrum One | 42161 | ETH | Aave V3 Pool, verified market | Proposed first personal activation |
| Base | 8453 | ETH | Aave V3 Pool, verified market | Independently enabled and funded |
| OP Mainnet | 10 | ETH | Aave V3 Pool, verified market | Independently enabled and funded |
| Polygon PoS | 137 | POL | Aave V3 Pool, verified market | Independently enabled and funded |
| Avalanche C-Chain | 43114 | AVAX | Aave V3 Pool, verified market | Independently enabled and funded |

Aave V3 `flashLoanSimple` is the baseline for one reserve asset. Query the applicable premium and reserve flash-loan eligibility instead of hardcoding a fee or assuming all listed reserves are borrowable. Verify market liquidity for each proposed amount.

Exchange coverage: implement direct, typed adapters for standard Uniswap V2-compatible exact-input routers and Uniswap V3-compatible exact-input routers/quoters. Discover cycles across distinct pools and fee tiers; same-protocol pools may qualify. On each chain select and verify at least two usable venues/pools, including Uniswap V3 where available and a second supported deployment where useful. Router ABI compatibility must be established explicitly; fork names do not prove compatibility. Other AMM designs, v4 hooks and arbitrary aggregator calldata are outside this fixed release scope.

Task 1 creates `docs/INTEGRATION_MATRIX.md` with the chosen actual venues, factories, routers, quoters, Aave provider/Pool, assets, decimals, addresses, ABI variants, source revisions and verification block. Confirm each address has expected code and interface behavior on its configured chain. Pin snapshots of official registries; never silently fetch new trusted addresses during live startup. Runtime checks must detect configuration drift.

Loan assets: begin with verified standard stablecoins supported for flash loans, with USDC as a candidate rather than an assumption. Permit only approved intermediate tokens. Avoid taxed, rebasing, ERC-777-like callback and unknown tokens. Loan and intermediate token support must be proven with fork tests.

## 3. Execution and payout

For every candidate, quote a two- or three-swap cycle at the same block, search permitted loan sizes, and calculate conservative net profit. Check reserve liquidity, per-hop minimum output, deadline, estimated gas and current provider premium. Simulate the actual executor call with the intended sender and parameters before submission.

The executor checks caller authorization, pause state, chain-specific provider, permitted loan asset, approved adapters/routers/tokens and route continuity. The callback accepts only the configured Aave Pool and this contract as initiator, and must match an active execution context. Reject unsolicited, replayed and nested callbacks.

Record starting borrowed-token balance before the loan. After swaps, require `endingBalance >= startingBalance + principal + premium + minProfitToken`. This prevents existing contract balances from subsidizing losses. Approve exactly the repayment obligation; transfer only incremental surplus to the configured profit recipient. Aave then pulls repayment before the outer transaction completes. A subsequent failure reverts the entire transaction, including payout. Clear allowances and execution state safely; payout failure must revert.

Separate contract owner, authorized bot operator and profit recipient. Owner manages allowlists, recipient, operator and pause; bot operator cannot change them or withdraw existing treasury balances. Emit execution/profit events with a unique intent identifier and route hash. Provide owner-only recovery outside active execution; do not give the bot arbitrary call or withdrawal permissions. Use a deployed executor without a proxy; upgrades require a new verified deployment.

Profits arrive in the borrowed token on the execution network. Same EVM address can receive across networks, but balances are separate. Automatic bridging, NGN conversion and bank withdrawal are outside scope.

## 4. Opportunity engine

Watch new blocks and selected pool events with reconnect/backfill logic; bound the pool universe and use multicall/batching where supported. Build directed cycles of length two or three over approved tokens and pools. V2 reserve math may shortlist routes; authoritative router/quoter calls and full-call simulation determine eligibility. Never send based only on a displayed spot-price spread.

Use bounded loan-size search between configured minimum/maximum amounts and liquidity limits. Optimizing a configured candidate set is not a claim to find the global maximum profit on a chain.

Decision formula: expected swap surplus minus flash premium minus conservative native-gas conversion minus optional chain-specific submission fees minus configured safety buffer. Swap quotes already include exchange fees and price impact; do not subtract those fees twice. Use fresh, verified price feeds/quotes for gas-to-loan-token conversion; stale/missing data disables live decisions. Set the contract's minimum token profit to cover conservative gas plus the required net margin.

Use maximum block age and short deadlines. Requote/resimulate if prices, loan fee, gas or block context changes beyond configured tolerances. Skip gracefully when no profitable route exists. RPC limits must slow/back off the worker, not cause uncontrolled retries.

## 5. Transaction safety and budget policy

One transaction submission worker per chain/operator pair; initially allow one unresolved nonce per pair. Persist intent, payload, nonce, budget reservation and locally computed transaction hash before network submission. After an ambiguous timeout, query by hash/nonce and rebroadcast identical signed bytes if appropriate; never create another intent blindly.

Replacement transactions use the same nonce, persist all hashes and increase reserved maximum liability before broadcast. Implement bounded fee escalation and configurable cancellation, with cancellation gas counted as spending. Pause scanning/submission independently of receipt reconciliation.

Enforce per-transaction gas liability, per-chain daily budget, optional global daily USD budget, fee ceilings and low-wallet-balance thresholds. Budget accounting includes pending maximum liabilities, failed/successful actual costs and replacements; settled replacement hashes count only the included transaction. Persist the selected daily accounting timezone, default Africa/Lagos. Never release unresolved liabilities merely because midnight passed.

Estimate complete fees for each chain, including Arbitrum L1 posting costs and OP/Base L1 data fees and any applicable additional fees; avoid double-counting where the estimator already includes them. If a maximum cost cannot be bounded conservatively, disable submission on that chain. Use actual receipt costs for reconciliation.

Do not claim universal private execution. Implement a chain-capability-aware submission adapter for verified private/conditional services where available. Public submission remains explicit in settings and reports; unavailable private routing must not silently fall back. No sandwich strategy is included.

## 6. Controls, signing and local operation

Dashboard binds to `127.0.0.1` by default. Require local authentication, CSRF protection for mutations and no secrets in HTML/API responses. Remote access is disabled until explicitly configured with TLS and authentication. Basic UI is server-rendered to avoid an unnecessary separate frontend build.

Controls: observe/simulate/live mode, per-network enable, start/pause/stop, approved tokens/routes, loan-size limits, minimum net profit, spending limits and recipient readout. Owner configuration transactions require the owner signer; operator cannot authorize them. Show last block, RPC usage/rate limits, health, pending transactions, wallet gas balances, estimated opportunities and realized profit separately.

Use encrypted local Ethereum keystores with interactive unlock for bot operation; keep the decrypted signing material in the worker process only. Keep the payout wallet's private key off the bot. No plaintext signing key in `.env`. Separate instances can use separate data/config directories. Document hardware/remote signer extension points without claiming they are shipped integrations.

Handle SIGTERM, network loss and clock/sleep gaps. Stop creating new intents, persist state and continue/recover receipt reconciliation on restart. Never automatically switch from observe to live after an unexpected restart without the configured local operator action.

## 7. Records and reports

SQLite WAL stores configuration versions, observed opportunities, rejection reasons, executions, raw receipts, profit events, fee components, nonce reservations and budget ledger. Single-process local deployment is the default; migrations and backups are included. Multi-machine shared SQLite is prohibited.

Track transactions as planned, signed, submitted, pending, provisionally mined, confirmed, failed, replaced or unknown. Confirmations are network-specific and configurable. Reorgs roll back provisional accounting and reconcile canonical receipts. All display/report entries distinguish estimated, provisional and finalized values.

Reports expose token-denominated profit, gas expense, timestamped USD valuations and net operating results including failed attempts. Export CSV and JSON; provide a daily local summary. No emails/messages are sent without separate user configuration and authorization. Keep operating infrastructure costs separate from trading costs, but include them in profitability review.

## 8. Verification and deployment gates

Automated tests cover Solidity repayment/payout/authentication invariants, Python financial calculations, budgets, crash recovery, stale data and dashboard access. Use local mocks for deterministic behavior plus pinned mainnet-fork integration tests for actual Aave and exchange contracts on all six networks. Fork tests need configured archive-capable RPC access. They do not spend real on-chain money.

Prove at least one controlled profitable full route, one unprofitable revert and correct fee/payout accounting on each fork. Any injected reserves/prices/liquidity must be disclosed; synthetic profitable routes demonstrate execution correctness, not naturally available income. Do not weaken min-profit checks or pre-fund executors to make loss cases look successful.

Use Foundry fuzz/invariant tests and static analysis for the contracts. Record compiler, dependencies, bytecode, addresses and test blocks. An independent contract audit is not claimed by automated checks; document review status for any company deployment.

Production deployment tools first generate an unsigned plan and cost report. Sending requires explicit operator action. Confirm chain ID, deployed bytecode, owner/operator/recipient and allowances before enabling live. Wallet creation, funding, paid services and mainnet sends are not authorized by this planning request.

## 9. Deliverables and boundaries

Deliverables: full source, lockfiles, verified six-chain registry, executors/adapters, local dashboard/worker, encrypted signing support, accounting/export, CLI, deployment/cost tools, automated CI, fork evidence, operation/security/handover documentation and backups/restore procedures. Repository initially contains its existing README and these planning documents only.

Exclusions: cross-chain flash repayment, Solana/Bitcoin execution, centralized-exchange arbitrage, automatic bridging/cash-out, arbitrary router execution, a newly built wallet, guaranteed profits and paid infrastructure provisioning. These boundaries prevent unsupported compatibility claims; they do not defer agreed core components to a later version.

## 10. File structure and shared interfaces

| Path | Responsibility |
| --- | --- |
| `config/chains/*.yaml`, `config/registry.lock.json` | Verified per-chain addresses/capabilities and pinned provenance |
| `src/flasharb/config.py`, `models.py` | Validated settings and shared integer-unit models |
| `src/flasharb/market/{rpc,pools,quotes}.py` | Chain checks, pool discovery and block-consistent quotes |
| `src/flasharb/strategy/{cycles,sizing,economics}.py` | Candidate generation, sizing and net-profit decisions |
| `src/flasharb/execution/{simulation,fees,budget,signer,transactions}.py` | Safe simulation, signing, budget reservation and submission |
| `src/flasharb/storage/{db,ledger,reconcile}.py` | Durable state, finalized accounting and recovery |
| `src/flasharb/{worker,cli}.py` | Worker lifecycle and command interface |
| `src/flasharb/web/`, `templates/`, `static/` | Authenticated local controls and reports |
| `contracts/src/FlashArbitrageExecutor.sol` | Atomic Aave execution and protected surplus payout |
| `contracts/src/adapters/{V2Adapter,V3Adapter}.sol` | Typed allowlisted exchange execution |
| `contracts/test/`, `tests/`, `tests/forks/` | Deterministic, invariant and chain-specific integration tests |
| `scripts/{deploy,estimate_cost,verify_deployment}.py` | Unsigned plans, measured fees and post-deployment checks |
| `docs/{INTEGRATION_MATRIX,OPERATIONS,SECURITY,HANDOVER}.md` | Integration evidence, lifecycle and company installation guide |

Shared models in `models.py`: `ChainConfig`, `Token(amount units/decimals metadata)`, `Hop`, `Route`, `Quote(block_number, amount_in, amount_out)`, `FeeEstimate(max_native_cost, expected_native_cost, components)`, `ProfitDecision(eligible, min_profit_token, reasons)`, `Intent(id, chain_id, operator, nonce, route, amount, deadline)`, `SimulationResult`, `Submission`, `ReceiptRecord`. Define concrete typed fields in Task 1 and preserve interfaces below. RPC/network work is async; SQLite transactions are atomic and brief.

## 11. Implementation tasks

Execute in order. For each task: write the named assertions first, run the test to see the intended failure, implement, rerun tests and commit the independently reviewable deliverable. Commands below are planned commands, not results already obtained.

### Task 1 — Configuration, registry and reproducible foundation

**Files:** `pyproject.toml`, `uv.lock`, `contracts/foundry.toml`, dependency lock/revisions, `.gitignore`, `.env.example`, `models.py`, `config.py`, six chain YAML files, registry lock, `docs/INTEGRATION_MATRIX.md`, `tests/test_config.py`.

**Interfaces:** `load_config(path: Path) -> AppConfig`; `async verify_chain(config: ChainConfig, rpc: RpcClient) -> VerificationReport`. `VerificationReport` contains checked chain ID, address code/ABI checks, verification block and explicit blocking reasons.

- [ ] Define all shared models, six chain IDs, unit/Decimal conventions and private-by-default settings.
- [ ] Tests `test_six_chain_ids`, `test_wrong_chain_blocks_live`, `test_unknown_token_rejected`, `test_registry_drift_requires_reverification`, `test_secrets_redacted`: assert exact IDs above, invalid configs cannot submit, and known test secret never appears in serialized config.
- [ ] Run `uv run pytest tests/test_config.py -q`; confirm expected failures before implementation.
- [ ] Pin dependencies/compiler; verify actual six-chain Aave/venue/token registries from official sources and RPC checks. Record compatible V2/V3 router variants; do not manufacture missing addresses.
- [ ] Implement config validation and chain checks; rerun tests and dependency/build checks; commit.

### Task 2 — Flash-loan executor and exchange adapters

**Files:** executor/adapters above, Solidity interfaces/types, `contracts/test/Executor.t.sol`, `contracts/test/ExecutorInvariant.t.sol`.

**Interfaces:** `execute(bytes32 intentId, address asset, uint256 amount, Hop[] route, uint256 minProfitToken, uint256 deadline)` callable only by operator; Aave `executeOperation(address,uint256,uint256,address,bytes) returns (bool)`. Define and publish the ABI-encoded Hop struct before implementing Python encoding. Adapters expose typed exact-input swap functions; no generic target/calldata field.

- [ ] Tests `testRepaysAndPaysOnlyIncrementalProfit`, `testExistingBalanceCannotSubsidizeLoss`, `testRejectsForgedCallback`, `testRejectsWrongInitiator`, `testRejectsReplayAndReentrancy`, `testRejectsUnknownRouter`, `testOperatorCannotChangeRecipient`, `testPayoutFailureReverts`, `testPauseAndDeadline`: assert balances, fees, roles and revert reasons.
- [ ] Run `forge test --root contracts`; observe failures, then implement the repayment/payout invariant and typed router variants.
- [ ] Add fuzz tests over amounts/premiums/start balances: no successful execution reduces starting treasury; repayment obligation remains reserved; unauthorized calls never move funds.
- [ ] Run unit/fuzz/invariant suite; publish compiler/ABI artifact checks and commit.

### Task 3 — Market data, discovery and quotes

**Files:** market modules, `tests/test_market.py`.

**Interfaces:** `async discover_pools(config: ChainConfig) -> list[Pool]`; `async quote_route(route: Route, amount: int, block: int) -> Quote`.

- [ ] Tests `test_quotes_share_block`, `test_stale_head_rejected`, `test_rate_limit_backoff_bounded`, `test_decimal_units_preserved`, `test_event_gap_backfill`, `test_rpc_failover_checks_chain`: no mixed-block routes, bounded requests, exact token units.
- [ ] Run `uv run pytest tests/test_market.py -q`; implement subscriptions/reconnect, allowlisted bounded pool discovery and V2/V3 quote ABI support; rerun and commit.

### Task 4 — Routes, sizing and economics

**Files:** strategy modules, `tests/test_strategy.py`.

**Interfaces:** `find_cycles(pools: list[Pool], max_hops: int = 3) -> list[Route]`; `async optimize_size(route: Route, limits: SizeLimits, block: int) -> SizedQuote`; `evaluate_profit(quote: Quote, premium: int, fees: FeeEstimate, conversion: PricePoint, policy: ProfitPolicy) -> ProfitDecision`.

- [ ] Tests `test_only_two_or_three_hop_closed_cycles`, `test_size_within_liquidity_limit`, `test_fees_not_double_counted`, `test_stale_conversion_blocks_trade`, `test_min_profit_covers_gas_and_margin`: use integer quote surplus 100, premium 10, gas-equivalent 20 and buffer 5; net 65 before configured additional net margin.
- [ ] Run `uv run pytest tests/test_strategy.py -q`; implement bounded search and conservative decisions, reject unsupported token behavior, rerun and commit.

### Task 5 — Full-call simulation, fee models and budgets

**Files:** simulation/fees/budget modules, `tests/test_simulation.py`, `tests/test_budget.py`.

**Interfaces:** `async simulate(intent: Intent) -> SimulationResult`; `async estimate_fees(intent: Intent) -> FeeEstimate`; `reserve_budget(intent_id: str, chain_id: int, max_cost: Decimal) -> Reservation`; `settle_budget(reservation_id: str, actual_cost: Decimal) -> None`.

- [ ] Tests `test_simulates_exact_sender_and_payload`, `test_revert_prevents_submission`, `test_arbitrum_cost_not_double_counted`, `test_op_base_data_fee_included`, `test_missing_fee_bound_blocks_live`.
- [ ] Budget tests: daily cap $1, unresolved reservation $0.70; attempting $0.40 is rejected. Failed receipt $0.20 remains spent. Midnight does not erase unresolved liability. Replacement releases no reservation until canonical settlement.
- [ ] Run `uv run pytest tests/test_simulation.py tests/test_budget.py -q`; implement complete fee estimates, transactions/locks and conservative reservation, rerun and commit.

### Task 6 — Signing, submission and crash-safe recovery

**Files:** signer/transactions modules, `tests/test_transactions.py`, `tests/test_signer.py`.

**Interfaces:** `Signer.sign(intent: Intent, fees: FeeEstimate) -> SignedEnvelope`; `async submit(intent: Intent) -> Submission`; `async recover_pending(chain_id: int, operator: str) -> RecoveryReport`.

- [ ] Tests `test_intent_persisted_before_broadcast`, `test_ambiguous_timeout_reuses_hash`, `test_restart_does_not_duplicate_nonce`, `test_replacement_same_nonce_budgeted`, `test_no_private_fallback`, `test_keystore_requires_unlock`, `test_secret_not_in_logs`.
- [ ] Run `uv run pytest tests/test_transactions.py tests/test_signer.py -q`; implement encrypted keystore signing, deterministic hash persistence, public/private capability policy and bounded replacement; rerun and commit.

### Task 7 — Receipt reconciliation and trustworthy accounting

**Files:** storage modules/migrations, `tests/test_ledger.py`, `tests/test_reconcile.py`.

**Interfaces:** `reconcile_receipt(receipt: ReceiptRecord) -> LedgerUpdate`; `async reconcile_chain(chain_id: int) -> ReconciliationReport`; `export_report(period: ReportPeriod, format: Literal['csv','json']) -> Path`.

- [ ] Tests `test_failed_gas_reduces_net`, `test_receipt_event_recipient_matches_config`, `test_duplicate_receipt_idempotent`, `test_reorg_rolls_back_provisional_profit`, `test_native_and_token_units_separate`, `test_backup_restore_pending_intents`.
- [ ] Run `uv run pytest tests/test_ledger.py tests/test_reconcile.py -q`; implement canonical confirmation/reorg handling, durable records, timestamped valuation, backup/restore and exports; rerun and commit.

### Task 8 — Worker lifecycle and command interface

**Files:** worker/cli modules, `tests/test_worker.py`.

**Interfaces:** `async run_worker(config: AppConfig, mode: RunMode) -> None`; CLI commands `flasharb doctor`, `observe`, `simulate`, `run`, `pause`, `status`, `report`, `backup`.

- [ ] Tests `test_sleep_gap_forces_requote`, `test_restart_requires_live_action`, `test_pause_keeps_reconciliation`, `test_one_chain_failure_isolated`, `test_low_balance_stops_submission`, `test_shutdown_persists_state`.
- [ ] Run `uv run pytest tests/test_worker.py -q`; implement independent chain workers, RPC usage bounds and signal/recovery behavior; rerun and commit.

### Task 9 — Complete local dashboard

**Files:** web routes/auth/templates/static, `tests/test_web.py`.

**Interfaces:** local authenticated pages `/`, `/networks`, `/opportunities`, `/transactions`, `/reports`, `/settings`; mutating `/control/*` routes require session and CSRF checks. Dashboard controls call the same worker/policy interfaces as CLI.

- [ ] Tests `test_unauthenticated_control_denied`, `test_csrf_rejected`, `test_settings_cannot_expose_secrets`, `test_operator_cannot_change_owner_settings`, `test_estimated_and_realized_profit_distinct`, `test_all_six_networks_visible`.
- [ ] Run `uv run pytest tests/test_web.py -q`; implement accessible mobile-friendly views and validated controls; rerun and manually check mobile/desktop, then commit.

### Task 10 — Deployment, cost report and reproducible packaging

**Files:** deployment/fee/verification scripts, Dockerfile/Compose, local launch scripts, `tests/test_deployment.py`, `docs/OPERATIONS.md`, `docs/SECURITY.md`.

**Interfaces:** CLI `flasharb deploy-plan --chain <id>`, `flasharb estimate-cost --chain <id>`, `flasharb verify-deployment --chain <id>`. Deployment plan includes compiler/revision, bytecode hash, chain, owner/operator/recipient and unsigned transactions; applying it is a separate explicit action.

- [ ] Tests `test_plan_does_not_broadcast`, `test_wrong_chain_or_bytecode_rejected`, `test_cost_report_has_all_fee_components`, `test_no_funding_assumption`, `test_clean_install_loads_six_network_configs`.
- [ ] Run `uv run pytest tests/test_deployment.py -q`; implement scripts and local Linux/WSL instructions with Windows host sleep notes; verify clean install and container build; commit.

### Task 11 — Six-network end-to-end verification and security checks

**Files:** `tests/forks/`, chain-specific Foundry fork tests, `.github/workflows/ci.yml`, evidence reports.

**Interfaces:** per-chain report records pinned block, RPC capability, real provider/router addresses, ordinary/injected state, transaction simulation, repayment, recipient payout and rejected loss case.

- [ ] Implement and run complete executor+Python integration on each of the six pinned forks; observe/simulate paths do not broadcast real transactions.
- [ ] Verify profitable controlled route and unprofitable revert on every chain; disclose all synthetic market changes. Missing RPC access is blocked evidence, not a passing test.
- [ ] Run `uv run pytest tests -q`, `forge test --root contracts`, Python lint/type checks and Solidity static analysis. Capture command outcomes without secrets; CI runs deterministic checks and optionally configured fork suites.
- [ ] Review authentication, allowances, callback state, token quirks, fee bounds and nonce recovery; close critical/high findings; commit evidence and remaining limitations.

### Task 12 — Handover, deployment and ongoing operation

**Files:** `docs/HANDOVER.md`, release readiness reports, updated checklist.

- [ ] Demonstrate one complete local installation: unlock signer, observe, simulate, view/export results, stop, restart and recover pending state.
- [ ] Publish source/dependency/test evidence and six-network readiness status; label operational blockers precisely.
- [ ] At deployment time measure fees and funding-route charges; approve network-specific budgets/recipients locally. No real funds or signing secrets are needed for this planning deliverable.
- [ ] Operator deploys/configures each funded chain, verifies bytecode/roles, and explicitly enables live; begin with Arbitrum for the personal low-cost setup if measured costs fit.
- [ ] Reconcile the first real receipts, verify payout, test emergency pause and establish backups. Increase networks/spending only by explicit settings changes supported by recorded net results.
- [ ] Tag release only after its completion criteria pass. Final source and operational instructions remain available for separate personal/company installations.

## 12. Evidence and definition of done

Every checked task references a commit and test/report path. Readiness reports use `PASS`, `BLOCKED` or `FAIL`, never infer a pass from absence of an error. Software completion and funded live deployment are separate states.

The release is feature-complete only when Tasks 1–11 pass on all six chains and Task 12 local handover is demonstrated. Production running status additionally requires mainnet deployment verification, funding, explicit live enablement and reconciled receipts for each enabled network. Natural profitable opportunities and monthly earnings are measured outcomes, not prerequisites that can be manufactured by test fixtures.

## Official references to recheck during implementation

- Aave flash loans: https://aave.com/docs/aave-v3/guides/flash-loans
- Aave Pool API: https://aave.com/docs/aave-v3/smart-contracts/pool
- Aave registry: https://github.com/aave-dao/aave-address-book
- Uniswap deployments: https://developers.uniswap.org/docs/protocols/v3/deployments
- Arbitrum complete gas estimation: https://docs.arbitrum.io/build-decentralized-apps/troubleshooting-building
- Ethereum gas and failed transactions: https://ethereum.org/developers/docs/gas/
- MEV competition: https://ethereum.org/developers/docs/mev/
- Alchemy usage/pricing: https://www.alchemy.com/pricing

These sources support the design direction. Exact integrations, fees and compatibility are implementation/deployment verification requirements, not facts established by this planning document.
