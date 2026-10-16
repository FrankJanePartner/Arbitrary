# Office desktop setup

This setup runs locally while the computer and bot process are running. It does not require a paid VPS or domain. Gas, RPC usage and any future hosting costs must be estimated before funded deployment; the earlier $20 figure is not a confirmed requirement.

## Install

Use Linux or a Linux environment in Windows WSL, with Git, Python 3.12+, uv and Node/npm installed. In that environment:

```sh
git clone https://github.com/FrankJanePartner/Arbitrary.git
cd Arbitrary
cp .env.example .env
uv sync --locked
npm ci
npm run contracts:build
```

Edit `.env` locally. The three payment roles are:

| Setting | Purpose |
| --- | --- |
| `ARBITRARY_PROFIT_WALLET` | Customer's profit destination |
| `ARBITRARY_GAS_WALLET` | Operator/signing wallet; fund native gas on the chosen chain |
| `ARBITRARY_MERCHANT_WALLET` | Merchant's profit-share destination |
| `ARBITRARY_MERCHANT_FEE_BPS=500` | Selected 5% merchant fee |

Also fill `ARBITRARY_OWNER_WALLET`, the public administrative owner address. It is not another revenue destination. Fill the RPC endpoint for each intended network. Global wallet addresses apply across networks; optional chain-ID suffixes override individual networks in the same file. Fill each `ARBITRARY_EXECUTOR_<chain ID>` only after that chain's contract deployment.

The fee is 5% of trading surplus after repaying the loan and premium, before native gas costs. Baseline routes pay customer and merchant in USDC. The gas wallet requires the selected chain's native currency. All addresses must be checked for the intended chain.

One `.env` holds these settings. Keep it private because RPC URLs can contain credentials; never commit it. No private keys, seed phrases or keystore passwords belong there. Signing uses an encrypted local keystore and an explicit CLI unlock. This file does not replace the database, keystore or network policy configuration.

Existing process environment variables take precedence over `.env`; environment wallet settings override YAML wallet settings. Restart after editing. Merchant address and fee are immutable in each deployed contract: changing `.env` afterward cannot change its terms, and mismatches block verification.

## Open locally

```sh
uv run flasharb init
uv run flasharb serve
```

Choose the local dashboard password at the prompt and open http://127.0.0.1:8000 on this computer. All networks initially remain disabled, and the app starts in observe mode. Follow [local operations](LOCAL_OPERATIONS.md) for enabling observation and controls.

With public addresses filled, `uv run flasharb deploy-plan 42161` generates an unsigned Arbitrum deployment plan. It does not deploy or spend funds. Inspect the plan before any later funded action.

Shutting down or sleeping the computer stops scanning and new submissions. Already-broadcast transactions can still finish on-chain. Restart the process after turning the computer back on; pending transactions must reconcile. Startup does not automatically unlock signing or enable live trading.

## Before funded operation

The remaining gates in [build status](BUILD_STATUS.md) still apply, including full Python-worker real-protocol fork acceptance. Base and OP live execution remain blocked by the fee-ceiling requirement. This desktop configuration change does not certify production readiness or demonstrate profitable trading. No code has been installed on the office computer by this repository update.

## Windows-clone registry digest error

A Windows Git checkout can convert LF to CRLF and change registry file hashes. The repository now pins registry files to LF using `.gitattributes`. For an existing checkout, pull the update and run inside Ubuntu:

```sh
git pull --ff-only
python3 scripts/repair-registry-line-endings.py
uv run flasharb init
```

The repair verifies all six files against the existing digest manifest before writing any changes. It only normalizes CRLF when doing so reproduces the exact expected bytes. It refuses other content differences and never regenerates hashes or bypasses verification.
