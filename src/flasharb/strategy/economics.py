import time
from decimal import Decimal, ROUND_CEILING
from ..models import ProfitDecision


def evaluate_profit(quote, premium, fees, conversion, policy, now=None):
    now = int(time.time()) if now is None else now
    gas = Decimal(fees.max_native_cost) * conversion.native_usd / 10**18
    surplus = (
        Decimal(quote.amount_out - quote.amount_in - premium)
        * conversion.loan_usd
        / 10**conversion.loan_decimals
    )
    net = surplus - gas - policy.safety_buffer_usd
    threshold = (
        (gas + policy.safety_buffer_usd + policy.min_profit_usd)
        / conversion.loan_usd
        * 10**conversion.loan_decimals
    ).to_integral_value(rounding=ROUND_CEILING)
    reasons = []
    if conversion.updated_at > now or now - conversion.updated_at > policy.price_max_age:
        reasons.append("stale_price")
    if gas > policy.max_tx_usd:
        reasons.append("transaction_budget")
    if net < policy.min_profit_usd:
        reasons.append("insufficient_profit")
    return ProfitDecision(
        eligible=not reasons,
        min_profit_token=int(threshold),
        expected_net_usd=net,
        gas_usd=gas,
        reasons=reasons,
    )
