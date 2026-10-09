from pathlib import Path
import re
import pytest
from fastapi.testclient import TestClient
from flasharb.config import load_config
from flasharb.storage.db import Store


@pytest.fixture
def client(tmp_path):
    from flasharb.web.app import create_app
    from flasharb.web.auth import password_hash

    cfg = load_config(Path("config/app.yaml"))
    cfg.data_dir = str(tmp_path)
    store = Store(tmp_path / "db")
    app = create_app(cfg, store, password_hash("long-test-password"), launch_worker=False)
    with TestClient(app) as c:
        yield c


def login(client):
    page = client.get("/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    r = client.post("/login", data={"password": "long-test-password", "csrf": csrf})
    assert r.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)


def test_unauthenticated_control_denied(client):
    assert client.post("/control/pause", data={"csrf": "x"}).status_code in (401, 403)


def test_csrf_rejected(client):
    login(client)
    assert client.post("/control/pause", data={"csrf": "wrong"}).status_code == 403


def test_all_six_networks_visible(client):
    login(client)
    r = client.get("/networks")
    for name in [
        "Ethereum",
        "Arbitrum One",
        "Base",
        "OP Mainnet",
        "Polygon PoS",
        "Avalanche C-Chain",
    ]:
        assert name in r.text


def test_operator_cannot_change_owner_settings(client):
    csrf = login(client)
    assert client.post("/control/settings", data={"csrf": csrf, "owner": "0x11"}).status_code == 422


def test_estimated_and_realized_profit_distinct(client):
    login(client)
    r = client.get("/")
    assert "Finalized net" in r.text and "Observed opportunities" in r.text


def test_dashboard_cannot_unlock_live_mode(client):
    csrf = login(client)
    assert client.post("/control/mode", data={"csrf": csrf, "mode": "live"}).status_code == 403
