from __future__ import annotations

import csv
import threading
from pathlib import Path
from queue import Queue
from unittest.mock import patch

from core.cleanup import delete_selected, safe_cleanup_path
from core.duplicate_finder import exact_duplicate_groups, reclaimable_bytes, sha256_file
from core.folder_tree import FolderTree
from core.history import HistoryStore
from core.reports import export_comparison, export_files
from core.scanner import FileRecord, Scanner
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
    candidate = tmp_path / "temp.log"
    candidate.write_text("safe")
    assert safe_cleanup_path(str(candidate), [str(tmp_path)])
    assert not safe_cleanup_path(str(tmp_path), [str(tmp_path)])
    result = scan(tmp_path)
    with patch("core.cleanup.send2trash", create=True) as mock_trash:
        mock_trash.side_effect = lambda p: Path(p).unlink()
        deleted = delete_selected([next(item for item in result.files if item.name == "temp.log")], [str(tmp_path)], confirm=True)
        assert deleted[0].status == "success"
        assert not candidate.exists()
        mock_trash.assert_called_once_with(str(candidate))


def test_cleanup_cross_drive_and_alternate_roots(tmp_path):
    candidate = tmp_path / "cache.tmp"
    candidate.write_text("temp data")
    # Simulates having D:\ selected in the UI while temp files are in tmp_path
    allowed = ["D:\\SimulatedDrive", str(tmp_path)]
    assert safe_cleanup_path(str(candidate), allowed)
    assert not safe_cleanup_path("D:\\NonExistent\\file.tmp", allowed)


def test_recycle_bin_failure_handling_never_unlinks(tmp_path):
    candidate = tmp_path / "important.tmp"
    candidate.write_text("must survive")
    result = scan(tmp_path)
    rec = next(item for item in result.files if item.name == "important.tmp")
    with patch("core.cleanup.send2trash", create=True) as mock_trash:
        mock_trash.side_effect = OSError("Recycle Bin is full or unavailable")
        results = delete_selected([rec], [str(tmp_path)], confirm=True)
        assert results[0].status == "failed"
        assert "Recycle Bin error" in results[0].message
        # Verify file is completely untouched on disk and never permanently unlinked
        assert candidate.exists()
        assert candidate.read_text() == "must survive"


def test_cleanup_missing_file(tmp_path):
    missing_path = tmp_path / "vanished.tmp"
    rec = FileRecord(str(missing_path), "vanished.tmp", 100, "tmp", 12345.0)
    results = delete_selected([rec], [str(tmp_path)], confirm=True)
    assert len(results) == 1
    assert results[0].status == "skipped"


def test_cleanup_modified_file(tmp_path):
    candidate = tmp_path / "changing.tmp"
    candidate.write_text("original content")
    result = scan(tmp_path)
    rec = next(item for item in result.files if item.name == "changing.tmp")
    # Mutate the file after it was scanned
    candidate.write_text("modified content has different size")
    results = delete_selected([rec], [str(tmp_path)], confirm=True)
    assert len(results) == 1
    assert results[0].status == "skipped"
    assert "File changed" in results[0].message
    assert candidate.exists()


def test_cleanup_symlink_protection(tmp_path):
    real = tmp_path / "target.txt"
    real.write_text("target")
    link = tmp_path / "link.tmp"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        return  # Symlinks not permitted in current OS privileges
    assert not safe_cleanup_path(str(link), [str(tmp_path)])
    rec = FileRecord(str(link), "link.tmp", 6, "tmp", 0.0)
    results = delete_selected([rec], [str(tmp_path)], confirm=True)
    assert results[0].status == "skipped"
    assert link.exists()


def test_cleanup_system_directory_protection():
    system_paths = [
        "C:\\Windows\\System32\\cmd.exe",
        "C:\\Program Files\\DiskDoctor\\app.exe",
        "C:\\Program Files (x86)\\Common\\test.dll",
        "D:\\System Volume Information\\indexer.dat",
        "C:\\$Recycle.Bin\\S-1-5-21\\trash.tmp",
        "C:\\Recovery\\recovery.wim",
    ]
    for sys_path in system_paths:
        assert not safe_cleanup_path(sys_path, ["C:\\", "D:\\"])


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


def test_quick_scan_coverage_reporting_and_properties(tmp_path):
    (tmp_path / "sample.txt").write_text("sample content")
    queue = Queue()
    Scanner().scan_async(str(tmp_path), "Quick Scan", queue).join(timeout=5)
    event = queue.get_nowait()
    while event.kind != "complete":
        event = queue.get_nowait()
    result = event.result

    assert result.mode == "Quick Scan"
    assert result.is_partial is True
    assert result.coverage_badge == "PARTIAL SCAN"
    assert "100,000 files" in result.coverage_description
    assert "triage mode" in result.coverage_description.lower()


def test_full_scan_coverage_reporting_and_properties(tmp_path):
    (tmp_path / "data.bin").write_bytes(b"comprehensive test")
    result = scan(tmp_path)
    assert result.mode == "Full Scan"
    assert result.is_partial is False
    assert result.coverage_badge == "FULL SCAN"
    assert "Comprehensive" in result.coverage_description


def test_history_incompatible_scan_modes_comparison(tmp_path):
    (tmp_path / "file1.txt").write_text("version 1")
    q_queue = Queue()
    Scanner().scan_async(str(tmp_path), "Quick Scan", q_queue).join(timeout=5)
    q_ev = q_queue.get_nowait()
    while q_ev.kind != "complete":
        q_ev = q_queue.get_nowait()
    quick_result = q_ev.result

    (tmp_path / "file2.txt").write_text("version 2")
    full_result = scan(tmp_path)

    store = HistoryStore(tmp_path / "history.sqlite3")
    quick_id = store.save(quick_result)
    full_id = store.save(full_result)

    recent = store.recent()
    assert len(recent) == 2
    quick_row = next(r for r in recent if r[0] == quick_id)
    full_row = next(r for r in recent if r[0] == full_id)
    assert quick_row[9] == 0
    assert full_row[9] == 1

    comp = store.compare(quick_id, full_id)
    assert comp.compatible is False
    assert "Incompatible scan modes" in comp.warning
    assert "Quick Scan is a 100k-file bounded triage sample" in comp.warning


def test_folder_tree_aggregation_and_details(tmp_path):
    root_dir = tmp_path / "project"
    root_dir.mkdir()
    sub_docs = root_dir / "docs"
    sub_docs.mkdir()
    sub_media = root_dir / "media"
    sub_media.mkdir()

    (root_dir / "readme.txt").write_bytes(b"A" * 100)
    (sub_docs / "spec.pdf").write_bytes(b"B" * 500)
    (sub_docs / "notes.txt").write_bytes(b"C" * 200)
    (sub_media / "video.mp4").write_bytes(b"D" * 2000)

    result = scan(root_dir)
    tree = FolderTree.build_from_scan(result)

    # Root metrics
    root_node = tree.get_node(str(root_dir))
    assert root_node is not None
    assert root_node.size == 2800
    assert root_node.file_count == 4
    assert root_node.direct_size == 100
    assert root_node.direct_file_count == 1
    assert root_node.subfolder_count == 2
    assert root_node.pct_of_total == 100.0

    # Largest files in root subtree
    assert len(root_node.largest_files) == 4
    assert root_node.largest_files[0].name == "video.mp4"
    assert root_node.largest_files[0].size == 2000
    assert root_node.largest_files[1].name == "spec.pdf"

    # Type summary in root subtree
    type_map = {ext: size for ext, size, _ in root_node.type_summary}
    assert type_map["mp4"] == 2000
    assert type_map["pdf"] == 500
    assert type_map["txt"] == 300

    # Subfolder metrics
    docs_node = tree.get_node(str(sub_docs))
    assert docs_node is not None
    assert docs_node.size == 700
    assert docs_node.file_count == 2
    assert round(docs_node.pct_of_total, 1) == 25.0
    assert docs_node.parent_path == str(root_dir)


def test_folder_tree_sorting(tmp_path):
    root_dir = tmp_path / "sort_test"
    root_dir.mkdir()
    alpha = root_dir / "alpha"; alpha.mkdir(); (alpha / "f1.bin").write_bytes(b"x" * 100)
    beta = root_dir / "beta"; beta.mkdir(); (beta / "f2.bin").write_bytes(b"x" * 500); (beta / "f3.bin").write_bytes(b"x" * 500)
    gamma = root_dir / "gamma"; gamma.mkdir(); (gamma / "f4.bin").write_bytes(b"x" * 300)

    result = scan(root_dir)
    tree = FolderTree.build_from_scan(result)

    # Sort by size descending
    by_size_desc = tree.get_children(str(root_dir), sort_by="size", reverse=True)
    assert [n.name for n in by_size_desc] == ["beta", "gamma", "alpha"]

    # Sort by size ascending
    by_size_asc = tree.get_children(str(root_dir), sort_by="size", reverse=False)
    assert [n.name for n in by_size_asc] == ["alpha", "gamma", "beta"]

    # Sort by name alphabetically
    by_name = tree.get_children(str(root_dir), sort_by="name", reverse=False)
    assert [n.name for n in by_name] == ["alpha", "beta", "gamma"]

    # Sort by file count descending
    by_files = tree.get_children(str(root_dir), sort_by="files", reverse=True)
    assert by_files[0].name == "beta"
    assert by_files[0].file_count == 2


def test_folder_tree_search_and_filters(tmp_path):
    root_dir = tmp_path / "filter_test"
    root_dir.mkdir()
    logs = root_dir / "logs"; logs.mkdir(); (logs / "app.log").write_bytes(b"x" * 50)
    data = root_dir / "data"; data.mkdir(); (data / "database.sqlite").write_bytes(b"x" * 5000)
    deep = data / "archive"; deep.mkdir(); (deep / "old.zip").write_bytes(b"x" * 10000)

    result = scan(root_dir)
    tree = FolderTree.build_from_scan(result)

    # Filter by name query matching folder
    log_match = tree.filter_nodes(query="logs")
    assert str(logs) in log_match
    assert str(root_dir) in log_match  # Ancestor retained

    # Filter by name query matching file inside deep folder
    zip_match = tree.filter_nodes(query="old.zip")
    assert str(deep) in zip_match
    assert str(data) in zip_match  # Parent retained
    assert str(root_dir) in zip_match  # Root retained
    assert str(logs) not in zip_match

    # Filter by min size >= 5000 bytes
    large_match = tree.filter_nodes(min_size=5000)
    assert str(data) in large_match
    assert str(deep) in large_match
    assert str(logs) not in large_match

    # Filter by extension
    ext_match = tree.filter_nodes(extension="sqlite")
    assert str(data) in ext_match
    assert str(logs) not in ext_match

    # Reset/empty filters include all nodes
    all_match = tree.filter_nodes()
    assert all_match == set(tree.nodes.keys())


def test_folder_tree_empty_and_inaccessible_lookups(tmp_path):
    root_dir = tmp_path / "empty_test"
    root_dir.mkdir()
    empty_sub = root_dir / "empty_dir"
    empty_sub.mkdir()

    result = scan(root_dir)
    tree = FolderTree.build_from_scan(result)

    assert tree.get_node(str(empty_sub)) is not None or tree.get_node(str(root_dir)) is not None
    assert tree.get_node("Z:\\NonExistent\\Path") is None
    assert tree.get_children("Z:\\NonExistent\\Path") == []

