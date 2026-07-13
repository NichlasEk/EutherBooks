from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.transcode_generated_audio import load_candidates, update_job_path


def test_transcode_candidate_updates_sqlite_job_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    audio_dir = tmp_path / "audio"
    source = audio_dir / "book" / "job" / "0000-000.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"wav")
    data_dir.mkdir()
    db_path = data_dir / "jobs.sqlite3"
    payload = {
        "id": "job",
        "book_id": "book",
        "status": "done",
        "audio_files": ["book/job/0000-000.wav"],
    }
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT, updated_at REAL, payload TEXT)"
        )
        connection.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?)",
            ("job", "done", 1.0, json.dumps(payload)),
        )

    candidates = load_candidates(db_path, audio_dir, 0)
    assert len(candidates) == 1
    candidate = candidates[0]
    candidate.target_path.write_bytes(b"mp3")
    assert update_job_path(db_path, candidate)

    with sqlite3.connect(db_path) as connection:
        updated = json.loads(connection.execute("SELECT payload FROM jobs WHERE id = 'job'").fetchone()[0])
    assert updated["audio_files"] == ["book/job/0000-000.mp3"]
