from __future__ import annotations

import hashlib
import os
import threading
from collections import defaultdict
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from .scanner import FileRecord


@dataclass(slots=True)
class HashProgress:
    completed: int
    total: int
    path: str


class HashCancelled(Exception):
    pass


def sha256_file(path: str, cancel_event: threading.Event | None = None, chunk_size: int = 1024 * 1024) -> str:
    before = os.stat(path)
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            if cancel_event and cancel_event.is_set():
                raise HashCancelled()
            digest.update(chunk)
    after = os.stat(path)
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise OSError("file changed while hashing")
    return digest.hexdigest()


def _partial_sha256(path: str, cancel_event: threading.Event | None = None, sample_size: int = 64 * 1024) -> str:
    """Hash the beginning and end of a file to reject obvious non-matches cheaply."""
    before = os.stat(path)
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        digest.update(handle.read(sample_size))
        if before.st_size > sample_size:
            handle.seek(max(0, before.st_size - sample_size))
            digest.update(handle.read(sample_size))
    if cancel_event and cancel_event.is_set(): raise HashCancelled()
    after = os.stat(path)
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise OSError("file changed while hashing")
    return digest.hexdigest()


def exact_duplicate_groups(
    files: list[FileRecord], minimum_size: int = 1,
    cancel_event: threading.Event | None = None,
    progress: Callable[[HashProgress], None] | None = None,
) -> list[list[FileRecord]]:
    candidates: dict[int, list[FileRecord]] = defaultdict(list)
    for record in files:
        if record.size >= minimum_size:
            candidates[record.size].append(record)
    hash_candidates = [record for group in candidates.values() if len(group) > 1 for record in group]
    if not hash_candidates: return []
    workers = min(8, max(2, os.cpu_count() or 4)); completed = 0
    partial_groups: dict[tuple[int, str], list[FileRecord]] = defaultdict(list)

    def partial_job(record: FileRecord):
        return record, _partial_sha256(record.path, cancel_event)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dd-partial") as pool:
        futures = [pool.submit(partial_job, record) for record in hash_candidates]
        for future in as_completed(futures):
            if cancel_event and cancel_event.is_set(): raise HashCancelled()
            try:
                record, digest = future.result(); partial_groups[(record.size, digest)].append(record)
            except (OSError, ValueError, HashCancelled):
                if cancel_event and cancel_event.is_set(): raise HashCancelled()
            finally:
                completed += 1
                if progress: progress(HashProgress(completed, len(hash_candidates), "partial content"))

    full_candidates = [record for group in partial_groups.values() if len(group) > 1 for record in group]
    if not full_candidates: return []
    full_groups: dict[str, list[FileRecord]] = defaultdict(list)

    def full_job(record: FileRecord):
        return record, sha256_file(record.path, cancel_event)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dd-sha256") as pool:
        futures = [pool.submit(full_job, record) for record in full_candidates]
        for future in as_completed(futures):
            if cancel_event and cancel_event.is_set(): raise HashCancelled()
            try:
                record, digest = future.result(); full_groups[digest].append(record)
            except (OSError, ValueError, HashCancelled):
                if cancel_event and cancel_event.is_set(): raise HashCancelled()
            finally:
                completed += 1
                if progress: progress(HashProgress(completed, len(hash_candidates) + len(full_candidates), "full SHA-256"))
    return [group for group in full_groups.values() if len(group) > 1]


def reclaimable_bytes(group: list[FileRecord]) -> int:
    """Keep one copy and report only the bytes represented by removable copies."""
    return max(0, (len(group) - 1) * group[0].size) if group else 0
