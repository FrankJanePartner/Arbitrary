import csv
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path


def report_rows(store):
    result = []
    for r in store.rows(
        "SELECT id,chain_id,tx_hash,status,metadata,receipt,created FROM executions ORDER BY created DESC"
    ):
        meta = json.loads(r.pop("metadata") or "{}")
        receipt = json.loads(r.pop("receipt") or "{}")
        r.update(
            {
                "asset": meta.get("asset"),
                "recipient": meta.get("recipient"),
                "merchant": meta.get("merchant"),
                "merchant_fee_bps": meta.get("merchant_fee_bps", 0),
            }
        )
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
        "merchant_fee_usd": str(
            sum((Decimal(r.get("merchant_fee_usd", "0")) for r in final), Decimal(0))
        ),
        "net_usd": str(sum((Decimal(r["net_usd"]) for r in final), Decimal(0))),
        "reserved_usd": str(store.reserved()),
        "valuation_basis": "submission price snapshots; infrastructure costs excluded",
    }


def activity_summary(store):
    """Summarize genuine persisted scan events and route rejections."""
    logs = store.path.parent / "logs"
    counts = Counter()
    rejections = Counter()
    first = last = None
    for path in sorted(logs.glob("worker.jsonl*")):
        try:
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    event = row.get("event")
                    if not event:
                        continue
                    counts[event] += 1
                    timestamp = row.get("timestamp")
                    first = min(first, timestamp) if first and timestamp else (timestamp or first)
                    last = max(last, timestamp) if last and timestamp else (timestamp or last)
                    if event == "opportunity_rejected":
                        rejections.update(str(x) for x in row.get("reasons", []))
        except OSError:
            continue
    observation_rows = store.rows("SELECT chain_id,payload FROM observations")
    observed_by_chain = Counter()
    for row in observation_rows:
        observed_by_chain[str(row["chain_id"])] += 1
    return {
        "first_event": first,
        "last_event": last,
        "event_counts": dict(counts),
        "rejection_reasons": dict(rejections),
        "stored_observations_by_chain": dict(observed_by_chain),
        "source": "worker JSONL event log and persisted observations",
    }


def export_report(store, path, format="json"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = report_rows(store)
    if format == "json":
        path.write_text(
            json.dumps(
                {
                    "summary": summary(store),
                    "activity": activity_summary(store),
                    "executions": rows,
                },
                indent=2,
            )
        )
    elif format == "csv":
        keys = sorted({k for r in rows for k in r} or {"id", "chain_id", "status"})
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
    else:
        raise ValueError("unsupported report format")
    return path
