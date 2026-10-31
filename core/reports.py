from __future__ import annotations

import csv
from pathlib import Path

from .history import ScanComparison
from .scanner import FileRecord


def export_files(records: list[FileRecord], destination: str) -> None:
    with Path(destination).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Name", "Path", "Size (bytes)", "Extension", "Modified"])
        for record in records: writer.writerow([record.name, record.path, record.size, record.extension, record.modified])
        writer.writerow([]); writer.writerow(["TOTAL", "", sum(record.size for record in records), "", ""])


def export_comparison(comparison: ScanComparison, destination: str) -> None:
    with Path(destination).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle); writer.writerow(["Change", "Path", "Before bytes", "After bytes", "Note"])
        for record in comparison.added or []: writer.writerow(["Added", record.path, "", record.size, ""])
        for record in comparison.removed or []: writer.writerow(["Removed", record.path, record.size, "", "Lower bound if coverage incomplete"])
        for old, new in comparison.changed or []: writer.writerow(["Changed", new.path, old.size, new.size, new.size - old.size])
        writer.writerow([]); writer.writerow(["WARNING", comparison.warning])
