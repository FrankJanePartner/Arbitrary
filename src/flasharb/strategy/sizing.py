async def optimize_size(route,limits,block,quote,liquidity,premium_bps=0):
    low=limits.min_loan;high=min(limits.max_loan,liquidity)
    if high<low:raise ValueError('insufficient flash liquidity')
    sizes=sorted({low+(high-low)*i//(limits.size_samples-1) for i in range(limits.size_samples)})
    best=None;score=None
    for amount in sizes:
        candidate=await quote(route,amount,block)
        value=candidate.amount_out-amount-(amount*premium_bps+9999)//10000
        if score is None or value>score:best=candidate;score=value
    return best
