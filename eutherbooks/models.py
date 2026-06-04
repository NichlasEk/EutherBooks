from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class BookFormat(str, Enum):
    EPUB = "epub"
    TEXT = "txt"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class Book:
    id: str
    title: str
    author: str | None
    format: BookFormat
    path: Path
    size_bytes: int
    modified_at: float


@dataclass(frozen=True)
class Chapter:
    index: int
    title: str
    text: str


@dataclass
class TtsJob:
    id: str
    book_id: str
    status: JobStatus
    language: str
    voice: str
    chapter_indexes: list[int]
    audio_files: list[str] = field(default_factory=list)
    total_audio_files: int = 0
    tts_options: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
