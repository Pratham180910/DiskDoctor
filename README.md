# DiskDoctor Pro

Native Windows disk analyzer built with Python and CustomTkinter. The supplied web prototype is preserved under `assets/design_reference` for visual reference only.

## Install and launch

```bat
cd "C:\Users\fahad\Desktop\app DiskDoctor Pro"
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

Choose a drive or folder, then use Quick Scan for bounded triage or Full Scan for complete traversal. Both modes use bounded worker threads and one metadata call per entry; Quick Scan stops at 100,000 files while Full Scan removes that cap. Scans report progress through a queue, skip symbolic links, and record access errors.

## Modules

- `main.py` — native entry point.
- `ui/` — CustomTkinter shell, theme, components, and screens.
- `core/scanner.py` — filesystem traversal, cancellation, progress, and drive usage.
- `core/treemap.py` — proportional rectangle layout.
- `core/duplicate_finder.py` — size grouping and SHA-256 verification.
- `core/history.py` — SQLite scan history.
- `core/cleanup.py` — cleanup path safety checks.
- `core/reports.py` — Unicode-safe CSV export.

Scan History can compare two saved scans and reports root/coverage compatibility, file/folder/size deltas, changed file sizes, and folder growth. Duplicate and cleanup deletion requires explicit selection and confirmation; each file is revalidated before removal and results are reported as successful, failed, or skipped.

Run validation with `.venv\\Scripts\\python.exe -m pytest -q`. See `TESTING.md` and `FEATURE_STATUS.md` for scope.
