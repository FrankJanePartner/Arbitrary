import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.depth = 0
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS budgets(id TEXT PRIMARY KEY,chain_id INTEGER,reserved TEXT,actual TEXT,day TEXT,settled INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS executions(id TEXT PRIMARY KEY,chain_id INTEGER,operator TEXT,nonce INTEGER,tx_hash TEXT,raw_tx TEXT,status TEXT,payload TEXT,metadata TEXT,receipt TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS tx_hashes(hash TEXT PRIMARY KEY,intent_id TEXT,raw_tx TEXT,kind TEXT DEFAULT 'trade');
CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY,chain_id INTEGER,block INTEGER,payload TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT);
""")

    @contextmanager
    def atomic(self):
        with self.lock:
            outer = self.depth == 0
            if outer:
                self.db.execute("BEGIN IMMEDIATE")
            self.depth += 1
            try:
                yield
                if outer:
                    self.db.execute("COMMIT")
            except BaseException:
                if outer:
                    self.db.execute("ROLLBACK")
                raise
            finally:
                self.depth -= 1

    def rows(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def reserve(self, id, chain_id, cost, chain_cap, global_cap, day):
        cost = Decimal(cost)
        if not cost.is_finite() or cost < 0:
            raise ValueError("invalid budget cost")
        with self.atomic():
            rows = self.rows("SELECT * FROM budgets")
            existing = next((r for r in rows if r["id"] == id), None)
            if existing and (existing["settled"] or existing["chain_id"] != chain_id):
                raise ValueError("settled or wrong-chain reservation")
            if existing:
                cost = max(cost, Decimal(existing["reserved"]))
            total = Decimal(0)
            chain = Decimal(0)
            for r in rows:
                if r["id"] == id:
                    continue
                value = (
                    Decimal(r["reserved"])
                    if not r["settled"]
                    else (Decimal(r["actual"]) if r["day"] == day else Decimal(0))
                )
                total += value
                if r["chain_id"] == chain_id:
                    chain += value
            if total + cost > global_cap or chain + cost > chain_cap:
                raise ValueError("daily budget exceeded")
            self.db.execute(
                "INSERT INTO budgets VALUES(?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET reserved=excluded.reserved",
                (id, chain_id, str(cost), "0", day),
            )

    def settle(self, id, cost, day):
        with self.atomic():
            self.db.execute(
                "UPDATE budgets SET actual=?,day=?,settled=1 WHERE id=?", (str(cost), day, id)
            )

    def reopen(self, id):
        with self.atomic():
            self.db.execute("UPDATE budgets SET actual='0',settled=0 WHERE id=?", (id,))

    def reserved(self):
        return sum(
            (
                Decimal(r["reserved"])
                for r in self.rows("SELECT reserved FROM budgets WHERE settled=0")
            ),
            Decimal(0),
        )

    def spent(self, day):
        return sum(
            (
                Decimal(r["actual"])
                for r in self.rows("SELECT actual FROM budgets WHERE settled=1 AND day=?", (day,))
            ),
            Decimal(0),
        )

    def execution(self, id):
        r = self.rows("SELECT * FROM executions WHERE id=?", (id,))
        return r[0] if r else None

    def pending(self, chain_id=None):
        sql = "SELECT * FROM executions WHERE status NOT IN ('confirmed','failed','cancelled')"
        args = ()
        if chain_id is not None:
            sql += " AND chain_id=?"
            args = (chain_id,)
        return self.rows(sql, args)

    def set_state(self, key, value):
        with self.atomic():
            self.db.execute(
                "INSERT INTO state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def get_state(self, key, default=None):
        r = self.rows("SELECT value FROM state WHERE key=?", (key,))
        return json.loads(r[0]["value"]) if r else default

    def observation(self, chain, block, payload):
        with self.atomic():
            self.db.execute(
                "INSERT INTO observations(chain_id,block,payload) VALUES(?,?,?)",
                (chain, block, json.dumps(payload, default=str)),
            )

    def backup(self, path):
        target = sqlite3.connect(path)
        with self.lock:
            self.db.backup(target)
        target.close()
        os.chmod(path, 0o600)

    def close(self):
        self.db.close()
