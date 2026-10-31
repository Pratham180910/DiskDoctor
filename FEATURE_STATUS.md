# Feature status

## Implemented

- Native CustomTkinter application launched with `python main.py`.
- Cool Gold theme, persistent sidebar, drive/folder picker, Quick Scan and Full Scan.
- Background filesystem scanning with progress, cancellation signal, access-error collection, disappearing-file handling, and symlink avoidance.
- Quick Scan uses bounded parallel directory workers and is capped at 100,000 files for responsive triage; Full Scan uses the same workers with no file cap.
- Actual drive usage, file/folder counts, extension summary, largest files, donut chart, and proportional treemap.
- Disk Analyzer, Large Files filtering, CSV export, Scan History backed by SQLite, and settings/insights/cleanup review screens.
- Exact duplicate engine with size grouping and SHA-256 confirmation.
- Duplicate progress/cancellation, file-stability checks, and reclaimable-space estimates.
- Cleanup path guard plus explicit, revalidated deletion reporting success/failed/skipped results.
- Saved-scan comparison with file/folder/size deltas, added/removed/changed metadata, folder growth, root mismatch, and incomplete-coverage warnings.
- Unicode-safe file and comparison CSV exports with totals.

## Partial / next phase

- Cleanup does not yet use the Windows Recycle Bin; deletion is permanent after confirmation.
- History comparison reports path-level changes from stored metadata; incomplete scans are explicitly marked and changes are lower bounds.
- Treemap currently prioritizes largest discovered files; hierarchical folder aggregation can be expanded.
