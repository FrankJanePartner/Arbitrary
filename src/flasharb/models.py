from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from web3 import Web3


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Token(Model):
    address: str
    symbol: str
    decimals: int = Field(ge=0, le=36)
    oracle: str | None = None
    loan: bool = False

    @field_validator("address", "oracle")
    @classmethod
    def address_valid(cls, v):
        if v is None:
            return v
        if not Web3.is_address(v) or int(v, 16) == 0:
            raise ValueError("invalid address")
        return Web3.to_checksum_address(v)


class RpcSettings(Model):
    url: SecretStr


class Venue(Model):
    name: str
    kind: Literal[0, 1, 2]  # 0=V2, 1=V3 original router, 2=V3 SwapRouter02
    factory: str
    router: str
    quoter: str | None = None
    fee_tiers: list[int] = [500, 3000, 10000]


class ChainConfig(Model):
    name: str
    chain_id: int
    native_symbol: str
    rpc_env: str
    provider: str
    pool: str
    oracle: str
    native_token: str
    tokens: list[Token]
    venues: list[Venue]
    enabled: bool = False
    executor: str | None = None
    executor_codehash: str | None = None
    recipient: str | None = None
    operator: str | None = None
    owner: str | None = None
    confirmations: int = Field(default=12, ge=1)
    max_head_age: int = Field(default=60, ge=1)
    fee_model: Literal["evm", "arbitrum", "op"] = "evm"
    private_rpc_env: str | None = None
    submission: Literal["public", "private"] = "public"
    registry_digest: str = ""


class Policy(Model):
    min_loan: int = Field(default=100_000_000, gt=0)
    max_loan: int = Field(default=10_000_000_000, gt=0)
    size_samples: int = Field(default=8, ge=2, le=32)
    min_profit_usd: Decimal = Field(default=Decimal("0.25"), ge=0)
    safety_buffer_usd: Decimal = Field(default=Decimal("0.10"), ge=0)
    max_tx_usd: Decimal = Field(default=Decimal("0.10"), gt=0)
    daily_usd: Decimal = Field(default=Decimal("1"), gt=0)
    global_daily_usd: Decimal = Field(default=Decimal("1"), gt=0)
    low_balance_usd: Decimal = Field(default=Decimal("5"), ge=0)
    slippage_bps: int = Field(default=20, ge=0, le=500)
    deadline_seconds: int = Field(default=30, ge=5, le=120)
    price_max_age: int = Field(default=300, ge=1)
    max_route_quotes: int = Field(default=24, ge=1, le=100)

    @model_validator(mode="after")
    def bounds(self):
        if self.min_loan > self.max_loan:
            raise ValueError("loan bounds reversed")
        return self


class AppConfig(Model):
    chains: list[ChainConfig]
    policy: Policy = Field(default_factory=Policy)
    mode: Literal["observe", "simulate", "live"] = "observe"
    data_dir: str = "data"
    timezone: str = "Africa/Lagos"
    poll_seconds: int = Field(default=12, ge=1)
    rpc_rps: int = Field(default=5, ge=1, le=15)
    rpc_daily_calls: int = Field(default=10000, ge=1)


class Hop(Model):
    kind: Literal[0, 1, 2]
    router: str
    pool: str
    token_in: str
    token_out: str
    fee: int = Field(default=0, ge=0, le=1_000_000)
    min_out: int = Field(default=0, ge=0)

    def abi_tuple(self):
        return (
            self.kind,
            Web3.to_checksum_address(self.router),
            Web3.to_checksum_address(self.token_in),
            Web3.to_checksum_address(self.token_out),
            self.fee,
            self.min_out,
        )


class Route(Model):
    chain_id: int
    hops: list[Hop] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def closed(self):
        for a, b in zip(self.hops, self.hops[1:] + self.hops[:1]):
            if a.token_out.lower() != b.token_in.lower():
                raise ValueError("route is not continuous and closed")
        if len({h.pool.lower() for h in self.hops}) != len(self.hops):
            raise ValueError("repeated pool")
        return self


class Pool(Model):
    address: str
    token0: str
    token1: str
    venue: Venue
    fee: int = 0


class Quote(Model):
    route: Route
    block_number: int
    amount_in: int = Field(gt=0)
    amount_out: int = Field(ge=0)
    hop_outputs: list[int]


class FeeEstimate(Model):
    gas_limit: int = Field(gt=0)
    max_fee_per_gas: int = Field(gt=0)
    priority_fee: int = Field(ge=0)
    max_native_cost: int = Field(gt=0)
    expected_native_cost: int = Field(gt=0)
    components: dict[str, int]


class PricePoint(Model):
    native_usd: Decimal = Field(gt=0)
    loan_usd: Decimal = Field(gt=0)
    updated_at: int
    loan_decimals: int


class ProfitDecision(Model):
    eligible: bool
    min_profit_token: int
    expected_net_usd: Decimal
    gas_usd: Decimal
    reasons: list[str]


class Intent(Model):
    id: str
    chain_id: int
    operator: str
    nonce: int = Field(ge=0)
    executor: str
    asset: str
    amount: int = Field(gt=0)
    route: Route
    min_profit_token: int = Field(ge=0)
    deadline: int
    block_number: int


class VerificationReport(Model):
    chain_id: int
    block_number: int = 0
    blockers: list[str] = []
    checks: dict[str, str] = {}

    @property
    def ok(self):
        return not self.blockers


class SimulationResult(Model):
    ok: bool
    block_number: int
    reason: str = ""


class Submission(Model):
    intent_id: str
    tx_hash: str
    status: str


class ReceiptRecord(Model):
    tx_hash: str
    block_number: int
    block_hash: str
    success: bool
    gas_native: int
    profit_token: int = 0
    recipient: str | None = None
