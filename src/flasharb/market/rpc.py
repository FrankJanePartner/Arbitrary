import asyncio
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import os
import random
import time
import httpx
from eth_abi import encode, decode
from web3 import Web3


class RpcError(RuntimeError):
    pass


class RpcQuotaExceeded(RpcError):
    """The application's persistent local per-chain/day request budget is exhausted."""


class RpcRateLimited(RpcError):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = max(0.0, float(retry_after))


def _retry_delay(attempt, headers=None):
    """Return Retry-After when valid, otherwise capped exponential backoff with jitter."""
    if headers:
        value = headers.get("Retry-After")
        if value:
            try:
                return max(0.0, float(value))
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(value)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    pass
    return min(30.0, 2**attempt) + random.uniform(0.0, 0.25)


def validate_head(block, max_age, now=None):
    now = int(time.time()) if now is None else now
    age = now - int(block["timestamp"], 16)
    if age < -15 or age > max_age:
        raise ValueError("stale chain head")


class RpcClient:
    def __init__(self, url, chain_id, rps=5, daily_calls=10000, transport=None, store=None):
        self.store = store
        self.owns_store = False
        self._url = url
        self.chain_id = chain_id
        self.rps = rps
        self.daily_calls = daily_calls
        # calls counts actual HTTP request attempts, including provider retries.
        self.calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.retries = 0
        self.rate_limited_calls = 0
        self.methods = Counter()
        self.last_error = None
        self._day = int(time.time() // 86400)
        self._next = 0.0
        self._lock = asyncio.Lock()
        self._provider_cooldown_until = 0.0
        self._last_chain_check = 0.0
        self.chain_check_seconds = 300
        self.client = httpx.AsyncClient(timeout=15, transport=transport)

    def __repr__(self):
        return f"RpcClient(chain_id={self.chain_id})"

    async def close(self):
        await self.client.aclose()
        if self.owns_store:
            self.store.close()

    @staticmethod
    def utc_day():
        return int(time.time() // 86400)

    @staticmethod
    def quota_reset_timestamp(day=None):
        day = RpcClient.utc_day() if day is None else day
        return datetime.fromtimestamp((day + 1) * 86400, timezone.utc).isoformat()

    def usage_snapshot(self):
        day = self.utc_day()
        used = self.calls
        if self.store is not None:
            used = self.store.get_state(f"rpc-quota:{self.chain_id}:{day}", 0)
        return {
            "scope": "local_per_chain_utc_day",
            "day_utc": datetime.fromtimestamp(day * 86400, timezone.utc).date().isoformat(),
            "used": used,
            "limit": self.daily_calls,
            "remaining": max(0, self.daily_calls - used),
            "resets_at": self.quota_reset_timestamp(day),
            "http_attempts": self.calls,
            "successful": self.successful_calls,
            "failed": self.failed_calls,
            "retries": self.retries,
            "provider_rate_limits": self.rate_limited_calls,
            "methods": dict(self.methods),
        }

    async def _reserve_request(self, method):
        async with self._lock:
            now_mono = time.monotonic()
            if now_mono < self._provider_cooldown_until:
                raise RpcRateLimited(
                    "RPC provider cooldown active",
                    retry_after=self._provider_cooldown_until - now_mono,
                )
            day = self.utc_day()
            if day != self._day:
                self.calls = 0
                self._day = day
            if self.store is not None:
                with self.store.atomic():
                    key = f"rpc-quota:{self.chain_id}:{day}"
                    used = self.store.get_state(key, 0)
                    if used >= self.daily_calls:
                        raise RpcQuotaExceeded("RPC daily request limit reached")
                    self.store.set_state(key, used + 1)
            elif self.calls >= self.daily_calls:
                raise RpcQuotaExceeded("RPC daily request limit reached")
            await asyncio.sleep(max(0, self._next - time.monotonic()))
            self._next = time.monotonic() + 1 / self.rps
            self.calls += 1
            self.methods[method] += 1

    async def _backoff(self, delay):
        self.retries += 1
        await asyncio.sleep(delay)

    async def call(self, method, params):
        for attempt in range(3):
            await self._reserve_request(method)
            try:
                response = await self.client.post(
                    self._url,
                    json={"jsonrpc": "2.0", "id": self.calls, "method": method, "params": params},
                )
                if response.status_code == 429:
                    self.rate_limited_calls += 1
                    delay = _retry_delay(attempt, response.headers)
                    self._provider_cooldown_until = max(
                        self._provider_cooldown_until, time.monotonic() + delay
                    )
                    self.last_error = "provider_http_429"
                    if attempt == 2:
                        self.failed_calls += 1
                        raise RpcRateLimited(
                            "RPC provider rate limit (HTTP 429)", retry_after=delay
                        )
                    await self._backoff(delay)
                    continue
                if response.status_code >= 500:
                    if attempt == 2:
                        self.failed_calls += 1
                        self.last_error = f"provider_http_{response.status_code}"
                        raise RpcError(f"{method} RPC provider unavailable (HTTP {response.status_code})")
                    await self._backoff(_retry_delay(attempt))
                    continue
                if response.status_code >= 400:
                    self.failed_calls += 1
                    self.last_error = f"provider_http_{response.status_code}"
                    raise RpcError(f"{method} RPC provider rejected request (HTTP {response.status_code})")
                body = response.json()
                if "error" in body:
                    # Do not expose provider messages which may echo credential-bearing URLs.
                    code = body["error"].get("code", "unknown")
                    message = str(body["error"].get("message", "")).lower()
                    if code in (-32005, -32016, 429) or "rate limit" in message or "too many requests" in message:
                        self.rate_limited_calls += 1
                        delay = _retry_delay(attempt)
                        self._provider_cooldown_until = max(
                            self._provider_cooldown_until, time.monotonic() + delay
                        )
                        self.last_error = "provider_jsonrpc_rate_limit"
                        if attempt == 2:
                            self.failed_calls += 1
                            raise RpcRateLimited(
                                f"{method} RPC provider rate limit (JSON-RPC code {code})",
                                retry_after=delay,
                            )
                        await self._backoff(delay)
                        continue
                    self.failed_calls += 1
                    self.last_error = f"provider_jsonrpc_{code}"
                    raise RpcError(f"{method} RPC error code {code}")
                self.successful_calls += 1
                self.last_error = None
                return body["result"]
            except (RpcQuotaExceeded, RpcRateLimited):
                raise
            except RpcError:
                raise
            except httpx.HTTPStatusError as error:
                if attempt == 2:
                    self.failed_calls += 1
                    self.last_error = f"provider_http_{error.response.status_code}"
                    raise RpcError(
                        f"{method} RPC provider unavailable (HTTP {error.response.status_code})"
                    ) from None
                await self._backoff(_retry_delay(attempt, error.response.headers))
            except (httpx.HTTPError, ValueError, KeyError):
                if attempt == 2:
                    self.failed_calls += 1
                    self.last_error = "provider_transport_or_response_error"
                    raise RpcError(f"{method} unavailable after 3 attempts") from None
                await self._backoff(_retry_delay(attempt))

    async def contract_call(self, to, signature, types, args, outputs, block="latest"):
        data = Web3.keccak(text=signature)[:4] + encode(types, args)
        result = await self.call(
            "eth_call",
            [
                {"to": Web3.to_checksum_address(to), "data": "0x" + data.hex()},
                hex(block) if isinstance(block, int) else block,
            ],
        )
        return decode(outputs, bytes.fromhex(result[2:]))

    async def check_chain(self, force=False):
        if not force and time.monotonic() - self._last_chain_check < self.chain_check_seconds:
            return
        if int(await self.call("eth_chainId", []), 16) != self.chain_id:
            raise RpcError("wrong chain_id")
        self._last_chain_check = time.monotonic()

    async def head(self, max_age=60):
        await self.check_chain()
        head = await self.call("eth_getBlockByNumber", ["latest", False])
        validate_head(head, max_age)
        return head


def from_config(chain, app, store=None):
    url = os.environ.get(chain.rpc_env)
    if not url:
        raise RpcError(f"Missing {chain.rpc_env}")
    if not url.startswith(("http://127.0.0.1:", "http://localhost:", "https://")):
        raise RpcError("RPC must use HTTPS or local HTTP")
    owns_store = store is None
    if owns_store:
        from pathlib import Path
        from ..storage.db import Store

        store = Store(Path(app.data_dir) / "arbitrary.db")
    client = RpcClient(url, chain.chain_id, app.rpc_rps, app.rpc_daily_calls, store=store)
    client.owns_store = owns_store
    return client
