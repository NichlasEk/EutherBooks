from __future__ import annotations

from array import array
import os
from pathlib import Path
import shutil
import sys
import uuid
import wave
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import Settings
from .extractors import extract_pdf_margin_cleanup_preview
from .jobs import JobStore, TtsQueue
from .library import Library
from .models import JobStatus, Book, BookFormat, Chapter, TtsJob
from .tts import TtsError, backend_from_name, eutherlink_health


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


class CancelJobsResponse(BaseModel):
    cancelled: int


class PdfCleanupSampleResponse(BaseModel):
    page: int
    removed: list[str]
    before: str
    after: str


class PdfCleanupPreviewResponse(BaseModel):
    page_count: int
    candidate_lines: list[str]
    sample_pages: list[PdfCleanupSampleResponse]


class CreateJobRequest(BaseModel):
    language: str | None = Field(default=None, examples=["sv"])
    voice: str | None = Field(default=None, examples=["sv"])
    model_backend: str | None = Field(default=None, examples=["voxcpm2"])
    owner: str | None = Field(default=None, max_length=120)
    cancel_existing: bool = True
    force_regenerate: bool = False
    chapters: list[int] | None = None
    length_scale: float | None = Field(default=None, examples=[1.0])
    noise_scale: float | None = Field(default=None, examples=[0.667])
    noise_w: float | None = Field(default=None, examples=[0.8])
    sentence_silence: float | None = Field(default=None, examples=[0.2])
    cfg_value: float | None = Field(default=None, ge=1.0, le=3.0, examples=[2.0])
    inference_timesteps: int | None = Field(default=None, ge=1, le=50, examples=[10])
    dots_template_name: str | None = Field(default=None, examples=["tts"])
    dots_ode_method: str | None = Field(default=None, examples=["euler"])
    dots_num_steps: int | None = Field(default=None, ge=1, le=50, examples=[4])
    dots_guidance_scale: float | None = Field(default=None, ge=0.0, le=5.0, examples=[1.2])
    dots_speaker_scale: float | None = Field(default=None, ge=0.0, le=5.0, examples=[1.5])
    dots_max_generate_length: int | None = Field(default=None, ge=128, le=4096, examples=[500])
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
    model_backend: str | None = None
    default_length_scale: float | None = None
    default_seed: int | None = None


class JobResponse(BaseModel):
    id: str
    book_id: str
    status: str
    language: str
    voice: str
    chapter_indexes: list[int]
    owner: str
    audio_files: list[str]
    audio_durations: list[float]
    total_audio_files: int
    tts_options: dict[str, float | int | str | bool]
    queue_remainder: bool
    progress_label: str
    progress_detail: str
    current_chapter_index: int | None
    current_chunk_index: int
    worker_progress: float
    total_chunks: int
    perf: dict[str, float | int | str | bool]
    error: str | None

    @classmethod
    def from_job(cls, job: TtsJob) -> "JobResponse":
        playable_audio: list[tuple[str, float]] = []
        if job.status is JobStatus.DONE:
            playable_audio = [
                (audio_path, job.audio_durations[index] if index < len(job.audio_durations) else 0.0)
                for index, audio_path in enumerate(job.audio_files)
                if ".stream-" not in audio_path
            ]
        return cls(
            id=job.id,
            book_id=job.book_id,
            status=job.status.value,
            language=job.language,
            voice=job.voice,
            chapter_indexes=job.chapter_indexes,
            owner=job.owner,
            audio_files=[audio_path for audio_path, _duration in playable_audio],
            audio_durations=[duration for _audio_path, duration in playable_audio],
            total_audio_files=job.total_audio_files,
            tts_options=job.tts_options,
            queue_remainder=job.queue_remainder,
            progress_label=job.progress_label,
            progress_detail=job.progress_detail,
            current_chapter_index=job.current_chapter_index,
            current_chunk_index=job.current_chunk_index,
            worker_progress=job.worker_progress,
            total_chunks=job.total_chunks,
            perf={
                key: value
                for key, value in job.perf.items()
                if isinstance(key, str) and isinstance(value, (str, int, float, bool))
            },
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
    def health() -> dict[str, object]:
        audio_usage = shutil.disk_usage(settings.audio_dir)
        payload: dict[str, object] = {
            "status": "ok",
            "tts_backend": backend.name,
            "storage": {
                "audio_dir": str(settings.audio_dir),
                "audio_free_bytes": audio_usage.free,
                "audio_total_bytes": audio_usage.total,
                "audio_used_bytes": audio_usage.used,
            },
        }
        if backend.name == "eutherlink":
            try:
                worker_health = eutherlink_health()
            except TtsError as exc:
                worker_health = {"ok": False, "error": str(exc)}
            payload["eutherlink"] = worker_health
            payload["dots_tts"] = worker_health.get("dots_tts") if isinstance(worker_health, dict) else None
        return payload

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

    @app.get("/debug/books/{book_id}/pdf-cleanup", response_model=PdfCleanupPreviewResponse)
    def preview_pdf_cleanup(book_id: str, max_pages: int = 8, lib: Library = Depends(get_library)) -> PdfCleanupPreviewResponse:
        book = lib.get_book(book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="Book not found")
        if book.format != BookFormat.PDF:
            raise HTTPException(status_code=400, detail="Book is not a PDF")
        try:
            return PdfCleanupPreviewResponse.model_validate(
                extract_pdf_margin_cleanup_preview(book.path, max_pages=max(1, min(max_pages, 20)))
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

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
                owner=_clean_job_owner(request.owner),
                tts_options={
                    "length_scale": request.length_scale,
                    "noise_scale": request.noise_scale,
                    "noise_w": request.noise_w,
                    "sentence_silence": request.sentence_silence,
                    "cfg_value": request.cfg_value,
                    "inference_timesteps": request.inference_timesteps,
                    "dots_template_name": request.dots_template_name,
                    "dots_ode_method": request.dots_ode_method,
                    "dots_num_steps": request.dots_num_steps,
                    "dots_guidance_scale": request.dots_guidance_scale,
                    "dots_speaker_scale": request.dots_speaker_scale,
                    "dots_max_generate_length": request.dots_max_generate_length,
                    "max_chunk_chars": request.max_chunk_chars,
                    "seed": request.seed,
                    "voice_reference_path": request.voice_reference_path,
                    "voice_prompt_text": request.voice_prompt_text,
                    "model_backend": request.model_backend,
                    "regenerate_nonce": uuid.uuid4().hex if request.force_regenerate else None,
                },
                queue_remainder=request.queue_remainder,
                cancel_existing=request.cancel_existing,
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

    @app.delete("/jobs/active", response_model=CancelJobsResponse)
    def cancel_active_jobs(owner: str | None = None, job_store: JobStore = Depends(get_store)) -> CancelJobsResponse:
        cancelled = job_store.cancel_active("Cancelled by user request.", owner=owner)
        return CancelJobsResponse(cancelled=cancelled)

    @app.get("/jobs/{job_id}/audio")
    def get_job_audio(job_id: str, job_store: JobStore = Depends(get_store)) -> FileResponse:
        job = job_store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        audio_files = [audio_path for audio_path in job.audio_files if ".stream-" not in audio_path]
        if not audio_files:
            raise HTTPException(status_code=404, detail="Audio not found")
        source_paths = [_resolve_audio_path(settings.audio_dir, audio_path) for audio_path in audio_files]
        missing = [path for path in source_paths if not path.exists()]
        if missing:
            raise HTTPException(status_code=404, detail="Audio not found")
        combined_path = settings.audio_dir / job.book_id / job.id / "combined.wav"
        try:
            _ensure_combined_wav(source_paths, combined_path)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return FileResponse(combined_path, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @app.get("/audio/{audio_path:path}")
    def get_audio(audio_path: str) -> FileResponse:
        path = _resolve_audio_path(settings.audio_dir, audio_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Audio not found")
        return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    return app


app = create_app()


def _clean_job_owner(value: str | None) -> str:
    owner = (value or "").strip()
    if not owner:
        return "anonymous"
    safe = "".join(ch for ch in owner[:120] if ch.isalnum() or ch in {"-", "_", ".", "@"})
    return safe or "anonymous"

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
    temp_path = combined_path.with_name(f".{combined_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        _write_smoothed_combined_wav(source_paths, temp_path)
        temp_path.replace(combined_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _write_smoothed_combined_wav(source_paths: list[Path], output_path: Path) -> None:
    first_params = None
    combined: array[int] | None = None
    for index, source_path in enumerate(source_paths):
        params, samples = _read_pcm16_wav(source_path)
        comparable = (params.nchannels, params.sampwidth, params.framerate, params.comptype, params.compname)
        if first_params is None:
            first_params = params
            combined = samples
            continue
        first_comparable = (first_params.nchannels, first_params.sampwidth, first_params.framerate, first_params.comptype, first_params.compname)
        if comparable != first_comparable:
            raise ValueError("Audio parts use incompatible WAV formats")
        samples = _trim_leading_pcm16_silence(samples, params.nchannels, params.framerate)
        combined = _append_pcm16_with_gap(combined or array("h"), samples, params.nchannels, params.framerate)

    if first_params is None or combined is None:
        raise ValueError("No audio parts to combine")
    with wave.open(str(output_path), "wb") as output:
        output.setparams(first_params)
        output.writeframes(combined.tobytes())


def _read_pcm16_wav(path: Path) -> tuple[wave._wave_params, array[int]]:
    with wave.open(str(path), "rb") as source:
        params = source.getparams()
        if params.sampwidth != 2 or params.comptype != "NONE":
            raise ValueError("Only PCM16 WAV audio can be combined")
        samples = array("h")
        samples.frombytes(source.readframes(params.nframes))
    if sys.byteorder != "little":
        samples.byteswap()
    return params, samples


def _trim_leading_pcm16_silence(samples: array[int], channels: int, sample_rate: int) -> array[int]:
    if not samples:
        return samples
    max_trim_frames = min(len(samples) // channels, int(sample_rate * 0.12))
    window_frames = max(1, int(sample_rate * 0.01))
    threshold = 90
    trim_frames = 0
    while trim_frames + window_frames <= max_trim_frames:
        start = trim_frames * channels
        end = (trim_frames + window_frames) * channels
        window = samples[start:end]
        if not window:
            break
        rms = int((sum(sample * sample for sample in window) / len(window)) ** 0.5)
        if rms >= threshold:
            break
        trim_frames += window_frames
    if trim_frames <= 0:
        return samples
    return samples[trim_frames * channels :]


def _append_pcm16_with_gap(left: array[int], right: array[int], channels: int, sample_rate: int) -> array[int]:
    if not left:
        return right
    if not right:
        return left
    out = array("h", left)
    gap_ms = _combined_audio_gap_ms()
    if gap_ms > 0:
        gap_samples = int(sample_rate * (gap_ms / 1000.0)) * channels
        out.extend(array("h", [0]) * gap_samples)
    out.extend(right)
    return out


def _combined_audio_gap_ms() -> float:
    try:
        parsed = float(os.environ.get("EUTHERBOOKS_COMBINED_AUDIO_GAP_MS", "180"))
    except ValueError:
        parsed = 180.0
    if parsed != parsed:
        return 180.0
    return min(500.0, max(0.0, parsed))


def _eutherlink_voices() -> list[VoiceResponse]:
    base_presets = [
        ("sv-female-warm", "Warm female narrator", "sv", "preset:sv-female-warm", 1.15),
        ("sv-female-clear", "Clear female narrator", "sv", "preset:sv-female-clear", 1.12),
        ("sv-female-soft", "Soft female narrator", "sv", "preset:sv-female-soft", 1.20),
        ("sv-female-deep", "Deep female narrator", "sv", "preset:sv-female-deep", 1.20),
        ("sv-female-elder", "Older female storyteller", "sv", "preset:sv-female-elder", 1.25),
        ("sv-male-warm", "Warm male narrator", "sv", "preset:sv-male-warm", 1.15),
        ("sv-male-clear", "Clear male narrator", "sv", "preset:sv-male-clear", 1.12),
        ("sv-male-deep", "Deep male narrator", "sv", "preset:sv-male-deep", 1.22),
        ("sv-male-soft", "Soft male narrator", "sv", "preset:sv-male-soft", 1.20),
        ("sv-male-elder", "Older male storyteller", "sv", "preset:sv-male-elder", 1.25),
        ("sv-neutral-calm", "Calm neutral narrator", "sv", "preset:sv-neutral-calm", 1.16),
        ("sv-neutral-news", "Crisp documentary voice", "sv", "preset:sv-neutral-news", 1.10),
        ("sv-neutral-theatre", "Expressive theatre narrator", "sv", "preset:sv-neutral-theatre", 1.14),
        ("sv-whisper", "Quiet bedtime voice", "sv", "preset:sv-whisper", 1.25),
        ("sv-character-bright", "Bright character voice", "sv", "preset:sv-character-bright", 1.08),
        ("sv-character-gritty", "Gritty character voice", "sv", "preset:sv-character-gritty", 1.18),
        ("en-female-warm", "English warm female narrator", "en", "preset:en-female-warm", 1.15),
        ("en-female-clear", "English clear female narrator", "en", "preset:en-female-clear", 1.12),
        ("en-female-soft", "English soft female narrator", "en", "preset:en-female-soft", 1.20),
        ("en-female-deep", "English deep female narrator", "en", "preset:en-female-deep", 1.20),
        ("en-female-elder", "English older female storyteller", "en", "preset:en-female-elder", 1.25),
        ("en-male-warm", "English warm male narrator", "en", "preset:en-male-warm", 1.15),
        ("en-male-clear", "English clear male narrator", "en", "preset:en-male-clear", 1.12),
        ("en-male-deep", "English deep male narrator", "en", "preset:en-male-deep", 1.22),
        ("en-male-soft", "English soft male narrator", "en", "preset:en-male-soft", 1.20),
        ("en-male-elder", "English older male storyteller", "en", "preset:en-male-elder", 1.25),
        ("en-neutral-calm", "English calm neutral narrator", "en", "preset:en-neutral-calm", 1.16),
        ("en-neutral-news", "English crisp documentary voice", "en", "preset:en-neutral-news", 1.10),
        ("en-neutral-theatre", "English expressive theatre narrator", "en", "preset:en-neutral-theatre", 1.14),
        ("en-whisper", "English quiet bedtime voice", "en", "preset:en-whisper", 1.25),
        ("en-character-bright", "English bright character voice", "en", "preset:en-character-bright", 1.08),
        ("en-character-gritty", "English gritty character voice", "en", "preset:en-character-gritty", 1.18),
    ]
    presets = [
        *base_presets,
        *[
            (f"dots-mf-{voice_id}", f"Dots MF {label}", language, path, length_scale)
            for voice_id, label, language, path, length_scale in base_presets
        ],
        *[
            (f"dots-soar-{voice_id}", f"Dots SOAR {label}", language, path, length_scale)
            for voice_id, label, language, path, length_scale in base_presets
        ],
        *[
            (f"auto-{voice_id}", f"Auto fallback {label}", language, path, length_scale)
            for voice_id, label, language, path, length_scale in base_presets
        ],
        ("own-sv", "Your own voice SV", "sv", "user:own-sv", None),
        ("own-en", "Your own voice EN", "en", "user:own-en", None),
        ("dots-mf-own-sv", "Dots MF own voice SV", "sv", "user:own-sv", None),
        ("dots-mf-own-en", "Dots MF own voice EN", "en", "user:own-en", None),
        ("dots-soar-own-sv", "Dots SOAR own voice SV", "sv", "user:own-sv", None),
        ("dots-soar-own-en", "Dots SOAR own voice EN", "en", "user:own-en", None),
        ("grapheneos-matcha-en", "GrapheneOS Matcha EN fallback", "en", "preset:grapheneos-matcha-en", 1.0),
        ("custom", "Custom voice prompt", "sv", "preset:custom", None),
    ]
    return [
        VoiceResponse(
            id=voice_id,
            label=label,
            language=language,
            backend="eutherlink",
            path=path,
            model_backend="dots.tts-mf" if voice_id.startswith("dots-mf-") else ("dots.tts-soar" if voice_id.startswith("dots-soar-") else ("grapheneos-matcha-en" if voice_id.startswith("grapheneos-matcha-") else ("auto-fallback" if voice_id.startswith("auto-") else "voxcpm2"))),
            default_length_scale=length_scale,
            default_seed=_default_voice_seed(_base_voice_seed_id(voice_id)) if path.startswith("preset:") and voice_id != "custom" else None,
        )
        for voice_id, label, language, path, length_scale in presets
    ]


def _base_voice_seed_id(voice_id: str) -> str:
    normalized = voice_id.strip()
    lower = normalized.lower()
    if lower.startswith("dots-mf-"):
        return normalized[len("dots-mf-") :]
    if lower.startswith("dots-soar-"):
        return normalized[len("dots-soar-") :]
    if lower.startswith("auto-"):
        return normalized[len("auto-") :]
    return normalized


def _default_voice_seed(voice_id: str) -> int:
    normalized = voice_id.strip().lower().replace("-", "_")
    digest = __import__("hashlib").sha256(f"eutherbooks:eutherlink:{normalized}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


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
