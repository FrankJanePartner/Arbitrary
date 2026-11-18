"""Human-readable live-worker output and a persistent, credential-free JSONL log."""

import json
import os
import sys
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from logging.handlers import RotatingFileHandler


class _PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        stream = super()._open()
        os.chmod(self.baseFilename, 0o600)
        return stream


class ActivityReporter:
    def __init__(self, path: Path, console=False):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.console = console
        self._lock = threading.RLock()
        self._counts = Counter()
        self._rejections = Counter()
        self._handler = _PrivateRotatingFileHandler(
            path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _human(record):
        event = record["event"].upper()
        network = record.get("network")
        prefix = f"[{record['timestamp']}]"
        if network:
            prefix += f" [{network} {record.get('chain_id')}]"
        fields = {k: v for k, v in record.items() if k not in {"timestamp", "event", "network", "chain_id"}}
        if event == "ECONOMICS":
            order = [
                "route", "gross_usd", "flash_loan_fee_usd", "merchant_fee_usd", "gas_usd",
                "slippage_allowance_usd", "safety_buffer_usd", "min_profit_usd", "expected_net_usd", "slippage_tolerance_bps",
                "pool_fees_in_quote", "eligible", "reasons",
            ]
        elif event == "SCAN_COMPLETE":
            order = ["block", "pools", "routes_considered", "quotes", "rpc_attempts", "rpc_used", "rpc_limit"]
        else:
            order = [
                "status", "route", "block", "pools", "routes", "quotes", "amount_in", "amount_out",
                "gross_surplus_token", "gross_usd", "flash_loan_fee_usd", "after_flash_loan_usd",
                "pool_fees_in_quote", "premium_token", "reason", "reasons", "rpc_attempts", "rpc_used",
                "rpc_limit", "retry_at", "tx_hash", "expected_net_usd", "cumulative_net_usd",
            ]
        parts = [f"{key}={fields[key]}" for key in order if key in fields]
        shown = set(order)
        parts.extend(f"{key}={value}" for key, value in fields.items() if key not in shown)
        return f"{prefix} {event}" + (" " + " ".join(parts) if parts else "")

    def emit(self, event, *, network=None, chain_id=None, **fields):
        record = {
            "timestamp": self._now(),
            "event": event,
        }
        if network is not None:
            record["network"] = network
        if chain_id is not None:
            record["chain_id"] = chain_id
        record.update(fields)
        with self._lock:
            self._counts[event] += 1
            if event == "opportunity_rejected":
                for reason in fields.get("reasons", [fields.get("reason", "unspecified")]):
                    self._rejections[str(reason)] += 1
            if self.console:
                print(self._human(record), file=sys.stdout, flush=True)
            self._handler.stream.write(json.dumps(record, default=str, sort_keys=True) + "\n")
            self._handler.flush()

    def session_summary(self, financial=None):
        self.emit(
            "session_summary",
            activity_counts=dict(self._counts),
            rejection_reasons=dict(self._rejections),
            financial=financial or {},
            log_file=str(self.path),
        )

    def close(self):
        self._handler.close()
