from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .scanner import FileRecord


def safe_cleanup_path(path: str, allowed_roots: list[str]) -> bool:
    raw = Path(path)
    if raw.is_symlink(): return False
    candidate = raw.resolve()
    if candidate.is_dir() or not candidate.exists(): return False
    roots = [Path(root).resolve() for root in allowed_roots]
    try:
        if not any(os.path.commonpath([str(candidate), str(root)]) == str(root) for root in roots): return False
    except ValueError: return False
    return not any(part.lower() in {"windows", "program files", "program files (x86)"} for part in candidate.parts)


@dataclass(slots=True)
class DeleteResult:
    path: str
    status: str
    message: str
    bytes_removed: int = 0


def discover_cleanup_candidates(max_items: int = 500) -> list[FileRecord]:
    """Discover only user-temp files; never infer cleanup from arbitrary folder names."""
    root = Path(tempfile.gettempdir())
    if not root.exists(): return []
    found: list[FileRecord] = []; stack = [root]
    while stack and len(found) < max_items:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_symlink(): continue
                    try:
                        if entry.is_dir(follow_symlinks=False): stack.append(Path(entry.path)); continue
                        if not entry.is_file(follow_symlinks=False): continue
                        stat = entry.stat(follow_symlinks=False); suffix = Path(entry.name).suffix.lower().lstrip(".") or "[none]"
                        found.append(FileRecord(entry.path, entry.name, stat.st_size, suffix, stat.st_mtime))
                        if len(found) >= max_items: break
                    except (OSError, ValueError): continue
        except (OSError, ValueError): continue
    return sorted(found, key=lambda item: item.size, reverse=True)


def delete_selected(records: list[FileRecord], allowed_roots: list[str], confirm: bool = False) -> list[DeleteResult]:
    """Delete only explicitly selected, revalidated files after a separate confirmation."""
    if not confirm:
        raise PermissionError("Explicit confirmation is required before deletion")
    results = []
    for record in records:
        path = Path(record.path)
        try:
            if not safe_cleanup_path(str(path), allowed_roots):
                results.append(DeleteResult(str(path), "skipped", "Path is outside the permitted cleanup roots or is protected.")); continue
            stat = path.stat()
            if stat.st_size != record.size or stat.st_mtime != record.modified:
                results.append(DeleteResult(str(path), "skipped", "File changed since it was scanned.")); continue
            path.unlink()
            results.append(DeleteResult(str(path), "success", "Deleted.", record.size))
        except FileNotFoundError:
            results.append(DeleteResult(str(path), "skipped", "File no longer exists."))
        except (PermissionError, OSError) as exc:
            results.append(DeleteResult(str(path), "failed", str(exc)))
    return results
