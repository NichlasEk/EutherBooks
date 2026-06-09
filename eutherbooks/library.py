from __future__ import annotations

import re
import time
from pathlib import Path

from .extractors import extract_chapters, extract_epub_metadata
from .ids import stable_book_id
from .models import Book, BookFormat, Chapter


SUPPORTED_SUFFIXES = {
    ".epub": BookFormat.EPUB,
    ".pdf": BookFormat.PDF,
    ".txt": BookFormat.TEXT,
    ".md": BookFormat.TEXT,
}


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

    def import_book_bytes(self, filename: str, data: bytes) -> Book:
        clean_name = clean_book_filename(filename)
        suffix = Path(clean_name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported ebook format: {suffix or filename}")
        if not data:
            raise ValueError("Uploaded book is empty")

        self.library_dir.mkdir(parents=True, exist_ok=True)
        path = unique_book_path(self.library_dir / clean_name)
        path.write_bytes(data)
        return self._book_from_path(path)

    def _iter_book_paths(self) -> list[Path]:
        if not self.library_dir.exists():
            return []
        return [
            path
            for path in self.library_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_SUFFIXES
            and not any(part.startswith(".") for part in path.relative_to(self.library_dir).parts)
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


def clean_book_filename(value: str) -> str:
    name = Path(str(value or "book")).name.strip()
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    return name[:160] or "book.txt"


def unique_book_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}-{time.time_ns()}{suffix}")
