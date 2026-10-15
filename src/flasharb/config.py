import hashlib
import os
from dotenv import load_dotenv
import json
from pathlib import Path
import yaml
from web3 import Web3
from .models import AppConfig, ChainConfig, Route, VerificationReport


def check_registry(path: Path, expected: str):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("registry digest mismatch; reverify")


def load_config(path: Path) -> AppConfig:
    path = path.resolve()
    load_dotenv(path.parent.parent / ".env", override=False, interpolate=False)
    data = yaml.safe_load(path.read_text())
    lock = json.loads((path.parent / "registry.lock.json").read_text())
    chains = []
    for name, digest in lock["files"].items():
        f = path.parent / name
        check_registry(f, digest)
        c = yaml.safe_load(f.read_text())
        c["registry_digest"] = digest
        chains.append(ChainConfig(**c))
    # Runtime overrides never replace trusted addresses or registry provenance.
    for c in chains:
        overrides = data.get("networks", {}).get(str(c.chain_id), {})
        for k, v in overrides.items():
            if k not in {
                "enabled",
                "executor",
                "executor_codehash",
                "operator",
                "owner",
                "recipient",
                "merchant",
                "merchant_fee_bps",
                "submission",
                "private_rpc_env",
            }:
                raise ValueError("unsupported network override")
            setattr(c, k, v)
    wallet_fields = {
        "OWNER_WALLET": "owner",
        "GAS_WALLET": "operator",
        "PROFIT_WALLET": "recipient",
        "MERCHANT_WALLET": "merchant",
    }
    for c in chains:
        for label, field in wallet_fields.items():
            value = os.getenv(f"ARBITRARY_{label}_{c.chain_id}") or os.getenv(f"ARBITRARY_{label}")
            if value:
                if not Web3.is_address(value) or int(value, 16) == 0:
                    raise ValueError(f"Invalid {label} public address")
                setattr(c, field, Web3.to_checksum_address(value))
        value = os.getenv(f"ARBITRARY_EXECUTOR_{c.chain_id}")
        if value:
            if not Web3.is_address(value) or int(value, 16) == 0:
                raise ValueError("Invalid executor address")
            c.executor = Web3.to_checksum_address(value)
        fee = os.getenv(f"ARBITRARY_MERCHANT_FEE_BPS_{c.chain_id}") or os.getenv(
            "ARBITRARY_MERCHANT_FEE_BPS"
        )
        if fee:
            try:
                rate = int(fee)
                if not 0 <= rate <= 1000:
                    raise ValueError()
            except ValueError:
                raise ValueError(
                    "Merchant rate must be an integer from 0 to 1000 basis points"
                ) from None
            c.merchant_fee_bps = rate
    data.pop("networks", None)
    return AppConfig(chains=chains, **data)


def validate_route(route: Route, tokens, routers):
    allowed = {t.address.lower() for t in tokens}
    venues = {r.lower() for r in routers}
    for h in route.hops:
        if (
            h.token_in.lower() not in allowed
            or h.token_out.lower() not in allowed
            or h.router.lower() not in venues
        ):
            raise ValueError("route outside allowlist")


async def verify_chain(config: ChainConfig, rpc) -> VerificationReport:
    r = VerificationReport(chain_id=config.chain_id)
    if int(await rpc.call("eth_chainId", []), 16) != config.chain_id:
        r.blockers.append("chain_id")
        return r
    r.block_number = int(await rpc.call("eth_blockNumber", []), 16)
    addresses = {"provider": config.provider, "pool": config.pool, "oracle": config.oracle}
    for t in config.tokens:
        addresses["token:" + t.symbol] = t.address
        if t.oracle:
            addresses["feed:" + t.symbol] = t.oracle
    for v in config.venues:
        for k in ["factory", "router", "quoter"]:
            if getattr(v, k):
                addresses[v.name + ":" + k] = getattr(v, k)
    for label, address in addresses.items():
        code = await rpc.call("eth_getCode", [address, hex(r.block_number)])
        if code in ("0x", "0x0"):
            r.blockers.append(label + ":no_code")
        else:
            r.checks[label] = Web3.keccak(hexstr=code).hex()
    selector = "0x" + Web3.keccak(text="getPool()")[:4].hex()
    current = await rpc.call(
        "eth_call", [{"to": config.provider, "data": selector}, hex(r.block_number)]
    )
    if current[-40:].lower() != config.pool[2:].lower():
        r.blockers.append("pool_registry_drift")
    return r
