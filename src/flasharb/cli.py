"""Explicit local controls. Nothing broadcasts unless run --live or apply-plan is invoked."""

import asyncio
import getpass
import json
import signal
from pathlib import Path
from decimal import Decimal
import typer
from .config import load_config, verify_chain
from .storage.db import Store
from .storage.ledger import summary, export_report
from .market.rpc import RpcError, from_config
from .execution.signer import Signer
from .execution.fees import estimate_fees
from .deployment import deploy_plan as make_plan, configuration_plan, verify_deployment as verify
from .models import Policy
from .worker import Worker, validate_live_policy

app = typer.Typer(no_args_is_help=True, help="Arbitrary · local flash-loan arbitrage controls")
DEFAULT = Path("config/app.yaml")


def context(config):
    c = load_config(config)
    return c, Store(Path(c.data_dir) / "arbitrary.db")


def selected(c, chain):
    try:
        return next(x for x in c.chains if x.chain_id == chain)
    except StopIteration:
        raise typer.BadParameter("Unknown chain ID") from None


def output(value):
    typer.echo(json.dumps(value, indent=2, default=str))


@app.command("init")
def initialize(config: Path = DEFAULT):
    """Set a local dashboard password; creates no wallet."""
    from .web.auth import password_hash

    c = load_config(config)
    d = Path(c.data_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "auth.json"
    if p.exists():
        raise typer.BadParameter("Dashboard already initialized; use reset-password")
    pw = getpass.getpass("Dashboard password (12+ characters): ")
    if pw != getpass.getpass("Confirm password: "):
        raise typer.BadParameter("Passwords differ")
    p.write_text(json.dumps({"password_hash": password_hash(pw)}))
    p.chmod(0o600)
    typer.echo("Dashboard initialized. Run flasharb serve.")


@app.command("reset-password")
def reset_password(config: Path = DEFAULT):
    from .web.auth import password_hash

    c = load_config(config)
    p = Path(c.data_dir) / "auth.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    pw = getpass.getpass("New dashboard password: ")
    if pw != getpass.getpass("Confirm: "):
        raise typer.BadParameter("Passwords differ")
    p.write_text(json.dumps({"password_hash": password_hash(pw)}))
    p.chmod(0o600)
    typer.echo("Password updated. Restart dashboard to invalidate sessions.")


@app.command()
def doctor(config: Path = DEFAULT, chain: int | None = None, out: Path | None = None):
    """Verify configured RPC chain IDs, registry contracts and token interfaces."""
    c = load_config(config)

    async def work():
        result = []
        for ch in c.chains:
            if chain is not None and ch.chain_id != chain:
                continue
            rpc = None
            try:
                rpc = from_config(ch, c)
                r = await verify_chain(ch, rpc)
                result.append(r.model_dump() | {"status": "PASS" if r.ok else "BLOCKED"})
            except Exception as e:
                result.append(
                    {
                        "chain_id": ch.chain_id,
                        "status": "BLOCKED",
                        "reason": str(e)
                        if isinstance(e, (ValueError, RpcError))
                        else type(e).__name__,
                    }
                )
            finally:
                if rpc:
                    await rpc.close()
        return result

    result = asyncio.run(work())
    output(result)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2))


@app.command()
def status(config: Path = DEFAULT):
    c, s = context(config)
    output(
        {
            "mode": s.get_state("mode", "observe"),
            "paused": s.get_state("paused", False),
            "summary": summary(s),
            "networks": {
                x.chain_id: s.get_state("health:" + str(x.chain_id), {"status": "not connected"})
                for x in c.chains
            },
        }
    )
    s.close()


@app.command()
def enable(chain: int, config: Path = DEFAULT, disable: bool = False):
    c, s = context(config)
    selected(c, chain)
    s.set_state("enabled:" + str(chain), not disable)
    s.close()
    typer.echo("Network setting saved.")


@app.command()
def pause(config: Path = DEFAULT):
    c, s = context(config)
    s.set_state("paused", True)
    s.close()
    typer.echo("New trading paused; reconciliation remains active.")


@app.command()
def resume(config: Path = DEFAULT):
    c, s = context(config)
    s.set_state("paused", False)
    s.close()
    typer.echo("Scanning resumed.")


def run_mode(config, mode, once, keystore=None):
    c, s = context(config)
    signer = None
    if mode == "live":
        if keystore is None:
            s.close()
            raise typer.BadParameter("--keystore required for live")
        chains = [
            chain
            for chain in c.chains
            if s.get_state("enabled:" + str(chain.chain_id), chain.enabled)
        ]
        if not chains:
            s.close()
            raise typer.BadParameter("Enable at least one network before starting live mode")
        policy = Policy(**s.get_state("policy", c.policy.model_dump(mode="json")))
        try:
            validate_live_policy(policy)
        except ValueError as error:
            s.close()
            raise typer.BadParameter(str(error)) from None
        network_names = ", ".join(f"{chain.name} ({chain.chain_id})" for chain in chains)
        duration = "one live scan" if once else "continuous LIVE trading"
        if not typer.confirm(
            f"Start {duration} on {network_names}? Gas cap: up to "
            f"${policy.max_tx_usd} per transaction, ${policy.daily_usd} per network per day, "
            f"and ${policy.global_daily_usd} across all networks per day. Failed or reverted "
            "transactions still spend gas.",
            default=False,
        ):
            s.close()
            raise typer.Abort()
        signer = Signer.unlock(keystore, getpass.getpass("Operator keystore password: "))
    w = Worker(c, s, signer, mode)

    async def main():
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, w.stop.set)
            except NotImplementedError:
                pass
        await w.run(once)

    try:
        asyncio.run(main())
    finally:
        s.close()


@app.command()
def observe(config: Path = DEFAULT, once: bool = False):
    """Read prices without signing or submitting transactions."""
    run_mode(config, "observe", once)


@app.command()
def simulate(config: Path = DEFAULT, once: bool = False):
    """Simulate routes through a configured deployed executor; never broadcast."""
    run_mode(config, "simulate", once)


@app.command()
def run(
    config: Path = DEFAULT, live: bool = False, once: bool = False, keystore: Path | None = None
):
    """Run observer or explicitly unlocked live worker."""
    run_mode(config, "live" if live else "observe", once, keystore)


@app.command()
def serve(config: Path = DEFAULT, port: int = 8000, dashboard_only: bool = False):
    """Start authenticated loopback dashboard and observe-mode worker."""
    import uvicorn
    from .web.app import create_app

    c, s = context(config)
    p = Path(c.data_dir) / "auth.json"
    if not p.exists():
        raise typer.BadParameter("Run flasharb init first")
    uvicorn.run(
        create_app(
            c, s, json.loads(p.read_text())["password_hash"], launch_worker=not dashboard_only
        ),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )


@app.command()
def report(out: Path = Path("data/report.json"), format: str = "json", config: Path = DEFAULT):
    c, s = context(config)
    typer.echo(str(export_report(s, out, format)))
    s.close()


@app.command()
def backup(out: Path, config: Path = DEFAULT):
    c, s = context(config)
    out.parent.mkdir(parents=True, exist_ok=True)
    s.backup(out)
    s.close()
    typer.echo(str(out))


@app.command("deploy-plan")
def deployment_plan(
    chain: int,
    owner: str | None = None,
    operator: str | None = None,
    recipient: str | None = None,
    merchant: str | None = None,
    merchant_fee_bps: int | None = None,
    out: Path = Path("data/deploy-plan.json"),
    config: Path = DEFAULT,
):
    c = load_config(config)
    ch = selected(c, chain)
    owner, operator, recipient = (
        owner or ch.owner,
        operator or ch.operator,
        recipient or ch.recipient,
    )
    if not all([owner, operator, recipient]):
        raise typer.BadParameter(
            "Set OWNER, GAS and PROFIT wallet addresses in .env or pass explicit options"
        )
    p = make_plan(ch, owner, operator, recipient, merchant, merchant_fee_bps)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(p, indent=2))
    output(p)


@app.command("deploy-plans")
def deployment_plans(
    owner: str | None = None,
    operator: str | None = None,
    recipient: str | None = None,
    merchant: str | None = None,
    merchant_fee_bps: int | None = None,
    out_dir: Path = Path("data/deploy-plans"),
    config: Path = DEFAULT,
):
    """Create unsigned deployment plans for every configured network."""
    c = load_config(config)
    plans = []
    missing = []
    for ch in c.chains:
        roles = (
            owner or ch.owner,
            operator or ch.operator,
            recipient or ch.recipient,
        )
        if not all(roles):
            missing.append(ch.chain_id)
            continue
        try:
            p = make_plan(
                ch,
                *roles,
                merchant or ch.merchant,
                ch.merchant_fee_bps if merchant_fee_bps is None else merchant_fee_bps,
            )
        except ValueError as error:
            raise typer.BadParameter(f"Chain {ch.chain_id}: {error}") from None
        path = out_dir / f"deploy-plan-{ch.chain_id}.json"
        plans.append(
            {
                "chain_id": ch.chain_id,
                "network": ch.name,
                "native_symbol": ch.native_symbol,
                "plan": str(path),
                "owner": p["owner"],
                "operator": p["operator"],
                "recipient": p["recipient"],
                "merchant": p["merchant"],
                "merchant_fee_bps": p["merchant_fee_bps"],
                "broadcast": False,
                "fee_estimate_status": (
                    "not_supported_for_funded_deployment"
                    if ch.fee_model == "op"
                    else "estimate_required"
                ),
            }
        )
    if missing:
        raise typer.BadParameter(
            "Missing owner/operator/profit wallet addresses for chain IDs: "
            + ", ".join(map(str, missing))
        )
    for entry, ch in zip(plans, c.chains):
        p = make_plan(
            ch,
            entry["owner"],
            entry["operator"],
            entry["recipient"],
            entry["merchant"],
            entry["merchant_fee_bps"],
        )
        path = Path(entry["plan"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(p, indent=2))
    output(
        {
            "broadcast": False,
            "plans": plans,
            "warning": (
                "Plans are unsigned and do not include configuration transactions. "
                "Base and OP Mainnet remain blocked for funded deployment."
            ),
        }
    )


@app.command("configure-plan")
def configure_plan(
    chain: int, out: Path = Path("data/configure-plan.json"), config: Path = DEFAULT
):
    c = load_config(config)
    ch = selected(c, chain)
    p = {
        "chain_id": chain,
        "kind": "configure",
        "registry_digest": ch.registry_digest,
        "transactions": configuration_plan(ch),
        "broadcast": False,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(p, indent=2))
    output(p)


@app.command("estimate-cost")
def estimate_cost(plan: Path, config: Path = DEFAULT):
    c = load_config(config)
    p = json.loads(plan.read_text())
    ch = selected(c, p["chain_id"])

    async def work():
        rpc = from_config(ch, c)
        try:
            await rpc.check_chain()
            txs = p.get("transactions", [p.get("transaction")])
            results = []
            for tx in txs:
                fee = await estimate_fees(tx, ch, rpc)
                results.append(fee.model_dump())
            return {
                "chain_id": ch.chain_id,
                "native_symbol": ch.native_symbol,
                "transactions": results,
                "estimated_reserve_native": str(
                    Decimal(sum(r["max_native_cost"] for r in results)) / 10**18
                ),
                "warning": "OP L1/operator fees are buffered estimates, not hard caps. Re-estimate immediately before sending.",
            }
        finally:
            await rpc.close()

    output(asyncio.run(work()))


@app.command("estimate-plans")
def estimate_plans(plans_dir: Path = Path("data/deploy-plans"), config: Path = DEFAULT):
    """Estimate unsigned deployment plans for all chains in a plan directory."""
    c = load_config(config)
    files = sorted(plans_dir.glob("deploy-plan-*.json"))
    if not files:
        raise typer.BadParameter(f"No deploy-plan-*.json files in {plans_dir}")

    async def work():
        results = []
        for path in files:
            rpc = None
            try:
                p = json.loads(path.read_text())
                ch = selected(c, p["chain_id"])
                if (
                    p.get("broadcast") is not False
                    or p.get("registry_digest") != ch.registry_digest
                ):
                    raise ValueError("unsigned plan or registry digest mismatch")
                rpc = from_config(ch, c)
                await rpc.check_chain()
                fee = await estimate_fees(p["transaction"], ch, rpc)
                results.append(
                    {
                        "chain_id": ch.chain_id,
                        "network": ch.name,
                        "status": "ESTIMATE_ONLY",
                        "native_symbol": ch.native_symbol,
                        "max_native_cost": str(Decimal(fee.max_native_cost) / 10**18),
                        "includes_configuration": False,
                        "funded_deployment_supported_by_fee_model": ch.fee_model != "op",
                        "fee_components": fee.components,
                        "warning": (
                            "L1/operator components are estimates, not a hard spending cap"
                            if ch.fee_model == "op"
                            else "Snapshot estimate only; recheck before signing"
                        ),
                    }
                )
            except Exception as error:
                results.append(
                    {
                        "plan": str(path),
                        "status": "BLOCKED",
                        "reason": type(error).__name__,
                    }
                )
            finally:
                if rpc:
                    await rpc.close()
        return {
            "broadcast": False,
            "results": results,
            "warning": (
                "These estimates cover contract creation only. They exclude token/router setup, "
                "live trading, and any future exchange integrations."
            ),
        }

    output(asyncio.run(work()))


@app.command("verify-deployment")
def verify_contract(chain: int, config: Path = DEFAULT):
    c = load_config(config)
    ch = selected(c, chain)

    async def work():
        rpc = from_config(ch, c)
        try:
            return await verify(ch, rpc)
        finally:
            await rpc.close()

    output(asyncio.run(work()))


@app.command("apply-plan")
def apply_plan(plan: Path, keystore: Path, max_cost_native: str, config: Path = DEFAULT):
    """Explicitly sign and broadcast a reviewed deployment/configuration plan."""
    c, s = context(config)
    p = json.loads(plan.read_text())
    ch = selected(c, p["chain_id"])
    if p["registry_digest"] != ch.registry_digest:
        raise typer.BadParameter("Registry changed; regenerate plan")
    if p.get("kind") == "configure":
        expected = configuration_plan(ch)
        if p["transactions"] != expected:
            raise typer.BadParameter("Configuration plan mismatch")
        txs = expected
    else:
        expected = make_plan(
            ch, p["owner"], p["operator"], p["recipient"], p["merchant"], p["merchant_fee_bps"]
        )
        if p != expected:
            raise typer.BadParameter("Deployment plan differs from compiled artifact/config")
        txs = [p["transaction"]]
    cap = int(Decimal(max_cost_native) * 10**18)
    if cap <= 0:
        raise typer.BadParameter("Positive native fee cap required")
    signer = Signer.unlock(keystore, getpass.getpass("Owner keystore password: "))
    if any(t["from"].lower() != signer.address.lower() for t in txs):
        raise typer.BadParameter("Owner signer mismatch")
    if not typer.confirm(
        f"Broadcast {len(txs)} transaction(s) on {ch.name} with total estimated reserve <= {max_cost_native} {ch.native_symbol}?"
    ):
        raise typer.Abort()

    async def work():
        from .deployment_runner import apply_transactions

        rpc = from_config(ch, c, s)
        try:
            return await apply_transactions(p, txs, ch, rpc, signer, s, cap)
        finally:
            await rpc.close()

    from .runtime import WorkerLock

    try:
        with WorkerLock(s.path.resolve().with_suffix(".worker.lock")):
            output(asyncio.run(work()))
    finally:
        s.close()


@app.command("recover")
def recover_transaction(
    intent_id: str, config: Path = DEFAULT, cancel: bool = False, keystore: Path | None = None
):
    """Reconcile then rebroadcast exact signed bytes, or explicitly cancel a stuck nonce."""
    from .runtime import WorkerLock
    from .execution.transactions import TransactionManager
    from .storage.reconcile import reconcile_chain
    from .models import Policy
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import os

    c, s = context(config)

    async def work():
        row = s.execution(intent_id)
        if row is None:
            raise typer.BadParameter("Unknown intent")
        ch = selected(c, row["chain_id"])
        if ch.fee_model == "op":
            raise typer.BadParameter("OP-stack recovery awaits fee ceiling certification")
        rpc = from_config(ch, c, s)
        private = None
        try:
            head = await rpc.head(ch.max_head_age)
            await reconcile_chain(s, ch, rpc, int(head["number"], 16), c.timezone)
            row = s.execution(intent_id)
            if row["status"] in ("confirmed", "failed", "cancelled", "provisional"):
                return {"status": row["status"], "broadcast": False}
            if ch.submission == "private":
                from .market.rpc import RpcClient

                url = os.environ.get(ch.private_rpc_env or "")
                if not url:
                    raise ValueError("Private endpoint missing; no fallback")
                private = RpcClient(url, ch.chain_id, c.rpc_rps, c.rpc_daily_calls, store=s)
                await private.check_chain()
            signer = None
            if cancel:
                if not keystore:
                    raise typer.BadParameter("Cancellation requires --keystore")
                signer = Signer.unlock(keystore, getpass.getpass("Operator keystore password: "))
            manager = TransactionManager(s, rpc, signer, ch.chain_id, private)
            if not cancel:
                return (await manager.recover(intent_id)).model_dump()
            policy = Policy(**s.get_state("policy", c.policy.model_dump(mode="json")))
            old = json.loads(row["payload"])
            tx = {"from": signer.address, "to": signer.address, "value": "0x0", "data": "0x"}
            fees = await estimate_fees(tx, ch, rpc)
            maximum = max(fees.max_fee_per_gas, old["maxFeePerGas"] * 110 // 100 + 1)
            priority = max(fees.priority_fee, old["maxPriorityFeePerGas"] * 110 // 100 + 1)
            maximum = max(maximum, priority)
            meta = json.loads(row["metadata"])
            cost = Decimal(fees.gas_limit * maximum) * Decimal(meta["native_usd"]) / 10**18
            if cost > policy.max_tx_usd:
                raise ValueError("Cancellation exceeds transaction budget")
            payload = {
                "to": signer.address,
                "value": 0,
                "data": "0x",
                "chainId": ch.chain_id,
                "nonce": row["nonce"],
                "type": 2,
                "gas": fees.gas_limit,
                "maxFeePerGas": maximum,
                "maxPriorityFeePerGas": priority,
            }
            day = datetime.now(ZoneInfo(c.timezone)).date().isoformat()
            return (
                await manager.replace(
                    intent_id,
                    payload,
                    cost,
                    policy.daily_usd,
                    policy.global_daily_usd,
                    day,
                    kind="cancel",
                )
            ).model_dump()
        finally:
            await rpc.close()
            if private:
                await private.close()

    try:
        with WorkerLock(s.path.resolve().with_suffix(".worker.lock")):
            if not typer.confirm(
                "Send a recovery transaction? Cancellation spends gas; stop the worker first."
            ):
                raise typer.Abort()
            output(asyncio.run(work()))
    finally:
        s.close()


if __name__ == "__main__":
    app()
