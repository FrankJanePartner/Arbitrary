from pathlib import Path
import pytest

ROOT = Path(__file__).parents[1]


def test_six_chain_ids():
    from flasharb.config import load_config

    cfg = load_config(ROOT / "config/app.yaml")
    assert {c.chain_id for c in cfg.chains} == {1, 42161, 8453, 10, 137, 43114}
    assert cfg.mode == "observe"
    assert not any(c.enabled for c in cfg.chains)


def test_official_uniswap_v2_routers_are_configured_on_all_six_chains():
    from flasharb.config import load_config

    cfg = load_config(ROOT / "config/app.yaml")
    expected = {
        1: (
            "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
            "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
        ),
        42161: (
            "0xf1D7CC64Fb4452F05c498126312eBE29f30Fbcf9",
            "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
        ),
        8453: (
            "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6",
            "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
        ),
        10: (
            "0x0c3c1c532F1e39EdF36BE9Fe0bE1410313E074Bf",
            "0x4A7b5Da61326A6379179b40d00F57E5bbDC962c2",
        ),
        137: (
            "0x9e5A52f57b3038F1B8EeE45F28b3C1967e22799C",
            "0xedf6066a2b290C185783862C7F4776A2C8077AD1",
        ),
        43114: (
            "0x9e5A52f57b3038F1B8EeE45F28b3C1967e22799C",
            "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
        ),
    }
    for chain in cfg.chains:
        v2 = next(v for v in chain.venues if v.kind == 0)
        factory, router = expected[chain.chain_id]
        assert v2.factory.lower() == factory.lower()
        assert v2.router.lower() == router.lower()
        assert v2.quoter is None


def test_unknown_token_rejected():
    from flasharb.models import Hop, Route, Token
    from flasharb.config import validate_route

    a = Token(address="0x" + "11" * 20, symbol="A", decimals=6)
    h = Hop(
        kind=1,
        router="0x" + "33" * 20,
        pool="0x" + "44" * 20,
        token_in=a.address,
        token_out="0x" + "22" * 20,
        fee=3000,
    )
    with pytest.raises(ValueError, match="allowlist"):
        validate_route(
            Route(
                chain_id=1,
                hops=[
                    h,
                    h.model_copy(
                        update={
                            "token_in": h.token_out,
                            "token_out": a.address,
                            "pool": "0x" + "55" * 20,
                        }
                    ),
                ],
            ),
            [a],
            [h.router],
        )


def test_registry_drift_requires_reverification(tmp_path):
    from flasharb.config import check_registry

    f = tmp_path / "a.json"
    f.write_text("{}")
    with pytest.raises(ValueError, match="registry"):
        check_registry(f, "bad")


def test_secrets_redacted():
    from flasharb.models import RpcSettings

    value = RpcSettings(url="https://provider.test/secret-token")
    assert "secret-token" not in repr(value)
    assert "secret-token" not in value.model_dump_json()


@pytest.mark.asyncio
async def test_wrong_chain_blocks_live():
    from flasharb.config import verify_chain, load_config

    class RPC:
        async def call(self, method, params):
            return "0x2"

    report = await verify_chain(load_config(ROOT / "config/app.yaml").chains[0], RPC())
    assert not report.ok
    assert "chain_id" in report.blockers
