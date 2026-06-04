from __future__ import annotations

from pathlib import Path

from eutherbooks.jobs import JobStore, _max_chars_for_backend, _split_for_tts
from eutherbooks.ids import stable_job_id
from eutherbooks.models import JobStatus, TtsJob


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
    )

    store.put(job)

    loaded = store.get("job1")
    assert loaded is not None
    assert loaded.status == JobStatus.DONE
    assert loaded.audio_files == ["book1/job1/0000-000.wav"]


def test_split_for_tts_honors_max_chars() -> None:
    assert _split_for_tts("abcdef", max_chars=2) == ["ab", "cd", "ef"]


def test_piper_uses_smaller_default_chunks(monkeypatch) -> None:
    monkeypatch.delenv("EUTHERBOOKS_PIPER_MAX_CHARS", raising=False)
    monkeypatch.delenv("EUTHERBOOKS_MAX_CHARS", raising=False)

    assert _max_chars_for_backend("piper") < _max_chars_for_backend("espeak")


def test_job_id_includes_backend_namespace() -> None:
    indexes = [0]

    assert stable_job_id("book", "piper:sv", indexes) != stable_job_id("book", "espeak:sv", indexes)
