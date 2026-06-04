from __future__ import annotations

from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import Settings
from .jobs import JobStore, TtsQueue
from .library import Library
from .models import Book, Chapter, TtsJob
from .tts import TtsError, backend_from_name


class BookResponse(BaseModel):
    id: str
    title: str
    author: str | None
    format: str
    path: str
    size_bytes: int
    modified_at: float

    @classmethod
    def from_book(cls, book: Book, library_dir: Path) -> "BookResponse":
        return cls(
            id=book.id,
            title=book.title,
            author=book.author,
            format=book.format.value,
            path=book.path.relative_to(library_dir).as_posix(),
            size_bytes=book.size_bytes,
            modified_at=book.modified_at,
        )


class ChapterResponse(BaseModel):
    index: int
    title: str
    char_count: int

    @classmethod
    def from_chapter(cls, chapter: Chapter) -> "ChapterResponse":
        return cls(index=chapter.index, title=chapter.title, char_count=len(chapter.text))


class ChapterTextResponse(ChapterResponse):
    text: str

    @classmethod
    def from_chapter(cls, chapter: Chapter) -> "ChapterTextResponse":
        return cls(index=chapter.index, title=chapter.title, char_count=len(chapter.text), text=chapter.text)


class CreateJobRequest(BaseModel):
    language: str | None = Field(default=None, examples=["sv"])
    voice: str | None = Field(default=None, examples=["sv"])
    chapters: list[int] | None = None


class JobResponse(BaseModel):
    id: str
    book_id: str
    status: str
    language: str
    voice: str
    chapter_indexes: list[int]
    audio_files: list[str]
    error: str | None

    @classmethod
    def from_job(cls, job: TtsJob) -> "JobResponse":
        return cls(
            id=job.id,
            book_id=job.book_id,
            status=job.status.value,
            language=job.language,
            voice=job.voice,
            chapter_indexes=job.chapter_indexes,
            audio_files=job.audio_files,
            error=job.error,
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_dirs()

    library = Library(settings.library_dir)
    store = JobStore(settings.data_dir)
    backend = backend_from_name(settings.tts_backend)
    queue = TtsQueue(library, store, backend, settings.audio_dir)

    app = FastAPI(
        title="EutherBooks",
        version="0.1.0",
        description="Local ebook-to-audiobook service for EutherOxide.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://apothictech.se:8080",
            "https://apothictech.se",
        ],
        allow_origin_regex=r"https?://(apothictech\.se|127\.0\.0\.1|localhost|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+)(:\d+)?",
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    def get_library() -> Library:
        return library

    def get_store() -> JobStore:
        return store

    def get_queue() -> TtsQueue:
        return queue

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "tts_backend": backend.name}

    @app.get("/books", response_model=list[BookResponse])
    def list_books(lib: Library = Depends(get_library)) -> list[BookResponse]:
        return [BookResponse.from_book(book, settings.library_dir) for book in lib.list_books()]

    @app.get("/books/{book_id}", response_model=BookResponse)
    def get_book(book_id: str, lib: Library = Depends(get_library)) -> BookResponse:
        book = lib.get_book(book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="Book not found")
        return BookResponse.from_book(book, settings.library_dir)

    @app.get("/books/{book_id}/chapters", response_model=list[ChapterResponse])
    def list_chapters(book_id: str, lib: Library = Depends(get_library)) -> list[ChapterResponse]:
        try:
            return [ChapterResponse.from_chapter(chapter) for chapter in lib.chapters_for(book_id)]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Book not found") from exc

    @app.get("/books/{book_id}/chapters/{chapter_index}", response_model=ChapterTextResponse)
    def get_chapter(book_id: str, chapter_index: int, lib: Library = Depends(get_library)) -> ChapterTextResponse:
        try:
            chapters = lib.chapters_for(book_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Book not found") from exc
        for chapter in chapters:
            if chapter.index == chapter_index:
                return ChapterTextResponse.from_chapter(chapter)
        raise HTTPException(status_code=404, detail="Chapter not found")

    @app.post("/books/{book_id}/tts", response_model=JobResponse, status_code=202)
    def create_tts_job(
        book_id: str,
        request: CreateJobRequest,
        tts_queue: TtsQueue = Depends(get_queue),
    ) -> JobResponse:
        try:
            job = tts_queue.enqueue(
                book_id=book_id,
                language=request.language or settings.default_language,
                voice=request.voice or settings.tts_voice,
                chapter_indexes=request.chapters,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Book not found") from exc
        except TtsError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return JobResponse.from_job(job)

    @app.get("/jobs", response_model=list[JobResponse])
    def list_jobs(job_store: JobStore = Depends(get_store)) -> list[JobResponse]:
        return [JobResponse.from_job(job) for job in job_store.list_jobs()]

    @app.get("/jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: str, job_store: JobStore = Depends(get_store)) -> JobResponse:
        job = job_store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return JobResponse.from_job(job)

    @app.get("/audio/{audio_path:path}")
    def get_audio(audio_path: str) -> FileResponse:
        path = (settings.audio_dir / audio_path).resolve()
        if settings.audio_dir.resolve() not in path.parents:
            raise HTTPException(status_code=400, detail="Invalid audio path")
        if not path.exists():
            raise HTTPException(status_code=404, detail="Audio not found")
        return FileResponse(path, media_type="audio/wav")

    return app


app = create_app()
