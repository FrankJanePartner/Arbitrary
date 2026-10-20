import runpy
from types import SimpleNamespace

import pytest


select_chains = runpy.run_path("scripts/run-forks.py")["select_chains"]


def test_fork_runner_selects_requested_chain_only():
    chains = [SimpleNamespace(chain_id=1), SimpleNamespace(chain_id=42161)]

    assert select_chains(chains, 42161) == [chains[1]]


def test_fork_runner_defaults_to_all_chains():
    chains = [SimpleNamespace(chain_id=1), SimpleNamespace(chain_id=42161)]

    assert select_chains(chains) == chains


def test_fork_runner_rejects_unconfigured_chain():
    with pytest.raises(ValueError, match="Chain 10 is not configured"):
        select_chains([SimpleNamespace(chain_id=1)], 10)
