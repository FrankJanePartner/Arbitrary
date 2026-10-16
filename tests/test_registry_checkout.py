import runpy
import shutil

import pytest

repair = runpy.run_path("scripts/repair-registry-line-endings.py")["repair"]


def test_windows_checkout_repaired_without_changing_manifest(tmp_path):
    shutil.copytree("config", tmp_path / "config")
    manifest = (tmp_path / "config/registry.lock.json").read_bytes()
    for path in (tmp_path / "config/chains").glob("*.yaml"):
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert repair(tmp_path) == 6
    assert repair(tmp_path) == 0
    assert (tmp_path / "config/registry.lock.json").read_bytes() == manifest


def test_modified_registry_rejected_before_any_repair(tmp_path):
    shutil.copytree("config", tmp_path / "config")
    first = tmp_path / "config/chains/1.yaml"
    first.write_bytes(first.read_bytes().replace(b"\n", b"\r\n"))
    changed = tmp_path / "config/chains/43114.yaml"
    changed.write_bytes(changed.read_bytes() + b"# unexpected edit\n")
    before = first.read_bytes()
    with pytest.raises(ValueError, match="content differs"):
        repair(tmp_path)
    assert first.read_bytes() == before
