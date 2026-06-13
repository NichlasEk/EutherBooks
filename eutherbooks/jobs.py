from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .ids import stable_job_id
from .extractors import pdf_ocr_cached_page_count, pdf_ocr_next_batch, pdf_page_count
from .library import Library
from .models import Chapter, JobStatus, TtsJob
from .tts import TtsBackend


DEFAULT_MAX_CHARS_PER_AUDIO_FILE = 4_000
DEFAULT_PIPER_MAX_CHARS_PER_AUDIO_FILE = 900


def _worker_parallelism() -> int:
    try:
        return max(1, int(os.environ.get("EUTHERBOOKS_TTS_PARALLELISM", "2")))
    except ValueError:
        return 2


_TTS_WORKER_SEMAPHORE = threading.Semaphore(_worker_parallelism())


class JobStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "jobs.json"
        self._lock = threading.Lock()

    def list_jobs(self) -> list[TtsJob]:
        with self._lock:
            return list(self._read().values())

    def get(self, job_id: str) -> TtsJob | None:
        with self._lock:
            return self._read().get(job_id)

    def put(self, job: TtsJob) -> None:
        with self._lock:
            jobs = self._read()
            jobs[job.id] = job
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {job_id: asdict(value) for job_id, value in jobs.items()}
            self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def reset_incomplete(self, reason: str = "Interrupted by service restart.") -> None:
        with self._lock:
            jobs = self._read()
            changed = False
            for job in jobs.values():
                if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                    job.status = JobStatus.FAILED
                    job.error = reason
                    job.progress_label = "Interrupted"
                    job.progress_detail = reason
                    changed = True
            if changed:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                payload = {job_id: asdict(value) for job_id, value in jobs.items()}
                self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _read(self) -> dict[str, TtsJob]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {
            job_id: TtsJob(
                id=value["id"],
                book_id=value["book_id"],
                status=JobStatus(value["status"]),
                language=value["language"],
                voice=value["voice"],
                chapter_indexes=list(value["chapter_indexes"]),
                audio_files=list(value.get("audio_files", [])),
                total_audio_files=int(value.get("total_audio_files", 0)),
                tts_options=dict(value.get("tts_options", {})),
                queue_remainder=bool(value.get("queue_remainder", False)),
                progress_label=_stored_progress_label(value),
                progress_detail=str(value.get("progress_detail") or _stored_progress_detail(value)),
                current_chapter_index=value.get("current_chapter_index"),
                current_chunk_index=int(value.get("current_chunk_index", 0)),
                total_chunks=int(value.get("total_chunks", 0)),
                error=value.get("error"),
            )
            for job_id, value in raw.items()
        }


class TtsQueue:
    def __init__(self, library: Library, store: JobStore, backend: TtsBackend, audio_dir: Path):
        self.library = library
        self.store = store
        self.backend = backend
        self.audio_dir = audio_dir

    def enqueue(
        self,
        book_id: str,
        language: str,
        voice: str,
        chapter_indexes: list[int] | None = None,
        tts_options: dict[str, Any] | None = None,
        queue_remainder: bool = False,
    ) -> TtsJob:
        chapters = self.library.chapters_for(book_id)
        book = self.library.get_book(book_id)
        pdf_remainder = bool(queue_remainder and book and book.path.suffix.lower() == ".pdf")
        indexes = chapter_indexes if chapter_indexes is not None else [chapter.index for chapter in chapters]
        if pdf_remainder and not indexes:
            indexes = [0]
        options = _normalized_tts_options(tts_options or {})
        options_key = json.dumps(options, sort_keys=True, separators=(",", ":"))
        mode_key = ":remainder" if pdf_remainder else ""
        job_id = stable_job_id(book_id, f"{self.backend.name}:{voice}:{options_key}{mode_key}", indexes)
        total_audio_files = (
            max(1, pdf_page_count(book.path) - indexes[0] if book else 0)
            if pdf_remainder
            else self._total_audio_files(chapters, indexes)
        )
        existing = self.store.get(job_id)
        if existing and existing.status in {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.DONE}:
            if existing.total_audio_files <= 0:
                existing.total_audio_files = total_audio_files
                self.store.put(existing)
            return existing

        job = TtsJob(
            id=job_id,
            book_id=book_id,
            status=JobStatus.QUEUED,
            language=language,
            voice=voice,
            chapter_indexes=indexes,
            total_audio_files=total_audio_files,
            tts_options=options,
            queue_remainder=pdf_remainder,
            progress_label="Queued",
            progress_detail="Waiting for a speech worker.",
            total_chunks=total_audio_files,
        )
        self.store.put(job)
        thread = threading.Thread(target=self._run_job, args=(job.id,), daemon=True)
        thread.start()
        return job

    def _total_audio_files(self, chapters: list[Chapter], indexes: list[int]) -> int:
        chapters_by_index = {chapter.index: chapter for chapter in chapters}
        max_chars = _max_chars_for_backend(self.backend.name)
        return sum(len(_split_for_tts(chapters_by_index[index].text, max_chars=max_chars)) for index in indexes)

    def _run_job(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            return

        with _TTS_WORKER_SEMAPHORE:
            job = self.store.get(job_id)
            if job is None or job.status != JobStatus.QUEUED:
                return
            job.status = JobStatus.RUNNING
            self._set_progress(job, "Preparing", "Loading text and speech settings.")

            try:
                if job.queue_remainder:
                    self._run_progressive_pdf_job(job)
                    return
                chapters = {chapter.index: chapter for chapter in self.library.chapters_for(job.book_id)}
                audio_files: list[str] = []
                total_chunks = self._total_audio_files(list(chapters.values()), job.chapter_indexes)
                job.total_chunks = total_chunks
                job.total_audio_files = max(job.total_audio_files, total_chunks)
                self.store.put(job)
                for chapter_index in job.chapter_indexes:
                    chapter = chapters[chapter_index]
                    chunks = _split_for_tts(chapter.text, max_chars=_max_chars_for_backend(self.backend.name))
                    for chunk_index, chunk in enumerate(chunks):
                        relative = Path(job.book_id) / job.id / f"{chapter_index:04d}-{chunk_index:03d}.wav"
                        output_path = self.audio_dir / relative
                        job.current_chapter_index = chapter_index
                        job.current_chunk_index = len(audio_files)
                        self._set_progress(
                            job,
                            "Synthesizing speech",
                            f"{chapter.title}: part {chunk_index + 1}/{len(chunks)} ({len(audio_files) + 1}/{total_chunks})",
                        )
                        if not output_path.exists() or output_path.stat().st_size == 0:
                            self.backend.synthesize(chunk, output_path, job.language, job.voice, job.tts_options)
                        audio_files.append(relative.as_posix())
                        job.audio_files = audio_files
                        job.current_chunk_index = len(audio_files)
                        self._set_progress(
                            job,
                            "Audio ready",
                            f"{len(audio_files)}/{max(job.total_audio_files, len(audio_files))} audio files generated.",
                        )

                job.audio_files = audio_files
                job.status = JobStatus.DONE
                job.error = None
                job.current_chunk_index = len(audio_files)
                self._set_progress(job, "Ready", f"{len(audio_files)} {_audio_file_word(len(audio_files))} generated.")
            except Exception as exc:  # noqa: BLE001
                job.status = JobStatus.FAILED
                job.error = str(exc)
                self._set_progress(job, "Failed", str(exc))
            finally:
                self.store.put(job)

    def _run_progressive_pdf_job(self, job: TtsJob) -> None:
        book = self.library.get_book(job.book_id)
        if book is None:
            raise KeyError(f"Unknown book id: {job.book_id}")
        start_index = job.chapter_indexes[0] if job.chapter_indexes else 0
        total_pages = pdf_page_count(book.path)
        audio_files = list(job.audio_files)
        seen_audio = set(audio_files)
        job.total_chunks = max(job.total_chunks, job.total_audio_files, total_pages - start_index)
        self._set_progress(
            job,
            "Reading PDF",
            f"Starting at page {start_index + 1}; {pdf_ocr_cached_page_count(book.path)}/{total_pages} pages cached.",
        )

        while True:
            chapters = [chapter for chapter in self.library.chapters_for(job.book_id) if chapter.index >= start_index]
            for chapter in chapters:
                chunks = _split_for_tts(chapter.text, max_chars=_max_chars_for_backend(self.backend.name))
                for chunk_index, chunk in enumerate(chunks):
                    relative = Path(job.book_id) / job.id / f"{chapter.index:04d}-{chunk_index:03d}.wav"
                    relative_posix = relative.as_posix()
                    output_path = self.audio_dir / relative
                    job.current_chapter_index = chapter.index
                    job.current_chunk_index = len(audio_files)
                    self._set_progress(
                        job,
                        "Synthesizing PDF speech",
                        f"Page {chapter.index + 1}, part {chunk_index + 1}/{len(chunks)}; {len(audio_files)}/{max(job.total_audio_files, len(audio_files) + 1)} ready.",
                    )
                    if not output_path.exists() or output_path.stat().st_size == 0:
                        self.backend.synthesize(chunk, output_path, job.language, job.voice, job.tts_options)
                    if relative_posix not in seen_audio:
                        seen_audio.add(relative_posix)
                        audio_files.append(relative_posix)
                        job.audio_files = audio_files
                        job.total_audio_files = max(job.total_audio_files, len(audio_files), total_pages - start_index)
                        job.total_chunks = max(job.total_chunks, job.total_audio_files)
                        job.current_chunk_index = len(audio_files)
                        self._set_progress(
                            job,
                            "PDF audio ready",
                            f"{len(audio_files)}/{job.total_audio_files} audio files generated.",
                        )

            if pdf_ocr_cached_page_count(book.path) >= total_pages:
                break
            cached_pages = pdf_ocr_cached_page_count(book.path)
            self._set_progress(job, "OCRing PDF", f"Reading more pages with OCR: {cached_pages}/{total_pages} cached.")
            pdf_ocr_next_batch(book.path)

        job.audio_files = audio_files
        job.status = JobStatus.DONE
        job.error = None
        job.current_chunk_index = len(audio_files)
        self._set_progress(job, "Ready", f"{len(audio_files)} {_audio_file_word(len(audio_files))} generated.")

    def _set_progress(self, job: TtsJob, label: str, detail: str = "") -> None:
        job.progress_label = label
        job.progress_detail = detail
        self.store.put(job)


def _max_chars_for_backend(backend_name: str) -> int:
    env_name = "EUTHERBOOKS_PIPER_MAX_CHARS" if backend_name == "piper" else "EUTHERBOOKS_MAX_CHARS"
    fallback = DEFAULT_PIPER_MAX_CHARS_PER_AUDIO_FILE if backend_name == "piper" else DEFAULT_MAX_CHARS_PER_AUDIO_FILE
    try:
        return max(200, int(os.environ.get(env_name, fallback)))
    except ValueError:
        return fallback


def _stored_progress_label(value: dict[str, Any]) -> str:
    label = str(value.get("progress_label") or "").strip()
    if label:
        return label
    status = str(value.get("status") or "")
    if status == JobStatus.DONE.value:
        return "Ready"
    if status == JobStatus.FAILED.value:
        return "Failed"
    if status == JobStatus.RUNNING.value:
        return "Running"
    return "Queued"


def _stored_progress_detail(value: dict[str, Any]) -> str:
    detail = str(value.get("progress_detail") or "").strip()
    if detail:
        return detail
    audio_count = len(value.get("audio_files", []) or [])
    total = int(value.get("total_audio_files", 0) or 0)
    status = str(value.get("status") or "")
    if status == JobStatus.DONE.value:
        return f"{audio_count} {_audio_file_word(audio_count)} generated."
    if status == JobStatus.FAILED.value:
        return str(value.get("error") or "Generation failed.")
    if status == JobStatus.RUNNING.value and total:
        return f"{audio_count}/{total} audio files generated."
    return ""


def _audio_file_word(count: int) -> str:
    return "audio file" if count == 1 else "audio files"


def _normalized_tts_options(options: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    ranges = {
        "length_scale": (0.65, 1.6),
        "noise_scale": (0.1, 1.2),
        "noise_w": (0.1, 1.4),
        "sentence_silence": (0.0, 1.5),
        "cfg_value": (1.0, 3.0),
        "inference_timesteps": (1.0, 50.0),
        "max_chunk_chars": (120.0, 1500.0),
    }
    for key, (minimum, maximum) in ranges.items():
        if key not in options or options[key] is None:
            continue
        try:
            value = float(options[key])
        except (TypeError, ValueError):
            continue
        clamped = min(maximum, max(minimum, value))
        normalized[key] = round(clamped) if key in {"inference_timesteps", "max_chunk_chars"} else clamped
    reference_path = _clean_reference_path(options.get("voice_reference_path"))
    prompt_text = _clean_prompt_text(options.get("voice_prompt_text"))
    if reference_path:
        normalized["voice_reference_path"] = reference_path
    if prompt_text:
        normalized["voice_prompt_text"] = prompt_text
    return normalized


def _clean_reference_path(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or len(value) > 600 or any(ord(ch) < 32 for ch in value):
        return ""
    if not value.endswith(".wav"):
        return ""
    return value


def _clean_prompt_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value.strip()[:500] if ch == "\t" or ord(ch) >= 32)


def _split_for_tts(text: str, max_chars: int = DEFAULT_MAX_CHARS_PER_AUDIO_FILE) -> list[str]:
    paragraphs = [part.strip() for part in text.splitlines() if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs or [text]:
        if current and current_len + len(paragraph) > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        while len(paragraph) > max_chars:
            chunks.append(paragraph[:max_chars])
            paragraph = paragraph[max_chars:].strip()
        if not paragraph:
            continue
        current.append(paragraph)
        current_len += len(paragraph)
    if current:
        chunks.append("\n".join(current))
    return chunks
