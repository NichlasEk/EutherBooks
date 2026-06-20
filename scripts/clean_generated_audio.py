#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ACTIVE_STATUSES = {"queued", "running"}
GIB = 1024**3


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    data: dict[str, Any]
    job_dir: Path
    modified_at: float
    size_bytes: int

    @property
    def status(self) -> str:
        return str(self.data.get("status") or "")

    @property
    def audio_files(self) -> list[str]:
        audio_files = self.data.get("audio_files")
        return [str(value) for value in audio_files] if isinstance(audio_files, list) else []

    @property
    def retention_key(self) -> tuple[str, str, tuple[int, ...]]:
        chapters = self.data.get("chapter_indexes")
        clean_chapters = tuple(int(value) for value in chapters) if isinstance(chapters, list) else ()
        return (
            str(self.data.get("owner") or ""),
            str(self.data.get("book_id") or ""),
            clean_chapters,
        )


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def directory_mtime(path: Path) -> float:
    if not path.exists():
        return 0.0
    newest = path.stat().st_mtime
    for child in path.rglob("*"):
        try:
            newest = max(newest, child.stat().st_mtime)
        except FileNotFoundError:
            continue
    return newest


def load_jobs(jobs_path: Path, audio_dir: Path) -> dict[str, JobRecord]:
    if not jobs_path.exists():
        return {}
    raw = json.loads(jobs_path.read_text(encoding="utf-8"))
    records: dict[str, JobRecord] = {}
    for job_id, data in raw.items():
        if not isinstance(data, dict):
            continue
        book_id = str(data.get("book_id") or "")
        job_dir = audio_dir / book_id / str(job_id)
        records[str(job_id)] = JobRecord(
            job_id=str(job_id),
            data=data,
            job_dir=job_dir,
            modified_at=directory_mtime(job_dir),
            size_bytes=directory_size(job_dir),
        )
    return records


def select_jobs_to_keep(records: dict[str, JobRecord], keep_per_chapter: int, failed_keep: int, min_age_seconds: float) -> set[str]:
    now = time.time()
    keep: set[str] = set()
    grouped_done: dict[tuple[str, str, tuple[int, ...]], list[JobRecord]] = defaultdict(list)
    grouped_failed: dict[tuple[str, str, tuple[int, ...]], list[JobRecord]] = defaultdict(list)

    for record in records.values():
        if record.status in ACTIVE_STATUSES:
            keep.add(record.job_id)
            continue
        if min_age_seconds > 0 and record.modified_at and now - record.modified_at < min_age_seconds:
            keep.add(record.job_id)
            continue
        if record.status == "done" and record.audio_files:
            grouped_done[record.retention_key].append(record)
        elif record.status == "failed":
            grouped_failed[record.retention_key].append(record)

    for group in grouped_done.values():
        keep.update(record.job_id for record in sorted(group, key=lambda item: item.modified_at, reverse=True)[:keep_per_chapter])
    for group in grouped_failed.values():
        keep.update(record.job_id for record in sorted(group, key=lambda item: item.modified_at, reverse=True)[:failed_keep])

    return keep


def select_floor_jobs(records: dict[str, JobRecord], floor_keep_per_chapter: int, min_age_seconds: float) -> set[str]:
    now = time.time()
    keep: set[str] = set()
    grouped_done: dict[tuple[str, str, tuple[int, ...]], list[JobRecord]] = defaultdict(list)

    for record in records.values():
        if record.status in ACTIVE_STATUSES:
            keep.add(record.job_id)
            continue
        if min_age_seconds > 0 and record.modified_at and now - record.modified_at < min_age_seconds:
            keep.add(record.job_id)
            continue
        if record.status == "done" and record.audio_files:
            grouped_done[record.retention_key].append(record)

    for group in grouped_done.values():
        keep.update(record.job_id for record in sorted(group, key=lambda item: item.modified_at, reverse=True)[:floor_keep_per_chapter])

    return keep


def apply_audio_budget(
    records: dict[str, JobRecord],
    keep_job_ids: set[str],
    max_audio_bytes: int,
    floor_keep_per_chapter: int,
    min_age_seconds: float,
) -> tuple[set[str], int, int]:
    if max_audio_bytes <= 0:
        return keep_job_ids, sum(record.size_bytes for record in records.values()), 0

    total_bytes = sum(record.size_bytes for record in records.values())
    if total_bytes <= max_audio_bytes:
        return keep_job_ids, total_bytes, 0

    floor_job_ids = select_floor_jobs(records, floor_keep_per_chapter, min_age_seconds)
    next_keep = set(keep_job_ids)
    reclaimed = 0
    candidates = [
        record
        for record in records.values()
        if record.job_id in next_keep
        and record.job_id not in floor_job_ids
        and record.status == "done"
        and record.audio_files
        and record.size_bytes > 0
    ]
    candidates.sort(key=lambda item: (item.modified_at, -item.size_bytes))

    for record in candidates:
        if total_bytes - reclaimed <= max_audio_bytes:
            break
        next_keep.discard(record.job_id)
        reclaimed += record.size_bytes

    return next_keep, total_bytes, reclaimed


def audio_job_dirs(audio_dir: Path) -> set[Path]:
    if not audio_dir.exists():
        return set()
    return {path for path in audio_dir.glob("*/*") if path.is_dir()}


def remove_empty_parents(audio_dir: Path) -> None:
    if not audio_dir.exists():
        return
    for book_dir in audio_dir.iterdir():
        if book_dir.is_dir():
            try:
                book_dir.rmdir()
            except OSError:
                pass


def format_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def old_enough(path: Path, min_age_seconds: float) -> bool:
    if min_age_seconds <= 0:
        return True
    try:
        return time.time() - path.stat().st_mtime >= min_age_seconds
    except FileNotFoundError:
        return False


def select_old_job_backups(data_dir: Path, keep_backups: int, max_age_seconds: float) -> list[Path]:
    backups = sorted(data_dir.glob("jobs.json.backup.*"), key=lambda item: item.stat().st_mtime, reverse=True)
    keep = max(0, keep_backups)
    return [path for path in backups[keep:] if old_enough(path, max_age_seconds)]


def select_python_cache_dirs(root: Path) -> list[Path]:
    cache_names = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_dir() and path.name in cache_names and ".venv" not in path.parts and ".git" not in path.parts
    )


def select_old_ocr_cache_dirs(library_dir: Path, max_age_seconds: float) -> list[Path]:
    cache_root = library_dir / ".eutherbooks-cache"
    if not cache_root.exists():
        return []
    return sorted(path for path in cache_root.glob("*.ocr") if path.is_dir() and old_enough(path, max_age_seconds))


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean old EutherBooks generated audio and stale job records.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--audio-dir", type=Path, default=None)
    parser.add_argument("--keep-per-chapter", type=int, default=2)
    parser.add_argument("--floor-keep-per-chapter", type=int, default=1)
    parser.add_argument("--failed-keep", type=int, default=0)
    parser.add_argument("--min-age-hours", type=float, default=2.0)
    parser.add_argument("--max-audio-gib", type=float, default=0.0, help="Optional generated-audio disk budget. 0 disables budget cleanup.")
    parser.add_argument("--backup-keep", type=int, default=3, help="Always keep this many newest jobs.json backups.")
    parser.add_argument("--backup-max-age-days", type=float, default=14.0)
    parser.add_argument("--library-dir", type=Path, default=Path("library"))
    parser.add_argument("--ocr-cache-max-age-days", type=float, default=0.0, help="Delete OCR cache dirs older than this. 0 disables OCR cache cleanup.")
    parser.add_argument("--clean-python-cache", action="store_true", help="Remove __pycache__ and test/tool cache dirs outside .venv and .git.")
    parser.add_argument("--apply", action="store_true", help="Delete files and rewrite jobs.json. Without this, only reports.")
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    audio_dir = (args.audio_dir or data_dir / "audio").resolve()
    jobs_path = data_dir / "jobs.json"
    keep_per_chapter = max(0, args.keep_per_chapter)
    floor_keep_per_chapter = max(1, args.floor_keep_per_chapter)
    failed_keep = max(0, args.failed_keep)
    min_age_seconds = max(0.0, args.min_age_hours) * 3600
    max_audio_bytes = int(max(0.0, args.max_audio_gib) * GIB)
    backup_max_age_seconds = max(0.0, args.backup_max_age_days) * 24 * 3600
    ocr_cache_max_age_seconds = max(0.0, args.ocr_cache_max_age_days) * 24 * 3600
    repo_root = Path.cwd().resolve()
    library_dir = args.library_dir.resolve()

    records = load_jobs(jobs_path, audio_dir)
    keep_job_ids = select_jobs_to_keep(records, keep_per_chapter, failed_keep, min_age_seconds)
    keep_job_ids, total_audio_bytes, budget_reclaim_bytes = apply_audio_budget(
        records,
        keep_job_ids,
        max_audio_bytes,
        floor_keep_per_chapter,
        min_age_seconds,
    )
    delete_job_ids = {job_id for job_id in records if job_id not in keep_job_ids}
    referenced_dirs = {record.job_dir for record in records.values()}
    orphan_dirs = audio_job_dirs(audio_dir) - referenced_dirs
    delete_dirs = {records[job_id].job_dir for job_id in delete_job_ids if records[job_id].job_dir.exists()} | orphan_dirs
    audio_reclaim_bytes = sum(directory_size(path) for path in delete_dirs)
    backup_files = select_old_job_backups(data_dir, args.backup_keep, backup_max_age_seconds)
    python_cache_dirs = select_python_cache_dirs(repo_root) if args.clean_python_cache else []
    ocr_cache_dirs = select_old_ocr_cache_dirs(library_dir, ocr_cache_max_age_seconds) if ocr_cache_max_age_seconds else []
    cleanup_dirs = set(delete_dirs) | set(python_cache_dirs) | set(ocr_cache_dirs)
    reclaim_bytes = sum(directory_size(path) for path in cleanup_dirs) + sum(path.stat().st_size for path in backup_files if path.exists())

    print(f"jobs: {len(records)} total, {len(keep_job_ids)} kept, {len(delete_job_ids)} removed")
    if max_audio_bytes:
        after_cleanup = max(0, total_audio_bytes - audio_reclaim_bytes)
        budget_note = "" if after_cleanup <= max_audio_bytes else f", still {format_bytes(after_cleanup - max_audio_bytes)} over target"
        print(f"audio budget: {format_bytes(total_audio_bytes)} total, target {format_bytes(max_audio_bytes)}, after cleanup {format_bytes(after_cleanup)}{budget_note}")
    print(f"audio dirs: {len(delete_dirs)} removed, reclaim {format_bytes(audio_reclaim_bytes)}")
    print(f"backup files: {len(backup_files)} removed, reclaim {format_bytes(sum(path.stat().st_size for path in backup_files if path.exists()))}")
    print(f"python cache dirs: {len(python_cache_dirs)} removed, reclaim {format_bytes(sum(directory_size(path) for path in python_cache_dirs))}")
    print(f"ocr cache dirs: {len(ocr_cache_dirs)} removed, reclaim {format_bytes(sum(directory_size(path) for path in ocr_cache_dirs))}")
    print(f"total reclaim: {format_bytes(reclaim_bytes)}")
    for record in sorted((records[job_id] for job_id in delete_job_ids), key=lambda item: (item.data.get("book_id", ""), item.modified_at)):
        print(
            "remove job",
            record.job_id,
            f"status={record.status}",
            f"owner={record.data.get('owner') or '<empty>'}",
            f"book={record.data.get('book_id')}",
            f"chapters={record.data.get('chapter_indexes')}",
            f"audio={format_bytes(record.size_bytes)}",
        )
    for path in sorted(orphan_dirs):
        print("remove orphan", path, format_bytes(directory_size(path)))
    for path in backup_files:
        print("remove backup", path, format_bytes(path.stat().st_size if path.exists() else 0))
    for path in python_cache_dirs:
        print("remove python-cache", path, format_bytes(directory_size(path)))
    for path in ocr_cache_dirs:
        print("remove ocr-cache", path, format_bytes(directory_size(path)))

    if not args.apply:
        print("dry run only; pass --apply to delete")
        return 0

    for path in sorted(cleanup_dirs, key=lambda item: len(item.parts), reverse=True):
        shutil.rmtree(path, ignore_errors=True)
    for path in backup_files:
        path.unlink(missing_ok=True)
    if jobs_path.exists():
        kept_payload = {job_id: records[job_id].data for job_id in records if job_id in keep_job_ids}
        jobs_path.write_text(json.dumps(kept_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    remove_empty_parents(audio_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
