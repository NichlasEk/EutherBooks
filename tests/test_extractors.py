from __future__ import annotations

from eutherbooks.extractors import clean_html_text, split_plain_text


def test_clean_html_text_removes_markup_and_decodes_entities() -> None:
    text = clean_html_text("<h1>Titel</h1><p>En &aring; rad.</p><script>bad()</script>")

    assert text == "Titel En å rad."


def test_split_plain_text_chunks_long_input() -> None:
    text = "\n\n".join(["A" * 2_000, "B" * 2_000, "C" * 2_000])

    chapters = split_plain_text(text, chunk_size=3_000)

    assert len(chapters) == 3
    assert chapters[0].index == 0

