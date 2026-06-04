from __future__ import annotations

from pathlib import Path

from .extractors import extract_chapters, extract_epub_metadata
from .ids import stable_book_id
from .models import Book, BookFormat, Chapter


SUPPORTED_SUFFIXES = {".epub": BookFormat.EPUB, ".txt": BookFormat.TEXT, ".md": BookFormat.TEXT}


class Library:
    def __init__(self, library_dir: Path):
        self.library_dir = library_dir.resolve()

    def list_books(self) -> list[Book]:
        books = [self._book_from_path(path) for path in self._iter_book_paths()]
        return sorted(books, key=lambda book: book.title.casefold())

    def get_book(self, book_id: str) -> Book | None:
        for book in self.list_books():
            if book.id == book_id:
                return book
        return None

    def chapters_for(self, book_id: str) -> list[Chapter]:
        book = self.get_book(book_id)
        if book is None:
            raise KeyError(f"Unknown book id: {book_id}")
        return extract_chapters(book.path)

    def _iter_book_paths(self) -> list[Path]:
        if not self.library_dir.exists():
            return []
        return [
            path
            for path in self.library_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        ]

    def _book_from_path(self, path: Path) -> Book:
        stat = path.stat()
        title = path.stem
        author = None
        if path.suffix.lower() == ".epub":
            meta_title, meta_author = extract_epub_metadata(path)
            title = meta_title or title
            author = meta_author

        return Book(
            id=stable_book_id(self.library_dir, path),
            title=title,
            author=author,
            format=SUPPORTED_SUFFIXES[path.suffix.lower()],
            path=path,
            size_bytes=stat.st_size,
            modified_at=stat.st_mtime,
        )

