"""Pure chunking unit tests (M3, Phase 1) — no DB, runs under ``make test``."""

from __future__ import annotations

from app.core.config import TenantDefaults
from app.domain.knowledge.chunking import (
    ChildChunk,
    ParentChunk,
    chunk_document,
    normalize_text,
    split_children,
    split_parents,
    token_count,
)

MAX_T = TenantDefaults.CHILD_CHUNK_MAX_TOKENS
MIN_T = TenantDefaults.CHILD_CHUNK_MIN_TOKENS
PARENT_T = TenantDefaults.PARENT_CHUNK_TOKENS


def _words(n: int) -> str:
    return " ".join(f"w{i}" for i in range(n))


def test_empty_and_whitespace_yield_no_chunks():
    assert chunk_document("") == []
    assert chunk_document("   \n\n  \t ") == []
    assert split_parents("") == []
    assert split_children("") == []


def test_normalize_text_crlf_trailing_and_blank_runs():
    raw = "line one   \r\nline two\r\n\r\n\r\n\r\npara two"
    out = normalize_text(raw)
    assert "\r" not in out
    assert "line one\nline two" in out  # trailing spaces stripped
    assert "\n\n\n" not in out  # 3+ blank lines collapsed to one gap


def test_short_document_is_a_single_parent_single_child():
    text = _words(120)
    parents = chunk_document(text)
    assert len(parents) == 1
    assert len(parents[0].children) == 1
    assert token_count(parents[0].children[0].content) == 120


def test_child_windows_have_overlap_and_are_within_bounds():
    # 900 words in one paragraph -> two children with ~15% overlap.
    children = split_children(_words(900))
    assert len(children) == 2
    lens = [token_count(c) for c in children]
    assert lens[0] == MAX_T  # 500
    assert MIN_T <= lens[1] <= MAX_T  # 475
    # Overlap: the tail of child 0 reappears at the head of child 1.
    step = MAX_T - round(MAX_T * TenantDefaults.CHILD_CHUNK_OVERLAP_PCT)  # 425
    overlap = MAX_T - step  # 75
    assert children[0].split()[-overlap:] == children[1].split()[:overlap]


def test_trailing_sliver_is_merged_not_emitted():
    # 550 words: naive windows would be 500 + 50; the 50-word sliver (< MIN_T) must merge.
    children = split_children(_words(550))
    assert all(token_count(c) >= MIN_T for c in children)
    assert len(children) == 1
    assert token_count(children[0]) == 550  # extended to the end


def test_oversized_paragraph_is_hard_split_into_parents():
    # A single 4500-word paragraph exceeds the 2000 parent budget -> multiple parents.
    parents = split_parents(_words(4500))
    assert len(parents) == 3  # 2000 + 2000 + 500
    assert [token_count(p) for p in parents] == [PARENT_T, PARENT_T, 500]


def test_multiple_paragraphs_accumulate_into_parents():
    # Three ~800-word paragraphs -> first two fit one parent (1600), third opens a new parent.
    doc = "\n\n".join([_words(800), _words(800), _words(800)])
    parents = split_parents(doc)
    assert len(parents) == 2
    assert token_count(parents[0]) >= 1600  # two paras joined
    assert token_count(parents[1]) == 800


def test_child_order_is_monotonic_across_parents():
    # Two 1500-word paragraphs (1500+1500 > 2000 budget) -> two separate parents, each with
    # multiple children, so we can prove order stays monotonic across the parent boundary.
    doc = "\n\n".join([_words(1500), _words(1500)])
    parents = chunk_document(doc)
    assert len(parents) == 2
    assert all(len(p.children) > 1 for p in parents)
    orders = [c.order for p in parents for c in p.children]
    assert orders == list(range(len(orders)))  # 0,1,2,... no gaps, no repeats
    # parent_index is set correctly on each child
    assert parents[0].children[0].parent_index == 0
    assert parents[1].children[0].parent_index == 1


def test_dataclass_shapes():
    p = chunk_document(_words(50))[0]
    assert isinstance(p, ParentChunk)
    assert isinstance(p.children[0], ChildChunk)
    assert p.index == 0


# --- structure-aware chunking (IMP-RAG-3) ---------------------------------------------------

def test_markdown_table_kept_atomic():
    table = "| Name | Days |\n| --- | --- |\n| Returns | 30 |\n| Warranty | 365 |"
    parents = chunk_document(table)
    assert len(parents) == 1
    assert len(parents[0].children) == 1  # not split
    assert "| Returns | 30 |" in parents[0].children[0].content


def test_list_kept_intact():
    lst = "\n".join(f"- item number {i}" for i in range(20))
    parents = chunk_document(lst)
    assert len(parents) == 1 and len(parents[0].children) == 1
    assert parents[0].children[0].content.count("- item number") == 20


def test_large_table_splits_repeating_header():
    header = "| id | value |\n| --- | --- |"
    rows = "\n".join(f"| {i} | {'word ' * 20}|" for i in range(60))  # > CHILD_MAX words total
    parents = chunk_document(header + "\n" + rows)
    children = parents[0].children
    assert len(children) > 1
    assert all("| id | value |" in c.content for c in children)  # header repeated in each piece


def test_table_between_prose_is_a_separate_parent():
    doc = "Intro about returns.\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\nOutro about shipping."
    parents = chunk_document(doc)
    assert len(parents) == 3  # prose | table | prose
    assert "Intro" in parents[0].content
    assert "| 1 | 2 |" in parents[1].content
    assert "Outro" in parents[2].content
