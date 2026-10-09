from decimal import Decimal as D
import pytest

def test_pending_budget_cannot_cross_daily_limit(tmp_path):
    from flasharb.storage.db import Store
    s=Store(tmp_path/'test.db')
    s.reserve('a',1,D('.70'),D('1'),D('1'),'2026-10-09')
    with pytest.raises(ValueError,match='budget'):s.reserve('b',1,D('.40'),D('1'),D('1'),'2026-10-09')

def test_midnight_keeps_pending_liability(tmp_path):
    from flasharb.storage.db import Store
    s=Store(tmp_path/'test.db');s.reserve('a',1,D('.70'),D('1'),D('1'),'2026-10-09')
    with pytest.raises(ValueError):s.reserve('b',1,D('.40'),D('1'),D('1'),'2026-10-10')

def test_failed_gas_reduces_net_and_idempotent(tmp_path):
    from flasharb.storage.db import Store
    s=Store(tmp_path/'test.db');s.reserve('a',1,D('.70'),D('1'),D('1'),'2026-10-09')
    s.settle('a',D('.20'),'2026-10-09');s.settle('a',D('.20'),'2026-10-09')
    assert s.spent('2026-10-09')==D('.20')
    with pytest.raises(ValueError):s.reserve('b',1,D('.81'),D('1'),D('1'),'2026-10-09')

def test_replacement_preserves_reservation(tmp_path):
    from flasharb.storage.db import Store
    s=Store(tmp_path/'test.db');s.reserve('a',1,D('.70'),D('1'),D('1'),'2026-10-09')
    s.reserve('a',1,D('.90'),D('1'),D('1'),'2026-10-09')
    with pytest.raises(ValueError):s.reserve('a',1,D('1.01'),D('1'),D('1'),'2026-10-09')
    assert s.reserved()==D('.90')

def test_reorg_restores_reservation(tmp_path):
    from flasharb.storage.db import Store
    s=Store(tmp_path/'test.db');s.reserve('a',1,D('.70'),D('1'),D('1'),'2026-10-09');s.settle('a',D('.20'),'2026-10-09');s.reopen('a')
    assert s.spent('2026-10-09')==0 and s.reserved()==D('.70')

def test_backup_restore_pending_intents(tmp_path):
    from flasharb.storage.db import Store
    s=Store(tmp_path/'test.db');s.reserve('a',1,D('.7'),D('1'),D('1'),'2026-10-09');s.backup(tmp_path/'backup.db')
    assert Store(tmp_path/'backup.db').reserved()==D('.7')
