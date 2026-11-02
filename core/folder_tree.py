from __future__ import annotations

import heapq
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.scanner import FileRecord, ScanResult


@dataclass(slots=True)
class FolderNode:
    path: str
    name: str
    size: int = 0
    direct_size: int = 0
    file_count: int = 0
    direct_file_count: int = 0
    subfolder_paths: list[str] = field(default_factory=list)
    parent_path: str | None = None
    largest_files: list[FileRecord] = field(default_factory=list)
    type_summary: list[tuple[str, int, int]] = field(default_factory=list)
    pct_of_total: float = 0.0

    @property
    def subfolder_count(self) -> int:
        return len(self.subfolder_paths)


class FolderTree:
    def __init__(self, root_path: str, total_bytes: int = 0, total_files: int = 0):
        self.root_path = os.path.normpath(root_path)
        self.nodes: dict[str, FolderNode] = {}
        self.total_bytes = max(1, total_bytes)
        self.total_files = total_files
        self.available_extensions: list[str] = []
        self._all_records: list[FileRecord] = []

    @classmethod
    def build_from_scan(cls, result: ScanResult) -> FolderTree:
        norm_root = os.path.normpath(result.target)
        tree = cls(norm_root, result.bytes_total, len(result.files))
        tree._all_records = result.files

        # Ensure root node exists
        root_name = os.path.basename(norm_root) or norm_root
        tree.nodes[norm_root] = FolderNode(path=norm_root, name=root_name)

        root_normcase = os.path.normcase(norm_root)
        parent_cache: dict[str, str | None] = {norm_root: None}
        dir_cache: dict[str, str] = {}

        def get_dir(filepath: str) -> str:
            last_sep = max(filepath.rfind('\\'), filepath.rfind('/'))
            raw_dir = filepath[:last_sep] if last_sep != -1 else ""
            if raw_dir in dir_cache:
                return dir_cache[raw_dir]
            nd = os.path.normpath(raw_dir)
            dir_cache[raw_dir] = nd
            return nd

        def get_parent(folder: str) -> str:
            if folder in parent_cache:
                return parent_cache[folder]
            p = os.path.normpath(os.path.dirname(folder))
            parent_cache[folder] = p
            return p

        # Temporary tracking structures for bottom-up aggregation
        direct_files_by_folder: dict[str, list[FileRecord]] = defaultdict(list)
        ext_summary_by_folder: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        subfolders_set: dict[str, set[str]] = defaultdict(set)
        discovered_extensions: set[str] = set()
        visited_dirs: set[str] = {norm_root}

        for record in result.files:
            file_dir = get_dir(record.path)
            direct_files_by_folder[file_dir].append(record)
            ext = record.extension.lower() if record.extension else "none"
            discovered_extensions.add(ext)

            stat = ext_summary_by_folder[file_dir][ext]
            stat[0] += record.size
            stat[1] += 1

            # Traverse directory hierarchy only once per unique directory
            if file_dir not in visited_dirs:
                visited_dirs.add(file_dir)
                curr = file_dir
                chain = []
                while os.path.normcase(curr) != root_normcase and curr not in tree.nodes:
                    chain.append(curr)
                    p = get_parent(curr)
                    if p == curr:
                        break
                    curr = p

                for c in reversed(chain):
                    par = get_parent(c)
                    tree.nodes[c] = FolderNode(path=c, name=os.path.basename(c) or c, parent_path=par)
                    subfolders_set[par].add(c)

        # Link subfolders to each node
        for folder_path, children in subfolders_set.items():
            if folder_path in tree.nodes:
                tree.nodes[folder_path].subfolder_paths = sorted(children)

        # Process direct sizes and file counts
        for folder_path, files in direct_files_by_folder.items():
            if folder_path in tree.nodes:
                node = tree.nodes[folder_path]
                node.direct_size = sum(f.size for f in files)
                node.direct_file_count = len(files)

        # Sort all nodes by path depth descending for single-pass bottom-up aggregation
        sorted_paths = sorted(tree.nodes.keys(), key=lambda p: p.count(os.sep), reverse=True)

        for path_key in sorted_paths:
            node = tree.nodes[path_key]
            total_size = node.direct_size
            total_count = node.direct_file_count
            node_ext_map = ext_summary_by_folder[path_key]

            # Candidate largest files using bounded heapq
            direct_candidates = heapq.nlargest(5, direct_files_by_folder.get(path_key, []), key=lambda f: f.size)
            largest_candidates = list(direct_candidates)

            for child_path in node.subfolder_paths:
                if child_path in tree.nodes:
                    child_node = tree.nodes[child_path]
                    total_size += child_node.size
                    total_count += child_node.file_count
                    if child_node.largest_files:
                        largest_candidates = heapq.nlargest(5, largest_candidates + child_node.largest_files, key=lambda f: f.size)

                    # Merge child extension counts
                    for ext, (c_size, c_count) in ext_summary_by_folder[child_path].items():
                        parent_ext = node_ext_map[ext]
                        parent_ext[0] += c_size
                        parent_ext[1] += c_count

            node.size = total_size
            node.file_count = total_count
            node.pct_of_total = (total_size / tree.total_bytes) * 100.0

            # Retain top 5 unique largest files
            seen_paths = set()
            unique_largest = []
            for item in largest_candidates:
                if item.path not in seen_paths:
                    seen_paths.add(item.path)
                    unique_largest.append(item)
                    if len(unique_largest) == 5:
                        break
            node.largest_files = unique_largest

            # Top 10 extension breakdown
            sorted_types = sorted(
                ((ext, stat[0], stat[1]) for ext, stat in node_ext_map.items()),
                key=lambda item: item[1],
                reverse=True,
            )
            node.type_summary = sorted_types[:10]

        tree.available_extensions = sorted(discovered_extensions)
        return tree

    def get_node(self, path: str) -> FolderNode | None:
        norm = os.path.normpath(path)
        return self.nodes.get(norm)

    def get_children(self, path: str, sort_by: str = "size", reverse: bool = True) -> list[FolderNode]:
        node = self.get_node(path)
        if not node:
            return []

        children = [self.nodes[p] for p in node.subfolder_paths if p in self.nodes]

        if sort_by == "name":
            return sorted(children, key=lambda n: n.name.lower(), reverse=reverse)
        if sort_by == "files":
            return sorted(children, key=lambda n: n.file_count, reverse=reverse)
        if sort_by == "pct":
            return sorted(children, key=lambda n: n.pct_of_total, reverse=reverse)
        # Default: size
        return sorted(children, key=lambda n: n.size, reverse=reverse)

    def filter_nodes(self, query: str = "", min_size: int = 0, extension: str = "All") -> set[str]:
        """Returns the set of folder paths that match the filters, plus all ancestor paths up to root."""
        matched_folders: set[str] = set()
        clean_query = query.strip().lower()
        clean_ext = extension.strip().lower().lstrip(".")

        for path, node in self.nodes.items():
            # Check min_size
            if min_size > 0 and node.size < min_size:
                continue

            # Check extension filter
            if clean_ext and clean_ext != "all":
                has_ext = any(ext.lower() == clean_ext for ext, _, _ in node.type_summary)
                if not has_ext:
                    continue

            # Check search query on folder name or path
            if clean_query:
                name_match = clean_query in node.name.lower() or clean_query in node.path.lower()
                file_match = any(clean_query in f.name.lower() for f in node.largest_files)
                if not (name_match or file_match):
                    continue

            matched_folders.add(path)

        # Include all ancestors of matched nodes so the hierarchy remains navigable
        result_paths: set[str] = set()
        for path in matched_folders:
            curr = path
            while curr:
                result_paths.add(curr)
                node = self.nodes.get(curr)
                if not node or not node.parent_path or node.parent_path == curr:
                    break
                curr = node.parent_path

        # Root must always be included
        if self.root_path in self.nodes:
            result_paths.add(self.root_path)

        return result_paths

