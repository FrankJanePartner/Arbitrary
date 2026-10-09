from itertools import combinations
from web3 import Web3
from ..models import Pool

async def discover_pools(config,rpc,block):
    result=[]
    for venue in config.venues:
        for a,b in combinations(config.tokens,2):
            for fee in (venue.fee_tiers if venue.kind else [0]):
                if venue.kind:
                    (address,)=await rpc.contract_call(venue.factory,'getPool(address,address,uint24)',['address','address','uint24'],[a.address,b.address,fee],['address'],block)
                else:
                    (address,)=await rpc.contract_call(venue.factory,'getPair(address,address)',['address','address'],[a.address,b.address],['address'],block)
                if int(address,16)==0:continue
                address=Web3.to_checksum_address(address)
                (t0,)=await rpc.contract_call(address,'token0()',[],[],['address'],block)
                (t1,)=await rpc.contract_call(address,'token1()',[],[],['address'],block)
                if {t0.lower(),t1.lower()}!={a.address.lower(),b.address.lower()}:raise ValueError('pool token mismatch')
                result.append(Pool(address=address,token0=t0,token1=t1,venue=venue,fee=fee))
    return result
