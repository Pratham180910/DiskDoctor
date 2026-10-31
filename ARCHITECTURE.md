# DiskDoctor Pro architecture

The deliverable is a native Python/CustomTkinter application:

```text
main.py -> ui.main_window.DiskDoctorApp -> core.Scanner worker thread
                                      -> treemap / duplicate hashing / SQLite history / comparison / CSV reports
```

Worker threads never touch widgets. They publish `ScanEvent` records to a thread-safe queue, and the main window consumes them on the Tk main thread. The Next.js files remain as an archived visual prototype and are not used by `main.py`.

Deletion is a separate, explicit flow: the UI shows exact paths and total bytes, asks for confirmation, then `core.cleanup.delete_selected` revalidates each file’s location, size, and modification time immediately before unlinking. Duplicate detection never preselects a copy for deletion.
