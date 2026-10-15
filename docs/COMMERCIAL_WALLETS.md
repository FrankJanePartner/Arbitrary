# Commercial wallet model

Every deployed executor has three payment destinations/roles. Addresses are configured per network. The selected merchant fee is 5% (500 basis points). Public addresses will be supplied in one local `.env` file during desktop setup.

| Role | What it receives / does | Currency |
|---|---|---|
| Customer profit recipient | Receives trading surplus after loan premium and merchant deduction | Borrowed token; baseline routes borrow USDC |
| Gas/operator wallet | Customer funds this address; its locally unlocked key signs trades and pays network costs | ETH on Ethereum/Arbitrum/Base/OP; POL on Polygon; AVAX on Avalanche |
| Merchant wallet | Receives the disclosed percentage of successful trading surplus | Same borrowed token as the customer payout |

The owner is a separate administrative role, not a fourth revenue destination. The operator key is needed locally; recipient and merchant private keys are never needed. Gas money goes to the operator address, not into the executor, merchant address or an invented internal wallet. Each network requires its own native gas balance, even when the hexadecimal operator address is identical.

## Fee definition

`gross surplus = swap proceeds - flash-loan principal - flash-loan premium`.
`merchant amount = floor(gross surplus × merchant_fee_bps / 10,000)`.
`customer proceeds = gross surplus - merchant amount`.

The fee is not charged on the loan principal. Example only: 10 USDC surplus with a configured 500 bps (5%) fee pays 0.50 USDC to the merchant and 9.50 USDC to the customer. Gas is paid separately by the operator. Failed/reverted transactions pay neither customer nor merchant, but can still consume gas.

This is a share of on-chain trading surplus **before gas**, not a guaranteed percentage of final net earnings. The bot's eligibility calculation subtracts merchant fees, conservative gas estimates and its safety buffer before accepting a trade. The contract enforces the minimum customer payout after the merchant fee. The accounting report separates customer proceeds, merchant fees and gas.

## Configuration and disclosure

The fee defaults to the selected 5%. The contract permits 0–1,000 basis points (0–10%). This maximum is an implementation safeguard, not a recommended commercial rate. Confirm the selected rate and merchant public address before deployment. They are immutable for that deployment; changing them requires a new disclosed deployment. Owner/recipient updates cannot silently change the merchant rate.

`uv run flasharb deploy-plan --help` exposes `--merchant` and `--merchant-fee-bps`. Generated plans show all roles and the fee before signing. Runtime `.env` settings (or `config/app.yaml` network overrides) must match the deployed merchant address and rate; deployment verification blocks mismatches. The dashboard displays the three addresses and merchant percentage. Never type seed phrases or private keys into a dashboard or send them in chat.

A customer with the complete source can fork it and deploy different code. This repository does not implement licence keys, subscriptions, anti-copy controls or centralized custody. Each commercial installation uses separate keys, budgets, database and recipient configuration. A full SaaS/multi-tenant service is outside this local-bot architecture.

The new six-argument constructor is incompatible with earlier deployment plans. Regenerate plans and deploy the new contract; old contracts cannot gain merchant splitting through a configuration toggle.
