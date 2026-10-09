import hashlib
from web3 import Web3
from .execution.abi import artifact, executor


def deploy_plan(chain, owner, operator, recipient):
    values = [Web3.to_checksum_address(x) for x in [chain.pool, owner, operator, recipient]]
    if any(int(x, 16) == 0 for x in values):
        raise ValueError("zero address")
    art = artifact()
    data = executor().constructor(*values).data_in_transaction
    return {
        "chain_id": chain.chain_id,
        "owner": values[1],
        "operator": values[2],
        "recipient": values[3],
        "pool": values[0],
        "compiler": art["compiler"],
        "registry_digest": chain.registry_digest,
        "bytecode_sha256": hashlib.sha256(bytes.fromhex(art["bytecode"][2:])).hexdigest(),
        "broadcast": False,
        "transaction": {"from": values[1], "data": data, "value": "0x0"},
    }


def configuration_plan(chain):
    if not chain.executor or not chain.owner:
        raise ValueError("configure executor and owner first")
    c = executor(chain.executor)
    txs = []
    for token in chain.tokens:
        txs.append(
            {
                "from": chain.owner,
                "to": chain.executor,
                "value": "0x0",
                "data": c.encode_abi("setToken", args=[token.address, True, token.loan]),
            }
        )
    for venue in chain.venues:
        txs.append(
            {
                "from": chain.owner,
                "to": chain.executor,
                "value": "0x0",
                "data": c.encode_abi(
                    "setRouter", args=[Web3.to_checksum_address(venue.router), venue.kind, True]
                ),
            }
        )
    return txs


def match_runtime(code):
    art = artifact()
    actual = bytearray.fromhex(code.removeprefix("0x"))
    expected = bytearray.fromhex(art["runtime"][2:])
    if len(actual) != len(expected):
        return False
    for entries in art["immutableReferences"].values():
        for x in entries:
            actual[x["start"] : x["start"] + x["length"]] = b"\0" * x["length"]
            expected[x["start"] : x["start"] + x["length"]] = b"\0" * x["length"]
    return actual == expected


async def verify_deployment(chain, rpc, block="latest"):
    if not all([chain.executor, chain.owner, chain.operator, chain.recipient]):
        raise ValueError("executor and roles are not configured")
    if int(await rpc.call("eth_chainId", []), 16) != chain.chain_id:
        raise ValueError("wrong chain")
    code = await rpc.call(
        "eth_getCode", [chain.executor, hex(block) if isinstance(block, int) else block]
    )
    if not match_runtime(code):
        raise ValueError("executor runtime mismatch")
    actual_hash = Web3.keccak(hexstr=code).hex()
    if chain.executor_codehash and actual_hash.removeprefix(
        "0x"
    ) != chain.executor_codehash.removeprefix("0x"):
        raise ValueError("executor codehash drift")
    for name, expected in [
        ("POOL", chain.pool),
        ("owner", chain.owner),
        ("operator", chain.operator),
        ("recipient", chain.recipient),
    ]:
        (value,) = await rpc.contract_call(chain.executor, name + "()", [], [], ["address"], block)
        if value.lower() != expected.lower():
            raise ValueError(name + " mismatch")
    (paused,) = await rpc.contract_call(chain.executor, "paused()", [], [], ["bool"], block)
    if paused:
        raise ValueError("contract is paused")
    for t in chain.tokens:
        decimals = (await rpc.contract_call(t.address, "decimals()", [], [], ["uint8"], block))[0]
        if decimals != t.decimals:
            raise ValueError("token decimals mismatch")
        enabled = (
            await rpc.contract_call(
                chain.executor, "tokens(address)", ["address"], [t.address], ["bool"], block
            )
        )[0]
        loan = (
            await rpc.contract_call(
                chain.executor, "loanAssets(address)", ["address"], [t.address], ["bool"], block
            )
        )[0]
        if not enabled or loan != t.loan:
            raise ValueError("token/loan permissions mismatch")
    for v in chain.venues:
        kind = (
            await rpc.contract_call(
                chain.executor, "routerKind(address)", ["address"], [v.router], ["uint8"], block
            )
        )[0]
        if kind != v.kind + 1:
            raise ValueError("router permission mismatch")
    return {
        "status": "PASS",
        "chain_id": chain.chain_id,
        "executor_codehash": actual_hash,
        "registry_digest": chain.registry_digest,
    }
