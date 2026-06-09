from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

from eutherbooks.extractors import clean_html_text, extract_pdf, split_plain_text


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
