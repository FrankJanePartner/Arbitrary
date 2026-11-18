import time
from decimal import Decimal, ROUND_CEILING
from ..models import ProfitDecision


def evaluate_profit(quote, premium, fees, conversion, policy, now=None, merchant_fee_bps=0):
    now = int(time.time()) if now is None else now
    gas = Decimal(fees.max_native_cost) * conversion.native_usd / 10**18
    if not 0 <= merchant_fee_bps <= 1000:
        raise ValueError("merchant fee outside permitted range")
    raw_surplus = quote.amount_out - quote.amount_in - premium
    merchant_fee = max(0, raw_surplus) * merchant_fee_bps // 10000
    surplus = (
        Decimal(raw_surplus - merchant_fee) * conversion.loan_usd / 10**conversion.loan_decimals
    )
    slip = Decimal(policy.slippage_bps) / 10000
    slippage_fraction = Decimal(1) - (Decimal(1) - slip) ** len(quote.route.hops)
    slippage_allowance = (
        Decimal(quote.amount_out) * slippage_fraction * conversion.loan_usd
        / 10**conversion.loan_decimals
    )
    net = surplus - gas - policy.safety_buffer_usd - slippage_allowance
    customer_threshold = (
        (gas + policy.safety_buffer_usd + slippage_allowance + policy.min_profit_usd)
        / conversion.loan_usd
        * 10**conversion.loan_decimals
    ).to_integral_value(rounding=ROUND_CEILING)
    customer_threshold = int(customer_threshold)
    # The contract checks the recipient's profit after paying the merchant.
    # Gross up the on-chain threshold so that the configured customer minimum
    # survives the merchant split, rounding down to integer token units.
    threshold = customer_threshold
    if merchant_fee_bps:
        threshold = (customer_threshold * 10000 + (10000 - merchant_fee_bps) - 1) // (
            10000 - merchant_fee_bps
        )
        while threshold > 0 and (threshold - 1) - (
            (threshold - 1) * merchant_fee_bps // 10000
        ) >= customer_threshold:
            threshold -= 1
    reasons = []
    if conversion.updated_at > now or now - conversion.updated_at > policy.price_max_age:
        reasons.append("stale_price")
    if gas > policy.max_tx_usd:
        reasons.append("transaction_budget")
    if net < policy.min_profit_usd:
        reasons.append("insufficient_profit")
    return ProfitDecision(
        eligible=not reasons,
        min_profit_token=threshold,
        expected_net_usd=net,
        gas_usd=gas,
        reasons=reasons,
        # Router quote output already reflects DEX swap fees and price impact.
        gross_usd=Decimal(quote.amount_out - quote.amount_in) * conversion.loan_usd / 10**conversion.loan_decimals,
        flash_loan_fee_usd=Decimal(premium) * conversion.loan_usd / 10**conversion.loan_decimals,
        merchant_fee_usd=Decimal(merchant_fee) * conversion.loan_usd / 10**conversion.loan_decimals,
        slippage_allowance_usd=slippage_allowance,
        safety_buffer_usd=policy.safety_buffer_usd,
        min_profit_usd=policy.min_profit_usd,
        slippage_tolerance_bps=policy.slippage_bps,
    )
