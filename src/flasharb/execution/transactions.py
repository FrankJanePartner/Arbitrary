import json
from ..models import Submission


class TransactionManager:
    def __init__(self, store, rpc, signer, chain_id, submission_rpc=None):
        self.store = store
        self.rpc = rpc
        self.signer = signer
        self.chain_id = chain_id
        self.submission_rpc = submission_rpc or rpc

    async def submit_transaction(self, id, tx, cost, chain_cap, global_cap, day, metadata):
        if (
            int(await self.rpc.call("eth_chainId", []), 16) != self.chain_id
            or tx["chainId"] != self.chain_id
        ):
            raise ValueError("wrong chain")
        with self.store.atomic():
            if self.store.pending(self.chain_id):
                raise ValueError("unresolved transaction blocks new nonce")
            if self.store.execution(id):
                raise ValueError("intent already exists")
            self.store.reserve(id, self.chain_id, cost, chain_cap, global_cap, day)
            signed = self.signer.sign_transaction(tx)
            raw = "0x" + signed.raw_transaction.hex()
            hash = "0x" + signed.hash.hex()
            self.store.db.execute(
                "INSERT INTO executions(id,chain_id,operator,nonce,tx_hash,raw_tx,status,payload,metadata) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    id,
                    self.chain_id,
                    self.signer.address,
                    tx["nonce"],
                    hash,
                    raw,
                    "signed",
                    json.dumps(tx),
                    json.dumps(metadata, default=str),
                ),
            )
            self.store.db.execute(
                "INSERT INTO tx_hashes(hash,intent_id,raw_tx) VALUES(?,?,?)", (hash, id, raw)
            )
        return await self.rebroadcast(id)

    async def rebroadcast(self, id):
        row = self.store.execution(id)
        if not row or row["status"] in ("confirmed", "failed", "cancelled", "provisional"):
            raise ValueError("not rebroadcastable")
        status = "submitted"
        try:
            returned = await self.submission_rpc.call("eth_sendRawTransaction", [row["raw_tx"]])
            if returned.lower() != row["tx_hash"].lower():
                status = "unknown"
        except Exception:
            status = "unknown"  # persist ambiguity; do not release budget or allocate another nonce
        with self.store.atomic():
            self.store.db.execute("UPDATE executions SET status=? WHERE id=?", (status, id))
        return Submission(intent_id=id, tx_hash=row["tx_hash"], status=status)

    async def replace(self, id, tx, new_cost, chain_cap, global_cap, day, kind="trade"):
        row = self.store.execution(id)
        if not row or row["status"] in ("provisional", "confirmed", "failed", "cancelled"):
            raise ValueError("not replaceable")
        old = json.loads(row["payload"])
        if tx["chainId"] != self.chain_id or tx["nonce"] != row["nonce"]:
            raise ValueError("replacement nonce/chain mismatch")
        if kind == "trade" and any(tx[k] != old[k] for k in ["to", "data", "value"]):
            raise ValueError("replacement changes trade")
        if kind == "cancel" and (
            tx["to"].lower() != self.signer.address.lower()
            or tx["data"] != "0x"
            or tx["value"] != 0
        ):
            raise ValueError("invalid cancellation")
        if tx["maxFeePerGas"] < old["maxFeePerGas"] * 110 // 100 + 1:
            raise ValueError("replacement fee not increased")
        with self.store.atomic():
            self.store.reserve(id, self.chain_id, new_cost, chain_cap, global_cap, day)
            signed = self.signer.sign_transaction(tx)
            raw = "0x" + signed.raw_transaction.hex()
            h = "0x" + signed.hash.hex()
            self.store.db.execute("INSERT INTO tx_hashes VALUES(?,?,?,?)", (h, id, raw, kind))
            self.store.db.execute(
                "UPDATE executions SET tx_hash=?,raw_tx=?,payload=?,status='signed' WHERE id=?",
                (h, raw, json.dumps(tx), id),
            )
        return await self.rebroadcast(id)
