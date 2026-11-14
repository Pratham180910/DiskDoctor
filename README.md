# 🩺 DiskDoctor Pro

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white)
![CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-gold?style=flat)
![SQLite](https://img.shields.io/badge/Database-SQLite-003B57?style=flat&logo=sqlite&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?style=flat&logo=windows&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=flat)

A standalone Windows desktop utility for analysing disk usage, detecting duplicate files, cleaning temporary files safely, and tracking storage changes over time — all without a browser or server.

---

## ✨ Key Features

- **Quick Scan** — Parallel bounded scan (capped at 100,000 files) for fast triage with a clear `PARTIAL SCAN` badge
- **Full Scan** — Uncapped comprehensive traversal across all accessible directories with a `FULL SCAN` badge
- **Parallel File Scanning** — Multi-threaded worker pool (up to 8 threads, auto-scaled to CPU count) using `os.scandir` with a single `stat()` call per entry
- **Interactive Disk Analyzer** — Lazy-loading `ttk.Treeview` folder explorer with sortable columns (name, size, file count, %)
- **Folder Details Panel** — Full path, total size, file/subfolder counts, 5 largest files, and file-type breakdown per selected folder
- **Search & Filter** — Debounced (350 ms) folder/file search, minimum-size filter, and file-type filter with incremental results
- **Treemap Visualisation** — Proportional slice-and-dice treemap of storage categories rendered on a `Canvas`
- **Duplicate Finder** — Two-phase SHA-256 detection: cheap partial hash pre-filter → full SHA-256 confirmation, with real-time progress and cancellation
- **Safe Temp Cleanup** — Discovers user-temp files, validates against allowed roots, revalidates size + mtime before action, and sends to the **Windows Recycle Bin** via `send2trash` — never permanently deletes
- **Scan History** — SQLite-backed history with scan mode and coverage stored; compare any two Full Scans to see added, removed, and changed files plus folder growth ranking
- **CSV Export** — Export file lists or scan comparisons to UTF-8 CSV
- **Dashboard** — Live drive stats (total/used/free space), files scanned, storage category chart, and scan coverage info
- **Cool Gold Dark Theme** — Consistent `#C9A84C` accent, dark `#1a1a1a` background, premium desktop aesthetic throughout

---

## 🏗️ Tech Stack & Architecture

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| GUI Framework | CustomTkinter 5.2+ · `ttk.Treeview` · `tkinter.Canvas` |
| Database | SQLite 3 (via `sqlite3` stdlib) |
| Concurrency | `threading.Thread` · `ThreadPoolExecutor` · `queue.Queue` |
| File Safety | `send2trash` 1.8+ (Recycle Bin integration) |
| Hashing | `hashlib.sha256` (stdlib) |
| Testing | `pytest` 8+ |

### Folder Structure

```
DiskDoctor/
├── main.py                     # Application entry point
├── requirements.txt            # pip dependencies
├── diskdoctor_history.sqlite3  # Auto-created scan history database
│
├── core/                       # Pure-Python business logic (no Tkinter)
│   ├── scanner.py              # FileRecord, ScanResult, Scanner (parallel & sequential)
│   ├── folder_tree.py          # FolderTree / FolderNode — cached aggregation engine
│   ├── duplicate_finder.py     # Two-phase SHA-256 duplicate detection
│   ├── cleanup.py              # Safe temp-file discovery & Recycle Bin deletion
│   ├── history.py              # HistoryStore (SQLite), StoredScan, ScanComparison
│   ├── reports.py              # CSV export for file lists and comparisons
│   ├── treemap.py              # Slice-and-dice treemap layout algorithm
│   └── __init__.py
│
├── ui/
│   ├── main_window.py          # Root CTk window, 8-page navigation, background workers
│   ├── components.py           # Reusable UI widgets (cards, badges, stat panels)
│   └── theme.py                # Colour constants and font definitions
│
├── tests/
│   └── test_core.py            # 20 pytest unit tests for core modules
│
└── assets/
    └── design_reference/       # Original Next.js/React design prototype (archived)
```

---

## 🚀 Getting Started

### Prerequisites

- **Windows 10/11**
- **Python 3.11+** — download from [python.org](https://www.python.org/downloads/)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/Pratham180910/DiskDoctor.git
cd DiskDoctor

# 2. (Recommended) Create a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

### Running the Application

```bash
python main.py
```

> The SQLite database (`diskdoctor_history.sqlite3`) is created automatically on first run in the project directory.

### Running Tests

```bash
pytest -q
```

Expected output: `20 passed`

---

## 📦 Dependencies

| Package | Version | Purpose |
|---|---|---|
| `customtkinter` | ≥ 5.2 | Modern themed Tkinter widgets |
| `send2trash` | ≥ 1.8.0 | Windows Recycle Bin integration |
| `pytest` | ≥ 8.0 | Test runner |

> All other dependencies (`hashlib`, `sqlite3`, `threading`, `csv`, `os`, `shutil`) are Python standard library — no external installation required.

---

## 🖥️ Application Pages

| Page | Description |
|---|---|
| **Dashboard** | Drive selector, real disk usage (total/used/free), scan stats, storage category breakdown |
| **Quick Scan** | Bounded parallel scan up to 100,000 files; shows `PARTIAL SCAN` badge and coverage note |
| **Full Scan** | Uncapped parallel scan; shows `FULL SCAN` badge, folder count, access errors |
| **Disk Analyzer** | Interactive folder tree explorer with search, filters, folder details, and 5 largest files |
| **Duplicates** | Two-phase SHA-256 duplicate detection with reclaimable-bytes summary |
| **Cleanup** | Temp-file discovery, preview list, Recycle Bin deletion with per-file result reporting |
| **History** | SQLite scan log with Quick/Full Scan labels; select two Full Scans to diff |
| **Reports** | Export current scan or comparison results to CSV |

---

## 🔒 Safety Guarantees

- **Never permanently deletes files** — `send2trash` is the only deletion path; if it fails, the file is left untouched and an error is reported.
- **Pre-deletion revalidation** — file size and modification time are rechecked against the scan record before any action.
- **Symlink protection** — symlinks are always skipped in scan and cleanup paths.
- **System directory block-list** — `Windows`, `Program Files`, `System Volume Information`, `$Recycle.Bin`, and `Recovery` directories are hard-blocked.
- **Allowed-roots containment** — cleanup is restricted to paths inside the system temp directory (or an explicitly provided root list).

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Run tests before committing: `pytest -q`
4. Push and open a Pull Request against `main`

---

## 📄 License

All rights reserved.
