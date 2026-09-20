"""Replay check: the same stored input gives the same canonical digest in another process (SW14.7).

Each stage runs in its own process under two hash seeds and with the input rows unshuffled and shuffled two ways.
This shows code behavior on SYNTHETIC input; it says nothing about model output, which is audited by being stored.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from determinism_stages import STAGES

REPO_ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = [(seed, shuffle) for seed in ("1", "2") for shuffle in (None, 1, 2)]


def digest(stage: str, hash_seed: str, shuffle: int | None) -> str:
    command = [sys.executable, str(Path(__file__).parent / "determinism_stages.py"), stage]
    if shuffle is not None:
        command += ["--shuffle", str(shuffle)]
    env = os.environ | {"PYTHONHASHSEED": hash_seed, "PYTHONPATH": f"{REPO_ROOT / 'backend'}:{REPO_ROOT / 'tests'}"}
    result = subprocess.run(command, capture_output=True, text=True, env=env, cwd=REPO_ROOT, check=True)
    return result.stdout.strip()


@pytest.mark.parametrize("stage", sorted(STAGES))
def test_a_stage_gives_one_digest_under_two_hash_seeds_and_two_row_orders(stage):
    digests = {(seed, shuffle): digest(stage, seed, shuffle) for seed, shuffle in CONDITIONS}
    assert len(set(digests.values())) == 1, digests


def test_a_fused_score_tie_is_broken_by_the_record_identifier_not_by_argument_order():
    from deixis.workflow.flow import fuse_rankings

    a = [{"id": "psg_b"}, {"id": "psg_a"}]
    b = [{"id": "psg_a"}, {"id": "psg_b"}]  # the same two rows, opposed: both end on the same fused score
    assert [r["id"] for r in fuse_rankings(a, b)] == [r["id"] for r in fuse_rankings(b, a)] == ["psg_a", "psg_b"]
