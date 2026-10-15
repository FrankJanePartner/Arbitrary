# Security and review record — 15 October 2026

No independent professional security audit or production approval is claimed. Default operation remains observe-only; deployment and live activation are explicit local actions.

## Reviewed boundaries

The executor admits only its configured Aave Pool callback, matching initiator and active context. The callback is consumed before external swaps; execute and configuration mutations require idle state. Routers/tokens are allowlisted, inputs use exact temporary allowances, and actual balance deltas determine outputs. Existing treasury cannot subsidize a trade. Customer minimum profit is enforced after the immutable merchant deduction. Either failed payout reverts repayment and swaps atomically.

A fresh-context AI code review found recovery, pre-sign control timing, external nonce, history polling, dashboard-worker and deployment-resume issues. Fixes added explicit recovery/cancellation, a final signing guard, pending/latest nonce matching, bounded history audits, dashboard-only mode and resumable plan records. Regression tests cover these changes. A separate review of the new merchant feature found no concrete Important defect; this is scoped review evidence, not an audit.

## Slither 0.11.3

Run from `contracts/` with the local Forge binary on PATH. The 15 October run completed: 13 findings, zero High, four Medium, eight Low and one Informational. Detector summaries are preserved in `evidence/static-analysis.json`.

- Medium `reentrancy-no-eth`, Low `reentrancy-benign/events`: state cleanup/events follow external calls by design. The custom phase/context checks prevent entering another execution or accepting another callback. Local router-reentry, forged-callback, replay and payout-failure tests pass. Accepted by inspection with those tests; no claim that automated detection alone proves safety.
- Three Medium `unused-return`: router-reported outputs are deliberately ignored; executor checks actual token balance deltas and exact input consumption. This avoids trusting a return value as evidence of funds received.
- Four Low `calls-loop`: route length is contract-limited to two or three hops and tokens/routers are allowlisted. External calls are necessary for swaps and balance checks.
- Two Low `timestamp`: deadlines use chain time deliberately. They are not randomness or price evidence.
- Informational `POOL` naming: immutable protocol identity uses uppercase naming.

## Remaining release limits

Base and OP Mainnet live signing/deployment/recovery remain blocked because the buffered L1/operator fee estimate does not provide the hard spending bound required by the specification. No switch silently bypasses that limit. All networks still require the full Python-worker-on-fork acceptance gate; successful Solidity protocol forks alone do not generate a live authorization file.

Finalized history audits run five records per chain per hour; deep-reorg detection is delayed accordingly. Pending records are reconciled first on every tick. Operators should use dedicated signing wallets; unknown external pending nonces block new trades. RPC credentials stay local; reports exclude signed raw transactions. Local SQLite data includes signed envelopes and must remain private.

The source is available to its recipient: merchant fees cannot prevent someone from modifying the source and deploying another contract. There is no licence-server, cloud multi-tenant isolation or custodian service in this codebase.
