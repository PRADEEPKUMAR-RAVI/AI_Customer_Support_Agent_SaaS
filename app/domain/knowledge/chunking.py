"""Structure-agnostic parent-child chunking (M3, Phase 1).

Splits normalized document text into ~2k-token **parents**, each split into overlapping
~300-500-token **children**. Children are what we embed + retrieve; the parent is expanded back
in as answer context at retrieval time. Token count is approximated as word count
(``len(text.split())``) so there's no tokenizer dependency — good enough for chunk sizing.

Sizes come from ``TenantDefaults`` so the whole team tunes one place:
``PARENT_CHUNK_TOKENS=2000``, ``CHILD_CHUNK_MIN_TOKENS=300``, ``CHILD_CHUNK_MAX_TOKENS=500``,
``CHILD_CHUNK_OVERLAP_PCT=0.15``.

Deferred to Phase 2 (see plan): structure-aware chunking that keeps tables/lists atomic
(``IMP-RAG-3``). Phase 1 is plain prose windowing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.config import TenantDefaults

_MULTI_BLANK = re.compile(r"\n{3,}")
_TABLE_LINE = re.compile(r"^\s*\|")
_LIST_LINE = re.compile(r"^\s*([-*+]|\d+[.)])\s+")


@dataclass
class ChildChunk:
    """An embeddable leaf chunk. ``order`` is monotonic across the whole document."""

    content: str
    order: int
    parent_index: int


@dataclass
class ParentChunk:
    """A ~2k-token block. Not embedded; expanded into answer context via its children."""

    content: str
    index: int
    children: list[ChildChunk] = field(default_factory=list)


def token_count(text: str) -> int:
    """Approximate tokens as whitespace-delimited words (no tokenizer dependency)."""
    return len(text.split())


def normalize_text(raw: str) -> str:
    """CRLF -> LF, strip per-line trailing whitespace, collapse 3+ blank lines to one gap."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()


def _hard_split_words(text: str, size: int) -> list[str]:
    """Split a too-large block into ``size``-word pieces (last piece may be smaller)."""
    words = text.split()
    return [" ".join(words[i : i + size]) for i in range(0, len(words), size)]


def split_parents(text: str) -> list[str]:
    """Greedy-accumulate paragraphs into ~PARENT_CHUNK_TOKENS-word parents.

    A single paragraph larger than the parent budget is hard-split by words so no parent
    grossly exceeds the budget. Empty/whitespace input -> ``[]``.
    """
    text = normalize_text(text)
    if not text:
        return []

    budget = TenantDefaults.PARENT_CHUNK_TOKENS
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    parents: list[str] = []
    current: list[str] = []
    current_tokens = 0

    def _flush() -> None:
        nonlocal current, current_tokens
        if current:
            parents.append("\n\n".join(current))
            current, current_tokens = [], 0

    for para in paragraphs:
        ptok = token_count(para)
        if ptok > budget:
            _flush()
            parents.extend(_hard_split_words(para, budget))
            continue
        if current and current_tokens + ptok > budget:
            _flush()
        current.append(para)
        current_tokens += ptok
    _flush()
    return parents


def split_children(parent: str) -> list[str]:
    """Sliding word-window children over one parent, with overlap.

    Window = CHILD_CHUNK_MAX_TOKENS; step = window - round(window * overlap_pct) (=425 for the
    500/0.15 defaults), giving ~15% overlap. A trailing sliver shorter than
    CHILD_CHUNK_MIN_TOKENS is merged into the previous child (extending it to the end) so we
    never emit a tiny fragment.
    """
    words = parent.split()
    n = len(words)
    if n == 0:
        return []

    max_t = TenantDefaults.CHILD_CHUNK_MAX_TOKENS
    min_t = TenantDefaults.CHILD_CHUNK_MIN_TOKENS
    step = max_t - round(max_t * TenantDefaults.CHILD_CHUNK_OVERLAP_PCT)
    if n <= max_t:
        return [" ".join(words)]

    starts: list[int] = []
    i = 0
    while True:
        starts.append(i)
        if i + max_t >= n:
            break
        i += step

    children = [" ".join(words[s : min(s + max_t, n)]) for s in starts]

    # Merge a too-short trailing window into the previous child (extend it to the document end).
    if len(children) >= 2 and (n - starts[-1]) < min_t:
        children[-2] = " ".join(words[starts[-2] : n])
        children.pop()
    return children


def _block_kind(block: str) -> str:
    """Classify a blank-line-delimited block as ``table``, ``list``, or ``prose`` (IMP-RAG-3)."""
    lines = [ln for ln in block.splitlines() if ln.strip()]
    if not lines:
        return "prose"
    threshold = max(2, len(lines) * 0.6)
    if sum(1 for ln in lines if _TABLE_LINE.match(ln)) >= threshold:
        return "table"
    if sum(1 for ln in lines if _LIST_LINE.match(ln)) >= threshold:
        return "list"
    return "prose"


def _split_table(table: str) -> list[str]:
    """Keep a table atomic; if it exceeds the child budget, split by rows and REPEAT the header
    (+ separator) row into each piece so every chunk is self-describing."""
    if token_count(table) <= TenantDefaults.CHILD_CHUNK_MAX_TOKENS:
        return [table]
    lines = [ln for ln in table.splitlines() if ln.strip()]
    header = [lines[0]]
    body_start = 1
    if len(lines) > 1 and set(lines[1].replace("|", "").strip()) <= set("-: "):
        header.append(lines[1])  # markdown separator row
        body_start = 2

    pieces: list[str] = []
    current = list(header)
    for row in lines[body_start:]:
        current.append(row)
        if token_count("\n".join(current)) >= TenantDefaults.CHILD_CHUNK_MAX_TOKENS:
            pieces.append("\n".join(current))
            current = list(header)  # repeat header in the next piece
    if len(current) > len(header):
        pieces.append("\n".join(current))
    return pieces or [table]


def chunk_document(text: str) -> list[ParentChunk]:
    """Full pipeline: normalized text -> parents -> children, with a monotonic child order.
    Structure-aware (IMP-RAG-3): markdown tables stay atomic (header repeated on any split) and
    lists stay intact; each becomes its own parent, while consecutive prose windows as before."""
    normalized = normalize_text(text)
    if not normalized:
        return []

    parents: list[tuple[str, str]] = []  # (text, kind)
    prose_buffer: list[str] = []

    def _flush_prose() -> None:
        if prose_buffer:
            for parent_text in split_parents("\n\n".join(prose_buffer)):
                parents.append((parent_text, "prose"))
            prose_buffer.clear()

    for block in (b for b in normalized.split("\n\n") if b.strip()):
        kind = _block_kind(block)
        if kind == "prose":
            prose_buffer.append(block)
        else:
            _flush_prose()
            parents.append((block, kind))
    _flush_prose()

    result: list[ParentChunk] = []
    order = 0
    for index, (parent_text, kind) in enumerate(parents):
        if kind == "table":
            child_texts = _split_table(parent_text)
        elif kind == "list":
            child_texts = [parent_text]  # keep the list intact
        else:
            child_texts = split_children(parent_text)
        children: list[ChildChunk] = []
        for child_text in child_texts:
            children.append(ChildChunk(content=child_text, order=order, parent_index=index))
            order += 1
        result.append(ParentChunk(content=parent_text, index=index, children=children))
    return result
