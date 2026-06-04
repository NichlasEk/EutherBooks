from __future__ import annotations

from pathlib import Path

from eutherbooks.jobs import JobStore
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

