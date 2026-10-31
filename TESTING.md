# Testing

Validated on 27 Oct 2026:

- Project-local `.venv` created and CustomTkinter/pytest installed.
- Python `compileall` passed for `core`, `ui`, and `main.py`.
- `pytest -q`: **7 passed**.
- Native import and `DiskDoctorApp` window initialization/update/clean shutdown passed.
- Tests cover recursive traversal, aggregation, symlink skipping, cancellation, duplicate hashing, same-size non-duplicates, reclaimable space, treemap area conservation, SQLite persistence, scan comparison, Unicode CSV escaping, deletion revalidation, and cleanup guards.
- Navigation smoke test initialized every sidebar page and shut down cleanly.
- Quick Scan benchmark on the project workspace: 98,993 files / 10,549 folders / 0 errors in approximately 1.7 seconds.
- Full Scan benchmark on the project workspace: 98,993 files / 10,549 folders / 0 errors in approximately 1.65 seconds after parallel traversal optimization.

Full-drive performance and protected-volume behavior still need testing on the target Windows machine because mounted volumes and permissions vary.
