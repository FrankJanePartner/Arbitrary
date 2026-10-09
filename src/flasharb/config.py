import hashlib
import json
from pathlib import Path
import yaml
from web3 import Web3
from .models import AppConfig, ChainConfig, Route, VerificationReport

def check_registry(path: Path, expected: str):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('registry digest mismatch; reverify')

def load_config(path: Path) -> AppConfig:
    data=yaml.safe_load(path.read_text())
    lock=json.loads((path.parent/'registry.lock.json').read_text())
    chains=[]
    for name,digest in lock['files'].items():
        f=path.parent/name
        check_registry(f,digest)
        c=yaml.safe_load(f.read_text()); c['registry_digest']=digest
        chains.append(ChainConfig(**c))
    # Runtime overrides never replace trusted addresses or registry provenance.
    for c in chains:
        overrides=data.get('networks',{}).get(str(c.chain_id),{})
        for k,v in overrides.items():
            if k not in {'enabled','executor','executor_codehash','operator','owner','recipient','submission','private_rpc_env'}:
                raise ValueError('unsupported network override')
            setattr(c,k,v)
    data.pop('networks',None)
    return AppConfig(chains=chains,**data)

def validate_route(route: Route, tokens, routers):
    allowed={t.address.lower() for t in tokens}; venues={r.lower() for r in routers}
    for h in route.hops:
        if h.token_in.lower() not in allowed or h.token_out.lower() not in allowed or h.router.lower() not in venues:
            raise ValueError('route outside allowlist')

async def verify_chain(config: ChainConfig, rpc) -> VerificationReport:
    r=VerificationReport(chain_id=config.chain_id)
    if int(await rpc.call('eth_chainId',[]),16)!=config.chain_id:
        r.blockers.append('chain_id'); return r
    r.block_number=int(await rpc.call('eth_blockNumber',[]),16)
    addresses={'provider':config.provider,'pool':config.pool,'oracle':config.oracle}
    for t in config.tokens:
        addresses['token:'+t.symbol]=t.address
        if t.oracle: addresses['feed:'+t.symbol]=t.oracle
    for v in config.venues:
        for k in ['factory','router','quoter']:
            if getattr(v,k): addresses[v.name+':'+k]=getattr(v,k)
    for label,address in addresses.items():
        code=await rpc.call('eth_getCode',[address,hex(r.block_number)])
        if code in ('0x','0x0'): r.blockers.append(label+':no_code')
        else: r.checks[label]=Web3.keccak(hexstr=code).hex()
    selector='0x'+Web3.keccak(text='getPool()')[:4].hex()
    current=await rpc.call('eth_call',[{'to':config.provider,'data':selector},hex(r.block_number)])
    if current[-40:].lower()!=config.pool[2:].lower(): r.blockers.append('pool_registry_drift')
    return r
