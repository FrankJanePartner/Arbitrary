async def optimize_size(route, limits, block, quote, liquidity, premium_bps=0, sample_count=None):
    low = limits.min_loan
    high = min(limits.max_loan, liquidity)
    if high < low:
        raise ValueError("insufficient flash liquidity")
    samples = limits.size_samples if sample_count is None else max(
        1, min(sample_count, limits.size_samples)
    )
    sizes = sorted(
        {low + (high - low) * i // (samples - 1) for i in range(samples)}
        if samples > 1
        else {low}
    )
    best = None
    score = None
    for amount in sizes:
        candidate = await quote(route, amount, block)
        value = candidate.amount_out - amount - (amount * premium_bps + 9999) // 10000
        if score is None or value > score:
            best = candidate
            score = value
    return best
