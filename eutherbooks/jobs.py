from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import wave
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from .ids import stable_job_id
from .extractors import pdf_ocr_cached_page_count, pdf_ocr_next_batch, pdf_page_count
from .library import Library
from .models import Chapter, JobStatus, TtsJob
from .tts import TtsBackend


LOGGER = logging.getLogger("eutherbooks.jobs")

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

    def cancel_incomplete_for_owner(self, owner: str, reason: str, except_job_id: str | None = None) -> int:
        clean_owner = owner.strip()
        if not clean_owner:
            return 0
        with self._lock:
            jobs = self._read()
            changed = False
            cancelled = 0
            for job in jobs.values():
                if job.id == except_job_id or job.owner != clean_owner:
                    continue
                if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                    job.status = JobStatus.FAILED
                    job.error = reason
                    job.progress_label = "Cancelled"
                    job.progress_detail = reason
                    job.worker_progress = 0.0
                    changed = True
                    cancelled += 1
            if changed:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                payload = {job_id: asdict(value) for job_id, value in jobs.items()}
                self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return cancelled

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
                    job.worker_progress = 0.0
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
                owner=str(value.get("owner") or ""),
                audio_files=list(value.get("audio_files", [])),
                audio_durations=_stored_audio_durations(value),
                total_audio_files=int(value.get("total_audio_files", 0)),
                tts_options=dict(value.get("tts_options", {})),
                queue_remainder=bool(value.get("queue_remainder", False)),
                progress_label=_stored_progress_label(value),
                progress_detail=str(value.get("progress_detail") or _stored_progress_detail(value)),
                current_chapter_index=value.get("current_chapter_index"),
                current_chunk_index=int(value.get("current_chunk_index", 0)),
                worker_progress=_stored_worker_progress(value),
                total_chunks=int(value.get("total_chunks", 0)),
                perf=dict(value.get("perf", {})) if isinstance(value.get("perf"), dict) else {},
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
        owner: str = "",
        cancel_existing: bool = True,
    ) -> TtsJob:
        chapters = self.library.chapters_for(book_id)
        book = self.library.get_book(book_id)
        pdf_remainder = bool(queue_remainder and book and book.path.suffix.lower() == ".pdf")
        indexes = chapter_indexes if chapter_indexes is not None else [chapter.index for chapter in chapters]
        if pdf_remainder and not indexes:
            indexes = [0]
        options = _normalized_tts_options(tts_options or {})
        clean_owner = _clean_owner(owner)
        options_key = json.dumps(options, sort_keys=True, separators=(",", ":"))
        mode_key = ":remainder" if pdf_remainder else ""
        job_id = stable_job_id(book_id, f"{self.backend.name}:{voice}:{options_key}{mode_key}", indexes)
        total_audio_files = (
            max(1, pdf_page_count(book.path) - indexes[0] if book else 0)
            if pdf_remainder
            else self._total_audio_files(chapters, indexes, options)
        )
        existing = self.store.get(job_id)
        if existing and existing.status in {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.DONE}:
            if existing.owner != clean_owner:
                existing.owner = clean_owner
                self.store.put(existing)
            if existing.total_audio_files <= 0:
                existing.total_audio_files = total_audio_files
                self.store.put(existing)
            if cancel_existing:
                self.store.cancel_incomplete_for_owner(clean_owner, "Cancelled by a newer request from the same user.", existing.id)
            return existing

        if clean_owner and cancel_existing:
            self.store.cancel_incomplete_for_owner(clean_owner, "Cancelled by a newer request from the same user.")

        job = TtsJob(
            id=job_id,
            book_id=book_id,
            status=JobStatus.QUEUED,
            language=language,
            voice=voice,
            chapter_indexes=indexes,
            owner=clean_owner,
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

    def _total_audio_files(self, chapters: list[Chapter], indexes: list[int], options: dict[str, Any] | None = None) -> int:
        chapters_by_index = {chapter.index: chapter for chapter in chapters}
        max_chars = _max_chars_for_options(self.backend.name, options or {})
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
                self._raise_if_cancelled(job.id)
                if job.queue_remainder:
                    self._run_progressive_pdf_job(job)
                    return
                chapters = {chapter.index: chapter for chapter in self.library.chapters_for(job.book_id)}
                audio_files: list[str] = []
                audio_durations: list[float] = []
                seen_audio: set[str] = set()
                total_chunks = self._total_audio_files(list(chapters.values()), job.chapter_indexes, job.tts_options)
                job.total_chunks = total_chunks
                job.total_audio_files = max(job.total_audio_files, total_chunks)
                self.store.put(job)
                for chapter_index in job.chapter_indexes:
                    chapter = chapters[chapter_index]
                    chunks = _split_for_tts(chapter.text, max_chars=_max_chars_for_options(self.backend.name, job.tts_options))
                    for chunk_index, chunk in enumerate(chunks):
                        self._raise_if_cancelled(job.id)
                        relative = Path(job.book_id) / job.id / f"{chapter_index:04d}-{chunk_index:03d}.wav"
                        output_path = self.audio_dir / relative
                        job.current_chapter_index = chapter_index
                        job.current_chunk_index = len(audio_files)
                        job.worker_progress = 0.0
                        self._set_progress(
                            job,
                            "Synthesizing speech",
                            f"{chapter.title}: part {chunk_index + 1}/{len(chunks)} ({len(audio_files) + 1}/{total_chunks})",
                        )
                        LOGGER.warning(
                            "TTS_TRACE eutherbooks_part job=%s book=%s chapter=%s chunk=%s/%s output=%s exists=%s voice=%s lang=%s seed=%s reference_path=%s text_len=%s text_sha=%s",
                            job.id,
                            job.book_id,
                            chapter_index,
                            chunk_index + 1,
                            len(chunks),
                            output_path,
                            output_path.exists() and output_path.stat().st_size > 0,
                            job.voice,
                            job.language,
                            job.tts_options.get("seed"),
                            job.tts_options.get("voice_reference_path"),
                            len(chunk),
                            _short_sha256(chunk.encode("utf-8")),
                        )
                        if not output_path.exists() or output_path.stat().st_size == 0:
                            part_started = time.perf_counter()
                            self.backend.synthesize(
                                chunk,
                                output_path,
                                job.language,
                                job.voice,
                                job.tts_options,
                                progress_callback=self._worker_progress_callback(
                                    job,
                                    "Synthesizing speech",
                                    f"{chapter.title}: part {chunk_index + 1}/{len(chunks)} ({len(audio_files) + 1}/{total_chunks})",
                                    lambda: len(audio_files),
                                    chapter_index,
                                    lambda status: self._publish_partial_audio(
                                        job,
                                        audio_files,
                                        audio_durations,
                                        seen_audio,
                                        status,
                                        total_chunks,
                                    ),
                                ),
                            )
                            job.perf.update(
                                {
                                    "eutherbooks_part_sec": time.perf_counter() - part_started,
                                    "eutherbooks_part_output_bytes": output_path.stat().st_size if output_path.exists() else 0,
                                }
                            )
                            self._raise_if_cancelled(job.id)
                        relative_posix = relative.as_posix()
                        self._replace_partial_audio_with_final(audio_files, audio_durations, seen_audio, relative_posix)
                        if relative_posix not in seen_audio:
                            seen_audio.add(relative_posix)
                            audio_files.append(relative_posix)
                            audio_durations.append(_wav_duration_seconds(output_path))
                            job.audio_files = audio_files
                            job.audio_durations = audio_durations
                            job.current_chunk_index = len(audio_files)
                            job.worker_progress = 0.0
                            self._set_progress(
                                job,
                                "Audio ready",
                                f"{len(audio_files)}/{max(job.total_audio_files, len(audio_files))} audio files generated.",
                            )

                self._raise_if_cancelled(job.id)
                job.audio_files = audio_files
                job.audio_durations = audio_durations
                job.status = JobStatus.DONE
                job.error = None
                job.current_chunk_index = len(audio_files)
                job.worker_progress = 0.0
                self._set_progress(job, "Ready", f"{len(audio_files)} {_audio_file_word(len(audio_files))} generated.")
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                job.status = JobStatus.FAILED
                job.error = message
                job.worker_progress = 0.0
                if message.startswith("Cancelled"):
                    self._set_progress(job, "Cancelled", message)
                else:
                    self._set_progress(job, "Failed", message)
            finally:
                self.store.put(job)

    def _run_progressive_pdf_job(self, job: TtsJob) -> None:
        book = self.library.get_book(job.book_id)
        if book is None:
            raise KeyError(f"Unknown book id: {job.book_id}")
        start_index = job.chapter_indexes[0] if job.chapter_indexes else 0
        total_pages = pdf_page_count(book.path)
        audio_files = list(job.audio_files)
        audio_durations = list(job.audio_durations)
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
                chunks = _split_for_tts(chapter.text, max_chars=_max_chars_for_options(self.backend.name, job.tts_options))
                for chunk_index, chunk in enumerate(chunks):
                    relative = Path(job.book_id) / job.id / f"{chapter.index:04d}-{chunk_index:03d}.wav"
                    relative_posix = relative.as_posix()
                    output_path = self.audio_dir / relative
                    job.current_chapter_index = chapter.index
                    job.current_chunk_index = len(audio_files)
                    job.worker_progress = 0.0
                    self._set_progress(
                        job,
                        "Synthesizing PDF speech",
                        f"Page {chapter.index + 1}, part {chunk_index + 1}/{len(chunks)}; {len(audio_files)}/{max(job.total_audio_files, len(audio_files) + 1)} ready.",
                    )
                    LOGGER.warning(
                        "TTS_TRACE eutherbooks_pdf_part job=%s book=%s page=%s chunk=%s/%s output=%s exists=%s voice=%s lang=%s seed=%s reference_path=%s text_len=%s text_sha=%s",
                        job.id,
                        job.book_id,
                        chapter.index,
                        chunk_index + 1,
                        len(chunks),
                        output_path,
                        output_path.exists() and output_path.stat().st_size > 0,
                        job.voice,
                        job.language,
                        job.tts_options.get("seed"),
                        job.tts_options.get("voice_reference_path"),
                        len(chunk),
                        _short_sha256(chunk.encode("utf-8")),
                    )
                    if not output_path.exists() or output_path.stat().st_size == 0:
                        self.backend.synthesize(
                            chunk,
                            output_path,
                            job.language,
                            job.voice,
                            job.tts_options,
                            progress_callback=self._worker_progress_callback(
                                job,
                                "Synthesizing PDF speech",
                                f"Page {chapter.index + 1}, part {chunk_index + 1}/{len(chunks)}; {len(audio_files)}/{max(job.total_audio_files, len(audio_files) + 1)} ready.",
                                lambda: len(audio_files),
                                chapter.index,
                                lambda status: self._publish_partial_audio(
                                    job,
                                    audio_files,
                                    audio_durations,
                                    seen_audio,
                                    status,
                                    total_pages - start_index,
                                ),
                            ),
                        )
                    self._replace_partial_audio_with_final(audio_files, audio_durations, seen_audio, relative_posix)
                    if relative_posix not in seen_audio:
                        seen_audio.add(relative_posix)
                        audio_files.append(relative_posix)
                        audio_durations.append(_wav_duration_seconds(output_path))
                        job.audio_files = audio_files
                        job.audio_durations = audio_durations
                        job.total_audio_files = max(job.total_audio_files, len(audio_files), total_pages - start_index)
                        job.total_chunks = max(job.total_chunks, job.total_audio_files)
                        job.current_chunk_index = len(audio_files)
                        job.worker_progress = 0.0
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
        job.audio_durations = audio_durations
        job.status = JobStatus.DONE
        job.error = None
        job.current_chunk_index = len(audio_files)
        job.worker_progress = 0.0
        self._set_progress(job, "Ready", f"{len(audio_files)} {_audio_file_word(len(audio_files))} generated.")

    def _worker_progress_callback(
        self,
        job: TtsJob,
        label: str,
        base_detail: str,
        ready_count: Callable[[], int],
        chapter_index: int,
        partial_publisher: Callable[[dict[str, Any]], None] | None = None,
    ) -> Callable[[dict[str, Any]], None]:
        def update(status: dict[str, Any]) -> None:
            self._raise_if_cancelled(job.id)
            if partial_publisher is not None:
                partial_publisher(status)
            perf = status.get("perf")
            if isinstance(perf, dict):
                job.perf.update(
                    {
                        f"worker_{key}": value
                        for key, value in perf.items()
                        if isinstance(key, str) and isinstance(value, (str, int, float, bool))
                    }
                )
            progress = _stored_worker_progress(status)
            message = str(status.get("message") or "").strip()
            job.worker_progress = progress
            job.current_chapter_index = chapter_index
            job.current_chunk_index = ready_count()
            percent = round(progress * 100)
            detail = f"{base_detail}; worker {percent}%"
            if message:
                detail = f"{detail} - {message}"
            self._set_progress(job, label, detail)

        return update

    def _publish_partial_audio(
        self,
        job: TtsJob,
        audio_files: list[str],
        audio_durations: list[float],
        seen_audio: set[str],
        status: dict[str, Any],
        total_hint: int,
    ) -> None:
        latest_partial: Path | None = None
        for value in status.get("partial_audio_paths") or []:
            path = Path(str(value))
            try:
                path.relative_to(self.audio_dir)
            except ValueError:
                continue
            if not path.exists() or path.stat().st_size <= 0:
                continue
            latest_partial = path
        if latest_partial is None:
            return
        job.perf.update(
            {
                "eutherbooks_partial_count": len([path for path in audio_files if ".stream-" in path]),
                "eutherbooks_last_partial_bytes": latest_partial.stat().st_size,
                "eutherbooks_last_partial_duration_sec": _wav_duration_seconds(latest_partial),
            }
        )
        job.total_audio_files = max(job.total_audio_files, total_hint)
        job.total_chunks = max(job.total_chunks, job.total_audio_files)
        job.current_chunk_index = len(audio_files)
        self.store.put(job)

    def _replace_partial_audio_with_final(
        self,
        audio_files: list[str],
        audio_durations: list[float],
        seen_audio: set[str],
        final_relative: str,
    ) -> None:
        partial_prefix = final_relative.removesuffix(".wav") + ".stream-"
        indexes = [
            index
            for index, audio_path in enumerate(audio_files)
            if audio_path.startswith(partial_prefix) and audio_path.endswith(".wav")
        ]
        for index in reversed(indexes):
            seen_audio.discard(audio_files[index])
            del audio_files[index]
            if index < len(audio_durations):
                del audio_durations[index]

    def _raise_if_cancelled(self, job_id: str) -> None:
        latest = self.store.get(job_id)
        if latest is None:
            raise RuntimeError("TTS job disappeared.")
        if latest.status == JobStatus.FAILED and str(latest.error or "").startswith("Cancelled"):
            raise RuntimeError(latest.error or "Cancelled by a newer request.")

    def _set_progress(self, job: TtsJob, label: str, detail: str = "") -> None:
        job.progress_label = label
        job.progress_detail = detail
        self.store.put(job)


def _short_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _max_chars_for_backend(backend_name: str) -> int:
    env_name = "EUTHERBOOKS_PIPER_MAX_CHARS" if backend_name == "piper" else "EUTHERBOOKS_MAX_CHARS"
    fallback = DEFAULT_PIPER_MAX_CHARS_PER_AUDIO_FILE if backend_name == "piper" else DEFAULT_MAX_CHARS_PER_AUDIO_FILE
    try:
        return max(200, int(os.environ.get(env_name, fallback)))
    except ValueError:
        return fallback


def _max_chars_for_options(backend_name: str, options: dict[str, Any]) -> int:
    default = _max_chars_for_backend(backend_name)
    requested = options.get("max_chunk_chars")
    try:
        value = int(requested) if requested is not None else default
    except (TypeError, ValueError):
        value = default
    return max(120, min(1500, value))


def _stored_worker_progress(value: dict[str, Any]) -> float:
    try:
        progress = float(value.get("worker_progress", value.get("progress", 0.0)) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if progress != progress:
        return 0.0
    return min(1.0, max(0.0, progress))


def _stored_audio_durations(value: dict[str, Any]) -> list[float]:
    durations = value.get("audio_durations", [])
    if not isinstance(durations, list):
        return []
    safe: list[float] = []
    for duration in durations:
        try:
            seconds = float(duration)
        except (TypeError, ValueError):
            seconds = 0.0
        safe.append(max(0.0, seconds) if seconds == seconds else 0.0)
    return safe


def _wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav_file:
            rate = wav_file.getframerate()
            if rate <= 0:
                return 0.0
            return round(wav_file.getnframes() / rate, 3)
    except (OSError, EOFError, wave.Error):
        return 0.0


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


def _clean_owner(value: Any) -> str:
    owner = str(value or "").strip()
    if not owner:
        return "anonymous"
    safe = "".join(ch for ch in owner[:120] if ch.isalnum() or ch in {"-", "_", ".", "@"})
    return safe or "anonymous"


def _normalized_tts_options(options: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    ranges = {
        "length_scale": (0.65, 1.6),
        "noise_scale": (0.1, 1.2),
        "noise_w": (0.1, 1.4),
        "sentence_silence": (0.0, 1.5),
        "cfg_value": (1.0, 3.0),
        "inference_timesteps": (10.0, 50.0),
        "dots_num_steps": (1.0, 50.0),
        "dots_guidance_scale": (0.0, 5.0),
        "dots_speaker_scale": (0.0, 5.0),
        "dots_max_generate_length": (128.0, 4096.0),
        "max_chunk_chars": (120.0, 1500.0),
        "seed": (0.0, 2147483647.0),
    }
    for key, (minimum, maximum) in ranges.items():
        if key not in options or options[key] is None:
            continue
        try:
            value = float(options[key])
        except (TypeError, ValueError):
            continue
        clamped = min(maximum, max(minimum, value))
        normalized[key] = round(clamped) if key in {"inference_timesteps", "dots_num_steps", "dots_max_generate_length", "max_chunk_chars", "seed"} else clamped
    reference_path = _clean_reference_path(options.get("voice_reference_path"))
    prompt_text = _clean_prompt_text(options.get("voice_prompt_text"))
    if reference_path:
        normalized["voice_reference_path"] = reference_path
    if prompt_text:
        normalized["voice_prompt_text"] = prompt_text
    model_backend = _clean_model_backend(options.get("model_backend"))
    if model_backend:
        normalized["model_backend"] = model_backend
    dots_template_name = _clean_dots_template_name(options.get("dots_template_name"))
    if dots_template_name:
        normalized["dots_template_name"] = dots_template_name
    dots_ode_method = _clean_dots_ode_method(options.get("dots_ode_method"))
    if dots_ode_method:
        normalized["dots_ode_method"] = dots_ode_method
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


def _clean_model_backend(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower()
    return normalized if normalized in {"voxcpm2", "dots.tts-soar", "dots.tts-mf"} else ""


def _clean_dots_template_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower()
    return normalized if normalized in {"tts", "instruction_tts", "text_to_audio", "tts_interleave"} else ""


def _clean_dots_ode_method(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower()
    return normalized if normalized in {"euler", "midpoint"} else ""


def _split_for_tts(text: str, max_chars: int = DEFAULT_MAX_CHARS_PER_AUDIO_FILE) -> list[str]:
    paragraphs = _tts_paragraphs(text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs or [text.strip()]:
        for segment in _split_tts_segment(paragraph, max_chars):
            separator_len = 1 if current else 0
            if current and current_len + separator_len + len(segment) > max_chars:
                chunks.append(" ".join(current))
                current = []
                current_len = 0
                separator_len = 0
            current.append(segment)
            current_len += separator_len + len(segment)
    if current:
        chunks.append(" ".join(current))
    return chunks


def _tts_paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n+", normalized)
    paragraphs: list[str] = []
    for block in blocks:
        paragraph = re.sub(r"[ \t]*\n[ \t]*", " ", block.strip())
        paragraph = re.sub(r"[ \t]{2,}", " ", paragraph).strip()
        if paragraph:
            paragraphs.append(paragraph)
    return paragraphs


def _split_tts_segment(text: str, max_chars: int) -> list[str]:
    remaining = text.strip()
    chunks: list[str] = []
    while len(remaining) > max_chars:
        split_at = _best_tts_split_index(remaining, max_chars)
        head = remaining[:split_at].strip()
        if head:
            chunks.append(head)
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _best_tts_split_index(text: str, max_chars: int) -> int:
    window = text[:max_chars + 1]
    min_index = max(1, int(max_chars * 0.45))
    for pattern in (r"(?<=[.!?。！？])\s+", r"(?<=[,;:])\s+", r"\s+"):
        matches = [match for match in re.finditer(pattern, window) if min_index <= match.end() <= max_chars]
        if matches:
            return matches[-1].end()
    return max_chars
