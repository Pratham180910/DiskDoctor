from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .scanner import FileRecord, ScanResult


@dataclass(slots=True)
class StoredScan:
    scan_id: int
    started_at: str
    target: str
    mode: str
    duration: float
    files: int
    folders: int
    bytes_total: int
    errors: int
    complete_coverage: bool
    records: list[FileRecord]


@dataclass(slots=True)
class ScanComparison:
    before: StoredScan
    after: StoredScan
    compatible: bool
    warning: str = ""
    added: list[FileRecord] | None = None
    removed: list[FileRecord] | None = None
    changed: list[tuple[FileRecord, FileRecord]] | None = None
    folder_growth: list[tuple[str, int]] | None = None


def _record_from_dict(item: dict) -> FileRecord:
    return FileRecord(str(item["path"]), str(item["name"]), int(item["size"]), str(item["extension"]), float(item["modified"]))


class HistoryStore:
    def __init__(self, path: str | Path = "diskdoctor_history.sqlite3") -> None:
        self.path = str(path)
        with sqlite3.connect(self.path) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, target TEXT NOT NULL,
                mode TEXT NOT NULL, duration REAL NOT NULL, files INTEGER NOT NULL,
                folders INTEGER NOT NULL, bytes INTEGER NOT NULL, errors INTEGER NOT NULL,
                complete_coverage INTEGER NOT NULL DEFAULT 1, metadata TEXT NOT NULL
            )""")
            # Upgrade databases created by the first native prototype.
            columns = {row[1] for row in connection.execute("PRAGMA table_info(scans)")}
            if "complete_coverage" not in columns:
                connection.execute("ALTER TABLE scans ADD COLUMN complete_coverage INTEGER NOT NULL DEFAULT 1")
            connection.commit()

    def save(self, result: ScanResult) -> int:
        metadata = json.dumps([{"path": r.path, "name": r.name, "size": r.size, "extension": r.extension, "modified": r.modified} for r in result.files], ensure_ascii=False)
        complete = int(not result.cancelled and not result.errors and result.mode == "Full Scan")
        with sqlite3.connect(self.path) as connection:
            cursor = connection.execute("INSERT INTO scans (started_at,target,mode,duration,files,folders,bytes,errors,complete_coverage,metadata) VALUES (?,?,?,?,?,?,?,?,?,?)", (result.started_at, result.target, result.mode, result.duration, len(result.files), result.folders, result.bytes_total, len(result.errors), complete, metadata))
            connection.commit()
            return int(cursor.lastrowid)

    def recent(self, limit: int = 20) -> list[tuple]:
        with sqlite3.connect(self.path) as connection:
            return connection.execute("SELECT id,started_at,target,mode,duration,files,folders,bytes,errors,complete_coverage FROM scans ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def get(self, scan_id: int) -> StoredScan:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT id,started_at,target,mode,duration,files,folders,bytes,errors,complete_coverage,metadata FROM scans WHERE id=?", (scan_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown scan id: {scan_id}")
        records = [_record_from_dict(item) for item in json.loads(row[10] or "[]")]
        return StoredScan(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], bool(row[9]), records)

    def compare(self, before_id: int, after_id: int) -> ScanComparison:
        before, after = self.get(before_id), self.get(after_id)
        before_root, after_root = str(Path(before.target).resolve()), str(Path(after.target).resolve())
        warnings = []
        if before_root != after_root: warnings.append("The scans use different roots and are not directly comparable.")
        if not before.complete_coverage or not after.complete_coverage: warnings.append("One or both scans are incomplete; added/removed results are lower bounds.")
        old = {record.path: record for record in before.records}; new = {record.path: record for record in after.records}
        added = [new[path] for path in sorted(new.keys() - old.keys())]
        removed = [old[path] for path in sorted(old.keys() - new.keys())]
        changed = [(old[path], new[path]) for path in sorted(old.keys() & new.keys()) if old[path].size != new[path].size]
        growth: dict[str, int] = {}
        for old_record, new_record in changed:
            parent = str(Path(new_record.path).parent)
            growth[parent] = growth.get(parent, 0) + (new_record.size - old_record.size)
        for record in added:
            parent = str(Path(record.path).parent); growth[parent] = growth.get(parent, 0) + record.size
        folder_growth = sorted(((folder, amount) for folder, amount in growth.items() if amount > 0), key=lambda pair: pair[1], reverse=True)
        return ScanComparison(before, after, not warnings, "; ".join(warnings), added, removed, changed, folder_growth)
