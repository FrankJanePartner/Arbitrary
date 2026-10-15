from pathlib import Path
from flasharb.config import load_config


def test_plan_does_not_broadcast():
    from flasharb.deployment import deploy_plan

    c = load_config(Path("config/app.yaml")).chains[0]
    a = "0x" + "11" * 20
    b = "0x" + "22" * 20
    d = "0x" + "33" * 20
    p = deploy_plan(c, a, b, d)
    assert p["chain_id"] == 1 and p["transaction"]["data"].startswith("0x")
    assert p["broadcast"] is False and p["operator"] == b
    assert "private" not in str(p)


def test_runtime_mismatch_rejected():
    from flasharb.deployment import match_runtime

    assert not match_runtime("0x1234")


def test_commercial_plan_exposes_merchant_terms():
    from flasharb.deployment import deploy_plan
    import pytest

    c = load_config(Path("config/app.yaml")).chains[0]
    a = "0x" + "11" * 20
    merchant = "0x" + "44" * 20
    p = deploy_plan(c, a, a, a, merchant, 250)
    assert p["merchant"] == merchant and p["merchant_fee_bps"] == 250
    with pytest.raises(ValueError):
        deploy_plan(c, a, a, a, merchant, 1001)
    with pytest.raises(ValueError):
        deploy_plan(c, a, a, a, merchant_fee_bps=250)
