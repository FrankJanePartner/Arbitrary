import json
from pathlib import Path
from eth_account import Account

class Signer:
    def __init__(self,account):self._account=account;self.address=account.address
    def __repr__(self):return f'Signer(address={self.address})'
    @classmethod
    def unlock(cls,path:Path,password:str):
        try:return cls(Account.from_key(Account.decrypt(json.loads(path.read_text()),password)))
        except Exception:raise ValueError('Unable to unlock keystore') from None
    def sign_transaction(self,tx):return self._account.sign_transaction(tx)
