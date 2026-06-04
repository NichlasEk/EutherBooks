from __future__ import annotations

import hashlib
from pathlib import Path


def stable_book_id(library_dir: Path, path: Path) -> str:
    relative = path.resolve().relative_to(library_dir.resolve()).as_posix()
    return hashlib.sha1(relative.encode("utf-8")).hexdigest()[:16]


def stable_job_id(book_id: str, voice: str, chapter_indexes: list[int]) -> str:
    material = f"{book_id}:{voice}:{','.join(str(i) for i in chapter_indexes)}"
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]

