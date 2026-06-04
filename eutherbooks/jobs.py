from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from pathlib import Path

from .ids import stable_job_id
from .library import Library
from .models import JobStatus, TtsJob
from .tts import TtsBackend


DEFAULT_MAX_CHARS_PER_AUDIO_FILE = 4_000
DEFAULT_PIPER_MAX_CHARS_PER_AUDIO_FILE = 900


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

    def enqueue(self, book_id: str, language: str, voice: str, chapter_indexes: list[int] | None = None) -> TtsJob:
        chapters = self.library.chapters_for(book_id)
        indexes = chapter_indexes if chapter_indexes is not None else [chapter.index for chapter in chapters]
        job = TtsJob(
            id=stable_job_id(book_id, f"{self.backend.name}:{voice}", indexes),
            book_id=book_id,
            status=JobStatus.QUEUED,
            language=language,
            voice=voice,
            chapter_indexes=indexes,
        )
        self.store.put(job)
        thread = threading.Thread(target=self._run_job, args=(job.id,), daemon=True)
        thread.start()
        return job

    def _run_job(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        job.status = JobStatus.RUNNING
        self.store.put(job)

        try:
            chapters = {chapter.index: chapter for chapter in self.library.chapters_for(job.book_id)}
            audio_files: list[str] = []
            for chapter_index in job.chapter_indexes:
                chapter = chapters[chapter_index]
                chunks = _split_for_tts(chapter.text, max_chars=_max_chars_for_backend(self.backend.name))
                for chunk_index, chunk in enumerate(chunks):
                    relative = Path(job.book_id) / job.id / f"{chapter_index:04d}-{chunk_index:03d}.wav"
                    output_path = self.audio_dir / relative
                    if not output_path.exists() or output_path.stat().st_size == 0:
                        self.backend.synthesize(chunk, output_path, job.language, job.voice)
                    audio_files.append(relative.as_posix())
                    job.audio_files = audio_files
                    self.store.put(job)

            job.audio_files = audio_files
            job.status = JobStatus.DONE
            job.error = None
        except Exception as exc:  # noqa: BLE001
            job.status = JobStatus.FAILED
            job.error = str(exc)
        finally:
            self.store.put(job)


def _max_chars_for_backend(backend_name: str) -> int:
    env_name = "EUTHERBOOKS_PIPER_MAX_CHARS" if backend_name == "piper" else "EUTHERBOOKS_MAX_CHARS"
    fallback = DEFAULT_PIPER_MAX_CHARS_PER_AUDIO_FILE if backend_name == "piper" else DEFAULT_MAX_CHARS_PER_AUDIO_FILE
    try:
        return max(200, int(os.environ.get(env_name, fallback)))
    except ValueError:
        return fallback


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
