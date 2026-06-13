from __future__ import annotations

from pathlib import Path
import wave
from fastapi import Depends, FastAPI, HTTPException, Request
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
    length_scale: float | None = Field(default=None, examples=[1.0])
    noise_scale: float | None = Field(default=None, examples=[0.667])
    noise_w: float | None = Field(default=None, examples=[0.8])
    sentence_silence: float | None = Field(default=None, examples=[0.2])
    cfg_value: float | None = Field(default=None, ge=1.0, le=3.0, examples=[2.0])
    inference_timesteps: int | None = Field(default=None, ge=1, le=50, examples=[10])
    max_chunk_chars: int | None = Field(default=None, ge=120, le=1500, examples=[700])
    seed: int | None = Field(default=None, ge=0, le=2147483647, examples=[123456])
    voice_reference_path: str | None = Field(default=None, max_length=600)
    voice_prompt_text: str | None = Field(default=None, max_length=500)
    queue_remainder: bool = False


class VoiceResponse(BaseModel):
    id: str
    label: str
    language: str
    backend: str
    path: str


class JobResponse(BaseModel):
    id: str
    book_id: str
    status: str
    language: str
    voice: str
    chapter_indexes: list[int]
    audio_files: list[str]
    total_audio_files: int
    tts_options: dict[str, float | int | str | bool]
    queue_remainder: bool
    progress_label: str
    progress_detail: str
    current_chapter_index: int | None
    current_chunk_index: int
    total_chunks: int
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
            total_audio_files=job.total_audio_files,
            tts_options=job.tts_options,
            queue_remainder=job.queue_remainder,
            progress_label=job.progress_label,
            progress_detail=job.progress_detail,
            current_chapter_index=job.current_chapter_index,
            current_chunk_index=job.current_chunk_index,
            total_chunks=job.total_chunks,
            error=job.error,
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_dirs()

    library = Library(settings.library_dir)
    store = JobStore(settings.data_dir)
    store.reset_incomplete()
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

    @app.get("/voices", response_model=list[VoiceResponse])
    def list_voices() -> list[VoiceResponse]:
        if backend.name == "eutherlink":
            return _eutherlink_voices()
        return _local_piper_voices()

    @app.get("/books", response_model=list[BookResponse])
    def list_books(lib: Library = Depends(get_library)) -> list[BookResponse]:
        return [BookResponse.from_book(book, settings.library_dir) for book in lib.list_books()]

    @app.post("/books/upload", response_model=BookResponse, status_code=201)
    async def upload_book(request: Request, name: str, lib: Library = Depends(get_library)) -> BookResponse:
        try:
            book = lib.import_book_bytes(name, await request.body())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return BookResponse.from_book(book, settings.library_dir)

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
                tts_options={
                    "length_scale": request.length_scale,
                    "noise_scale": request.noise_scale,
                    "noise_w": request.noise_w,
                    "sentence_silence": request.sentence_silence,
                    "cfg_value": request.cfg_value,
                    "inference_timesteps": request.inference_timesteps,
                    "max_chunk_chars": request.max_chunk_chars,
                    "voice_reference_path": request.voice_reference_path,
                    "voice_prompt_text": request.voice_prompt_text,
                },
                queue_remainder=request.queue_remainder,
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

    @app.get("/jobs/{job_id}/audio")
    def get_job_audio(job_id: str, job_store: JobStore = Depends(get_store)) -> FileResponse:
        job = job_store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if not job.audio_files:
            raise HTTPException(status_code=404, detail="Audio not found")
        source_paths = [_resolve_audio_path(settings.audio_dir, audio_path) for audio_path in job.audio_files]
        missing = [path for path in source_paths if not path.exists()]
        if missing:
            raise HTTPException(status_code=404, detail="Audio not found")
        combined_path = settings.audio_dir / job.book_id / job.id / "combined.wav"
        try:
            _ensure_combined_wav(source_paths, combined_path)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return FileResponse(combined_path, media_type="audio/wav")

    @app.get("/audio/{audio_path:path}")
    def get_audio(audio_path: str) -> FileResponse:
        path = _resolve_audio_path(settings.audio_dir, audio_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Audio not found")
        return FileResponse(path, media_type="audio/wav")

    return app


app = create_app()


def _resolve_audio_path(audio_dir: Path, audio_path: str) -> Path:
    root = audio_dir.resolve()
    path = (audio_dir / audio_path).resolve()
    if root not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid audio path")
    return path


def _ensure_combined_wav(source_paths: list[Path], combined_path: Path) -> None:
    newest_source = max(path.stat().st_mtime_ns for path in source_paths)
    if combined_path.exists() and combined_path.stat().st_mtime_ns >= newest_source:
        return
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = combined_path.with_name(f".{combined_path.name}.tmp")
    first_params = None
    with wave.open(str(temp_path), "wb") as output:
        for source_path in source_paths:
            with wave.open(str(source_path), "rb") as source:
                params = source.getparams()
                comparable = (params.nchannels, params.sampwidth, params.framerate, params.comptype, params.compname)
                if first_params is None:
                    first_params = comparable
                    output.setparams(params)
                elif comparable != first_params:
                    raise ValueError("Audio parts use incompatible WAV formats")
                while True:
                    frames = source.readframes(8192)
                    if not frames:
                        break
                    output.writeframesraw(frames)
    temp_path.replace(combined_path)


def _eutherlink_voices() -> list[VoiceResponse]:
    presets = [
        ("sv-female-warm", "Warm female narrator", "sv", "preset:sv-female-warm"),
        ("sv-female-clear", "Clear female narrator", "sv", "preset:sv-female-clear"),
        ("sv-female-soft", "Soft female narrator", "sv", "preset:sv-female-soft"),
        ("sv-female-deep", "Deep female narrator", "sv", "preset:sv-female-deep"),
        ("sv-female-elder", "Older female storyteller", "sv", "preset:sv-female-elder"),
        ("sv-male-warm", "Warm male narrator", "sv", "preset:sv-male-warm"),
        ("sv-male-clear", "Clear male narrator", "sv", "preset:sv-male-clear"),
        ("sv-male-deep", "Deep male narrator", "sv", "preset:sv-male-deep"),
        ("sv-male-soft", "Soft male narrator", "sv", "preset:sv-male-soft"),
        ("sv-male-elder", "Older male storyteller", "sv", "preset:sv-male-elder"),
        ("sv-neutral-calm", "Calm neutral narrator", "sv", "preset:sv-neutral-calm"),
        ("sv-neutral-news", "Crisp documentary voice", "sv", "preset:sv-neutral-news"),
        ("sv-neutral-theatre", "Expressive theatre narrator", "sv", "preset:sv-neutral-theatre"),
        ("sv-whisper", "Quiet bedtime voice", "sv", "preset:sv-whisper"),
        ("sv-character-bright", "Bright character voice", "sv", "preset:sv-character-bright"),
        ("sv-character-gritty", "Gritty character voice", "sv", "preset:sv-character-gritty"),
        ("en-female-warm", "English warm female", "en", "preset:en-female-warm"),
        ("en-male-warm", "English warm male", "en", "preset:en-male-warm"),
        ("own-sv", "Your own voice SV", "sv", "user:own-sv"),
        ("own-en", "Your own voice EN", "en", "user:own-en"),
        ("custom", "Custom voice prompt", "sv", "preset:custom"),
    ]
    return [
        VoiceResponse(id=voice_id, label=label, language=language, backend="eutherlink", path=path)
        for voice_id, label, language, path in presets
    ]


def _local_piper_voices() -> list[VoiceResponse]:
    voice_dir = Path("models/piper")
    voices: list[VoiceResponse] = []
    for model_path in sorted(voice_dir.glob("*.onnx")):
        stem = model_path.stem
        parts = stem.split("-")
        language = parts[0] if parts else "unknown"
        name = parts[1] if len(parts) > 1 else stem
        quality = parts[2] if len(parts) > 2 else ""
        voices.append(
            VoiceResponse(
                id=stem,
                label=" ".join(part for part in [language, name, quality] if part),
                language=language,
                backend="piper",
                path=model_path.as_posix(),
            )
        )
    if not voices:
        voices.extend(
            [
                VoiceResponse(
                    id="sv",
                    label="Swedish default",
                    language="sv",
                    backend="piper",
                    path="models/piper/sv_SE-nst-medium.onnx",
                ),
                VoiceResponse(
                    id="en",
                    label="English default",
                    language="en",
                    backend="piper",
                    path="models/piper/en_US-lessac-medium.onnx",
                ),
            ]
        )
    return voices
