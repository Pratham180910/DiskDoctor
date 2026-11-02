from __future__ import annotations

import os
import shutil
import stat as stat_module
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue


@dataclass(slots=True)
class FileRecord:
    path: str
    name: str
    size: int
    extension: str
    modified: float


@dataclass(slots=True)
class ScanResult:
    target: str
    mode: str
    started_at: str
    duration: float
    files: list[FileRecord] = field(default_factory=list)
    folders: int = 0
    errors: list[str] = field(default_factory=list)
    bytes_total: int = 0
    cancelled: bool = False
    limit_reached: bool = False

    @property
    def is_partial(self) -> bool:
        return self.mode == "Quick Scan" or self.limit_reached or self.cancelled

    @property
    def coverage_badge(self) -> str:
        if self.cancelled:
            return "CANCELLED"
        if self.mode == "Quick Scan":
            return "PARTIAL SCAN"
        return "FULL SCAN"

    @property
    def coverage_description(self) -> str:
        if self.cancelled:
            return "Scan was cancelled before traversal finished. Results represent an incomplete sample."
        if self.mode == "Quick Scan":
            return "Quick Scan is a bounded triage mode capped at 100,000 files. Category breakdown and file totals represent only this indexed sample, not full volume capacity."
        return f"Comprehensive Full Scan completed across {self.folders:,} folders. All accessible directories were traversed without file caps."

    @property
    def largest_files(self) -> list[FileRecord]:
        return sorted(self.files, key=lambda item: item.size, reverse=True)

    @property
    def type_summary(self) -> list[tuple[str, int, int]]:
        summary: dict[str, list[int]] = {}
        for item in self.files:
            row = summary.setdefault(item.extension or "[none]", [0, 0])
            row[0] += item.size
            row[1] += 1
        return [(key, value[0], value[1]) for key, value in sorted(summary.items(), key=lambda pair: pair[1][0], reverse=True)]


@dataclass(slots=True)
class ScanEvent:
    kind: str
    files: int = 0
    folders: int = 0
    bytes_total: int = 0
    message: str = ""
    result: ScanResult | None = None


def available_drives() -> list[str]:
    drives = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{letter}:\\")
        if root.exists():
            drives.append(str(root))
    return drives or [str(Path.cwd().anchor or Path.cwd())]


class Scanner:
    def __init__(self) -> None:
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def scan_async(self, target: str, mode: str, events: Queue[ScanEvent]) -> threading.Thread:
        self.cancel_event.clear()
        thread = threading.Thread(target=self._scan, args=(target, mode, events), daemon=True)
        thread.start()
        return thread

    def _scan(self, target: str, mode: str, events: Queue[ScanEvent]) -> None:
        started = time.perf_counter()
        started_at = datetime.now().isoformat(timespec="seconds")
        result = ScanResult(target=target, mode=mode, started_at=started_at, duration=0)
        if mode in {"Quick Scan", "Full Scan"}:
            self._scan_parallel(target, result, events, started, limit=100_000 if mode == "Quick Scan" else None)
            return
        stack = [Path(target)]
        last_emit = 0.0
        while stack and not self.cancel_event.is_set():
            current = stack.pop()
            try:
                with os.scandir(current) as entries:
                    result.folders += 1
                    for entry in entries:
                        if self.cancel_event.is_set():
                            break
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                            stat = entry.stat(follow_symlinks=False)
                            suffix = Path(entry.name).suffix.lower().lstrip(".") or "[none]"
                            result.files.append(FileRecord(entry.path, entry.name, stat.st_size, suffix, stat.st_mtime))
                            result.bytes_total += stat.st_size
                        except (OSError, ValueError) as exc:
                            result.errors.append(f"{entry.path}: {exc}")
            except (OSError, ValueError) as exc:
                result.errors.append(f"{current}: {exc}")
            now = time.monotonic()
            if now - last_emit >= 0.15:
                events.put(ScanEvent("progress", len(result.files), result.folders, result.bytes_total))
                last_emit = now
            # Quick Scan is intentionally bounded for fast triage; Full Scan has no file cap.
            if mode == "Quick Scan" and len(result.files) >= 100_000:
                result.limit_reached = True
                break
        result.cancelled = self.cancel_event.is_set()
        result.duration = time.perf_counter() - started
        events.put(ScanEvent("complete", len(result.files), result.folders, result.bytes_total, result=result))

    def _scan_parallel(self, target: str, result: ScanResult, events: Queue[ScanEvent], started: float, limit: int | None) -> None:
        """Parallel traversal using bounded workers and one stat call per entry."""
        directories: Queue[Path] = Queue()
        directories.put(Path(target))
        lock = threading.Lock()
        active = 1
        limit_reached = False
        worker_count = min(8, max(2, (os.cpu_count() or 4)))

        def worker() -> None:
            nonlocal active, limit_reached
            while not self.cancel_event.is_set():
                try:
                    current = directories.get(timeout=0.05)
                except Empty:
                    with lock:
                        if active == 0:
                            return
                    continue
                try:
                    with os.scandir(current) as entries:
                        with lock: result.folders += 1
                        for entry in entries:
                            if self.cancel_event.is_set() or limit_reached: break
                            try:
                                metadata = entry.stat(follow_symlinks=False)
                                if stat_module.S_ISDIR(metadata.st_mode):
                                    with lock: active += 1
                                    directories.put(Path(entry.path))
                                elif stat_module.S_ISREG(metadata.st_mode):
                                    suffix = Path(entry.name).suffix.lower().lstrip(".") or "[none]"
                                    record = FileRecord(entry.path, entry.name, metadata.st_size, suffix, metadata.st_mtime)
                                    with lock:
                                        if limit is not None and len(result.files) >= limit:
                                            limit_reached = True
                                            break
                                        result.files.append(record); result.bytes_total += metadata.st_size
                            except (OSError, ValueError) as exc:
                                with lock: result.errors.append(f"{entry.path}: {exc}")
                except (OSError, ValueError) as exc:
                    with lock: result.errors.append(f"{current}: {exc}")
                finally:
                    directories.task_done()
                    with lock: active -= 1

        workers = [threading.Thread(target=worker, daemon=True) for _ in range(worker_count)]
        for thread in workers: thread.start()
        last_emit = 0.0
        while True:
            with lock: remaining = active; file_count = len(result.files); folder_count = result.folders; total = result.bytes_total
            now = time.monotonic()
            if now - last_emit >= 0.15:
                events.put(ScanEvent("progress", file_count, folder_count, total)); last_emit = now
            if remaining == 0 or self.cancel_event.is_set() or limit_reached: break
            time.sleep(0.02)
        if limit_reached:
            result.limit_reached = True
            while not directories.empty():
                try: directories.get_nowait(); directories.task_done()
                except Empty: break
        for thread in workers: thread.join(timeout=1)
        result.cancelled = self.cancel_event.is_set()
        result.duration = time.perf_counter() - started
        events.put(ScanEvent("complete", len(result.files), result.folders, result.bytes_total, result=result))


def disk_usage(target: str) -> tuple[int, int, int]:
    try:
        usage = shutil.disk_usage(target)
        return usage.total, usage.used, usage.free
    except OSError:
        return 0, 0, 0
