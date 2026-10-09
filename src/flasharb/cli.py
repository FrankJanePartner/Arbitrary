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
from .market.rpc import from_config
from .execution.signer import Signer
from .execution.fees import estimate_fees
from .deployment import deploy_plan as make_plan, configuration_plan, verify_deployment as verify
from .worker import Worker

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
                        "reason": str(e) if isinstance(e, ValueError) else type(e).__name__,
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
            raise typer.BadParameter("--keystore required for live")
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
def serve(config: Path = DEFAULT, port: int = 8000):
    """Start authenticated loopback dashboard and observe-mode worker."""
    import uvicorn
    from .web.app import create_app

    c, s = context(config)
    p = Path(c.data_dir) / "auth.json"
    if not p.exists():
        raise typer.BadParameter("Run flasharb init first")
    uvicorn.run(
        create_app(c, s, json.loads(p.read_text())["password_hash"]),
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
    owner: str,
    operator: str,
    recipient: str,
    out: Path = Path("data/deploy-plan.json"),
    config: Path = DEFAULT,
):
    c = load_config(config)
    p = make_plan(selected(c, chain), owner, operator, recipient)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(p, indent=2))
    output(p)


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
        expected = make_plan(ch, p["owner"], p["operator"], p["recipient"])
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
        rpc = from_config(ch, c)
        remaining = cap
        results = []
        try:
            await rpc.check_chain()
            for tx in txs:
                fee = await estimate_fees(tx, ch, rpc)
                if fee.max_native_cost > remaining:
                    raise ValueError("deployment fee cap exceeded")
                nonce = int(
                    await rpc.call("eth_getTransactionCount", [signer.address, "pending"]), 16
                )
                latest = int(
                    await rpc.call("eth_getTransactionCount", [signer.address, "latest"]), 16
                )
                if nonce != latest:
                    raise ValueError("unresolved owner nonce; reconcile before deployment")
                payload = dict(tx)
                payload.pop("from")
                payload["value"] = 0
                payload.update(
                    {
                        "chainId": ch.chain_id,
                        "nonce": nonce,
                        "type": 2,
                        "gas": fee.gas_limit,
                        "maxFeePerGas": fee.max_fee_per_gas,
                        "maxPriorityFeePerGas": fee.priority_fee,
                    }
                )
                signed = signer.sign_transaction(payload)
                h = "0x" + signed.hash.hex()
                journal = Path(c.data_dir) / "deployments"
                journal.mkdir(parents=True, exist_ok=True)
                record = {
                    "chain_id": ch.chain_id,
                    "hash": h,
                    "nonce": nonce,
                    "status": "signed",
                    "payload": payload,
                    "raw_tx": "0x" + signed.raw_transaction.hex(),
                }
                f = journal / (h + ".json")
                f.write_text(json.dumps(record, indent=2))
                f.chmod(0o600)
                await rpc.call("eth_sendRawTransaction", [record["raw_tx"]])
                record["status"] = "submitted"
                f.write_text(json.dumps(record, indent=2))
                receipt = None
                for _ in range(60):
                    receipt = await rpc.call("eth_getTransactionReceipt", [h])
                    if receipt:
                        break
                    await asyncio.sleep(2)
                if not receipt:
                    raise ValueError("deployment pending; journal retained; do not repeat blindly")
                record["receipt"] = receipt
                record["status"] = "mined"
                f.write_text(json.dumps(record, indent=2))
                results.append(
                    {
                        "hash": h,
                        "contract": receipt.get("contractAddress"),
                        "status": receipt["status"],
                    }
                )
                remaining -= fee.max_native_cost
                if int(receipt["status"], 16) != 1:
                    raise ValueError("deployment/configuration reverted")
            return results
        finally:
            await rpc.close()

    try:
        output(asyncio.run(work()))
    finally:
        s.close()


if __name__ == "__main__":
    app()
