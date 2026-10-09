import json
from importlib.resources import files
from web3 import Web3


def artifact():
    return json.loads(
        files("flasharb").joinpath("artifacts/FlashArbitrageExecutor.json").read_text()
    )


def executor(address=None):
    return Web3().eth.contract(
        address=Web3.to_checksum_address(address) if address else None,
        abi=artifact()["abi"],
        bytecode=artifact()["bytecode"],
    )


def transaction(intent):
    data = executor(intent.executor).encode_abi(
        "execute",
        args=[
            bytes.fromhex(intent.id.removeprefix("0x")),
            Web3.to_checksum_address(intent.asset),
            intent.amount,
            [h.abi_tuple() for h in intent.route.hops],
            intent.min_profit_token,
            intent.deadline,
        ],
    )
    return {
        "from": Web3.to_checksum_address(intent.operator),
        "to": Web3.to_checksum_address(intent.executor),
        "data": data,
        "value": "0x0",
    }
