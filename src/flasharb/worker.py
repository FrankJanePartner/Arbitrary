import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from web3 import Web3
from .config import verify_chain, validate_route
from .models import Intent, Policy
from .market.rpc import from_config, RpcClient
from .market.pools import discover_pools
from .market.quotes import QuoteService
from .market.prices import prices, loan_terms
from .strategy.cycles import find_cycles
from .strategy.sizing import optimize_size
from .strategy.economics import evaluate_profit
from .execution.abi import transaction
from .execution.simulation import simulate
from .execution.fees import estimate_fees
from .execution.transactions import TransactionManager
from .storage.reconcile import reconcile_chain
from .deployment import verify_deployment

OBSERVE_MAX_ROUTES = 2
OBSERVE_SIZE_SAMPLES = 2
OBSERVE_MIN_POLL_SECONDS = 240
POOL_CACHE_SECONDS = 900
POOL_CACHE_BLOCKS = 100_000


def scan_quote_budget(policy, mode):
    if mode == "observe":
        return (
            min(policy.max_route_quotes, OBSERVE_MAX_ROUTES),
            min(policy.size_samples, OBSERVE_SIZE_SAMPLES),
        )
    return policy.max_route_quotes, policy.size_samples


class Worker:
    def __init__(self, config, store, signer=None, mode="observe"):
        if mode == "live" and signer is None:
            raise ValueError("live mode requires unlocked signer")
        self.config = config
        self.store = store
        self.signer = signer
        self.mode = mode
        self.stop = asyncio.Event()
        self.rpcs = {}
        self._seen = {}
        self._pools = {}
        self._pool_cache_meta = {}
        self._verified = {}

    async def load_pools(self, chain, rpc, block):
        now = time.monotonic()
        cached = self._pools.get(chain.chain_id)
        meta = self._pool_cache_meta.get(chain.chain_id)
        if cached is not None and meta is not None:
            fresh = (
                meta["registry_digest"] == chain.registry_digest
                and block >= meta["block"]
                and block - meta["block"] < POOL_CACHE_BLOCKS
                and now - meta["time"] < POOL_CACHE_SECONDS
            )
            if fresh:
                return cached
        pools = await discover_pools(chain, rpc, block)
        self._pools[chain.chain_id] = pools
        self._pool_cache_meta[chain.chain_id] = {
            "registry_digest": chain.registry_digest,
            "block": block,
            "time": now,
        }
        return pools

    def submission_allowed(self, chain, policy):
        return (
            not self.stop.is_set()
            and not self.store.get_state("paused", False)
            and self.store.get_state("enabled:" + str(chain.chain_id), chain.enabled)
            and self.store.get_state("mode", "observe") == "live"
            and self.store.get_state("policy", self.config.policy.model_dump(mode="json"))
            == policy.model_dump(mode="json")
        )

    async def reconcile(self, chain, rpc):
        head = await rpc.head(chain.max_head_age)
        await reconcile_chain(self.store, chain, rpc, int(head["number"], 16), self.config.timezone)

    async def tick(self, chain, rpc):
        await self.reconcile(chain, rpc)
        if self.store.get_state("paused", False) or not self.store.get_state(
            "enabled:" + str(chain.chain_id), chain.enabled
        ):
            return
        mode = self.store.get_state("mode", "observe")
        if mode == "live" and (self.mode != "live" or self.signer is None):
            raise ValueError("live requires local signer unlock and explicit process start")
        await self.scan(chain, rpc, mode)

    async def safe_tick(self, chain, rpc):
        try:
            await self.tick(chain, rpc)
        except Exception as error:
            self.store.set_state(
                "health:" + str(chain.chain_id),
                {"status": "error", "reason": type(error).__name__, "time": int(time.time())},
            )

    async def scan(self, chain, rpc, mode):
        policy = Policy(
            **self.store.get_state("policy", self.config.policy.model_dump(mode="json"))
        )
        head = await rpc.head(chain.max_head_age)
        block = int(head["number"], 16)
        now = int(time.time())
        last = self._seen.get(chain.chain_id)
        if last == head["hash"]:
            return
        self._seen[chain.chain_id] = head["hash"]
        self.store.set_state(
            "health:" + str(chain.chain_id),
            {"status": "scanning", "block": block, "time": now, "rpc_calls": rpc.calls},
        )
        if chain.chain_id not in self._verified:
            check = await verify_chain(chain, rpc)
            if not check.ok:
                raise ValueError("integration verification failed")
            self._verified[chain.chain_id] = check.checks
        if mode != "observe":
            await verify_deployment(chain, rpc, block)
        if mode == "live":
            # A fee estimate buffer is not an enforceable OP-stack L1/operator fee cap.
            if chain.fee_model == "op":
                raise ValueError(
                    "live OP-stack fee ceilings await certification; observe/simulate available"
                )
            evidence = Path(self.config.data_dir) / f"fork-{chain.chain_id}.json"
            if not evidence.exists():
                raise ValueError("fork verification evidence required")
            ev = json.loads(evidence.read_text())
            if ev.get("status") != "PASS" or ev.get("registry_digest") != chain.registry_digest:
                raise ValueError("fork verification outdated")
            if self.signer.address.lower() != chain.operator.lower():
                raise ValueError("operator signer mismatch")
        pools = await self.load_pools(chain, rpc, block)
        routes = find_cycles(pools, chain_id=chain.chain_id)
        loans = {t.address.lower(): t for t in chain.tokens if t.loan}
        route_limit, sample_count = scan_quote_budget(policy, mode)
        routes = [r for r in routes if r.hops[0].token_in.lower() in loans][
            :route_limit
        ]
        qs = QuoteService(chain, rpc)
        loan_terms_cache = {}
        for route in routes:
            if self.stop.is_set() or self.store.get_state("paused", False):
                break
            loan = loans[route.hops[0].token_in.lower()]
            try:
                if loan.address.lower() not in loan_terms_cache:
                    loan_terms_cache[loan.address.lower()] = await loan_terms(
                        chain, rpc, loan.address, block
                    )
                premium_bps, liquidity = loan_terms_cache[loan.address.lower()]
                q = await optimize_size(
                    route,
                    policy,
                    block,
                    qs.quote_route,
                    liquidity,
                    premium_bps,
                    sample_count=sample_count,
                )
                payload = {
                    "mode": mode,
                    "route": route.model_dump(),
                    "amount_in": str(q.amount_in),
                    "amount_out": str(q.amount_out),
                    "gross_surplus": str(q.amount_out - q.amount_in),
                    "status": "observed",
                }
                if mode == "observe":
                    self.store.observation(chain.chain_id, block, payload)
                    continue
                if q.amount_out <= q.amount_in + (q.amount_in * premium_bps + 9999) // 10000:
                    continue
                # Refresh the winning candidate after bounded size search; never execute an old scan quote.
                fresh = await rpc.head(chain.max_head_age)
                b = int(fresh["number"], 16)
                now = int(time.time())
                block_timestamp = int(fresh["timestamp"], 16)
                q = await qs.quote_route(route, q.amount_in, b)
                premium_bps, liquidity = await loan_terms(chain, rpc, loan.address, b)
                if q.amount_in > liquidity:
                    continue
                price = await prices(chain, rpc, loan, b, now, policy.price_max_age)
                r = route.model_copy(deep=True)
                for h, out in zip(r.hops, q.hop_outputs):
                    h.min_out = max(1, out * (10000 - policy.slippage_bps) // 10000)
                nonce = int(
                    await rpc.call("eth_getTransactionCount", [chain.operator, "pending"]), 16
                )
                id = Web3.keccak(
                    text=f"{chain.chain_id}:{chain.operator}:{nonce}:{fresh['hash']}:{time.time_ns()}"
                ).hex()
                intent = Intent(
                    id=id,
                    chain_id=chain.chain_id,
                    operator=chain.operator,
                    nonce=nonce,
                    executor=chain.executor,
                    asset=loan.address,
                    amount=q.amount_in,
                    route=r,
                    min_profit_token=1,
                    deadline=min(now + policy.deadline_seconds, block_timestamp + 120),
                    block_number=b,
                )
                if intent.deadline <= now + 3:
                    continue
                validate_route(r, chain.tokens, [v.router for v in chain.venues])
                simulation = await simulate(intent, rpc)
                if not simulation.ok:
                    continue
                fees = await estimate_fees(transaction(intent), chain, rpc, b)
                premium = (q.amount_in * premium_bps + 9999) // 10000
                decision = evaluate_profit(
                    q,
                    premium,
                    fees,
                    price,
                    policy,
                    now=now,
                    merchant_fee_bps=chain.merchant_fee_bps,
                )
                payload.update(
                    {
                        "decision": decision.model_dump(mode="json"),
                        "status": "eligible" if decision.eligible else "rejected",
                        "block": b,
                    }
                )
                self.store.observation(chain.chain_id, b, payload)
                if not decision.eligible:
                    continue
                intent.min_profit_token = decision.min_profit_token
                final = await simulate(intent, rpc)
                if not final.ok or int(time.time()) >= intent.deadline - 3:
                    continue
                if mode == "simulate":
                    continue
                if self.store.pending(chain.chain_id):
                    continue
                balance = int(await rpc.call("eth_getBalance", [chain.operator, "pending"]), 16)
                floor = int(policy.low_balance_usd / price.native_usd * 10**18)
                if balance < floor + fees.max_native_cost:
                    raise ValueError("low gas balance")
                private = None
                if chain.submission == "private":
                    url = os.environ.get(chain.private_rpc_env or "")
                    if not url:
                        raise ValueError("private submission endpoint missing; no fallback")
                    private = RpcClient(
                        url,
                        chain.chain_id,
                        self.config.rpc_rps,
                        self.config.rpc_daily_calls,
                        store=self.store,
                    )
                    await private.check_chain()
                try:
                    tx = transaction(intent)
                    tx.pop("from")
                    tx.update(
                        {
                            "value": 0,
                            "chainId": chain.chain_id,
                            "nonce": nonce,
                            "type": 2,
                            "gas": fees.gas_limit,
                            "maxFeePerGas": fees.max_fee_per_gas,
                            "maxPriorityFeePerGas": fees.priority_fee,
                        }
                    )
                    metadata = {
                        "executor": chain.executor,
                        "asset": loan.address,
                        "recipient": chain.recipient,
                        "merchant": chain.merchant,
                        "merchant_fee_bps": chain.merchant_fee_bps,
                        "amount": intent.amount,
                        "native_usd": str(price.native_usd),
                        "loan_usd": str(price.loan_usd),
                        "loan_decimals": loan.decimals,
                        "price_timestamp": price.updated_at,
                        "intent": intent.model_dump(mode="json"),
                    }
                    day = datetime.now(ZoneInfo(self.config.timezone)).date().isoformat()
                    manager = TransactionManager(
                        self.store, rpc, self.signer, chain.chain_id, private
                    )
                    if not self.submission_allowed(chain, policy):
                        break
                    await manager.submit_transaction(
                        id,
                        tx,
                        decision.gas_usd,
                        policy.daily_usd,
                        policy.global_daily_usd,
                        day,
                        metadata,
                        can_submit=lambda: (
                            self.submission_allowed(chain, policy)
                            and int(time.time()) < intent.deadline - 3
                        ),
                    )
                    break
                finally:
                    if private:
                        await private.close()
            except Exception as error:
                self.store.observation(
                    chain.chain_id, block, {"status": "rejected", "reason": type(error).__name__}
                )
        self.store.set_state(
            "health:" + str(chain.chain_id),
            {
                "status": "idle",
                "block": block,
                "pools": len(pools),
                "routes": len(routes),
                "time": int(time.time()),
                "rpc_calls": rpc.calls,
            },
        )

    async def run(self, once=False):
        from .runtime import WorkerLock

        with WorkerLock(self.store.path.resolve().with_suffix(".worker.lock")):
            self.store.set_state("mode", self.mode)
            self.store.set_state("worker", "running")
            await self._run(once)

    async def _run(self, once=False):
        try:
            while not self.stop.is_set():
                for chain in self.config.chains:
                    enabled = self.store.get_state("enabled:" + str(chain.chain_id), chain.enabled)
                    if (
                        enabled or self.store.pending(chain.chain_id)
                    ) and chain.chain_id not in self.rpcs:
                        try:
                            self.rpcs[chain.chain_id] = from_config(chain, self.config, self.store)
                        except Exception as error:
                            self.store.set_state(
                                "health:" + str(chain.chain_id),
                                {"status": "error", "reason": type(error).__name__},
                            )
                    if (
                        not enabled
                        and chain.chain_id in self.rpcs
                        and not self.store.pending(chain.chain_id)
                    ):
                        await self.rpcs.pop(chain.chain_id).close()
                await asyncio.gather(
                    *(
                        self.safe_tick(c, self.rpcs[c.chain_id])
                        for c in self.config.chains
                        if c.chain_id in self.rpcs
                    )
                )
                if once:
                    break
                try:
                    interval = self.config.poll_seconds
                    if self.store.get_state("mode", "observe") == "observe":
                        interval = max(interval, OBSERVE_MIN_POLL_SECONDS)
                    await asyncio.wait_for(self.stop.wait(), timeout=interval)
                except TimeoutError:
                    pass
        finally:
            self.store.set_state("mode", "observe")
            self.store.set_state("worker", "stopped")
            for rpc in self.rpcs.values():
                await rpc.close()
