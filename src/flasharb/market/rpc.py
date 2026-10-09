import asyncio
import os
import time
from decimal import Decimal
import httpx
from eth_abi import encode,decode
from web3 import Web3

class RpcError(RuntimeError): pass

def validate_head(block, max_age, now=None):
    now=int(time.time()) if now is None else now
    age=now-int(block['timestamp'],16)
    if age< -15 or age>max_age: raise ValueError('stale chain head')

class RpcClient:
    def __init__(self,url,chain_id,rps=5,daily_calls=10000,transport=None):
        self._url=url;self.chain_id=chain_id;self.rps=rps;self.daily_calls=daily_calls
        self.calls=0;self._day=int(time.time()//86400);self._next=0.;self._lock=asyncio.Lock()
        self.client=httpx.AsyncClient(timeout=15,transport=transport)
    def __repr__(self): return f'RpcClient(chain_id={self.chain_id})'
    async def close(self): await self.client.aclose()
    async def call(self,method,params):
        for attempt in range(3):
            async with self._lock:
                day=int(time.time()//86400)
                if day!=self._day:self.calls=0;self._day=day
                if self.calls>=self.daily_calls:raise RpcError('RPC daily request limit reached')
                await asyncio.sleep(max(0,self._next-time.monotonic()))
                self._next=time.monotonic()+1/self.rps;self.calls+=1
            try:
                response=await self.client.post(self._url,json={'jsonrpc':'2.0','id':self.calls,'method':method,'params':params})
                response.raise_for_status();body=response.json()
                if 'error' in body:
                    # Do not expose provider messages which may echo credential-bearing URLs.
                    raise RpcError(f'{method} RPC error code {body["error"].get("code","unknown")}')
                return body['result']
            except RpcError: raise
            except (httpx.HTTPError,ValueError,KeyError):
                if attempt==2:raise RpcError(f'{method} unavailable after 3 attempts') from None
                await asyncio.sleep(2**attempt)
    async def contract_call(self,to,signature,types,args,outputs,block='latest'):
        data=Web3.keccak(text=signature)[:4]+encode(types,args)
        result=await self.call('eth_call',[{'to':Web3.to_checksum_address(to),'data':'0x'+data.hex()},hex(block) if isinstance(block,int) else block])
        return decode(outputs,bytes.fromhex(result[2:]))
    async def check_chain(self):
        if int(await self.call('eth_chainId',[]),16)!=self.chain_id:raise RpcError('wrong chain_id')
    async def head(self,max_age=60):
        await self.check_chain();head=await self.call('eth_getBlockByNumber',['latest',False]);validate_head(head,max_age);return head

def from_config(chain,app):
    url=os.environ.get(chain.rpc_env)
    if not url:raise RpcError(f'Missing {chain.rpc_env}')
    if not url.startswith(('http://127.0.0.1:','http://localhost:','https://')):raise RpcError('RPC must use HTTPS or local HTTP')
    return RpcClient(url,chain.chain_id,app.rpc_rps,app.rpc_daily_calls)
