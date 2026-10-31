from __future__ import annotations

import os
import time
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.cleanup import DeleteResult, delete_selected, discover_cleanup_candidates
from core.duplicate_finder import HashCancelled, HashProgress, exact_duplicate_groups, reclaimable_bytes
from core.history import HistoryStore, ScanComparison
from core.reports import export_comparison, export_files
from core.scanner import FileRecord, ScanEvent, ScanResult, Scanner, available_drives, disk_usage
from core.treemap import layout
from .components import Card, SectionTitle, button, format_bytes, label
from .theme import BG, BORDER, BRIGHT_GOLD, CARD, ELEVATED, GOLD, MUTED, SECONDARY, SIDEBAR, SUCCESS, SURFACE, TEXT, configure


NAV = [("Dashboard", "dashboard"), ("Disk Analyzer", "analyzer"), ("Large Files", "large"), ("Duplicates", "duplicates"), ("Cleanup Center", "cleanup"), ("File Insights", "insights"), ("Scan History", "history"), ("Settings", "settings")]


class DiskDoctorApp(ctk.CTk):
    def __init__(self):
        configure()
        super().__init__()
        self.title("DiskDoctor Pro — Storage Intelligence")
        self.geometry("1420x900")
        self.minsize(1080, 700)
        self.configure(fg_color=BG)
        self.queue: Queue[ScanEvent] = Queue()
        self.duplicate_queue: Queue = Queue()
        self.scanner = Scanner()
        self.history = HistoryStore(Path(__file__).resolve().parents[1] / "diskdoctor_history.sqlite3")
        self.result: ScanResult | None = None
        self.last_scan_id: int | None = None
        self.duplicate_groups = []
        self.duplicate_checks = []
        self.duplicate_cancel = None
        self.compare_view: ScanComparison | None = None
        self.scan_started = 0.0
        self.page = "dashboard"
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self._build_shell()
        self.show_page("dashboard")
        self.after(100, self._poll_events)

    def _build_shell(self):
        self.sidebar = ctk.CTkFrame(self, width=230, fg_color=SIDEBAR, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(22, 30))
        ctk.CTkLabel(brand, text="◈", text_color=GOLD, font=ctk.CTkFont(size=28, weight="bold")).pack(side="left")
        text = ctk.CTkFrame(brand, fg_color="transparent"); text.pack(side="left", padx=10)
        label(text, "DiskDoctor ", 15, TEXT, "bold").pack(side="left")
        label(text, "Pro", 15, GOLD, "bold").pack(side="left")
        label(text, "Storage Intelligence", 9, MUTED).pack(anchor="w")
        label(self.sidebar, "WORKSPACE", 9, MUTED, "bold").pack(anchor="w", padx=22, pady=(0, 10))
        for title, key in NAV:
            btn = ctk.CTkButton(self.sidebar, text=f"  {title}", anchor="w", height=38, corner_radius=6, fg_color="transparent", hover_color=ELEVATED, text_color=SECONDARY, command=lambda k=key: self.show_page(k))
            btn.pack(fill="x", padx=12, pady=2); self.nav_buttons[key] = btn
        ctk.CTkFrame(self.sidebar, fg_color="transparent").pack(expand=True, fill="both")
        self.sidebar_drive = label(self.sidebar, "●  Drive ready", 10, SUCCESS); self.sidebar_drive.pack(anchor="w", padx=22, pady=(0, 8))
        label(self.sidebar, "Native Windows analyzer", 9, MUTED).pack(anchor="w", padx=22, pady=(0, 20))
        self.main = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        self.main.pack(side="left", fill="both", expand=True)
        self.header = ctk.CTkFrame(self.main, height=92, fg_color=SURFACE, corner_radius=0)
        self.header.pack(fill="x", padx=28, pady=(18, 0))
        self.header.grid_columnconfigure(0, weight=1)
        self.header_title = label(self.header, "Storage Overview", 25, TEXT, "bold"); self.header_title.grid(row=0, column=0, sticky="w")
        self.header_subtitle = label(self.header, "Understand your disk. Find wasted space. Take control.", 11, SECONDARY); self.header_subtitle.grid(row=1, column=0, sticky="w", pady=(3, 0))
        controls = ctk.CTkFrame(self.header, fg_color="transparent"); controls.grid(row=0, column=1, rowspan=2, sticky="e")
        self.target = ctk.CTkComboBox(controls, values=available_drives(), width=170, height=32, fg_color=ELEVATED, border_color=BORDER, button_color=ELEVATED, text_color=TEXT)
        self.target.set(available_drives()[0]); self.target.pack(side="left", padx=5)
        ctk.CTkButton(controls, text="Browse", width=68, height=32, fg_color=ELEVATED, hover_color="#242A32", command=self.browse_target).pack(side="left", padx=5)
        button(controls, "Quick Scan", self.start_quick, True, 105).pack(side="left", padx=5)
        button(controls, "Full Scan", self.start_full, False, 100).pack(side="left", padx=5)
        self.status = label(self.main, "Ready for a scan", 10, MUTED); self.status.pack(anchor="w", padx=32, pady=(2, 8))
        self.content = ctk.CTkScrollableFrame(self.main, fg_color="transparent", corner_radius=0)
        self.content.pack(fill="both", expand=True, padx=18, pady=(0, 18))

    def browse_target(self):
        selected = filedialog.askdirectory(title="Choose a folder to analyze")
        if selected: self.target.set(selected)

    def show_page(self, key: str):
        self.page = key
        titles = {k: t for t, k in NAV}
        self.header_title.configure(text="Storage Overview" if key == "dashboard" else titles[key])
        self.header_subtitle.configure(text="Understand your disk. Find wasted space. Take control." if key == "dashboard" else "Explore measured storage data and review actions safely.")
        for name, btn in self.nav_buttons.items(): btn.configure(fg_color="#2A2110" if name == key else "transparent", text_color=BRIGHT_GOLD if name == key else SECONDARY)
        for child in self.content.winfo_children(): child.destroy()
        getattr(self, f"page_{key}")()

    def start_quick(self): self._start_scan("Quick Scan")
    def start_full(self): self._start_scan("Full Scan")
    def _start_scan(self, mode: str):
        if self.scan_started: return
        target = self.target.get().strip()
        if not target or not os.path.exists(target):
            messagebox.showerror("Scan target unavailable", "Choose an existing drive or folder first."); return
        self.scan_started = time.perf_counter(); self.scanner.scan_async(target, mode, self.queue)
        self.status.configure(text=f"Scanning {target} · {mode} · 0 files", text_color=GOLD)

    def cancel_scan(self): self.scanner.cancel(); self.status.configure(text="Cancellation requested…", text_color=GOLD)
    def _poll_events(self):
        try:
            while True:
                event = self.queue.get_nowait()
                if event.kind == "progress": self.status.configure(text=f"Scanning · {event.files:,} files · {event.folders:,} folders · {format_bytes(event.bytes_total)}")
                elif event.kind == "complete":
                    self.scan_started = 0; self.result = event.result
                    if self.result:
                        self.last_scan_id = self.history.save(self.result)
                        self.status.configure(text=f"Scan complete · {len(self.result.files):,} files · {len(self.result.errors):,} access errors", text_color=SUCCESS)
                        self.sidebar_drive.configure(text=f"●  {self.result.target} indexed")
                        self.show_page(self.page)
        except Empty: pass
        try:
            while True:
                event = self.duplicate_queue.get_nowait()
                if event[0] == "progress": self.status.configure(text=f"Hashing duplicates · {event[1]} / {event[2]}", text_color=GOLD)
                elif event[0] == "complete":
                    self.duplicate_groups = event[1]; self.status.configure(text=f"Duplicate scan complete · {len(self.duplicate_groups)} exact groups", text_color=SUCCESS); self.show_page("duplicates")
                elif event[0] == "cancelled": self.status.configure(text="Duplicate hashing cancelled", text_color=WARNING)
        except Empty: pass
        self.after(100, self._poll_events)

    def page_dashboard(self):
        self._summary(); self._dashboard_lower()
    def _summary(self):
        result = self.result; target = self.target.get(); total, used, free = disk_usage(target)
        values = [("Total Space", format_bytes(total), target), ("Used Space", format_bytes(used), f"{used / total * 100:.1f}% used" if total else "Unavailable"), ("Free Space", format_bytes(free), f"{free / total * 100:.1f}% available" if total else "Unavailable"), ("Files Scanned", f"{len(result.files):,}" if result else "—", f"{result.folders:,} folders" if result else "Run a scan to measure")]
        grid = ctk.CTkFrame(self.content, fg_color="transparent"); grid.pack(fill="x", pady=(0, 16))
        for index, (title, value, meta) in enumerate(values):
            grid.grid_columnconfigure(index, weight=1); card = Card(grid); card.grid(row=0, column=index, sticky="nsew", padx=5)
            label(card, title, 10, SECONDARY).pack(anchor="w", padx=16, pady=(15, 5)); label(card, value, 22, TEXT, "bold").pack(anchor="w", padx=16); label(card, meta, 10, MUTED).pack(anchor="w", padx=16, pady=(4, 15))

    def _dashboard_lower(self):
        result = self.result
        row = ctk.CTkFrame(self.content, fg_color="transparent"); row.pack(fill="x", expand=False)
        left = Card(row); left.pack(fill="x", expand=False, padx=5, pady=(0, 14))
        SectionTitle(left, "Storage Usage").pack(fill="x", padx=15, pady=14)
        canvas = tk.Canvas(left, width=240, height=240, bg=CARD, highlightthickness=0); canvas.pack(side="left", padx=25, pady=18)
        self._draw_donut(canvas, result)
        legend = ctk.CTkFrame(left, fg_color="transparent"); legend.pack(side="left", fill="both", expand=True, padx=5)
        if result:
            categories = result.type_summary[:5]
            remainder_size = sum(size for _, size, _ in result.type_summary[5:])
            remainder_count = sum(count for _, _, count in result.type_summary[5:])
            if remainder_size: categories.append(("Other", remainder_size, remainder_count))
            for ext, size, count in categories: label(legend, f"●  {ext:<12} {format_bytes(size)}  · {count:,}", 10, SECONDARY).pack(anchor="w", pady=4)
        if not result: label(legend, "Run a scan to see measured categories.", 10, MUTED, wraplength=220).pack(anchor="w", pady=20)
        right = Card(row); right.pack(fill="x", expand=False, padx=5, pady=(0, 14))
        SectionTitle(right, "Storage Treemap").pack(fill="x", padx=15, pady=14)
        treemap_host = ctk.CTkFrame(right, fg_color=CARD, height=280); treemap_host.pack(fill="both", expand=True, padx=15, pady=(0, 15)); treemap_host.pack_propagate(False); treemap_host.after(100, lambda h=treemap_host, r=result: self._render_treemap_blocks(h, r))
        bottom = Card(self.content); bottom.pack(fill="x", pady=(16, 0)); SectionTitle(bottom, "Largest Files", "Open Large Files", lambda: self.show_page("large")).pack(fill="x", padx=15, pady=14)
        for item in (result.largest_files[:6] if result else []): label(bottom, f"{item.name}    {format_bytes(item.size)}    {item.path}", 10, SECONDARY).pack(fill="x", padx=20, pady=4)
        if not result: label(bottom, "No measured files yet. Start a Quick Scan or Full Scan above.", 10, MUTED).pack(anchor="w", padx=20, pady=(0, 18))

    def _draw_donut(self, canvas, result):
        canvas.create_oval(35, 35, 205, 205, outline="#252A31", width=28)
        if result and result.type_summary:
            total = max(1, result.bytes_total); start = -90; colors = ["#E8B84D", "#49C99A", "#5D8FE8", "#D87855", "#9D7B38"]
            for index, (_, size, _) in enumerate(result.type_summary[:5]):
                extent = size / total * 360; canvas.create_arc(35, 35, 205, 205, start=start, extent=extent, style="arc", outline=colors[index % len(colors)], width=28); start += extent
        canvas.create_text(120, 105, text=format_bytes(result.bytes_total) if result else "—", fill=TEXT, font=("Segoe UI", 16, "bold")); canvas.create_text(120, 132, text="measured", fill=MUTED, font=("Segoe UI", 9))

    def _draw_treemap(self, canvas, result):
        canvas.delete("all")
        if not result: canvas.create_text(300, 120, text="Run a scan to generate a proportional map", fill=MUTED, font=("Segoe UI", 11)); return
        canvas.update_idletasks(); width = max(600, canvas.winfo_width()); height = max(260, canvas.winfo_height())
        items = [(extension, size) for extension, size, _count in result.type_summary[:12]]
        rects = layout(items, width, height)
        colors = ["#8B5CF6", "#D65A5A", "#3195CF", "#3BAE78", "#D6A928", "#C57443"]
        for index, rect in enumerate(rects):
            x1, y1, x2, y2 = rect.x + 2, rect.y + 2, rect.x + rect.width - 2, rect.y + rect.height - 2; canvas.create_rectangle(x1, y1, x2, y2, fill=colors[index % len(colors)], outline="#FFFFFF30");
            if rect.width > 70 and rect.height > 28: canvas.create_text(x1 + 8, y1 + 8, anchor="nw", text=rect.label[:20], fill="white", font=("Segoe UI", 9, "bold"))

    def _render_treemap_blocks(self, host, result):
        """Render proportional measured areas as native CustomTkinter blocks."""
        for child in host.winfo_children(): child.destroy()
        if not result or not result.type_summary:
            label(host, "Run a scan to generate a proportional map", 11, MUTED).place(relx=0.5, rely=0.5, anchor="center")
            return
        host.update_idletasks(); width = host.winfo_width(); height = host.winfo_height()
        if width <= 1 or height <= 1:
            host.after(100, lambda h=host, r=result: self._render_treemap_blocks(h, r)); return
        rects = layout([(extension, size) for extension, size, _count in result.type_summary[:12]], width, height)
        colors = ["#8B5CF6", "#D65A5A", "#3195CF", "#3BAE78", "#D6A928", "#C57443", "#3E8BAA", "#7254A5"]
        for index, rect in enumerate(rects):
            rel_x = min(0.999, max(0.001, (rect.x + 2) / width)); rel_y = min(0.999, max(0.001, (rect.y + 2) / height))
            rel_w = min(1.0 - rel_x, max(0.002, (rect.width - 4) / width)); rel_h = min(1.0 - rel_y, max(0.002, (rect.height - 4) / height))
            block = ctk.CTkFrame(host, width=1, height=1, fg_color=colors[index % len(colors)], corner_radius=3)
            block.place(relx=rel_x, rely=rel_y, relwidth=rel_w, relheight=rel_h)
            if rect.width > 105 and rect.height > 38:
                label(block, f".{rect.label}\n{format_bytes(rect.value)}", 10, "#FFFFFF", "bold", justify="left").pack(anchor="nw", padx=8, pady=7)

    def page_analyzer(self):
        card = Card(self.content); card.pack(fill="both", expand=True, padx=5); SectionTitle(card, "Disk Analyzer", "Refresh", lambda: self.show_page("analyzer")).pack(fill="x", padx=15, pady=14)
        if not self.result: label(card, "Run a scan to populate the folder tree and proportional storage map.", 12, MUTED).pack(anchor="w", padx=20, pady=30); return
        tree = tk.Text(card, bg=CARD, fg=SECONDARY, insertbackground=GOLD, height=10, relief="flat", font=("Consolas", 10)); tree.pack(fill="x", padx=20)
        for path, size, count in self.result.type_summary[:30]: tree.insert("end", f"{path:<24} {format_bytes(size):>12}  {count:,} files\n")
        treemap_host = ctk.CTkFrame(card, fg_color=CARD, height=300); treemap_host.pack(fill="both", expand=True, padx=20, pady=20); treemap_host.pack_propagate(False); treemap_host.after(100, lambda h=treemap_host, r=self.result: self._render_treemap_blocks(h, r))

    def page_large(self):
        card = Card(self.content); card.pack(fill="both", expand=True, padx=5); top = ctk.CTkFrame(card, fg_color="transparent"); top.pack(fill="x", padx=15, pady=14); label(top, "Large Files", 14, TEXT, "bold").pack(side="left"); self.large_search = ctk.CTkEntry(top, placeholder_text="Search filename…", width=220); self.large_search.pack(side="right", padx=5); button(top, "Export CSV", self.export_current, False, 95).pack(side="right", padx=5)
        self.large_body = ctk.CTkScrollableFrame(card, fg_color="transparent"); self.large_body.pack(fill="both", expand=True, padx=12, pady=8); self._render_large_files()
    def _render_large_files(self):
        for child in self.large_body.winfo_children(): child.destroy()
        query = self.large_search.get().lower() if hasattr(self, "large_search") else ""; items = [item for item in (self.result.largest_files if self.result else []) if query in item.name.lower()]
        for item in items[:200]:
            row = ctk.CTkFrame(self.large_body, fg_color="transparent"); row.pack(fill="x", pady=3)
            label(row, f"{format_bytes(item.size):>12}   {item.name}   {item.path}", 10, SECONDARY, anchor="w").pack(side="left", fill="x", expand=True)
            button(row, "Delete", lambda record=item: self.confirm_delete([record], "Delete file"), False, 72).pack(side="right")
    def export_current(self):
        if not self.result: return
        dest = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if dest: export_files(self.result.largest_files, dest); self.status.configure(text=f"Exported {dest}", text_color=SUCCESS)

    def page_duplicates(self):
        card = Card(self.content); card.pack(fill="both", expand=True, padx=5)
        head = ctk.CTkFrame(card, fg_color="transparent"); head.pack(fill="x", padx=15, pady=14)
        label(head, "Exact Duplicates", 15, TEXT, "bold").pack(side="left")
        button(head, "Cancel", self.cancel_duplicate_scan, False, 75).pack(side="right", padx=4)
        button(head, "Scan Hashes", self.start_duplicate_scan, True, 105).pack(side="right", padx=4)
        button(head, "Delete Selected", self.delete_duplicate_selection, False, 125).pack(side="right", padx=4)
        if not self.result: label(card, "Run a scan first. Duplicate detection verifies content with SHA-256 and never preselects files.", 11, MUTED, wraplength=760).pack(anchor="w", padx=20, pady=25); return
        if not self.duplicate_groups: label(card, "No hashed duplicate groups yet. Start Hashes to verify equal-sized candidates.", 11, MUTED).pack(anchor="w", padx=20, pady=25); return
        self.duplicate_checks = []
        body = ctk.CTkScrollableFrame(card, fg_color="transparent"); body.pack(fill="both", expand=True, padx=12, pady=5)
        for group_index, group in enumerate(self.duplicate_groups, 1):
            box = ctk.CTkFrame(body, fg_color=ELEVATED, corner_radius=6); box.pack(fill="x", pady=6)
            label(box, f"Group {group_index} · {len(group)} exact copies · {format_bytes(reclaimable_bytes(group))} reclaimable if all but one are removed", 10, BRIGHT_GOLD).pack(anchor="w", padx=12, pady=(9, 5))
            for record in group:
                variable = tk.BooleanVar(value=False); self.duplicate_checks.append((variable, record)); ctk.CTkCheckbutton(box, text=f"{record.path}  ·  {format_bytes(record.size)}", variable=variable, text_color=SECONDARY, fg_color=GOLD, hover_color=BRIGHT_GOLD).pack(anchor="w", padx=12, pady=3)

    def start_duplicate_scan(self):
        if not self.result: return
        self.duplicate_cancel = __import__("threading").Event(); self.status.configure(text="Hashing duplicate candidates…", text_color=GOLD)
        def worker():
            try:
                groups = exact_duplicate_groups(self.result.files, cancel_event=self.duplicate_cancel, progress=lambda p: self.duplicate_queue.put(("progress", p.completed, p.total)))
                self.duplicate_queue.put(("complete", groups))
            except HashCancelled: self.duplicate_queue.put(("cancelled",))
        __import__("threading").Thread(target=worker, daemon=True).start()
    def cancel_duplicate_scan(self):
        if self.duplicate_cancel: self.duplicate_cancel.set()
    def delete_duplicate_selection(self):
        selected = [record for variable, record in self.duplicate_checks if variable.get()]
        if not selected: messagebox.showinfo("Nothing selected", "Select the exact copies you want to remove. One copy is never selected automatically."); return
        self.confirm_delete(selected, "Delete selected duplicate copies")

    def page_cleanup(self):
        # Use the dashboard's main scroll surface for this long list. A nested
        # CTkScrollableFrame can leave its canvas viewport blank on Windows.
        card = Card(self.content); card.pack(fill="x", expand=False, padx=5)
        label(card, "Cleanup Center", 15, TEXT, "bold").pack(anchor="w", padx=20, pady=(20, 5)); label(card, "Category selection is separate from deletion. Only explicit file selections can be executed.", 11, SECONDARY).pack(anchor="w", padx=20, pady=(0, 15))
        # Cleanup is intentionally independent from the scan result: a scan may
        # be capped, may not include %TEMP%, or may have been run on another drive.
        # Discover only files inside the user's Windows temp directory and leave
        # every checkbox clear until the user explicitly selects an item.
        candidates = discover_cleanup_candidates()
        self.cleanup_checks = []
        body = ctk.CTkFrame(card, fg_color="transparent"); body.pack(fill="x", expand=False, padx=12)
        if candidates:
            label(body, f"{len(candidates):,} user-temp files found · {format_bytes(sum(item.size for item in candidates))} estimated", 11, SECONDARY).pack(anchor="w", padx=10, pady=(8, 12))
        else:
            label(body, "No user-temp files were found in %TEMP%. Cleanup candidates will appear here when available.", 11, MUTED, wraplength=760).pack(anchor="w", padx=10, pady=25)
        for record in candidates[:200]:
            variable = tk.BooleanVar(value=False); self.cleanup_checks.append((variable, record)); ctk.CTkCheckBox(body, text=f"{record.path} · {format_bytes(record.size)}", variable=variable, text_color=SECONDARY, fg_color=GOLD, hover_color=BRIGHT_GOLD).pack(anchor="w", padx=10, pady=3)
        button(card, "Preview / Delete Selected", self.delete_cleanup_selection, False, 180).pack(anchor="e", padx=20, pady=15)
    def delete_cleanup_selection(self):
        selected = [record for variable, record in getattr(self, "cleanup_checks", []) if variable.get()]
        if not selected: messagebox.showinfo("Nothing selected", "Select cleanup candidates to review before deletion."); return
        self.confirm_delete(selected, "Delete selected cleanup files")

    def confirm_delete(self, records: list[FileRecord], title: str):
        total = sum(record.size for record in records)
        paths = "\n".join(record.path for record in records[:12]); suffix = "\n…" if len(records) > 12 else ""
        if not messagebox.askyesno(title, f"The following {len(records)} file(s) will be deleted ({format_bytes(total)}):\n\n{paths}{suffix}\n\nContinue?", icon="warning"): return
        results = delete_selected(records, [self.target.get()], confirm=True)
        success = sum(item.status == "success" for item in results); failed = sum(item.status == "failed" for item in results); skipped = sum(item.status == "skipped" for item in results)
        self.status.configure(text=f"Deletion complete · {success} removed · {failed} failed · {skipped} skipped", text_color=SUCCESS if not failed else WARNING)
        messagebox.showinfo("Deletion result", f"Successful: {success}\nFailed: {failed}\nSkipped: {skipped}\nRecovered: {format_bytes(sum(item.bytes_removed for item in results))}")
    def page_insights(self):
        self._simple_page("File Insights", "Transparent findings from measured file sizes, extensions, and scan history.")
    def page_history(self):
        card = Card(self.content); card.pack(fill="both", expand=True, padx=5); SectionTitle(card, "Scan History").pack(fill="x", padx=15, pady=14)
        rows = self.history.recent(); ids = [str(row[0]) for row in rows]
        if not rows: label(card, "No saved scans yet.", 11, MUTED).pack(anchor="w", padx=20, pady=25); return
        controls = ctk.CTkFrame(card, fg_color="transparent"); controls.pack(fill="x", padx=15, pady=(0, 12)); label(controls, "Compare older → newer", 10, SECONDARY).pack(side="left", padx=(0, 8))
        self.compare_before = ctk.CTkComboBox(controls, values=ids, width=90); self.compare_before.set(ids[-1]); self.compare_before.pack(side="left", padx=4)
        self.compare_after = ctk.CTkComboBox(controls, values=ids, width=90); self.compare_after.set(ids[0]); self.compare_after.pack(side="left", padx=4)
        button(controls, "Compare", self.run_comparison, True, 95).pack(side="left", padx=4); button(controls, "Export", self.export_comparison_view, False, 85).pack(side="left", padx=4)
        for row in rows: label(card, f"#{row[0]}  {row[1]}   {row[3]:<10}   {row[2]}   {row[5]:,} files · {row[6]:,} folders · {format_bytes(row[7])} · {row[8]} errors · {'complete' if row[9] else 'incomplete'}", 10, SECONDARY).pack(anchor="w", padx=20, pady=5)
        if self.compare_view: self._render_comparison(card, self.compare_view)
    def run_comparison(self):
        try: self.compare_view = self.history.compare(int(self.compare_before.get()), int(self.compare_after.get())); self.show_page("history")
        except (KeyError, ValueError) as exc: messagebox.showerror("Comparison unavailable", str(exc))
    def export_comparison_view(self):
        if not self.compare_view: messagebox.showinfo("No comparison", "Run a comparison first."); return
        dest = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if dest: export_comparison(self.compare_view, dest); self.status.configure(text=f"Exported comparison to {dest}", text_color=SUCCESS)
    def _render_comparison(self, parent, comparison: ScanComparison):
        section = ctk.CTkFrame(parent, fg_color=ELEVATED, corner_radius=6); section.pack(fill="x", padx=15, pady=14)
        label(section, "Comparison", 13, BRIGHT_GOLD, "bold").pack(anchor="w", padx=15, pady=(12, 5))
        if comparison.warning: label(section, "⚠ " + comparison.warning, 10, WARNING, wraplength=820, justify="left").pack(anchor="w", padx=15, pady=4)
        delta = comparison.after
        label(section, f"Files: {comparison.before.files:,} → {delta.files:,} ({delta.files - comparison.before.files:+,})    Folders: {comparison.before.folders:,} → {delta.folders:,} ({delta.folders - comparison.before.folders:+,})    Size: {format_bytes(comparison.before.bytes_total)} → {format_bytes(delta.bytes_total)}", 10, SECONDARY).pack(anchor="w", padx=15, pady=4)
        label(section, f"New: {len(comparison.added or []):,} · Removed: {len(comparison.removed or []):,} · Changed sizes: {len(comparison.changed or []):,}", 10, SECONDARY).pack(anchor="w", padx=15, pady=4)
        for folder, amount in (comparison.folder_growth or [])[:5]: label(section, f"Growth · {format_bytes(amount)} · {folder}", 10, SUCCESS).pack(anchor="w", padx=25, pady=2)
    def page_settings(self): self._simple_page("Settings", "Cool Gold theme is active. Scan defaults, units, exclusions, and confirmation preferences will be persisted here.")
    def _simple_page(self, title: str, description: str):
        card = Card(self.content); card.pack(fill="x", padx=5, pady=5); label(card, title, 16, TEXT, "bold").pack(anchor="w", padx=20, pady=(20, 8)); label(card, description, 11, SECONDARY, wraplength=820, justify="left").pack(anchor="w", padx=20, pady=(0, 20))
