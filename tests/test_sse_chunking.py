"""Pure-logic guard for the streamed-answer chunker.

Regression: the fake token stream must NOT collapse whitespace. The answer is rendered as
Markdown on the client, so newlines (headings, list items, table rows, paragraph breaks) must
survive to the browser — a previous ``text.split()`` + ``" ".join()`` flattened everything onto
one line, so lists/headings/tables broke into a single blob with raw ``1.``/``-``/``|`` markers.
"""

from app.services.conversation_service import _chunk_tokens

_MARKDOWN = (
    "## Order statuses\n"
    "1. **Placed** — received.\n"
    "2. **Shipped** — on the way.\n"
    "\n"
    "| A | B |\n"
    "| --- | --- |\n"
    "| 1 | 2 |"
)


def test_chunker_is_lossless_and_preserves_newlines():
    rebuilt = "".join(_chunk_tokens(_MARKDOWN))
    assert rebuilt == _MARKDOWN          # exact reconstruction
    assert rebuilt.count("\n") == _MARKDOWN.count("\n")  # every newline survives


def test_chunker_emits_multiple_chunks_for_streaming():
    chunks = list(_chunk_tokens(_MARKDOWN, size=4))
    assert len(chunks) > 1               # actually streams in pieces
    assert all(c for c in chunks)        # no empty frames


def test_chunker_handles_empty_and_plain_text():
    assert list(_chunk_tokens("")) == []
    assert "".join(_chunk_tokens("just a plain sentence")) == "just a plain sentence"
