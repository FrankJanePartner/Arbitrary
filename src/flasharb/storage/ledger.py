import csv
import json
from decimal import Decimal
from pathlib import Path


def report_rows(store):
    result = []
    for r in store.rows(
        "SELECT id,chain_id,tx_hash,status,metadata,receipt,created FROM executions ORDER BY created DESC"
    ):
        meta = json.loads(r.pop("metadata") or "{}")
        receipt = json.loads(r.pop("receipt") or "{}")
        r.update({"asset": meta.get("asset"), "recipient": meta.get("recipient")})
        r.update(receipt.get("accounting", {}))
        result.append(r)
    return result


def summary(store):
    rows = report_rows(store)
    final = [r for r in rows if r.get("finalized")]
    return {
        "trades": len(rows),
        "finalized": len(final),
        "pending": len(store.pending()),
        "gas_usd": str(sum((Decimal(r["gas_usd"]) for r in final), Decimal(0))),
        "net_usd": str(sum((Decimal(r["net_usd"]) for r in final), Decimal(0))),
        "reserved_usd": str(store.reserved()),
        "valuation_basis": "submission price snapshots; infrastructure costs excluded",
    }


def export_report(store, path, format="json"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = report_rows(store)
    if format == "json":
        path.write_text(json.dumps({"summary": summary(store), "executions": rows}, indent=2))
    elif format == "csv":
        keys = sorted({k for r in rows for k in r} or {"id", "chain_id", "status"})
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
    else:
        raise ValueError("unsupported report format")
    return path
