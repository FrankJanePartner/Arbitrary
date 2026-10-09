import pytest
from eth_account import Account
from decimal import Decimal

def test_keystore_requires_unlock(tmp_path):
    from flasharb.execution.signer import Signer
    a=Account.create();p=tmp_path/'key.json';p.write_text(__import__('json').dumps(Account.encrypt(a.key,'test password',kdf='pbkdf2',iterations=1000)))
    with pytest.raises(ValueError):Signer.unlock(p,'wrong')
    s=Signer.unlock(p,'test password');assert s.address==a.address
    assert a.key.hex() not in repr(s)

@pytest.mark.asyncio
async def test_ambiguous_timeout_reuses_hash(tmp_path):
    from flasharb.execution.transactions import TransactionManager
    from flasharb.execution.signer import Signer
    from flasharb.storage.db import Store
    from flasharb.models import FeeEstimate
    class RPC:
        raws=[]
        async def call(self,m,p):
            if m=='eth_sendRawTransaction':self.raws.append(p[0]);raise RuntimeError('timeout')
            if m=='eth_getTransactionReceipt':return None
            if m=='eth_getTransactionCount':return '0x0'
            if m=='eth_chainId':return '0x1'
    rpc=RPC();s=Store(tmp_path/'db');signer=Signer(Account.create());tm=TransactionManager(s,rpc,signer,1)
    tx={'chainId':1,'nonce':0,'to':'0x'+'11'*20,'value':0,'data':'0x','gas':21000,'maxFeePerGas':2,'maxPriorityFeePerGas':1,'type':2}
    result=await tm.submit_transaction('a',tx,Decimal('.1'),Decimal('1'),Decimal('1'),'2026-10-09',{})
    assert result.status=='unknown'
    row=s.execution('a');assert row['tx_hash']==result.tx_hash and row['raw_tx']==rpc.raws[0]
    await tm.rebroadcast('a')
    assert rpc.raws[0]==rpc.raws[1]
    with pytest.raises(ValueError,match='unresolved'):await tm.submit_transaction('b',tx,Decimal('.1'),Decimal('1'),Decimal('1'),'2026-10-09',{})
