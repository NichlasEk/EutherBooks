from __future__ import annotations

from pathlib import Path

from eutherbooks.jobs import JobStore, TtsQueue, _max_chars_for_backend, _split_for_tts
from eutherbooks.ids import stable_job_id
from eutherbooks.library import Library
from eutherbooks.models import JobStatus, TtsJob
from eutherbooks.tts import TtsBackend


class RecordingBackend(TtsBackend):
    name = "recording"

    def __init__(self) -> None:
        self.calls = 0

    def synthesize(
        self,
        text: str,
        output_path: Path,
        language: str,
        voice: str,
        options: dict[str, object] | None = None,
    ) -> None:
        self.calls += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")


def test_job_store_round_trips_jobs(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    job = TtsJob(
        id="job1",
        book_id="book1",
        status=JobStatus.DONE,
        language="sv",
        voice="sv",
        chapter_indexes=[0],
        audio_files=["book1/job1/0000-000.wav"],
        total_audio_files=1,
        progress_label="Ready",
        progress_detail="1 audio file generated.",
        current_chapter_index=0,
        current_chunk_index=1,
        total_chunks=1,
    )

    store.put(job)

    loaded = store.get("job1")
    assert loaded is not None
    assert loaded.status == JobStatus.DONE
    assert loaded.audio_files == ["book1/job1/0000-000.wav"]
    assert loaded.total_audio_files == 1
    assert loaded.progress_label == "Ready"
    assert loaded.progress_detail == "1 audio file generated."
    assert loaded.current_chapter_index == 0
    assert loaded.current_chunk_index == 1
    assert loaded.total_chunks == 1


def test_job_store_backfills_legacy_progress_fields(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        """
        {
          "job1": {
            "id": "job1",
            "book_id": "book1",
            "status": "done",
            "language": "sv",
            "voice": "sv",
            "chapter_indexes": [0],
            "audio_files": ["book1/job1/0000-000.wav"],
            "total_audio_files": 1,
            "tts_options": {}
          }
        }
        """,
        encoding="utf-8",
    )

    loaded = store.get("job1")

    assert loaded is not None
    assert loaded.progress_label == "Ready"
    assert loaded.progress_detail == "1 audio file generated."


def test_job_store_resets_incomplete_jobs(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    store.put(
        TtsJob(
            id="job1",
            book_id="book1",
            status=JobStatus.RUNNING,
            language="sv",
            voice="sv",
            chapter_indexes=[0],
        )
    )

    store.reset_incomplete("Restarted.")

    loaded = store.get("job1")
    assert loaded is not None
    assert loaded.status == JobStatus.FAILED
    assert loaded.error == "Restarted."
    assert loaded.progress_label == "Interrupted"
    assert loaded.progress_detail == "Restarted."


def test_tts_queue_reuses_existing_active_job(tmp_path: Path) -> None:
    library_dir = tmp_path / "library"
    book_path = library_dir / "book.txt"
    book_path.parent.mkdir(parents=True)
    book_path.write_text("Hello", encoding="utf-8")
    library = Library(library_dir)
    book = library.list_books()[0]
    store = JobStore(tmp_path / "data")
    backend = RecordingBackend()
    queue = TtsQueue(library, store, backend, tmp_path / "audio")

    first = queue.enqueue(book.id, "en", "en", [0])
    second = queue.enqueue(book.id, "en", "en", [0])

    assert first.id == second.id


def test_tts_queue_backfills_total_for_existing_job(tmp_path: Path) -> None:
    library_dir = tmp_path / "library"
    book_path = library_dir / "book.txt"
    book_path.parent.mkdir(parents=True)
    book_path.write_text("Hello", encoding="utf-8")
    library = Library(library_dir)
    book = library.list_books()[0]
    store = JobStore(tmp_path / "data")
    backend = RecordingBackend()
    job_id = stable_job_id(book.id, "recording:en:{}", [0])
    store.put(
        TtsJob(
            id=job_id,
            book_id=book.id,
            status=JobStatus.DONE,
            language="en",
            voice="en",
            chapter_indexes=[0],
            audio_files=["book/job/0000-000.wav"],
        )
    )
    queue = TtsQueue(library, store, backend, tmp_path / "audio")

    job = queue.enqueue(book.id, "en", "en", [0])

    assert job.total_audio_files == 1
    assert store.get(job_id).total_audio_files == 1  # type: ignore[union-attr]


def test_split_for_tts_honors_max_chars() -> None:
    assert _split_for_tts("abcdef", max_chars=2) == ["ab", "cd", "ef"]


def test_piper_uses_smaller_default_chunks(monkeypatch) -> None:
    monkeypatch.delenv("EUTHERBOOKS_PIPER_MAX_CHARS", raising=False)
    monkeypatch.delenv("EUTHERBOOKS_MAX_CHARS", raising=False)

    assert _max_chars_for_backend("piper") < _max_chars_for_backend("espeak")


def test_job_id_includes_backend_namespace() -> None:
    indexes = [0]

    assert stable_job_id("book", "piper:sv", indexes) != stable_job_id("book", "espeak:sv", indexes)
