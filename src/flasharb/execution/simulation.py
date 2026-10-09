from ..models import SimulationResult
from .abi import transaction


async def simulate(intent, rpc):
    try:
        await rpc.call("eth_call", [transaction(intent), hex(intent.block_number)])
        return SimulationResult(ok=True, block_number=intent.block_number)
    except Exception as error:
        return SimulationResult(
            ok=False, block_number=intent.block_number, reason=type(error).__name__
        )
