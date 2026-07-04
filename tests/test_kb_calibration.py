"""Provisional grounding-threshold calibration (M3 Phase 1, marked ``rls``).

Ingests the eval corpus, runs the REAL hybrid pipeline for every eval query with the gate opened
(threshold=0) to capture the top-1 rerank score, and asserts on-topic and off-topic scores are
cleanly separable — validating that ``PROVISIONAL_THRESHOLD`` sits between them. Prints the score
distribution + a suggested cutoff. Real BGE calibration (different score scale) is Phase 2.
"""

from __future__ import annotations

import pytest

from app.services.knowledge_service import (
    NO_GROUNDING,
    PROVISIONAL_THRESHOLD,
    GroundedResult,
    kb_retrieve,
)
from app.infra.db.session import with_tenant
from tests.fixtures.kb_eval import EVAL_PAIRS, ingest_corpus, make_tenant

pytestmark = pytest.mark.rls


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    from app.infra.db.engine import engine

    await engine.dispose()
    yield
    await engine.dispose()


async def test_threshold_separates_on_and_off_topic(capsys):
    tenant = await make_tenant("kb-calibration")
    await ingest_corpus(tenant)

    on_scores: list[float] = []
    off_scores: list[float] = []
    async with with_tenant(tenant) as session:
        for query, should_answer, _expected in EVAL_PAIRS:
            # threshold=0 opens the gate so we always get a top-1 score to inspect.
            result = await kb_retrieve(session, query, threshold=0.0)
            score = result.top_score if isinstance(result, GroundedResult) else 0.0
            (on_scores if should_answer else off_scores).append(score)

    min_on, max_off = min(on_scores), max(off_scores)
    suggested = round((min_on + max_off) / 2, 3)
    with capsys.disabled():
        print(f"\n[calibration] on-topic  min/scores = {min_on:.3f} {['%.2f' % s for s in on_scores]}")
        print(f"[calibration] off-topic max/scores = {max_off:.3f} {['%.2f' % s for s in off_scores]}")
        print(f"[calibration] suggested threshold ~ {suggested}  (current PROVISIONAL={PROVISIONAL_THRESHOLD})")

    # On-topic clearly outscores off-topic, and the provisional default sits between them.
    assert min_on > max_off, "on/off-topic scores must be separable"
    assert max_off < PROVISIONAL_THRESHOLD <= min_on


async def test_provisional_threshold_answers_on_topic_refuses_off_topic():
    # End-to-end with the REAL provisional gate (not opened): on-topic grounds, off-topic refuses.
    tenant = await make_tenant("kb-gate")
    await ingest_corpus(tenant)
    async with with_tenant(tenant) as session:
        for query, should_answer, _ in EVAL_PAIRS:
            result = await kb_retrieve(session, query)
            grounded = isinstance(result, GroundedResult)
            assert grounded is should_answer, f"{query!r} expected answer={should_answer}, got {result}"
            if not grounded:
                assert result == NO_GROUNDING
