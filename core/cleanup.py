
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .scanner import FileRecord

try:
    from send2trash import send2trash
except ImportError:
    send2trash = None


PROTECTED_DIR_NAMES = {
    "windows",
    "program files",
    "program files (x86)",
    "system volume information",
    "$recycle.bin",
    "recovery",
}


def _is_path_relative_to(candidate: Path, root: Path) -> bool:
    """Check if candidate is within root, handling cross-drive paths on Windows gracefully."""
    try:
        resolved_cand = candidate.resolve()
        resolved_root = root.resolve()
        if resolved_cand == resolved_root:
            return False
        return resolved_cand.is_relative_to(resolved_root)
    except (ValueError, AttributeError):
        try:
            cand_str = str(candidate.resolve())
            root_str = str(root.resolve())
            if cand_str == root_str:
                return False
            return os.path.commonpath([cand_str, root_str]) == root_str
        except (ValueError, OSError):
            return False


def safe_cleanup_path(path: str, allowed_roots: list[str] | None = None) -> bool:
    raw = Path(path)
    if raw.is_symlink():
        return False
    try:
        candidate = raw.resolve()
    except (OSError, RuntimeError):
        return False

    if candidate.is_dir() or not candidate.exists():
        return False

    # Block protected operating system and program directories
    if any(part.lower() in PROTECTED_DIR_NAMES for part in candidate.parts):
        return False

    # Determine allowed roots (defaulting to system tempdir if none provided)
    roots_to_check = list(allowed_roots) if allowed_roots is not None else [tempfile.gettempdir()]
    if not roots_to_check:
        return False

    roots = [Path(root).resolve() for root in roots_to_check]
    # File must be contained within at least one valid root
    return any(_is_path_relative_to(candidate, root) for root in roots)


@dataclass(slots=True)
class DeleteResult:
    path: str
    status: str
    message: str
    bytes_removed: int = 0


def discover_cleanup_candidates(max_items: int = 500) -> list[FileRecord]:
    """Discover only user-temp files; never infer cleanup from arbitrary folder names."""
    root = Path(tempfile.gettempdir())
    if not root.exists():
        return []
    found: list[FileRecord] = []
    stack = [root]
    while stack and len(found) < max_items:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        stat = entry.stat(follow_symlinks=False)
                        suffix = Path(entry.name).suffix.lower().lstrip(".") or "[none]"
                        found.append(FileRecord(entry.path, entry.name, stat.st_size, suffix, stat.st_mtime))
                        if len(found) >= max_items:
                            break
                    except (OSError, ValueError):
                        continue
        except (OSError, ValueError):
            continue
    return sorted(found, key=lambda item: item.size, reverse=True)


def delete_selected(
    records: list[FileRecord],
    allowed_roots: list[str] | None = None,
    confirm: bool = False,
) -> list[DeleteResult]:
    """Send explicitly selected, revalidated files to the Recycle Bin after confirmation.

    NEVER falls back to permanent deletion (os.unlink or Path.unlink) if Recycle Bin operations fail.
    If send2trash fails or is unavailable, reports the failure and leaves the file untouched.
    """
    if not confirm:
        raise PermissionError("Explicit confirmation is required before deletion")

    effective_roots = list(allowed_roots) if allowed_roots is not None else [tempfile.gettempdir()]
    results: list[DeleteResult] = []

    for record in records:
        path = Path(record.path)
        try:
            if not safe_cleanup_path(str(path), effective_roots):
                results.append(
                    DeleteResult(
                        str(path),
                        "skipped",
                        "Path is outside the permitted cleanup roots or is protected.",
                    )
                )
                continue

            stat = path.stat()
            if stat.st_size != record.size or stat.st_mtime != record.modified:
                results.append(
                    DeleteResult(str(path), "skipped", "File changed since it was scanned.")
                )
                continue

            # Ensure send2trash is available
            if send2trash is None:
                results.append(
                    DeleteResult(
                        str(path),
                        "failed",
                        "Recycle Bin integration (send2trash) is not available. File untouched.",
                    )
                )
                continue

            # Move to Recycle Bin (NEVER fall back to unlink)
            send2trash(str(path))
            results.append(
                DeleteResult(str(path), "success", "Sent to Recycle Bin.", record.size)
            )
        except FileNotFoundError:
            results.append(DeleteResult(str(path), "skipped", "File no longer exists."))
        except (PermissionError, OSError) as exc:
            # Leave file untouched and report failure
            results.append(
                DeleteResult(str(path), "failed", f"Recycle Bin error: {exc}. File untouched.")
            )
        except Exception as exc:
            results.append(
                DeleteResult(str(path), "failed", f"Recycle Bin error: {exc}. File untouched.")
            )

    return results
