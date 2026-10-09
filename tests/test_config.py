from pathlib import Path
import pytest

ROOT = Path(__file__).parents[1]


def test_six_chain_ids():
    from flasharb.config import load_config

    cfg = load_config(ROOT / "config/app.yaml")
    assert {c.chain_id for c in cfg.chains} == {1, 42161, 8453, 10, 137, 43114}
    assert cfg.mode == "observe"
    assert not any(c.enabled for c in cfg.chains)


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
