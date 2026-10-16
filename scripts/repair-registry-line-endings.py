"""Restore LF only when the result matches the committed registry digest."""

import hashlib
import json
from pathlib import Path


def repair(root: Path):
    config = root / "config"
    lock = json.loads((config / "registry.lock.json").read_text())
    pending = []
    for name, digest in lock["files"].items():
        path = (config / name).resolve()
        if not path.is_relative_to((config / "chains").resolve()):
            raise ValueError("Unexpected registry path")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() == digest:
            continue
        normalized = raw.replace(b"\r\n", b"\n")
        if hashlib.sha256(normalized).hexdigest() != digest:
            raise ValueError(f"{name}: content differs beyond line endings; no files changed")
        pending.append((path, normalized))
    # Validate every file before changing any. Never regenerate the trust manifest.
    for path, normalized in pending:
        path.write_bytes(normalized)
    return len(pending)


if __name__ == "__main__":
    count = repair(Path(__file__).resolve().parent.parent)
    print(f"Registry verified; normalized {count} file(s) to LF.")
