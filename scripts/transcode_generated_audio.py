#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from eutherbooks.jobs import _finalize_generated_audio


@dataclass(frozen=True)
class Candidate:
    job_id: str
    relative_path: str
    source_path: Path
    target_path: Path
    source_bytes: int


def load_candidates(db_path: Path, audio_dir: Path, min_age_seconds: float) -> list[Candidate]:
    now = time.time()
    candidates: list[Candidate] = []
    with sqlite3.connect(db_path, timeout=30) as connection:
        rows = connection.execute(
            "SELECT id, payload, updated_at FROM jobs WHERE status = 'done' ORDER BY updated_at ASC"
        ).fetchall()
    for job_id, raw_payload, updated_at in rows:
        if min_age_seconds and now - float(updated_at) < min_age_seconds:
            continue
        payload = json.loads(raw_payload)
        for relative in payload.get("audio_files", []):
            relative = str(relative)
            if not relative.endswith(".wav") or ".stream-" in relative:
                continue
            source = audio_dir / relative
            target = source.with_suffix(".mp3")
            if not source.exists() and not target.exists():
                continue
            candidates.append(
                Candidate(
                    job_id=str(job_id),
                    relative_path=relative,
                    source_path=source,
                    target_path=target,
                    source_bytes=source.stat().st_size if source.exists() else 0,
                )
            )
    return candidates


def update_job_path(db_path: Path, candidate: Candidate) -> bool:
    with sqlite3.connect(db_path, timeout=30) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT payload FROM jobs WHERE id = ? AND status = 'done'", (candidate.job_id,)
        ).fetchone()
        if row is None:
            return False
        payload = json.loads(row[0])
        audio_files = [str(value) for value in payload.get("audio_files", [])]
        replacement = candidate.target_path.relative_to(candidate.source_path.parents[2]).as_posix()
        changed = False
        for index, value in enumerate(audio_files):
            if value == candidate.relative_path:
                audio_files[index] = replacement
                changed = True
        if not changed:
            return False
        payload["audio_files"] = audio_files
        connection.execute(
            "UPDATE jobs SET payload = ?, updated_at = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False, separators=(",", ":")), time.time(), candidate.job_id),
        )
        return True


def cleanup_unreferenced_wavs(db_path: Path, audio_dir: Path, min_age_seconds: float) -> tuple[int, int]:
    with sqlite3.connect(db_path, timeout=30) as connection:
        rows = connection.execute("SELECT payload FROM jobs").fetchall()
    referenced = {
        str(relative)
        for (raw_payload,) in rows
        for relative in json.loads(raw_payload).get("audio_files", [])
    }
    now = time.time()
    removed = 0
    reclaimed = 0
    for path in audio_dir.glob("*/*/*.wav"):
        relative = path.relative_to(audio_dir).as_posix()
        if relative in referenced or ".stream-" in relative or not path.with_suffix(".mp3").exists():
            continue
        if min_age_seconds and now - path.stat().st_mtime < min_age_seconds:
            continue
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        removed += 1
        reclaimed += size
    return removed, reclaimed


def format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resumably convert completed EutherBooks WAV parts to MP3.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--audio-dir", type=Path, default=None)
    parser.add_argument("--bitrate-kbps", type=int, default=64)
    parser.add_argument("--min-age-hours", type=float, default=2.0)
    parser.add_argument("--max-files", type=int, default=100)
    parser.add_argument("--delete-source-after-days", type=float, default=7.0)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    data_dir = args.data_dir.resolve()
    audio_dir = (args.audio_dir or data_dir / "audio").resolve()
    db_path = data_dir / "jobs.sqlite3"
    if not db_path.exists():
        raise SystemExit(f"jobs database not found: {db_path}")
    limit = max(1, args.max_files)
    candidates = load_candidates(db_path, audio_dir, max(0.0, args.min_age_hours) * 3600)[:limit]
    source_bytes = sum(candidate.source_bytes for candidate in candidates)
    print(f"candidates: {len(candidates)}, WAV input: {format_bytes(source_bytes)}")
    if not args.apply:
        print("dry run only; pass --apply to transcode")
        return 0

    os.environ["EUTHERBOOKS_AUDIO_FORMAT"] = "mp3"
    os.environ["EUTHERBOOKS_MP3_BITRATE_KBPS"] = str(max(48, min(192, args.bitrate_kbps)))
    os.environ["EUTHERBOOKS_KEEP_SOURCE_WAV"] = "1"
    converted = 0
    output_bytes = 0
    for candidate in candidates:
        _finalize_generated_audio(candidate.source_path)
        if update_job_path(db_path, candidate):
            converted += 1
            output_bytes += candidate.target_path.stat().st_size
            candidate.source_path.touch()
            print(f"converted {candidate.relative_path} -> {candidate.target_path.name}")
    removed, reclaimed = cleanup_unreferenced_wavs(
        db_path,
        audio_dir,
        max(0.0, args.delete_source_after_days) * 24 * 3600,
    )
    print(
        f"converted: {converted}, MP3 output: {format_bytes(output_bytes)}, "
        f"expired WAV removed: {removed}, reclaimed: {format_bytes(reclaimed)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
