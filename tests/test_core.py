from __future__ import annotations

import csv
import threading
from pathlib import Path
from queue import Queue

from core.cleanup import delete_selected, safe_cleanup_path
from core.duplicate_finder import exact_duplicate_groups, reclaimable_bytes, sha256_file
from core.history import HistoryStore
from core.reports import export_comparison, export_files
from core.scanner import Scanner
from core.treemap import layout


def scan(path: Path):
    queue = Queue()
    Scanner().scan_async(str(path), "Full Scan", queue).join(timeout=5)
    event = queue.get_nowait()
    while event.kind != "complete": event = queue.get_nowait()
    return event.result


def test_scan_and_aggregation(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.bin").write_bytes(b"123456789")
    result = scan(tmp_path)
    assert len(result.files) == 2
    assert result.folders == 2
    assert result.bytes_total == 14
    assert result.type_summary[0][0] in {"bin", "txt"}


def test_scanner_skips_symlinks_and_can_cancel(tmp_path):
    (tmp_path / "real.txt").write_text("real")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(tmp_path / "real.txt")
    except (OSError, NotImplementedError):
        link = None
    result = scan(tmp_path)
    assert len(result.files) == 1 if link else len(result.files) >= 1
    for index in range(1200): (tmp_path / f"bulk-{index}.txt").write_text("x")
    scanner = Scanner(); queue = Queue(); thread = scanner.scan_async(str(tmp_path), "Full Scan", queue); scanner.cancel(); thread.join(timeout=5)
    events = [queue.get() for _ in range(queue.qsize())]; result = [event.result for event in events if event.kind == "complete"][0]
    assert result.cancelled is True


def test_duplicate_hashing(tmp_path):
    first = tmp_path / "one.bin"; second = tmp_path / "two.bin"; other = tmp_path / "other.bin"
    first.write_bytes(b"same"); second.write_bytes(b"same"); other.write_bytes(b"diff")
    result = scan(tmp_path)
    groups = exact_duplicate_groups(result.files)
    assert len(groups) == 1
    assert {record.name for record in groups[0]} == {"one.bin", "two.bin"}
    assert reclaimable_bytes(groups[0]) == 4
    assert sha256_file(str(first)) == sha256_file(str(second))


def test_same_size_different_content_is_not_duplicate(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"1234")
    (tmp_path / "b.bin").write_bytes(b"5678")
    result = scan(tmp_path)
    assert exact_duplicate_groups(result.files) == []


def test_treemap_area_and_history(tmp_path):
    rectangles = layout([("a", 25), ("b", 75)], 100, 100)
    assert round(sum(rect.width * rect.height for rect in rectangles), 5) == 10000
    result = scan(tmp_path)
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.save(result)
    assert len(store.recent()) == 1


def test_cleanup_guard(tmp_path):
    candidate = tmp_path / "temp.log"; candidate.write_text("safe")
    assert safe_cleanup_path(str(candidate), [str(tmp_path)])
    assert not safe_cleanup_path(str(tmp_path), [str(tmp_path)])
    result = scan(tmp_path)
    deleted = delete_selected([next(item for item in result.files if item.name == "temp.log")], [str(tmp_path)], confirm=True)
    assert deleted[0].status == "success"
    assert not candidate.exists()


def test_scan_comparison_and_unicode_csv(tmp_path):
    scan_root = tmp_path / "scan"; scan_root.mkdir()
    unicode_file = scan_root / "café.csv"
    unicode_file.write_text("old")
    first = scan(scan_root)
    store = HistoryStore(tmp_path / "history.sqlite3"); before_id = store.save(first)
    unicode_file.write_text("new content")
    (scan_root / "新.txt").write_text("added")
    second = scan(scan_root); after_id = store.save(second)
    comparison = store.compare(before_id, after_id)
    assert len(comparison.added) == 1
    assert len(comparison.changed) == 1
    assert comparison.removed == []
    csv_path = tmp_path / "report.csv"; export_files(second.files, str(csv_path))
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        content = handle.read()
    assert "café.csv" in content and "TOTAL" in content
    compare_path = tmp_path / "comparison.csv"; export_comparison(comparison, str(compare_path))
    assert "Changed" in compare_path.read_text(encoding="utf-8-sig")
