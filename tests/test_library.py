from __future__ import annotations

from pathlib import Path

from eutherbooks.library import Library


def test_library_lists_nested_text_books(tmp_path: Path) -> None:
    library_dir = tmp_path / "library"
    book_path = library_dir / "svenska" / "bok.txt"
    book_path.parent.mkdir(parents=True)
    book_path.write_text("Kapitel 1\n\nDet var en gång.", encoding="utf-8")

    books = Library(library_dir).list_books()

    assert len(books) == 1
    assert books[0].title == "bok"
    assert books[0].format.value == "txt"


def test_library_lists_pdf_books(tmp_path: Path) -> None:
    library_dir = tmp_path / "library"
    book_path = library_dir / "resor" / "Bornholm 2026.pdf"
    book_path.parent.mkdir(parents=True)
    book_path.write_bytes(b"%PDF-1.4")

    books = Library(library_dir).list_books()

    assert len(books) == 1
    assert books[0].title == "Bornholm 2026"
    assert books[0].format.value == "pdf"


def test_library_extracts_text_chapters(tmp_path: Path) -> None:
    library_dir = tmp_path / "library"
    book_path = library_dir / "bok.txt"
    book_path.parent.mkdir(parents=True)
    book_path.write_text("Första kapitlet\n\nText här.\n\nAndra stycket.", encoding="utf-8")

    library = Library(library_dir)
    book = library.list_books()[0]
    chapters = library.chapters_for(book.id)

    assert len(chapters) == 1
    assert "Text här." in chapters[0].text


def test_library_imports_book_bytes_with_unique_name(tmp_path: Path) -> None:
    library_dir = tmp_path / "library"
    library = Library(library_dir)

    first = library.import_book_bytes("../Bok?.txt", b"Text 1")
    second = library.import_book_bytes("../Bok?.txt", b"Text 2")

    assert first.path.name == "Bok_.txt"
    assert second.path.name == "Bok_-2.txt"
    assert second.path.read_bytes() == b"Text 2"
