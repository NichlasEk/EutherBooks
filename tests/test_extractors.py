from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

from eutherbooks.extractors import clean_html_text, extract_pdf, pdf_margin_cleanup_preview, split_plain_text


def test_clean_html_text_removes_markup_and_decodes_entities() -> None:
    text = clean_html_text("<h1>Titel</h1><p>En &aring; rad.</p><script>bad()</script>")

    assert text == "Titel En å rad."


def test_split_plain_text_chunks_long_input() -> None:
    text = "\n\n".join(["A" * 2_000, "B" * 2_000, "C" * 2_000])

    chapters = split_plain_text(text, chunk_size=3_000)

    assert len(chapters) == 3
    assert chapters[0].index == 0


def test_extract_pdf_uses_pdftotext(monkeypatch, tmp_path: Path) -> None:
    book_path = tmp_path / "bok.pdf"
    book_path.write_bytes(b"%PDF-1.4")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        calls.append(command)
        return CompletedProcess(command, 0, stdout="Kapitel 1\n\nText från PDF.", stderr="")

    monkeypatch.setattr("eutherbooks.extractors.subprocess.run", fake_run)

    chapters = extract_pdf(book_path)

    assert calls == [["pdftotext", "-enc", "UTF-8", "-layout", str(book_path), "-"]]
    assert len(chapters) == 1
    assert "Text från PDF." in chapters[0].text


def test_extract_pdf_removes_repeated_margin_titles(monkeypatch, tmp_path: Path) -> None:
    book_path = tmp_path / "blindsight.pdf"
    book_path.write_bytes(b"%PDF-1.4")
    text = "\f".join(
        [
            "Peter Watts Blindsight\n\nChapter text one.\n\nPeter Watts Blindsight",
            "Peter Watts Blindsight\n\nChapter text two.\n\nPeter Watts Blindsight",
            "Peter Watts Blindsight\n\nChapter text three.\n\nPeter Watts Blindsight",
        ]
    )

    def fake_run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(command, 0, stdout=text, stderr="")

    monkeypatch.setattr("eutherbooks.extractors.subprocess.run", fake_run)

    chapters = extract_pdf(book_path)
    combined = "\n".join(chapter.text for chapter in chapters)

    assert "Peter Watts Blindsight" not in combined
    assert "Chapter text one." in combined
    assert "Chapter text three." in combined


def test_pdf_margin_cleanup_preview_reports_removed_lines() -> None:
    text = "\f".join(
        [
            "Peter Watts Blindsight\n\nChapter text one.",
            "Peter Watts Blindsight\n\nChapter text two.",
            "Peter Watts Blindsight\n\nChapter text three.",
        ]
    )

    preview = pdf_margin_cleanup_preview(text)

    assert preview["candidate_lines"] == ["Peter Watts Blindsight"]
    assert preview["sample_pages"][0]["removed"] == ["Peter Watts Blindsight"]


def test_pdf_margin_cleanup_matches_margin_titles_with_page_numbers() -> None:
    text = "\f".join(
        [
            "Peter Watts   6   Blindsight\n\nChapter text one.",
            "Peter Watts   7   Blindsight\n\nChapter text two.",
            "Peter Watts   8   Blindsight\n\nChapter text three.",
        ]
    )

    preview = pdf_margin_cleanup_preview(text)

    assert preview["candidate_lines"] == ["Peter Watts   6   Blindsight"]
    assert preview["sample_pages"][0]["removed"] == ["Peter Watts   6   Blindsight"]
    assert "Peter Watts" not in preview["sample_pages"][0]["after"]
