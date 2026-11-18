import asyncio
import json
import os
import time
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from web3 import Web3
from .config import verify_chain, validate_route
from .models import Intent, Policy
from .market.rpc import from_config, RpcClient, RpcError, RpcQuotaExceeded, RpcRateLimited, validate_head
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
LIVE_MAX_TX_USD = Decimal("0.10")
LIVE_DAILY_USD = Decimal("1.00")


def validate_live_policy(policy):
    """Keep the initial live trial within the operator-approved gas budget."""
    if policy.max_tx_usd > LIVE_MAX_TX_USD:
        raise ValueError("live max transaction gas budget exceeds $0.10")
    if policy.daily_usd > LIVE_DAILY_USD or policy.global_daily_usd > LIVE_DAILY_USD:
        raise ValueError("live daily gas budget exceeds $1.00")


def scan_quote_budget(policy, mode, config=None):
    if mode == "observe":
        return (
            min(policy.max_route_quotes, OBSERVE_MAX_ROUTES),
            min(policy.size_samples, OBSERVE_SIZE_SAMPLES),
        )
    if mode == "live" and config is not None:
        return (
            min(policy.max_route_quotes, config.live_max_route_quotes),
            min(policy.size_samples, config.live_size_samples),
        )
    return policy.max_route_quotes, policy.size_samples


def rotate_routes(routes, limit, cursor=0):
    if not routes or limit <= 0:
        return [], 0
    start = cursor % len(routes)
    count = min(limit, len(routes))
    selected = (routes + routes)[start : start + count]
    return selected, (start + count) % len(routes)


def route_quote_segments(route):
    return 1 + sum(
        1
        for previous, current in zip(route.hops, route.hops[1:])
        if previous.router.lower() != current.router.lower() or previous.kind != current.kind
    )


def select_live_routes(routes, max_routes, samples, daily_limit, interval_seconds, cursor=0):
    """Bound the quote-search share of the local daily RPC budget, with reserve for overhead."""
    if not routes or max_routes <= 0:
        return [], 0, 0, 0
    scans_per_day = 86400 / max(1, interval_seconds)
    budget_per_scan = max(1, int(daily_limit * 0.65 / scans_per_day) - 6)
    start = cursor % len(routes)
    selected = []
    planned_calls = 0
    index = start
    while len(selected) < min(max_routes, len(routes)):
        route = routes[index]
        cost = max(1, samples * route_quote_segments(route))
        if selected and planned_calls + cost > budget_per_scan:
            break
        selected.append(route)
        planned_calls += cost
        index = (index + 1) % len(routes)
        if index == start:
            break
    if not selected:
        selected = [routes[start]]
        planned_calls = max(1, samples * route_quote_segments(selected[0]))
        index = (start + 1) % len(routes)
    return selected, index, budget_per_scan, planned_calls


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
        self._heads = {}
        self._deployment_verified_at = {}
        self._skip_until = {}
        self._route_cursor = {}
        self.reporter = None

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
        self._heads[chain.chain_id] = head
        before = {row["id"]: row["status"] for row in self.store.pending(chain.chain_id)}
        await reconcile_chain(self.store, chain, rpc, int(head["number"], 16), self.config.timezone)
        for intent_id, old_status in before.items():
            row = self.store.execution(intent_id)
            if not row or row["status"] == old_status:
                continue
            receipt = json.loads(row["receipt"] or "{}")
            accounting = receipt.get("accounting", {})
            from .storage.ledger import summary

            self._emit(
                "trade_reconciled",
                chain,
                status=row["status"],
                tx_hash=row.get("tx_hash"),
                gas_usd=accounting.get("gas_usd"),
                realized_profit_usd=accounting.get("profit_usd"),
                realized_net_usd=accounting.get("net_usd"),
                cumulative_net_usd=summary(self.store).get("net_usd"),
                block=receipt.get("blockNumber"),
            )
        return head

    async def tick(self, chain, rpc):
        await self.reconcile(chain, rpc)
        if self.store.get_state("paused", False) or not self.store.get_state(
            "enabled:" + str(chain.chain_id), chain.enabled
        ):
            return
        mode = self.store.get_state("mode", "observe")
        if mode == "live" and (self.mode != "live" or self.signer is None):
            raise ValueError("live requires local signer unlock and explicit process start")
        if mode == "live":
            validate_live_policy(
                Policy(**self.store.get_state("policy", self.config.policy.model_dump(mode="json")))
            )
        await self.scan(chain, rpc, mode)

    async def safe_tick(self, chain, rpc):
        if time.time() < self._skip_until.get(chain.chain_id, 0):
            return
        try:
            await self.tick(chain, rpc)
        except Exception as error:
            usage = rpc.usage_snapshot() if hasattr(rpc, "usage_snapshot") else {}
            status = (
                "quota_exhausted" if isinstance(error, RpcQuotaExceeded) else
                "rate_limited" if isinstance(error, RpcRateLimited) else
                "rpc_error" if isinstance(error, RpcError) else "error"
            )
            retry_after = getattr(error, "retry_after", None)
            if status == "quota_exhausted" and usage.get("resets_at"):
                self._skip_until[chain.chain_id] = datetime.fromisoformat(
                    usage["resets_at"]
                ).timestamp()
            elif status == "rate_limited":
                self._skip_until[chain.chain_id] = time.time() + max(30, retry_after or 0)
            self.store.set_state(
                "health:" + str(chain.chain_id),
                {
                    "status": status,
                    "reason": str(error)[:180] if isinstance(error, RpcError) else type(error).__name__,
                    "time": int(time.time()),
                    "rpc": usage,
                    **({"retry_after_seconds": round(retry_after, 2)} if retry_after else {}),
                },
            )
            self._emit(
                "rpc_health" if isinstance(error, RpcError) else "worker_error",
                chain,
                status=status,
                reason=(str(error)[:180] if isinstance(error, RpcError) else type(error).__name__),
                retry_after_seconds=round(retry_after, 2) if retry_after else None,
                rpc_used=usage.get("used"),
                rpc_limit=usage.get("limit"),
                rpc_attempts=usage.get("http_attempts"),
                rpc_remaining=usage.get("remaining"),
                resets_at=usage.get("resets_at"),
            )

    async def scan(self, chain, rpc, mode):
        policy = Policy(
            **self.store.get_state("policy", self.config.policy.model_dump(mode="json"))
        )
        head = self._heads.pop(chain.chain_id, None)
        if head is not None:
            try:
                validate_head(head, chain.max_head_age)
            except ValueError:
                head = None
        if head is None:
            head = await rpc.head(chain.max_head_age)
        block = int(head["number"], 16)
        calls_before = getattr(rpc, "calls", 0)
        now = int(time.time())
        last = self._seen.get(chain.chain_id)
        if last == head["hash"]:
            return
        self._seen[chain.chain_id] = head["hash"]
        self.store.set_state(
            "health:" + str(chain.chain_id),
            {"status": "scanning", "block": block, "time": now, "rpc_calls": rpc.calls},
        )
        self._emit("network_status", chain, status="connected", block=block, last_update=now)
        if chain.chain_id not in self._verified:
            check = await verify_chain(chain, rpc)
            if not check.ok:
                raise ValueError("integration verification failed")
            self._verified[chain.chain_id] = check.checks
        verified_at = self._deployment_verified_at.get(chain.chain_id, 0)
        if mode != "observe" and time.monotonic() - verified_at >= 300:
            await verify_deployment(chain, rpc, block)
            self._deployment_verified_at[chain.chain_id] = time.monotonic()
        if mode == "live":
            # A fee estimate buffer is not an enforceable OP-stack L1/operator fee cap.
            if chain.fee_model == "op":
                raise ValueError(
                    "live OP-stack fee ceilings await certification; observe/simulate available"
                )
            if self.signer.address.lower() != chain.operator.lower():
                raise ValueError("operator signer mismatch")
        pools = await self.load_pools(chain, rpc, block)
        routes = find_cycles(pools, chain_id=chain.chain_id)
        loans = {t.address.lower(): t for t in chain.tokens if t.loan}
        route_limit, sample_count = scan_quote_budget(policy, mode, self.config)
        routes = [r for r in routes if r.hops[0].token_in.lower() in loans]
        routes_found = len(routes)
        quote_budget = planned_quotes = None
        if mode == "live":
            routes, self._route_cursor[chain.chain_id], quote_budget, planned_quotes = select_live_routes(
                routes,
                route_limit,
                sample_count,
                self.config.rpc_daily_calls,
                max(self.config.poll_seconds, self.config.live_poll_seconds),
                self._route_cursor.get(chain.chain_id, 0),
            )
        elif routes:
            routes, self._route_cursor[chain.chain_id] = rotate_routes(
                routes, route_limit, self._route_cursor.get(chain.chain_id, 0)
            )
        token_symbols = {t.address.lower(): t.symbol for t in chain.tokens}
        venue_names = {v.router.lower(): v.name for v in chain.venues}
        self._emit(
            "scan_start",
            chain,
            status="scanning",
            block=block,
            pools=len(pools),
            routes=len(routes),
            routes_found=routes_found,
            size_samples=sample_count,
            planned_quote_rpc_calls=planned_quotes,
            quote_rpc_budget_per_scan=quote_budget,
            live_poll_seconds=self.config.live_poll_seconds if mode == "live" else None,
            dexes=sorted({p.venue.name for p in pools}),
            rpc_used=(rpc.usage_snapshot().get("used") if hasattr(rpc, "usage_snapshot") else None),
            rpc_limit=(rpc.usage_snapshot().get("limit") if hasattr(rpc, "usage_snapshot") else None),
        )
        qs = QuoteService(chain, rpc)
        loan_terms_cache = {}
        quote_price_cache = {}
        for route in routes:
            if self.stop.is_set() or self.store.get_state("paused", False):
                break
            loan = loans[route.hops[0].token_in.lower()]
            route_label = " -> ".join(
                [token_symbols.get(route.hops[0].token_in.lower(), route.hops[0].token_in[:10])]
                + [token_symbols.get(h.token_out.lower(), h.token_out[:10]) for h in route.hops]
            )
            try:
                if loan.address.lower() not in loan_terms_cache:
                    loan_terms_cache[loan.address.lower()] = await loan_terms(
                        chain, rpc, loan.address, block
                    )
                premium_bps, liquidity = loan_terms_cache[loan.address.lower()]

                async def size_quote(candidate_route, candidate_amount, candidate_block):
                    return await qs.quote_route(
                        candidate_route, candidate_amount, candidate_block, detailed=False
                    )

                q = await optimize_size(
                    route,
                    policy,
                    block,
                    size_quote,
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
                quote_gross_usd = None
                quote_premium_usd = None
                if mode != "observe":
                    if loan.address.lower() not in quote_price_cache:
                        quote_price_cache[loan.address.lower()] = await prices(
                            chain, rpc, loan, block, now, policy.price_max_age
                        )
                    quote_price = quote_price_cache[loan.address.lower()]
                    quote_gross_usd = (
                        Decimal(q.amount_out - q.amount_in)
                        * quote_price.loan_usd
                        / 10**quote_price.loan_decimals
                    )
                    quote_premium = (q.amount_in * premium_bps + 9999) // 10000
                    quote_premium_usd = (
                        Decimal(quote_premium)
                        * quote_price.loan_usd
                        / 10**quote_price.loan_decimals
                    )
                self._emit(
                    "quote_evaluated",
                    chain,
                    block=block,
                    route=route_label,
                    dexes=[venue_names.get(h.router.lower(), h.router[:10]) for h in route.hops],
                    pools=[h.pool for h in route.hops],
                    amount_in=str(q.amount_in),
                    amount_out=str(q.amount_out),
                    gross_surplus_token=str(q.amount_out - q.amount_in),
                    gross_usd=str(quote_gross_usd) if quote_gross_usd is not None else None,
                    flash_loan_fee_usd=str(quote_premium_usd) if quote_premium_usd is not None else None,
                    after_flash_loan_usd=(str(quote_gross_usd - quote_premium_usd) if quote_gross_usd is not None else None),
                    pool_fees_in_quote=True,
                    loan_premium_bps=premium_bps,
                )
                if mode == "observe":
                    self.store.observation(chain.chain_id, block, payload)
                    continue
                if q.amount_out <= q.amount_in + (q.amount_in * premium_bps + 9999) // 10000:
                    self._emit("opportunity_rejected", chain, route=route_label, reasons=["gross_does_not_cover_flash_loan_fee"])
                    continue
                # Refresh the winning candidate after bounded size search; never execute an old scan quote.
                fresh = await rpc.head(chain.max_head_age)
                b = int(fresh["number"], 16)
                now = int(time.time())
                block_timestamp = int(fresh["timestamp"], 16)
                q = await qs.quote_route(route, q.amount_in, b)
                premium_bps, liquidity = await loan_terms(chain, rpc, loan.address, b)
                if q.amount_in > liquidity:
                    self._emit("opportunity_rejected", chain, route=route_label, reasons=["flash_loan_liquidity"])
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
                    self._emit("opportunity_rejected", chain, route=route_label, reasons=["execution_deadline_too_close"])
                    continue
                validate_route(r, chain.tokens, [v.router for v in chain.venues])
                simulation = await simulate(intent, rpc)
                if not simulation.ok:
                    self._emit("simulation", chain, status="rejected", route=route_label, reason=simulation.reason or "initial_simulation_failed")
                    self._emit("opportunity_rejected", chain, route=route_label, reasons=["initial_simulation_failed"])
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
                self._emit("economics", chain, route=route_label, gross_usd=str(decision.gross_usd), flash_loan_fee_usd=str(decision.flash_loan_fee_usd), merchant_fee_usd=str(decision.merchant_fee_usd), gas_usd=str(decision.gas_usd), slippage_allowance_usd=str(decision.slippage_allowance_usd), safety_buffer_usd=str(decision.safety_buffer_usd), min_profit_usd=str(decision.min_profit_usd), expected_net_usd=str(decision.expected_net_usd), slippage_tolerance_bps=decision.slippage_tolerance_bps, eligible=decision.eligible, reasons=decision.reasons)
                if not decision.eligible:
                    self._emit("opportunity_rejected", chain, route=route_label, reasons=decision.reasons, expected_net_usd=str(decision.expected_net_usd))
                    continue
                intent.min_profit_token = decision.min_profit_token
                final = await simulate(intent, rpc)
                if not final.ok or int(time.time()) >= intent.deadline - 3:
                    self._emit("simulation", chain, status="rejected", route=route_label, reason=final.reason or "final_simulation_or_deadline_failed")
                    self._emit("opportunity_rejected", chain, route=route_label, reasons=["final_simulation_or_deadline_failed"])
                    continue
                self._emit("simulation", chain, status="passed", route=route_label, block=b, expected_net_usd=str(decision.expected_net_usd))
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
                    self._emit("trade_submitted", chain, route=route_label, tx_hash=self.store.execution(id).get("tx_hash"), expected_net_usd=str(decision.expected_net_usd), block=b)
                    break
                finally:
                    if private:
                        await private.close()
            except Exception as error:
                if isinstance(error, RpcError):
                    raise
                self.store.observation(
                    chain.chain_id, block, {"status": "rejected", "reason": type(error).__name__}
                )
                self._emit("opportunity_rejected", chain, route=locals().get("route_label", "unknown"), reasons=[type(error).__name__])
        usage = rpc.usage_snapshot() if hasattr(rpc, "usage_snapshot") else {}
        self._emit(
            "scan_complete",
            chain,
            block=block,
            pools=len(pools),
            routes_considered=len(routes),
            quotes=qs.quotes,
            rpc_attempts=max(0, getattr(rpc, "calls", 0) - calls_before),
            rpc_used=usage.get("used"),
            rpc_limit=usage.get("limit"),
            rpc_remaining=usage.get("remaining"),
            provider_rate_limits=usage.get("provider_rate_limits"),
            rpc_methods=usage.get("methods"),
            rpc_failures=usage.get("failed"),
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
                "rpc": usage,
            },
        )

    def _emit(self, event, chain, **fields):
        if self.reporter:
            self.reporter.emit(event, network=chain.name, chain_id=chain.chain_id, **fields)

    async def run(self, once=False):
        from .runtime import WorkerLock
        from pathlib import Path
        from .observability import ActivityReporter

        with WorkerLock(self.store.path.resolve().with_suffix(".worker.lock")):
            self.reporter = ActivityReporter(
                Path(self.config.data_dir) / "logs" / "worker.jsonl",
                console=self.mode == "live",
            )
            self.store.set_state("mode", self.mode)
            self.store.set_state("worker", "running")
            self.reporter.emit("worker_started", mode=self.mode, networks=[x.name for x in self.config.chains if self.store.get_state("enabled:" + str(x.chain_id), x.enabled)], poll_seconds=max(self.config.poll_seconds, self.config.live_poll_seconds) if self.mode == "live" else self.config.poll_seconds, rpc_daily_limit=self.config.rpc_daily_calls)
            try:
                await self._run(once)
            finally:
                self.reporter.session_summary()
                self.reporter.close()
                self.reporter = None

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
                            self._emit(
                                "network_connection_failed",
                                chain,
                                reason=type(error).__name__,
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
                    elif self.store.get_state("mode") == "live":
                        interval = max(interval, self.config.live_poll_seconds)
                    await asyncio.wait_for(self.stop.wait(), timeout=interval)
                except TimeoutError:
                    pass
        finally:
            self.store.set_state("mode", "observe")
            self.store.set_state("worker", "stopped")
            for rpc in self.rpcs.values():
                await rpc.close()
