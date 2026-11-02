from __future__ import annotations

import math
import os
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from core.cleanup import DeleteResult, delete_selected, discover_cleanup_candidates
from core.duplicate_finder import HashCancelled, HashProgress, exact_duplicate_groups, reclaimable_bytes
from core.folder_tree import FolderNode, FolderTree
from core.history import HistoryStore, ScanComparison
from core.reports import export_comparison, export_files
from core.scanner import FileRecord, ScanEvent, ScanResult, Scanner, available_drives, disk_usage
from core.treemap import layout
from .components import Badge, Card, SectionTitle, StatCard, button, format_bytes, label
from .theme import (
    BG,
    BORDER,
    BORDER_ACCENT,
    BRIGHT_GOLD,
    CARD,
    CARD_HOVER,
    CHART_COLORS,
    ELEVATED,
    ERROR,
    GOLD,
    GOLD_BG,
    MUTED,
    MUTED_GOLD,
    SECONDARY,
    SIDEBAR,
    SUCCESS,
    SURFACE,
    TEXT,
    WARNING,
    configure,
)

NAV = [
    ("Dashboard", "dashboard", "⊞"),
    ("Disk Analyzer", "analyzer", "⌕"),
    ("Large Files", "large", "☰"),
    ("Duplicates", "duplicates", "⧉"),
    ("Cleanup Center", "cleanup", "✦"),
    ("File Insights", "insights", "📈"),
    ("Scan History", "history", "⏱"),
    ("Settings", "settings", "⚙"),
]


class DiskDoctorApp(ctk.CTk):
    def __init__(self):
        configure()
        super().__init__()
        self.title("DiskDoctor Pro — Storage Intelligence")
        self.geometry("1440x920")
        self.minsize(1100, 720)
        self.configure(fg_color=BG)

        # Threading queues & engines
        self.queue: Queue[ScanEvent] = Queue()
        self.duplicate_queue: Queue = Queue()
        self.analyzer_queue: Queue = Queue()
        self.scanner = Scanner()
        self.history = HistoryStore(Path(__file__).resolve().parents[1] / "diskdoctor_history.sqlite3")

        # Runtime state
        self.result: ScanResult | None = None
        self.last_scan_id: int | None = None
        self.duplicate_groups: list[list[FileRecord]] = []
        self.duplicate_checks: list[tuple[tk.BooleanVar, FileRecord]] = []
        self.duplicate_cancel = None
        self.compare_view: ScanComparison | None = None
        self.scan_started = 0.0
        self.current_scan_mode = "Quick Scan"
        self.page = "dashboard"
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self.cleanup_checks: list[tuple[tk.BooleanVar, FileRecord]] = []

        # Donut hover state
        self.donut_segments: list[dict] = []
        self.donut_hover_label = None

        # Large files view filters
        self.large_sort_mode = "Size (Largest First)"
        self.large_min_size_filter = "All Sizes"

        # Analyzer & Folder Explorer state
        self.folder_tree: FolderTree | None = None
        self.folder_tree_cache_id: tuple | None = None
        self.folder_tree_building: bool = False
        self.folder_tree_job_id: int = 0
        self._search_debounce_timer = None
        self._expand_in_progress: bool = False
        self._expand_cancelled: bool = False
        self.btn_expand_all: ctk.CTkButton | None = None
        self.analyzer_view_mode = "explorer"
        self.analyzer_sort_column = "size"
        self.analyzer_sort_reverse = True
        self.analyzer_search_query = ""
        self.analyzer_min_size = 0
        self.analyzer_ext_filter = "All"
        self.analyzer_treeview: ttk.Treeview | None = None
        self.analyzer_details_frame: ctk.CTkScrollableFrame | None = None
        self.analyzer_breadcrumb: ctk.CTkLabel | None = None
        self.selected_folder_node: FolderNode | None = None
        self.analyzer_search_entry: ctk.CTkEntry | None = None
        self.analyzer_min_size_combo: ctk.CTkComboBox | None = None
        self.analyzer_ext_combo: ctk.CTkComboBox | None = None

        self._configure_ttk_styles()
        self._build_shell()
        self.show_page("dashboard")
        self.after(100, self._poll_events)

    def _configure_ttk_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Treeview",
            background=CARD,
            foreground=TEXT,
            fieldbackground=CARD,
            rowheight=28,
            font=("Segoe UI", 10),
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=ELEVATED,
            foreground=SECONDARY,
            font=("Segoe UI", 9, "bold"),
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", GOLD_BG)],
            foreground=[("selected", BRIGHT_GOLD)],
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#1C212A")],
            foreground=[("active", GOLD)],
        )

    def _build_shell(self):
        # 1. SIDEBAR
        self.sidebar = ctk.CTkFrame(self, width=240, fg_color=SIDEBAR, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Logo / Brand
        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(22, 24))
        mark = ctk.CTkFrame(brand, width=34, height=34, fg_color=GOLD_BG, border_color=GOLD, border_width=1, corner_radius=8)
        mark.pack(side="left")
        mark.pack_propagate(False)
        ctk.CTkLabel(mark, text="◈", text_color=GOLD, font=ctk.CTkFont(size=20, weight="bold")).place(relx=0.5, rely=0.5, anchor="center")

        brand_text = ctk.CTkFrame(brand, fg_color="transparent")
        brand_text.pack(side="left", padx=10)
        title_row = ctk.CTkFrame(brand_text, fg_color="transparent")
        title_row.pack(anchor="w")
        label(title_row, "DiskDoctor ", 15, TEXT, "bold").pack(side="left")
        label(title_row, "Pro", 15, GOLD, "bold").pack(side="left")
        label(brand_text, "Storage Intelligence", 9, MUTED).pack(anchor="w", pady=(1, 0))

        # Section Label
        label(self.sidebar, "WORKSPACE", 9, MUTED, "bold").pack(anchor="w", padx=22, pady=(0, 8))

        # Navigation Buttons
        for title, key, icon in NAV:
            btn = ctk.CTkButton(
                self.sidebar,
                text=f"  {icon}   {title}",
                anchor="w",
                height=38,
                corner_radius=6,
                fg_color="transparent",
                hover_color="#181C22",
                text_color=SECONDARY,
                font=ctk.CTkFont(size=11, weight="bold" if key == "dashboard" else "normal"),
                command=lambda k=key: self.show_page(k),
            )
            btn.pack(fill="x", padx=12, pady=2)
            self.nav_buttons[key] = btn

        # Spacer
        ctk.CTkFrame(self.sidebar, fg_color="transparent").pack(expand=True, fill="both")

        # Sidebar Bottom Drive Widget
        self.sidebar_drive_box = Card(self.sidebar, fg_color="#0D1015", border_color=BORDER, border_width=1, corner_radius=6)
        self.sidebar_drive_box.pack(fill="x", padx=12, pady=(0, 14))

        drive_head = ctk.CTkFrame(self.sidebar_drive_box, fg_color="transparent")
        drive_head.pack(fill="x", padx=12, pady=(10, 4))
        self.sidebar_drive_dot = label(drive_head, "●", 10, SUCCESS)
        self.sidebar_drive_dot.pack(side="left")
        self.sidebar_drive_title = label(drive_head, " C: Drive", 10, TEXT, "bold")
        self.sidebar_drive_title.pack(side="left")
        self.sidebar_drive_free = label(drive_head, "— free", 9, MUTED)
        self.sidebar_drive_free.pack(side="right")

        self.sidebar_progress = ctk.CTkProgressBar(self.sidebar_drive_box, height=4, corner_radius=2, fg_color="#1F232B", progress_color=GOLD)
        self.sidebar_progress.pack(fill="x", padx=12, pady=(4, 6))
        self.sidebar_progress.set(0.0)

        self.sidebar_drive_sub = label(self.sidebar_drive_box, "Select a drive to analyze", 9, MUTED)
        self.sidebar_drive_sub.pack(anchor="w", padx=12, pady=(0, 10))

        label(self.sidebar, "Windows Desktop Utility v1.0", 8, MUTED).pack(anchor="w", padx=22, pady=(0, 16))

        # 2. MAIN CONTENT AREA
        self.main = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        self.main.pack(side="left", fill="both", expand=True)

        # Header Bar
        self.header = ctk.CTkFrame(self.main, height=94, fg_color=SURFACE, corner_radius=0)
        self.header.pack(fill="x", padx=30, pady=(18, 0))
        self.header.grid_columnconfigure(0, weight=1)

        header_info = ctk.CTkFrame(self.header, fg_color="transparent")
        header_info.grid(row=0, column=0, sticky="w")
        self.header_title = label(header_info, "Storage Overview", 24, TEXT, "bold")
        self.header_title.pack(anchor="w")
        self.header_subtitle = label(header_info, "Understand your disk. Find wasted space. Take control.", 11, SECONDARY)
        self.header_subtitle.pack(anchor="w", pady=(2, 0))

        # Scan Controls Toolbar
        controls = ctk.CTkFrame(self.header, fg_color="transparent")
        controls.grid(row=0, column=1, sticky="e")

        label(controls, "Target:", 10, MUTED, "bold").pack(side="left", padx=(0, 4))
        self.target = ctk.CTkComboBox(
            controls,
            values=available_drives(),
            width=140,
            height=32,
            fg_color=ELEVATED,
            border_color=BORDER,
            button_color=ELEVATED,
            text_color=TEXT,
            command=self._on_drive_changed,
        )
        self.target.set(available_drives()[0])
        self.target.pack(side="left", padx=4)

        ctk.CTkButton(
            controls,
            text="Browse",
            width=68,
            height=32,
            corner_radius=6,
            fg_color=ELEVATED,
            hover_color="#242A32",
            text_color=TEXT,
            font=ctk.CTkFont(size=11),
            command=self.browse_target,
        ).pack(side="left", padx=4)

        self.btn_quick = button(controls, "⚡ Quick Scan", self.start_quick, True, 110)
        self.btn_quick.pack(side="left", padx=4)

        self.btn_full = button(controls, "🔍 Full Scan", self.start_full, False, 105)
        self.btn_full.pack(side="left", padx=4)

        self.btn_cancel = ctk.CTkButton(
            controls,
            text="✕ Cancel",
            width=80,
            height=32,
            corner_radius=6,
            fg_color="#36171B",
            hover_color="#542127",
            text_color="#FFB3B3",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.cancel_scan,
        )
        self.btn_cancel.pack(side="left", padx=4)
        self.btn_cancel.configure(state="disabled")

        # Scan Progress Bar & Live Status Bar
        status_bar = ctk.CTkFrame(self.main, fg_color="transparent")
        status_bar.pack(fill="x", padx=30, pady=(6, 10))

        self.progress_bar = ctk.CTkProgressBar(status_bar, height=3, corner_radius=2, fg_color="#181B22", progress_color=GOLD)
        self.progress_bar.pack(fill="x", pady=(0, 4))
        self.progress_bar.set(0.0)

        self.status = label(status_bar, "Ready for a scan — choose a drive or custom folder", 10, MUTED)
        self.status.pack(anchor="w")

        # Scrollable Viewport
        self.content = ctk.CTkScrollableFrame(self.main, fg_color="transparent", corner_radius=0)
        self.content.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        self._update_sidebar_drive()

    def _on_drive_changed(self, _choice=None):
        self._update_sidebar_drive()
        if self.page == "dashboard":
            self.show_page("dashboard")

    def _update_sidebar_drive(self):
        target = self.target.get().strip()
        total, used, free = disk_usage(target)
        if total > 0:
            pct = used / total
            self.sidebar_drive_title.configure(text=f" {target[:8]}")
            self.sidebar_drive_free.configure(text=f"{format_bytes(free)} free")
            self.sidebar_progress.set(pct)
            self.sidebar_progress.configure(progress_color=WARNING if pct > 0.85 else GOLD)
            self.sidebar_drive_sub.configure(text=f"{format_bytes(used)} of {format_bytes(total)} ({pct*100:.1f}%)")
        else:
            self.sidebar_drive_title.configure(text=f" {target[:8]}")
            self.sidebar_drive_free.configure(text="—")
            self.sidebar_progress.set(0.0)
            self.sidebar_drive_sub.configure(text="Drive stats unavailable")

    def browse_target(self):
        selected = filedialog.askdirectory(title="Choose a folder to analyze")
        if selected:
            self.target.set(selected)
            self._update_sidebar_drive()
            if self.page == "dashboard":
                self.show_page("dashboard")

    def show_page(self, key: str):
        self.page = key
        titles = {k: t for t, k, _ in NAV}
        subtitles = {
            "dashboard": "Understand your disk. Find wasted space. Take control.",
            "analyzer": "Explore storage breakdown across file extensions and proportional spaces.",
            "large": "Identify and sort large files consuming the most disk space.",
            "duplicates": "Find redundant bit-for-bit file duplicates verified with SHA-256.",
            "cleanup": "Safely clean user temporary files and send them to the Recycle Bin.",
            "insights": "Automated observations and storage recommendations from scan data.",
            "history": "Historical snapshots, trend analysis, and delta comparisons.",
            "settings": "Configure scan limits, unit displays, and confirmation preferences.",
        }

        self.header_title.configure(text="Storage Overview" if key == "dashboard" else titles[key])
        self.header_subtitle.configure(text=subtitles.get(key, "Explore measured storage data safely."))

        for name, btn in self.nav_buttons.items():
            if name == key:
                btn.configure(fg_color=GOLD_BG, text_color=BRIGHT_GOLD, font=ctk.CTkFont(size=11, weight="bold"))
            else:
                btn.configure(fg_color="transparent", text_color=SECONDARY, font=ctk.CTkFont(size=11, weight="normal"))

        for child in self.content.winfo_children():
            child.destroy()

        getattr(self, f"page_{key}")()

    def start_quick(self):
        self._start_scan("Quick Scan")

    def start_full(self):
        self._start_scan("Full Scan")

    def _start_scan(self, mode: str):
        if self.scan_started:
            return
        target = self.target.get().strip()
        if not target or not os.path.exists(target):
            messagebox.showerror("Scan target unavailable", "Choose an existing drive or folder first.")
            return

        self.current_scan_mode = mode
        self.scan_started = time.perf_counter()
        self.btn_cancel.configure(state="normal")
        self.btn_quick.configure(state="disabled")
        self.btn_full.configure(state="disabled")
        self.progress_bar.set(0.08)

        self.scanner.scan_async(target, mode, self.queue)
        self.status.configure(text=f"Scanning {target} · {mode} initializing…", text_color=GOLD)

    def cancel_scan(self):
        self.scanner.cancel()
        self.status.configure(text="Cancellation requested… finishing active thread work", text_color=WARNING)

    def _poll_events(self):
        try:
            while True:
                event = self.queue.get_nowait()
                if event.kind == "progress":
                    pct = min(0.95, max(0.1, (event.files / 100_000) if self.current_scan_mode == "Quick Scan" else 0.5))
                    self.progress_bar.set(pct)
                    self.status.configure(
                        text=f"Scanning · {event.files:,} files · {event.folders:,} folders · {format_bytes(event.bytes_total)} indexed",
                        text_color=GOLD,
                    )
                elif event.kind == "complete":
                    self.scan_started = 0
                    self.btn_cancel.configure(state="disabled")
                    self.btn_quick.configure(state="normal")
                    self.btn_full.configure(state="normal")
                    self.progress_bar.set(1.0)

                    self.result = event.result
                    if self.result:
                        self.last_scan_id = self.history.save(self.result)
                        cancel_tag = " (Cancelled)" if self.result.cancelled else ""
                        if self.result.mode == "Quick Scan":
                            status_msg = f"Quick Scan complete (Partial sample) · {len(self.result.files):,} files indexed (100k cap) · {self.result.duration:.2f}s"
                            status_clr = WARNING
                        else:
                            status_msg = f"Full Scan complete (Comprehensive) · {len(self.result.files):,} files indexed · {len(self.result.errors):,} access errors · {self.result.duration:.2f}s"
                            status_clr = SUCCESS
                        self.status.configure(
                            text=f"{status_msg}{cancel_tag}",
                            text_color=status_clr if not self.result.cancelled else WARNING,
                        )
                        self._update_sidebar_drive()
                        cache_key = (self.result.target, self.result.duration, len(self.result.files))
                        self._start_folder_tree_build(cache_key)
                        self.show_page(self.page)
        except Empty:
            pass

        try:
            while True:
                event = self.duplicate_queue.get_nowait()
                if event[0] == "progress":
                    self.status.configure(text=f"Hashing duplicates · {event[1]} / {event[2]} ({event[3]})", text_color=GOLD)
                elif event[0] == "complete":
                    self.duplicate_groups = event[1]
                    self.status.configure(text=f"Duplicate scan complete · {len(self.duplicate_groups)} exact groups verified", text_color=SUCCESS)
                    self.show_page("duplicates")
                elif event[0] == "cancelled":
                    self.status.configure(text="Duplicate hashing cancelled", text_color=WARNING)
        except Empty:
            pass

        try:
            while True:
                ev = self.analyzer_queue.get_nowait()
                _, job_id, cache_key, tree, err = ev
                self._on_folder_tree_ready(job_id, cache_key, tree, err)
        except Empty:
            pass

        self.after(100, self._poll_events)

    # -------------------------------------------------------------------------
    # 3. DASHBOARD PAGE
    # -------------------------------------------------------------------------
    def page_dashboard(self):
        self._summary()
        self._dashboard_lower()

    def _summary(self):
        result = self.result
        target = self.target.get().strip()
        total, used, free = disk_usage(target)

        # Prominent Scan Coverage Banner
        if result:
            is_partial = result.is_partial
            banner_bg = "#1F180B" if is_partial else "#0E1E16"
            banner_border = WARNING if is_partial else SUCCESS
            banner = Card(self.content, fg_color=banner_bg, border_color=banner_border, border_width=1, corner_radius=8)
            banner.pack(fill="x", pady=(0, 14))

            top_line = ctk.CTkFrame(banner, fg_color="transparent")
            top_line.pack(fill="x", padx=16, pady=(12, 4))

            badge_text = result.coverage_badge
            badge_color = WARNING if is_partial else SUCCESS
            Badge(top_line, badge_text, color=badge_color).pack(side="left", padx=(0, 10))

            if result.mode == "Quick Scan":
                label(top_line, f"Quick Scan indexed {len(result.files):,} files in {result.duration:.2f}s", 13, BRIGHT_GOLD, "bold").pack(side="left")
                if self.btn_full.cget("state") != "disabled":
                    button(top_line, "Run Full Scan →", self.start_full, True, 125, 26).pack(side="right")

                desc = (
                    f"Quick Scan is a bounded triage mode capped at 100,000 files (visited {result.folders:,} folders on {result.target}). "
                    "Notice: Storage category distribution, largest files, and treemap represent only this partial sample and do NOT reflect the entire partition. "
                    "For comprehensive disk analysis without file limits, run a Full Scan."
                )
                label(banner, desc, 10, SECONDARY, wraplength=1050, justify="left").pack(anchor="w", padx=16, pady=(0, 12))
            else:
                label(top_line, f"Comprehensive Full Scan completed in {result.duration:.2f}s", 13, SUCCESS, "bold").pack(side="left")
                err_text = f" · {len(result.errors):,} permission-restricted system files were skipped" if result.errors else " · 0 access errors"
                desc = (
                    f"Traversed {result.folders:,} folders across {result.target} without file caps. "
                    f"Successfully indexed {len(result.files):,} files totaling {format_bytes(result.bytes_total)}{err_text}. "
                    "All accessible directories were comprehensively analyzed."
                )
                label(banner, desc, 10, SECONDARY, wraplength=1050, justify="left").pack(anchor="w", padx=16, pady=(0, 12))

        # 4 Responsive Statistics Cards
        grid = ctk.CTkFrame(self.content, fg_color="transparent")
        grid.pack(fill="x", pady=(0, 16))
        for i in range(4):
            grid.grid_columnconfigure(i, weight=1)

        # Card 1: Total Capacity
        StatCard(
            grid,
            title="Total Capacity",
            value=format_bytes(total) if total else "—",
            meta=f"Volume: {target}",
            icon="💾",
            accent_color=SECONDARY,
        ).grid(row=0, column=0, sticky="nsew", padx=5)

        # Card 2: Volume Used
        used_meta = f"{used / total * 100:.1f}% partition allocated" if total else "Filesystem usage unavailable"
        StatCard(
            grid,
            title="Volume Used",
            value=format_bytes(used) if total else "—",
            meta=used_meta,
            icon="📊",
            accent_color=GOLD,
        ).grid(row=0, column=1, sticky="nsew", padx=5)

        # Card 3: Volume Free
        free_meta = f"{free / total * 100:.1f}% available capacity" if total else "Free space unavailable"
        StatCard(
            grid,
            title="Volume Free",
            value=format_bytes(free) if total else "—",
            meta=free_meta,
            icon="💿",
            accent_color=SUCCESS,
        ).grid(row=0, column=2, sticky="nsew", padx=5)

        # Card 4: Scanned Content (Clearly distinguishing partial vs full)
        if result:
            scanned_val = format_bytes(result.bytes_total)
            if result.is_partial:
                scanned_title = "Scanned Files (Partial)"
                scanned_meta = f"{len(result.files):,} files (100k cap) · Sample only"
                scanned_color = WARNING
            else:
                scanned_title = "Scanned Files (Full)"
                err_s = f" · {len(result.errors)} errors" if result.errors else ""
                scanned_meta = f"{len(result.files):,} files · Comprehensive{err_s}"
                scanned_color = SUCCESS
        else:
            scanned_title = "Scanned Content"
            scanned_val = "Ready"
            scanned_meta = "Start Quick or Full Scan"
            scanned_color = BRIGHT_GOLD

        StatCard(
            grid,
            title=scanned_title,
            value=scanned_val,
            meta=scanned_meta,
            icon="📁",
            accent_color=scanned_color,
        ).grid(row=0, column=3, sticky="nsew", padx=5)

    def _dashboard_lower(self):
        result = self.result

        # Middle Grid: Donut Breakdown (Left) + Treemap (Right)
        middle_row = ctk.CTkFrame(self.content, fg_color="transparent")
        middle_row.pack(fill="x", expand=False)
        middle_row.grid_columnconfigure(0, weight=1)
        middle_row.grid_columnconfigure(1, weight=1)

        # Left: Donut Chart Card
        left_card = Card(middle_row)
        left_card.grid(row=0, column=0, sticky="nsew", padx=5, pady=(0, 14))

        if result and getattr(result, "is_partial", False):
            storage_subtitle = "Partial sample breakdown (capped at 100,000 files)"
        elif result:
            storage_subtitle = "Comprehensive breakdown of all indexed disk files"
        else:
            storage_subtitle = "Indexed content categorized by file type"
        SectionTitle(left_card, "Storage Breakdown", subtitle=storage_subtitle).pack(fill="x", padx=16, pady=(14, 8))

        donut_container = ctk.CTkFrame(left_card, fg_color="transparent")
        donut_container.pack(fill="both", expand=True, padx=14, pady=8)

        # Donut Canvas (enlarged to 280x280 for visual clarity)
        canvas = tk.Canvas(donut_container, width=280, height=280, bg=CARD, highlightthickness=0)
        canvas.pack(side="left", padx=(10, 15), pady=10)
        self._draw_donut(canvas, result)

        # Legend on the right
        legend = ctk.CTkFrame(donut_container, fg_color="transparent")
        legend.pack(side="left", fill="both", expand=True, padx=(5, 10))

        if result and result.type_summary:
            total_bytes = max(1, result.bytes_total)
            top_categories = result.type_summary[:5]
            remainder_size = sum(size for _, size, _ in result.type_summary[5:])
            remainder_count = sum(count for _, _, count in result.type_summary[5:])

            cat_rows = list(top_categories)
            if remainder_size > 0:
                cat_rows.append(("Other", remainder_size, remainder_count))

            for index, (ext, size, count) in enumerate(cat_rows):
                row = ctk.CTkFrame(legend, fg_color="transparent")
                row.pack(fill="x", pady=3)
                color = CHART_COLORS[index % len(CHART_COLORS)]
                label(row, "●", 12, color).pack(side="left", padx=(0, 6))
                label(row, f"{ext:<8}", 11, TEXT, "bold").pack(side="left")
                pct = size / total_bytes * 100
                label(row, f"{format_bytes(size)}  ({pct:.1f}%)", 10, SECONDARY).pack(side="right")
        else:
            label(legend, "Run a Quick or Full Scan to view\nmeasured storage categories.", 11, MUTED, justify="left").pack(anchor="w", pady=35)

        # Interactive hover label
        self.donut_hover_label = label(left_card, "Hover over chart slices to inspect category details.", 10, MUTED)
        self.donut_hover_label.pack(anchor="w", padx=18, pady=(0, 4))

        # Explicit Discrepancy & Coverage Clarification Footnote
        if result and getattr(result, "is_partial", False):
            note_text = (
                "⚠ PARTIAL SCAN NOTICE: This breakdown reflects a fast triage sample of the first 100,000 files. "
                "Category distribution may not represent the entire drive. Run a Full Scan for comprehensive metrics."
            )
            note_color = WARNING
        else:
            note_text = (
                "ℹ Scanned content reflects indexed user files. Volume Used above also includes OS pagefile, "
                "system restore points, and NTFS metadata."
            )
            note_color = MUTED_GOLD

        footnote = label(
            left_card,
            note_text,
            9,
            note_color,
            wraplength=480,
            justify="left",
        )
        footnote.pack(anchor="w", padx=18, pady=(0, 14))

        # Right: Treemap Card
        right_card = Card(middle_row)
        right_card.grid(row=0, column=1, sticky="nsew", padx=5, pady=(0, 14))

        SectionTitle(right_card, "Storage Treemap", "View Analyzer", lambda: self.show_page("analyzer"), subtitle="Proportional file distribution").pack(
            fill="x", padx=16, pady=(14, 8)
        )

        treemap_host = ctk.CTkFrame(right_card, fg_color="#0E1217", border_color=BORDER, border_width=1, corner_radius=6, height=295)
        treemap_host.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        treemap_host.pack_propagate(False)
        treemap_host.after(100, lambda h=treemap_host, r=result: self._render_treemap_blocks(h, r))

        # Bottom Card: Largest Files Preview
        bottom = Card(self.content)
        bottom.pack(fill="x", padx=5, pady=(4, 0))
        SectionTitle(bottom, "Largest Discovered Files", "Open Large Files →", lambda: self.show_page("large"), subtitle="Top disk space consumers").pack(
            fill="x", padx=18, pady=(14, 10)
        )

        if result and result.largest_files:
            # Table Header
            head = ctk.CTkFrame(bottom, fg_color=ELEVATED, height=28, corner_radius=4)
            head.pack(fill="x", padx=18, pady=(0, 6))
            label(head, "RANK", 9, MUTED, "bold").pack(side="left", padx=(12, 10))
            label(head, "FILE NAME", 9, MUTED, "bold").pack(side="left", padx=10)
            label(head, "ACTION", 9, MUTED, "bold").pack(side="right", padx=(10, 14))
            label(head, "SIZE", 9, MUTED, "bold").pack(side="right", padx=30)
            label(head, "PATH", 9, MUTED, "bold").pack(side="right", padx=60)

            for i, item in enumerate(result.largest_files[:6], 1):
                row = ctk.CTkFrame(bottom, fg_color="transparent")
                row.pack(fill="x", padx=18, pady=3)
                label(row, f"#{i:02d}", 10, GOLD, "bold").pack(side="left", padx=(12, 12))
                Badge(row, item.extension.upper()[:5]).pack(side="left", padx=(0, 10))
                label(row, item.name, 11, TEXT, "bold").pack(side="left", padx=(0, 10))

                button(row, "Recycle", lambda record=item: self.confirm_delete([record], "Send file to Recycle Bin", allowed_roots=[self.target.get()]), False, 72, 26).pack(
                    side="right", padx=(8, 12)
                )
                label(row, format_bytes(item.size), 11, BRIGHT_GOLD, "bold").pack(side="right", padx=(20, 25))
                path_str = item.path if len(item.path) < 55 else item.path[:25] + "…" + item.path[-28:]
                label(row, path_str, 10, MUTED).pack(side="right", padx=10)
            ctk.CTkFrame(bottom, height=8, fg_color="transparent").pack()
        else:
            label(bottom, "No indexed files yet. Run a Quick Scan or Full Scan above to inspect largest files.", 11, MUTED).pack(anchor="w", padx=20, pady=(0, 18))

    def _draw_donut(self, canvas: tk.Canvas, result: ScanResult | None):
        canvas.delete("all")
        self.donut_segments.clear()

        # Canvas Dimensions: 280x280; Outer Circle: (35, 35, 245, 245)
        cx, cy, radius, width = 140, 140, 105, 30
        x0, y0, x1, y1 = cx - radius, cy - radius, cx + radius, cy + radius

        # Base track ring
        canvas.create_oval(x0, y0, x1, y1, outline="#1C212A", width=width)

        if result and result.type_summary:
            total_bytes = max(1, result.bytes_total)
            start_angle = -90.0

            top_categories = result.type_summary[:5]
            remainder_size = sum(size for _, size, _ in result.type_summary[5:])
            slices = list(top_categories)
            if remainder_size > 0:
                slices.append(("Other", remainder_size, sum(count for _, _, count in result.type_summary[5:])))

            for index, (ext, size, count) in enumerate(slices):
                extent = (size / total_bytes) * 360.0
                color = CHART_COLORS[index % len(CHART_COLORS)]
                canvas.create_arc(x0, y0, x1, y1, start=start_angle, extent=extent, style="arc", outline=color, width=width)

                # Store segment angles for hover detection
                self.donut_segments.append(
                    {
                        "start": start_angle,
                        "extent": extent,
                        "label": ext,
                        "size": size,
                        "count": count,
                        "pct": (size / total_bytes) * 100.0,
                        "color": color,
                    }
                )
                start_angle += extent

            # Center metrics text
            canvas.create_text(cx, cy - 14, text=format_bytes(result.bytes_total), fill=TEXT, font=("Segoe UI", 16, "bold"))
            if getattr(result, "is_partial", False):
                canvas.create_text(cx, cy + 8, text="partial sample", fill=WARNING, font=("Segoe UI", 9, "bold"))
                canvas.create_text(cx, cy + 24, text=f"{len(result.files):,} files (100k cap)", fill=MUTED_GOLD, font=("Segoe UI", 8))
            else:
                canvas.create_text(cx, cy + 8, text="comprehensive", fill=SUCCESS, font=("Segoe UI", 9, "bold"))
                canvas.create_text(cx, cy + 24, text=f"{len(result.files):,} files indexed", fill=MUTED_GOLD, font=("Segoe UI", 8))

            canvas.bind("<Motion>", self._on_donut_motion)
            canvas.bind("<Leave>", self._on_donut_leave)
        else:
            canvas.create_text(cx, cy - 8, text="No scan data", fill=MUTED, font=("Segoe UI", 12, "bold"))
            canvas.create_text(cx, cy + 12, text="Run scan to index", fill=MUTED, font=("Segoe UI", 9))

    def _on_donut_motion(self, event):
        if not self.donut_segments or not self.donut_hover_label:
            return
        cx, cy = 140, 140
        dx, dy = event.x - cx, event.y - cy
        dist = math.hypot(dx, dy)

        # Check if cursor is on the donut ring (radius 75 to 135)
        if 75 <= dist <= 135:
            # Convert cartesian (dx, dy) to Tkinter angle in degrees
            angle = -math.degrees(math.atan2(dy, dx))
            # Normalize to match Tkinter arc start (-90 is top)
            for seg in self.donut_segments:
                start = seg["start"] % 360
                end = (start + seg["extent"]) % 360
                norm_angle = angle % 360

                matched = False
                if start < end:
                    matched = start <= norm_angle <= end
                else:
                    matched = norm_angle >= start or norm_angle <= end

                if matched:
                    self.donut_hover_label.configure(
                        text=f"● {seg['label']}: {format_bytes(seg['size'])} ({seg['pct']:.1f}% of scanned files · {seg['count']:,} items)",
                        text_color=seg["color"],
                    )
                    return
        self.donut_hover_label.configure(text="Hover over chart slices to inspect category details.", text_color=MUTED)

    def _on_donut_leave(self, _event):
        if self.donut_hover_label:
            self.donut_hover_label.configure(text="Hover over chart slices to inspect category details.", text_color=MUTED)

    def _render_treemap_blocks(self, host: ctk.CTkFrame, result: ScanResult | None):
        for child in host.winfo_children():
            child.destroy()
        if not result or not result.type_summary:
            label(host, "Run a scan to generate a proportional treemap", 11, MUTED).place(relx=0.5, rely=0.5, anchor="center")
            return

        host.update_idletasks()
        width = host.winfo_width()
        height = host.winfo_height()
        if width <= 10 or height <= 10:
            host.after(100, lambda h=host, r=result: self._render_treemap_blocks(h, r))
            return

        items = [(extension, size) for extension, size, _count in result.type_summary[:12]]
        rects = layout(items, width, height)

        for index, rect in enumerate(rects):
            rel_x = min(0.999, max(0.001, (rect.x + 2) / width))
            rel_y = min(0.999, max(0.001, (rect.y + 2) / height))
            rel_w = min(1.0 - rel_x, max(0.002, (rect.width - 4) / width))
            rel_h = min(1.0 - rel_y, max(0.002, (rect.height - 4) / height))

            color = CHART_COLORS[index % len(CHART_COLORS)]
            block = ctk.CTkFrame(host, width=1, height=1, fg_color=color, corner_radius=4)
            block.place(relx=rel_x, rely=rel_y, relwidth=rel_w, relheight=rel_h)

            if rect.width > 75 and rect.height > 34:
                pct = (rect.value / max(1, result.bytes_total)) * 100
                txt = f".{rect.label}\n{format_bytes(rect.value)} ({pct:.0f}%)"
                label(block, txt, 9, "#FFFFFF", "bold", justify="left").pack(anchor="nw", padx=6, pady=5)

    # -------------------------------------------------------------------------
    # 4. DISK ANALYZER PAGE
    # -------------------------------------------------------------------------
    def page_analyzer(self):
        card = Card(self.content)
        card.pack(fill="both", expand=True, padx=5)

        # Header
        top_hdr = ctk.CTkFrame(card, fg_color="transparent")
        top_hdr.pack(fill="x", padx=16, pady=(14, 10))
        SectionTitle(
            top_hdr,
            "Disk Analyzer",
            "Refresh",
            lambda: self.show_page("analyzer"),
            subtitle="Interactive folder explorer, size distribution, and storage treemap",
        ).pack(side="left", fill="x", expand=True)

        if not self.result:
            label(card, "Run a Quick or Full Scan to populate storage breakdown data and explore folders.", 12, MUTED).pack(anchor="w", padx=20, pady=30)
            return

        # Summary Metrics
        meta_row = ctk.CTkFrame(card, fg_color=ELEVATED, corner_radius=6)
        meta_row.pack(fill="x", padx=16, pady=(0, 10))
        label(meta_row, f"Target: {self.result.target}", 10, TEXT, "bold").pack(side="left", padx=14, pady=8)
        label(meta_row, f"Mode: {self.result.mode}", 10, GOLD).pack(side="left", padx=10)
        Badge(meta_row, self.result.coverage_badge, color=WARNING if self.result.is_partial else SUCCESS).pack(side="left", padx=6)
        label(meta_row, f"Files: {len(self.result.files):,}", 10, SECONDARY).pack(side="left", padx=12)
        label(meta_row, f"Folders: {self.result.folders:,}", 10, SECONDARY).pack(side="left", padx=12)
        if self.result.errors:
            label(meta_row, f"Errors: {len(self.result.errors):,}", 10, WARNING).pack(side="left", padx=12)
        label(meta_row, f"Total Indexed: {format_bytes(self.result.bytes_total)}", 10, BRIGHT_GOLD, "bold").pack(side="right", padx=14)

        if self.result.is_partial:
            part_bar = ctk.CTkFrame(card, fg_color="#2A2315", corner_radius=6)
            part_bar.pack(fill="x", padx=16, pady=(0, 10))
            Badge(part_bar, "PARTIAL SCAN NOTICE", color=WARNING).pack(side="left", padx=10, pady=8)
            label(
                part_bar,
                "Quick Scan indexes up to 100,000 files for high-speed triage. The folder sizes, file counts, and category proportions shown below reflect this sample and may not represent the entire drive. Run a Full Scan for comprehensive disk-wide coverage.",
                10,
                WARNING,
                wraplength=800,
                justify="left",
            ).pack(side="left", padx=4, pady=8)

        # Check if FolderTree is ready or still being computed in background
        cache_key = (self.result.target, self.result.duration, len(self.result.files))
        if self.folder_tree is None or self.folder_tree_cache_id != cache_key:
            self._start_folder_tree_build(cache_key)
            self._render_analyzer_loading(card)
            return

        # View Mode Toggle (Folder Explorer vs Treemap)
        switch_frame = ctk.CTkFrame(card, fg_color="transparent")
        switch_frame.pack(fill="x", padx=16, pady=(0, 10))

        is_exp = (self.analyzer_view_mode == "explorer")
        exp_btn = ctk.CTkButton(
            switch_frame,
            text="📁 Interactive Folder Explorer",
            fg_color=GOLD_BG if is_exp else ELEVATED,
            text_color=BRIGHT_GOLD if is_exp else SECONDARY,
            border_color=BORDER_ACCENT if is_exp else BORDER,
            border_width=1,
            hover_color=CARD_HOVER,
            height=28,
            command=lambda: self._set_analyzer_view("explorer"),
        )
        exp_btn.pack(side="left", padx=(0, 8))

        tree_btn = ctk.CTkButton(
            switch_frame,
            text="🗺 Proportional Storage Treemap",
            fg_color=ELEVATED if is_exp else GOLD_BG,
            text_color=SECONDARY if is_exp else BRIGHT_GOLD,
            border_color=BORDER if is_exp else BORDER_ACCENT,
            border_width=1,
            hover_color=CARD_HOVER,
            height=28,
            command=lambda: self._set_analyzer_view("treemap"),
        )
        tree_btn.pack(side="left")

        if self.analyzer_view_mode == "treemap":
            self._render_analyzer_treemap_view(card)
        else:
            self._render_analyzer_explorer_view(card)

    def _render_analyzer_loading(self, parent):
        loading_box = Card(parent, fg_color="#12161D", border_color=BORDER, border_width=1, corner_radius=6)
        loading_box.pack(fill="x", padx=16, pady=30)
        label(loading_box, "✦ Aggregating Storage Hierarchy", 15, BRIGHT_GOLD, "bold").pack(anchor="w", padx=20, pady=(18, 4))
        label(
            loading_box,
            "Processing indexed files into a navigable directory tree in the background. The user interface remains responsive.",
            11,
            SECONDARY,
        ).pack(anchor="w", padx=20, pady=(0, 14))
        p_bar = ctk.CTkProgressBar(loading_box, mode="indeterminate", width=360, height=8, progress_color=GOLD)
        p_bar.pack(anchor="w", padx=20, pady=(0, 20))
        p_bar.start()

    def _start_folder_tree_build(self, cache_key: tuple):
        if self.folder_tree_building:
            return
        self.folder_tree_building = True
        self.folder_tree_job_id += 1
        job_id = self.folder_tree_job_id
        target_result = self.result
        if not target_result:
            self.folder_tree_building = False
            return

        def worker():
            try:
                tree = FolderTree.build_from_scan(target_result)
                self.analyzer_queue.put(("ready", job_id, cache_key, tree, None))
            except Exception as exc:
                self.analyzer_queue.put(("error", job_id, cache_key, None, str(exc)))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _on_folder_tree_ready(self, job_id: int, cache_key: tuple, tree: FolderTree | None, error: str | None):
        if job_id != self.folder_tree_job_id:
            return
        self.folder_tree_building = False
        if error:
            self.status.configure(text=f"Analyzer aggregation error: {error}", text_color=ERROR)
            return
        self.folder_tree = tree
        self.folder_tree_cache_id = cache_key
        if self.page == "analyzer":
            self.show_page("analyzer")

    def _render_analyzer_explorer_view(self, parent):
        # 1. Navigation & Breadcrumb Toolbar
        nav_toolbar = ctk.CTkFrame(parent, fg_color=ELEVATED, corner_radius=6)
        nav_toolbar.pack(fill="x", padx=16, pady=(0, 8))

        # Left: Breadcrumb
        left_box = ctk.CTkFrame(nav_toolbar, fg_color="transparent")
        left_box.pack(side="left", fill="x", expand=True, padx=12, pady=6)
        label(left_box, "LOCATION:", 9, MUTED, "bold").pack(side="left", padx=(0, 6))
        self.analyzer_breadcrumb = label(left_box, f"📁 {self.folder_tree.root_path}", 10, TEXT, "bold")
        self.analyzer_breadcrumb.pack(side="left")

        # Right: Action buttons
        button(nav_toolbar, "⬆ Up", self._navigate_analyzer_up, False, 65, 26).pack(side="left", padx=4)
        self.btn_expand_all = button(nav_toolbar, "⊞ Expand All", self._expand_all_analyzer, False, 95, 26)
        self.btn_expand_all.pack(side="left", padx=4)
        button(nav_toolbar, "⊟ Collapse All", self._collapse_all_analyzer, False, 100, 26).pack(side="left", padx=4)
        button(nav_toolbar, "⟳ Reset View", self._reset_analyzer_filters, False, 90, 26).pack(side="left", padx=(4, 12))

        # 2. Search & Filter Bar
        filter_bar = ctk.CTkFrame(parent, fg_color="#12161D", border_color=BORDER, border_width=1, corner_radius=6)
        filter_bar.pack(fill="x", padx=16, pady=(0, 10))

        label(filter_bar, "FILTERS:", 9, GOLD, "bold").pack(side="left", padx=(12, 8), pady=8)

        # Search Entry with debounce
        self.analyzer_search_entry = ctk.CTkEntry(filter_bar, placeholder_text="Search folder or file name...", width=230, height=28)
        if self.analyzer_search_query:
            self.analyzer_search_entry.insert(0, self.analyzer_search_query)
        self.analyzer_search_entry.pack(side="left", padx=(0, 6))
        self.analyzer_search_entry.bind("<KeyRelease>", self._on_search_key)
        self.analyzer_search_entry.bind("<Return>", lambda e: self._apply_analyzer_filters(immediate=True))
        self.analyzer_search_entry = ctk.CTkEntry(filter_bar, placeholder_text="Search folder or file name...", width=230, height=28)
        if self.analyzer_search_query:
            self.analyzer_search_entry.insert(0, self.analyzer_search_query)
        self.analyzer_search_entry.pack(side="left", padx=(0, 6))
        self.analyzer_search_entry.bind("<Return>", lambda e: self._apply_analyzer_filters())

        button(filter_bar, "Search", self._apply_analyzer_filters, True, 70, 28).pack(side="left", padx=(0, 10))

        # Size dropdown
        label(filter_bar, "Min Size:", 10, SECONDARY).pack(side="left", padx=(4, 4))
        size_opts = ["All Sizes", ">= 1 MB", ">= 10 MB", ">= 100 MB", ">= 1 GB"]
        self.analyzer_min_size_combo = ctk.CTkComboBox(filter_bar, values=size_opts, width=120, height=28, command=lambda _: self._apply_analyzer_filters())
        size_map_rev = {0: "All Sizes", 1024 * 1024: ">= 1 MB", 10 * 1024 * 1024: ">= 10 MB", 100 * 1024 * 1024: ">= 100 MB", 1024 * 1024 * 1024: ">= 1 GB"}
        self.analyzer_min_size_combo.set(size_map_rev.get(self.analyzer_min_size, "All Sizes"))
        self.analyzer_min_size_combo.pack(side="left", padx=(0, 10))

        # Ext dropdown
        label(filter_bar, "File Type:", 10, SECONDARY).pack(side="left", padx=(4, 4))
        ext_opts = ["All Types"] + [f".{ext}" for ext in self.folder_tree.available_extensions[:30]]
        self.analyzer_ext_combo = ctk.CTkComboBox(filter_bar, values=ext_opts, width=110, height=28, command=lambda _: self._apply_analyzer_filters())
        self.analyzer_ext_combo.set(f".{self.analyzer_ext_filter}" if self.analyzer_ext_filter != "All" else "All Types")
        self.analyzer_ext_combo.pack(side="left", padx=(0, 10))

        # Reset button
        button(filter_bar, "Reset Filters", self._reset_analyzer_filters, False, 95, 28).pack(side="left", padx=4)

        # 3. Main Split View: Left (Treeview) and Right (Details Panel)
        body = ctk.CTkFrame(parent, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        body.grid_columnconfigure(0, weight=6)
        body.grid_columnconfigure(1, weight=4)
        body.grid_rowconfigure(0, weight=1)

        # Left Column: Treeview Host
        tree_card = ctk.CTkFrame(body, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=6)
        tree_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        # Header over treeview
        tree_hdr = ctk.CTkFrame(tree_card, fg_color="transparent")
        tree_hdr.pack(fill="x", padx=12, pady=(10, 6))
        label(tree_hdr, "FOLDER DIRECTORY HIERARCHY", 9, MUTED, "bold").pack(side="left")
        self.tree_status_lbl = label(tree_hdr, f"Click headings to sort (Current: {self.analyzer_sort_column.title()})", 9, MUTED)
        self.tree_status_lbl.pack(side="right")

        tree_inner = ctk.CTkFrame(tree_card, fg_color="transparent")
        tree_inner.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        columns = ("size", "files", "pct")
        self.analyzer_treeview = ttk.Treeview(tree_inner, columns=columns, selectmode="browse")

        # Configure columns & sortable headings
        sort_indicator = " ▼" if self.analyzer_sort_reverse else " ▲"
        name_title = "Folder Name" + (sort_indicator if self.analyzer_sort_column == "name" else "")
        size_title = "Size" + (sort_indicator if self.analyzer_sort_column == "size" else "")
        files_title = "Files" + (sort_indicator if self.analyzer_sort_column == "files" else "")
        pct_title = "Share" + (sort_indicator if self.analyzer_sort_column == "pct" else "")

        self.analyzer_treeview.heading("#0", text=name_title, anchor="w", command=lambda: self._sort_analyzer_by("name"))
        self.analyzer_treeview.heading("size", text=size_title, anchor="e", command=lambda: self._sort_analyzer_by("size"))
        self.analyzer_treeview.heading("files", text=files_title, anchor="e", command=lambda: self._sort_analyzer_by("files"))
        self.analyzer_treeview.heading("pct", text=pct_title, anchor="e", command=lambda: self._sort_analyzer_by("pct"))

        self.analyzer_treeview.column("#0", width=280, minwidth=180, stretch=True)
        self.analyzer_treeview.column("size", width=95, minwidth=75, anchor="e", stretch=False)
        self.analyzer_treeview.column("files", width=95, minwidth=75, anchor="e", stretch=False)
        self.analyzer_treeview.column("pct", width=75, minwidth=60, anchor="e", stretch=False)

        tree_scroll = ctk.CTkScrollbar(tree_inner, orientation="vertical", command=self.analyzer_treeview.yview)
        self.analyzer_treeview.configure(yscrollcommand=tree_scroll.set)

        self.analyzer_treeview.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        # Bind events
        self.analyzer_treeview.bind("<<TreeviewSelect>>", self._on_analyzer_select)
        self.analyzer_treeview.bind("<<TreeviewOpen>>", self._on_analyzer_open)
        self.analyzer_treeview.bind("<Double-1>", self._on_analyzer_double_click)

        # Right Column: Details Scrollable Card
        self.analyzer_details_frame = ctk.CTkScrollableFrame(body, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=6)
        self.analyzer_details_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        # Initial populate
        self._refresh_analyzer_tree()

    def _render_analyzer_treemap_view(self, parent):
        label(parent, "PROPORTIONAL STORAGE TREEMAP", 10, MUTED, "bold").pack(anchor="w", padx=16, pady=(8, 4))
        treemap_host = ctk.CTkFrame(parent, fg_color="#0E1217", border_color=BORDER, border_width=1, corner_radius=6, height=320)
        treemap_host.pack(fill="x", padx=16, pady=(0, 16))
        treemap_host.pack_propagate(False)
        treemap_host.after(100, lambda h=treemap_host, r=self.result: self._render_treemap_blocks(h, r))

        label(parent, "FILE TYPE OCCUPATION TABLE", 10, MUTED, "bold").pack(anchor="w", padx=16, pady=(8, 4))
        tree_box = ctk.CTkFrame(parent, fg_color=ELEVATED, corner_radius=6)
        tree_box.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        tree = tk.Text(tree_box, bg=ELEVATED, fg=TEXT, insertbackground=GOLD, height=12, relief="flat", font=("Consolas", 10))
        tree.pack(fill="both", expand=True, padx=12, pady=10)
        tree.insert("end", f"{'EXTENSION':<16} {'TOTAL SIZE':>14}   {'FILE COUNT':>12}   {'SHARE OF INDEXED':>18}\n")
        tree.insert("end", "-" * 66 + "\n")
        total_b = max(1, self.result.bytes_total)
        for ext, size, count in self.result.type_summary[:35]:
            pct = size / total_b * 100
            tree.insert("end", f".{ext:<15} {format_bytes(size):>14}   {count:>12,} files   {pct:>17.1f}%\n")
        tree.configure(state="disabled")

    def _update_folder_details(self, node: FolderNode):
        if not self.analyzer_details_frame:
            return

        for child in self.analyzer_details_frame.winfo_children():
            child.destroy()

        # Update breadcrumb label
        if self.analyzer_breadcrumb:
            bc_text = node.path
            if len(bc_text) > 75:
                bc_text = bc_text[:35] + " … " + bc_text[-35:]
            self.analyzer_breadcrumb.configure(text=f"📁 {bc_text}")

        # Top Header & Actions
        hdr = ctk.CTkFrame(self.analyzer_details_frame, fg_color="transparent")
        hdr.pack(fill="x", padx=12, pady=(10, 6))
        label(hdr, node.name, 15, TEXT, "bold").pack(anchor="w")

        path_row = ctk.CTkFrame(self.analyzer_details_frame, fg_color=ELEVATED, corner_radius=4)
        path_row.pack(fill="x", padx=12, pady=(0, 10))
        path_lbl = label(path_row, node.path, 9, SECONDARY, wraplength=380, justify="left")
        path_lbl.pack(side="left", padx=8, pady=6)

        btn_box = ctk.CTkFrame(self.analyzer_details_frame, fg_color="transparent")
        btn_box.pack(fill="x", padx=12, pady=(0, 12))
        button(btn_box, "Copy Path", lambda p=node.path: self._copy_to_clipboard(p), False, 85, 26).pack(side="left", padx=(0, 6))
        button(btn_box, "Open Folder", lambda p=node.path: self._open_folder_in_os(p), False, 95, 26).pack(side="left")

        # 4 Metric Cards in 2x2 grid
        grid = ctk.CTkFrame(self.analyzer_details_frame, fg_color="transparent")
        grid.pack(fill="x", padx=12, pady=(0, 14))
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        # Card 1: Total Size
        c1 = ctk.CTkFrame(grid, fg_color=ELEVATED, corner_radius=6)
        c1.grid(row=0, column=0, sticky="nsew", padx=3, pady=3)
        label(c1, "TOTAL SIZE", 9, MUTED, "bold").pack(anchor="w", padx=10, pady=(8, 2))
        label(c1, format_bytes(node.size), 14, BRIGHT_GOLD, "bold").pack(anchor="w", padx=10)
        label(c1, f"{format_bytes(node.direct_size)} direct", 9, SECONDARY).pack(anchor="w", padx=10, pady=(1, 8))

        # Card 2: Files Count
        c2 = ctk.CTkFrame(grid, fg_color=ELEVATED, corner_radius=6)
        c2.grid(row=0, column=1, sticky="nsew", padx=3, pady=3)
        label(c2, "FILES COUNT", 9, MUTED, "bold").pack(anchor="w", padx=10, pady=(8, 2))
        label(c2, f"{node.file_count:,}", 14, TEXT, "bold").pack(anchor="w", padx=10)
        label(c2, f"{node.direct_file_count:,} direct files", 9, SECONDARY).pack(anchor="w", padx=10, pady=(1, 8))

        # Card 3: Subfolders
        c3 = ctk.CTkFrame(grid, fg_color=ELEVATED, corner_radius=6)
        c3.grid(row=1, column=0, sticky="nsew", padx=3, pady=3)
        label(c3, "SUBFOLDERS", 9, MUTED, "bold").pack(anchor="w", padx=10, pady=(8, 2))
        label(c3, f"{node.subfolder_count:,}", 14, TEXT, "bold").pack(anchor="w", padx=10)
        label(c3, "immediate child dirs", 9, SECONDARY).pack(anchor="w", padx=10, pady=(1, 8))

        # Card 4: Share of Scanned Content
        c4 = ctk.CTkFrame(grid, fg_color=ELEVATED, corner_radius=6)
        c4.grid(row=1, column=1, sticky="nsew", padx=3, pady=3)
        label(c4, "TOTAL SHARE", 9, MUTED, "bold").pack(anchor="w", padx=10, pady=(8, 2))
        label(c4, f"{node.pct_of_total:.1f}%", 14, GOLD, "bold").pack(anchor="w", padx=10)
        label(c4, f"of {format_bytes(self.folder_tree.total_bytes)}", 9, SECONDARY).pack(anchor="w", padx=10, pady=(1, 8))

        # Top 5 Largest Files in this folder
        SectionTitle(self.analyzer_details_frame, "Top 5 Largest Files", subtitle="Heaviest files in this directory subtree").pack(
            fill="x", padx=12, pady=(8, 6)
        )

        if node.largest_files:
            head = ctk.CTkFrame(self.analyzer_details_frame, fg_color=ELEVATED, height=24, corner_radius=4)
            head.pack(fill="x", padx=12, pady=(0, 4))
            label(head, "RANK", 8, MUTED, "bold").pack(side="left", padx=(8, 6))
            label(head, "FILE NAME", 8, MUTED, "bold").pack(side="left", padx=6)
            label(head, "SIZE", 8, MUTED, "bold").pack(side="right", padx=(6, 12))

            for idx, f in enumerate(node.largest_files[:5], 1):
                row = ctk.CTkFrame(self.analyzer_details_frame, fg_color="transparent")
                row.pack(fill="x", padx=12, pady=2)
                label(row, f"#{idx:02d}", 9, GOLD, "bold").pack(side="left", padx=(8, 8))
                Badge(row, f.extension.upper()[:5]).pack(side="left", padx=(0, 6))
                f_name = f.name if len(f.name) < 26 else f.name[:14] + "…" + f.name[-10:]
                label(row, f_name, 10, TEXT).pack(side="left")
                label(row, format_bytes(f.size), 10, BRIGHT_GOLD, "bold").pack(side="right", padx=(6, 10))
        else:
            label(self.analyzer_details_frame, "No files found in this folder.", 10, MUTED).pack(anchor="w", padx=14, pady=6)

        # File-Type Distribution
        SectionTitle(self.analyzer_details_frame, "File-Type Distribution", subtitle="Storage categories in this subtree").pack(
            fill="x", padx=12, pady=(14, 6)
        )

        if node.type_summary:
            total_node_bytes = max(1, node.size)
            for idx, (ext, size, count) in enumerate(node.type_summary[:6]):
                t_row = ctk.CTkFrame(self.analyzer_details_frame, fg_color="transparent")
                t_row.pack(fill="x", padx=12, pady=2)
                color = CHART_COLORS[idx % len(CHART_COLORS)]
                label(t_row, "●", 11, color).pack(side="left", padx=(6, 6))
                label(t_row, f".{ext:<8}", 10, TEXT, "bold").pack(side="left")
                pct = (size / total_node_bytes) * 100.0
                label(t_row, f"{format_bytes(size)}  ({pct:.1f}%)", 9, SECONDARY).pack(side="right", padx=10)
                label(t_row, f"{count:,} files", 9, MUTED).pack(side="right", padx=8)
        else:
            label(self.analyzer_details_frame, "No category distribution data.", 10, MUTED).pack(anchor="w", padx=14, pady=6)

        ctk.CTkFrame(self.analyzer_details_frame, height=12, fg_color="transparent").pack()

    def _copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.configure(text=f"Copied to clipboard: {text}", text_color=SUCCESS)

    def _open_folder_in_os(self, path: str):
        if os.path.exists(path):
            try:
                os.startfile(path)
            except Exception as exc:
                messagebox.showerror("Cannot open folder", str(exc))
        else:
            messagebox.showwarning("Folder not found", f"The directory does not exist on disk:\n{path}")

    def _set_analyzer_view(self, mode: str):
        self.analyzer_view_mode = mode
        self.show_page("analyzer")

    def _on_search_key(self, event=None):
        if self._search_debounce_timer:
            self.after_cancel(self._search_debounce_timer)
        self._search_debounce_timer = self.after(350, lambda: self._apply_analyzer_filters(immediate=True))

    def _apply_analyzer_filters(self, immediate: bool = False):
        if self._search_debounce_timer:
            self.after_cancel(self._search_debounce_timer)
            self._search_debounce_timer = None
        if not self.analyzer_search_entry or not self.analyzer_min_size_combo or not self.analyzer_ext_combo:
            return
        self.analyzer_search_query = self.analyzer_search_entry.get().strip()
        size_str = self.analyzer_min_size_combo.get()
        size_map = {
            ">= 1 MB": 1024 * 1024,
            ">= 10 MB": 10 * 1024 * 1024,
            ">= 100 MB": 100 * 1024 * 1024,
            ">= 1 GB": 1024 * 1024 * 1024,
        }
        self.analyzer_min_size = size_map.get(size_str, 0)
        ext_str = self.analyzer_ext_combo.get()
        self.analyzer_ext_filter = ext_str.lstrip(".") if ext_str != "All Types" else "All"
        self._refresh_analyzer_tree()

    def _reset_analyzer_filters(self):
        if self._search_debounce_timer:
            self.after_cancel(self._search_debounce_timer)
            self._search_debounce_timer = None
        self.analyzer_search_query = ""
        self.analyzer_min_size = 0
        self.analyzer_ext_filter = "All"
        if self.analyzer_search_entry:
            self.analyzer_search_entry.delete(0, "end")
        if self.analyzer_min_size_combo:
            self.analyzer_min_size_combo.set("All Sizes")
        if self.analyzer_ext_combo:
            self.analyzer_ext_combo.set("All Types")
        self._refresh_analyzer_tree()

    def _sort_analyzer_by(self, col: str):
        if self.analyzer_sort_column == col:
            self.analyzer_sort_reverse = not self.analyzer_sort_reverse
        else:
            self.analyzer_sort_column = col
            self.analyzer_sort_reverse = True if col in ("size", "files", "pct") else False
        self._refresh_analyzer_tree()

    def _navigate_analyzer_up(self):
        if not self.analyzer_treeview or not self.folder_tree:
            return
        selected = self.analyzer_treeview.selection()
        if not selected:
            return
        node = self.folder_tree.get_node(selected[0])
        if node and node.parent_path and self.analyzer_treeview.exists(node.parent_path):
            self.analyzer_treeview.see(node.parent_path)
            self.analyzer_treeview.selection_set(node.parent_path)
            self.analyzer_treeview.focus(node.parent_path)
            self._select_folder_path(node.parent_path)

    def _expand_all_analyzer(self):
        if not self.analyzer_treeview or not self.folder_tree:
            return
        self._expand_cancelled = False
        self._expand_in_progress = True
        if self.btn_expand_all:
            self.btn_expand_all.configure(text="⏹ Stop", command=self._cancel_expand_analyzer)

        queue = [(root_id, 0) for root_id in self.analyzer_treeview.get_children()]

        def _step_expand():
            if self._expand_cancelled or not queue or not self.analyzer_treeview:
                self._expand_in_progress = False
                if self.btn_expand_all:
                    self.btn_expand_all.configure(text="⊞ Expand All", command=self._expand_all_analyzer)
                return

            for _ in range(10):
                if not queue:
                    break
                item_id, depth = queue.pop(0)
                if not self.analyzer_treeview.exists(item_id):
                    continue
                self._load_subfolders(item_id)
                self.analyzer_treeview.item(item_id, open=True)
                if depth < 2:
                    for child in self.analyzer_treeview.get_children(item_id):
                        if self.analyzer_treeview.item(child, "text") != "Loading...":
                            queue.append((child, depth + 1))

            if queue and not self._expand_cancelled:
                self.after(10, _step_expand)
            else:
                self._expand_in_progress = False
                if self.btn_expand_all:
                    self.btn_expand_all.configure(text="⊞ Expand All", command=self._expand_all_analyzer)

        _step_expand()

    def _cancel_expand_analyzer(self):
        self._expand_cancelled = True

    def _collapse_all_analyzer(self):
        self._cancel_expand_analyzer()
        if not self.analyzer_treeview:
            return
        for root_id in self.analyzer_treeview.get_children():
            for child in self.analyzer_treeview.get_children(root_id):
                self.analyzer_treeview.item(child, open=False)

    def _on_analyzer_open(self, event=None):
        if not self.analyzer_treeview:
            return
        item = self.analyzer_treeview.focus()
        if item:
            self._load_subfolders(item)

    def _on_analyzer_select(self, event=None):
        if not self.analyzer_treeview:
            return
        selected = self.analyzer_treeview.selection()
        if not selected:
            return
        self._select_folder_path(selected[0])

    def _on_analyzer_double_click(self, event):
        if not self.analyzer_treeview:
            return
        item = self.analyzer_treeview.identify_row(event.y)
        if not item:
            return
        is_open = bool(self.analyzer_treeview.item(item, "open"))
        if not is_open:
            self._load_subfolders(item)
        self.analyzer_treeview.item(item, open=not is_open)

    def _load_subfolders(self, item_id: str, allowed: set[str] | None = None):
        if not self.analyzer_treeview or not self.folder_tree:
            return
        children = self.analyzer_treeview.get_children(item_id)
        if len(children) == 1 and self.analyzer_treeview.item(children[0], "text") == "Loading...":
            self.analyzer_treeview.delete(children[0])
            self._populate_folder_children(item_id, allowed=allowed)

    def _select_folder_path(self, path: str):
        if not self.folder_tree:
            return
        node = self.folder_tree.get_node(path)
        if node:
            self.selected_folder_node = node
            self._update_folder_details(node)

    def _refresh_analyzer_tree(self):
        if not self.folder_tree or not self.analyzer_treeview:
            return
        self.analyzer_treeview.delete(*self.analyzer_treeview.get_children())

        is_filtered = bool(self.analyzer_search_query or self.analyzer_min_size > 0 or (self.analyzer_ext_filter and self.analyzer_ext_filter != "All"))
        allowed = None
        if is_filtered:
            allowed = self.folder_tree.filter_nodes(
                query=self.analyzer_search_query,
                min_size=self.analyzer_min_size,
                extension=self.analyzer_ext_filter,
            )

        root_node = self.folder_tree.get_node(self.folder_tree.root_path)
        if not root_node:
            return

        root_id = root_node.path
        self.analyzer_treeview.insert(
            "",
            "end",
            iid=root_id,
            text="📁 " + root_node.name,
            values=(format_bytes(root_node.size), f"{root_node.file_count:,} files", f"{root_node.pct_of_total:.1f}%"),
            open=True,
        )

        self._populate_folder_children(root_id, allowed=allowed)

        if is_filtered and allowed:
            for p in self.analyzer_treeview.get_children(root_id):
                if p in allowed:
                    self._load_subfolders(p, allowed=allowed)
                    self.analyzer_treeview.item(p, open=True)

        self.analyzer_treeview.selection_set(root_id)
        self._select_folder_path(root_id)

    def _populate_folder_children(self, parent_path: str, allowed: set[str] | None = None):
        if not self.folder_tree or not self.analyzer_treeview:
            return
        children = self.folder_tree.get_children(
            parent_path,
            sort_by=self.analyzer_sort_column,
            reverse=self.analyzer_sort_reverse,
        )
        if allowed is not None:
            filtered_children = [c for c in children if c.path in allowed]
        else:
            filtered_children = children

        batch_size = 40

        def _insert_batch(start_idx: int):
            if not self.analyzer_treeview or not self.analyzer_treeview.exists(parent_path):
                return
            end_idx = min(start_idx + batch_size, len(filtered_children))
            for i in range(start_idx, end_idx):
                child = filtered_children[i]
                if self.analyzer_treeview.exists(child.path):
                    continue
                self.analyzer_treeview.insert(
                    parent_path,
                    "end",
                    iid=child.path,
                    text="📁 " + child.name,
                    values=(format_bytes(child.size), f"{child.file_count:,} files", f"{child.pct_of_total:.1f}%"),
                    open=False,
                )
                if child.subfolder_paths:
                    if allowed is None or any(p in allowed for p in child.subfolder_paths):
                        self.analyzer_treeview.insert(child.path, "end", text="Loading...")

            if end_idx < len(filtered_children):
                self.after(5, lambda: _insert_batch(end_idx))

        _insert_batch(0)

    # -------------------------------------------------------------------------
    # 5. LARGE FILES PAGE
    # -------------------------------------------------------------------------
    def page_large(self):
        card = Card(self.content)
        card.pack(fill="both", expand=True, padx=5)

        # Header with Search & Filter Controls
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=14)
        SectionTitle(top, "Large Files Explorer", subtitle="Filter, sort, and inspect largest storage consumers").pack(side="left")

        controls = ctk.CTkFrame(top, fg_color="transparent")
        controls.pack(side="right")

        # Search Bar
        self.large_search = ctk.CTkEntry(controls, placeholder_text="Search filename…", width=200, height=30)
        self.large_search.pack(side="left", padx=4)
        self.large_search.bind("<KeyRelease>", lambda _e: self._render_large_files())

        # Sort Mode Combobox
        self.sort_combo = ctk.CTkComboBox(
            controls,
            values=["Size (Largest First)", "Size (Smallest First)", "Name (A → Z)", "Type"],
            width=160,
            height=30,
            command=self._on_large_sort_changed,
        )
        self.sort_combo.set(self.large_sort_mode)
        self.sort_combo.pack(side="left", padx=4)

        # Min Size Filter
        self.min_size_combo = ctk.CTkComboBox(
            controls,
            values=["All Sizes", "> 10 MB", "> 50 MB", "> 100 MB", "> 500 MB", "> 1 GB"],
            width=110,
            height=30,
            command=self._on_large_size_filter_changed,
        )
        self.min_size_combo.set(self.large_min_size_filter)
        self.min_size_combo.pack(side="left", padx=4)

        button(controls, "Export CSV", self.export_current, False, 95, 30).pack(side="left", padx=4)

        # Table Header
        tbl_head = ctk.CTkFrame(card, fg_color=ELEVATED, height=30, corner_radius=4)
        tbl_head.pack(fill="x", padx=16, pady=(0, 4))
        label(tbl_head, "RANK", 9, MUTED, "bold").pack(side="left", padx=(14, 10))
        label(tbl_head, "TYPE", 9, MUTED, "bold").pack(side="left", padx=(0, 15))
        label(tbl_head, "FILE NAME", 9, MUTED, "bold").pack(side="left", padx=10)
        label(tbl_head, "ACTION", 9, MUTED, "bold").pack(side="right", padx=(10, 16))
        label(tbl_head, "SIZE", 9, MUTED, "bold").pack(side="right", padx=35)
        label(tbl_head, "FULL PATH", 9, MUTED, "bold").pack(side="right", padx=100)

        # File List Scrollable Container
        self.large_body = ctk.CTkScrollableFrame(card, fg_color="transparent", height=480)
        self.large_body.pack(fill="both", expand=True, padx=12, pady=4)

        # Footer Stats Bar
        self.large_footer = label(card, "0 files displayed", 10, MUTED)
        self.large_footer.pack(anchor="w", padx=18, pady=(6, 12))

        self._render_large_files()

    def _on_large_sort_changed(self, choice):
        self.large_sort_mode = choice
        self._render_large_files()

    def _on_large_size_filter_changed(self, choice):
        self.large_min_size_filter = choice
        self._render_large_files()

    def _render_large_files(self):
        for child in self.large_body.winfo_children():
            child.destroy()

        if not self.result:
            label(self.large_body, "Run a scan first to populate and sort large files.", 11, MUTED).pack(anchor="w", padx=20, pady=25)
            self.large_footer.configure(text="No files indexed yet.")
            return

        query = self.large_search.get().lower() if hasattr(self, "large_search") else ""
        items = [f for f in self.result.files if query in f.name.lower()]

        # Apply Min Size Filter
        min_bytes = 0
        if self.large_min_size_filter == "> 10 MB":
            min_bytes = 10 * 1024 * 1024
        elif self.large_min_size_filter == "> 50 MB":
            min_bytes = 50 * 1024 * 1024
        elif self.large_min_size_filter == "> 100 MB":
            min_bytes = 100 * 1024 * 1024
        elif self.large_min_size_filter == "> 500 MB":
            min_bytes = 500 * 1024 * 1024
        elif self.large_min_size_filter == "> 1 GB":
            min_bytes = 1024 * 1024 * 1024
        if min_bytes > 0:
            items = [f for f in items if f.size >= min_bytes]

        # Apply Sorting
        if self.large_sort_mode == "Size (Largest First)":
            items.sort(key=lambda x: x.size, reverse=True)
        elif self.large_sort_mode == "Size (Smallest First)":
            items.sort(key=lambda x: x.size)
        elif self.large_sort_mode == "Name (A → Z)":
            items.sort(key=lambda x: x.name.lower())
        elif self.large_sort_mode == "Type":
            items.sort(key=lambda x: x.extension.lower())

        displayed = items[:300]
        total_size = sum(f.size for f in displayed)
        self.large_footer.configure(text=f"Showing {len(displayed):,} of {len(items):,} filtered files · Cumulative size: {format_bytes(total_size)}")

        for i, item in enumerate(displayed, 1):
            row = ctk.CTkFrame(self.large_body, fg_color="transparent")
            row.pack(fill="x", pady=2)

            label(row, f"#{i:02d}", 10, GOLD, "bold").pack(side="left", padx=(14, 10))
            Badge(row, item.extension.upper()[:5]).pack(side="left", padx=(0, 10))
            label(row, item.name, 11, TEXT, "bold").pack(side="left", padx=(0, 10))

            button(
                row,
                "Recycle",
                lambda record=item: self.confirm_delete([record], "Send file to Recycle Bin", allowed_roots=[self.target.get()]),
                False,
                72,
                26,
            ).pack(side="right", padx=(8, 12))

            label(row, format_bytes(item.size), 11, BRIGHT_GOLD, "bold").pack(side="right", padx=(20, 25))
            path_str = item.path if len(item.path) < 65 else item.path[:28] + "…" + item.path[-34:]
            label(row, path_str, 10, MUTED).pack(side="right", padx=10)

    def export_current(self):
        if not self.result:
            return
        dest = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if dest:
            export_files(self.result.largest_files, dest)
            self.status.configure(text=f"Exported {dest}", text_color=SUCCESS)

    # -------------------------------------------------------------------------
    # 6. DUPLICATES PAGE
    # -------------------------------------------------------------------------
    def page_duplicates(self):
        card = Card(self.content)
        card.pack(fill="both", expand=True, padx=5)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=14)
        SectionTitle(head, "Exact Duplicate Finder", subtitle="Cryptographically verified bit-for-bit duplicate files").pack(side="left")

        actions = ctk.CTkFrame(head, fg_color="transparent")
        actions.pack(side="right")
        button(actions, "Cancel", self.cancel_duplicate_scan, False, 75).pack(side="left", padx=4)
        button(actions, "⚡ Scan Hashes", self.start_duplicate_scan, True, 115).pack(side="left", padx=4)
        button(actions, "Recycle Selected", self.delete_duplicate_selection, False, 130).pack(side="left", padx=4)

        if not self.result:
            label(card, "Run a scan first. Duplicate detection verifies identical file size and SHA-256 hash.", 11, MUTED).pack(anchor="w", padx=20, pady=25)
            return

        if not self.duplicate_groups:
            label(card, "No duplicate scan executed yet. Click 'Scan Hashes' to verify duplicate candidates.", 11, MUTED).pack(anchor="w", padx=20, pady=25)
            return

        total_reclaimable = sum(reclaimable_bytes(g) for g in self.duplicate_groups)
        stat_bar = ctk.CTkFrame(card, fg_color=ELEVATED, corner_radius=6)
        stat_bar.pack(fill="x", padx=16, pady=(0, 10))
        label(stat_bar, f"Found {len(self.duplicate_groups)} duplicate groups", 11, TEXT, "bold").pack(side="left", padx=14, pady=8)
        label(stat_bar, f"Potential savings: {format_bytes(total_reclaimable)} reclaimable", 11, SUCCESS, "bold").pack(side="right", padx=14)

        self.duplicate_checks = []
        body = ctk.CTkScrollableFrame(card, fg_color="transparent", height=460)
        body.pack(fill="both", expand=True, padx=12, pady=5)

        for group_index, group in enumerate(self.duplicate_groups, 1):
            box = Card(body, fg_color=ELEVATED, border_color=BORDER, border_width=1, corner_radius=6)
            box.pack(fill="x", pady=6)

            box_head = ctk.CTkFrame(box, fg_color="transparent")
            box_head.pack(fill="x", padx=12, pady=(10, 4))
            label(box_head, f"Group #{group_index}: {len(group)} exact copies ({format_bytes(group[0].size)} each)", 11, BRIGHT_GOLD, "bold").pack(side="left")
            label(box_head, f"+{format_bytes(reclaimable_bytes(group))} reclaimable", 10, SUCCESS).pack(side="right")

            for record in group:
                variable = tk.BooleanVar(value=False)
                self.duplicate_checks.append((variable, record))
                chk = ctk.CTkCheckBox(box, text=f"{record.path}  ({format_bytes(record.size)})", variable=variable, text_color=SECONDARY, fg_color=GOLD, hover_color=BRIGHT_GOLD)
                chk.pack(anchor="w", padx=14, pady=4)
            ctk.CTkFrame(box, height=4, fg_color="transparent").pack()

    def start_duplicate_scan(self):
        if not self.result:
            return
        self.duplicate_cancel = __import__("threading").Event()
        self.status.configure(text="Hashing duplicate candidates with multi-threaded SHA-256…", text_color=GOLD)

        def worker():
            try:
                groups = exact_duplicate_groups(
                    self.result.files,
                    cancel_event=self.duplicate_cancel,
                    progress=lambda p: self.duplicate_queue.put(("progress", p.completed, p.total, p.path)),
                )
                self.duplicate_queue.put(("complete", groups))
            except HashCancelled:
                self.duplicate_queue.put(("cancelled",))

        __import__("threading").Thread(target=worker, daemon=True).start()

    def cancel_duplicate_scan(self):
        if self.duplicate_cancel:
            self.duplicate_cancel.set()

    def delete_duplicate_selection(self):
        selected = [record for variable, record in self.duplicate_checks if variable.get()]
        if not selected:
            messagebox.showinfo("Nothing selected", "Select the duplicate copies you want to send to the Recycle Bin. Original copies are never selected automatically.")
            return
        self.confirm_delete(selected, "Send selected duplicate copies to Recycle Bin", allowed_roots=[self.target.get()])

    # -------------------------------------------------------------------------
    # 7. CLEANUP CENTER PAGE
    # -------------------------------------------------------------------------
    def page_cleanup(self):
        card = Card(self.content)
        card.pack(fill="x", expand=False, padx=5)

        SectionTitle(card, "Cleanup Center", subtitle="Safely purge temporary files without risking user data").pack(fill="x", padx=18, pady=(16, 6))

        info_bar = ctk.CTkFrame(card, fg_color=ELEVATED, corner_radius=6)
        info_bar.pack(fill="x", padx=16, pady=8)
        label(info_bar, "🛡 Safe Recycle Bin Guarantee: Files are sent to the Windows Recycle Bin, never permanently deleted.", 10, SUCCESS).pack(side="left", padx=14, pady=8)

        candidates = discover_cleanup_candidates()
        self.cleanup_checks = []

        ctrl_row = ctk.CTkFrame(card, fg_color="transparent")
        ctrl_row.pack(fill="x", padx=16, pady=8)

        if candidates:
            total_cand = sum(item.size for item in candidates)
            label(ctrl_row, f"{len(candidates):,} temporary candidates in %TEMP% · Estimated: {format_bytes(total_cand)}", 11, TEXT, "bold").pack(side="left")
        else:
            label(ctrl_row, "No user-temp files were found in %TEMP%.", 11, MUTED).pack(side="left")

        button(ctrl_row, "Preview / Recycle Selected", self.delete_cleanup_selection, False, 190, 30).pack(side="right")

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", expand=False, padx=12, pady=(0, 14))

        for record in candidates[:200]:
            variable = tk.BooleanVar(value=False)
            self.cleanup_checks.append((variable, record))
            ctk.CTkCheckBox(
                body,
                text=f"{record.path} · {format_bytes(record.size)}",
                variable=variable,
                text_color=SECONDARY,
                fg_color=GOLD,
                hover_color=BRIGHT_GOLD,
            ).pack(anchor="w", padx=10, pady=3)

    def delete_cleanup_selection(self):
        selected = [record for variable, record in getattr(self, "cleanup_checks", []) if variable.get()]
        if not selected:
            messagebox.showinfo("Nothing selected", "Select cleanup candidates to review before sending to the Recycle Bin.")
            return
        allowed = [self.target.get(), tempfile.gettempdir()]
        self.confirm_delete(selected, "Send selected cleanup files to Recycle Bin", allowed_roots=allowed)

    def confirm_delete(self, records: list[FileRecord], title: str, allowed_roots: list[str] | None = None):
        total = sum(record.size for record in records)
        paths = "\n".join(record.path for record in records[:12])
        suffix = "\n…" if len(records) > 12 else ""
        if not messagebox.askyesno(
            title,
            f"The following {len(records)} file(s) will be sent to the Recycle Bin ({format_bytes(total)}):\n\n{paths}{suffix}\n\nContinue?",
            icon="warning",
        ):
            return

        roots = allowed_roots if allowed_roots is not None else [self.target.get(), tempfile.gettempdir()]
        results = delete_selected(records, roots, confirm=True)
        success = sum(item.status == "success" for item in results)
        failed = sum(item.status == "failed" for item in results)
        skipped = sum(item.status == "skipped" for item in results)

        self.status.configure(text=f"Recycle Bin complete · {success} sent · {failed} failed · {skipped} skipped", text_color=SUCCESS if not failed else WARNING)
        messagebox.showinfo("Recycle Bin Result", f"Sent to Recycle Bin: {success}\nFailed: {failed}\nSkipped: {skipped}\nSpace Reclaimed: {format_bytes(sum(item.bytes_removed for item in results))}")

    # -------------------------------------------------------------------------
    # 8. FILE INSIGHTS PAGE
    # -------------------------------------------------------------------------
    def page_insights(self):
        card = Card(self.content)
        card.pack(fill="both", expand=True, padx=5)
        SectionTitle(card, "File Insights & Storage Patterns", subtitle="Deterministic findings from measured scan statistics").pack(fill="x", padx=18, pady=16)

        if not self.result:
            label(card, "Run a Quick or Full Scan to generate automated storage insights.", 11, MUTED).pack(anchor="w", padx=20, pady=25)
            return

        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=8)
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        # Insight 1: Top Category
        top_ext = self.result.type_summary[0] if self.result.type_summary else ("none", 0, 0)
        c1 = Card(grid, fg_color=ELEVATED, border_color=BORDER, border_width=1, corner_radius=6)
        c1.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        label(c1, "TOP STORAGE CONSUMER", 9, MUTED, "bold").pack(anchor="w", padx=14, pady=(12, 4))
        label(c1, f".{top_ext[0].upper()} files", 16, BRIGHT_GOLD, "bold").pack(anchor="w", padx=14)
        pct = (top_ext[1] / max(1, self.result.bytes_total)) * 100
        label(c1, f"{format_bytes(top_ext[1])} across {top_ext[2]:,} files ({pct:.1f}% of indexed content)", 10, SECONDARY).pack(anchor="w", padx=14, pady=(2, 12))

        # Insight 2: Massive Files
        massive = [f for f in self.result.files if f.size >= 1024 * 1024 * 1024]
        c2 = Card(grid, fg_color=ELEVATED, border_color=BORDER, border_width=1, corner_radius=6)
        c2.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        label(c2, "FILES EXCEEDING 1 GB", 9, MUTED, "bold").pack(anchor="w", padx=14, pady=(12, 4))
        label(c2, f"{len(massive):,} files", 16, TEXT, "bold").pack(anchor="w", padx=14)
        massive_bytes = sum(f.size for f in massive)
        label(c2, f"Total space: {format_bytes(massive_bytes)} · Check Large Files explorer to review", 10, SECONDARY).pack(anchor="w", padx=14, pady=(2, 12))

        # Insight 3: Access Errors
        c3 = Card(grid, fg_color=ELEVATED, border_color=BORDER, border_width=1, corner_radius=6)
        c3.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        label(c3, "FILE ACCESS & PERMISSIONS", 9, MUTED, "bold").pack(anchor="w", padx=14, pady=(12, 4))
        label(c3, f"{len(self.result.errors):,} protected items", 16, WARNING if self.result.errors else SUCCESS, "bold").pack(anchor="w", padx=14)
        label(c3, "System folders (e.g. System Volume Information) skipped due to Windows security", 10, SECONDARY).pack(anchor="w", padx=14, pady=(2, 12))

        # Insight 4: Average File Size
        avg_size = self.result.bytes_total / max(1, len(self.result.files))
        c4 = Card(grid, fg_color=ELEVATED, border_color=BORDER, border_width=1, corner_radius=6)
        c4.grid(row=1, column=1, sticky="nsew", padx=6, pady=6)
        label(c4, "AVERAGE FILE METRIC", 9, MUTED, "bold").pack(anchor="w", padx=14, pady=(12, 4))
        label(c4, format_bytes(int(avg_size)), 16, TEXT, "bold").pack(anchor="w", padx=14)
        label(c4, f"Spread across {self.result.folders:,} directories on {self.result.target}", 10, SECONDARY).pack(anchor="w", padx=14, pady=(2, 12))

    # -------------------------------------------------------------------------
    # 9. SCAN HISTORY PAGE
    # -------------------------------------------------------------------------
    def page_history(self):
        card = Card(self.content)
        card.pack(fill="both", expand=True, padx=5)
        SectionTitle(card, "Scan History & Comparisons", subtitle="Inspect previous drive snapshots and calculate storage growth deltas").pack(
            fill="x", padx=18, pady=16
        )

        rows = self.history.recent()
        ids = [str(row[0]) for row in rows]
        if not rows:
            label(card, "No saved scans found in SQLite database yet.", 11, MUTED).pack(anchor="w", padx=20, pady=25)
            return

        controls = ctk.CTkFrame(card, fg_color=ELEVATED, corner_radius=6)
        controls.pack(fill="x", padx=16, pady=(0, 14))
        label(controls, "Compare Snapshots:", 10, TEXT, "bold").pack(side="left", padx=(14, 8), pady=8)

        label(controls, "Older ID:", 10, SECONDARY).pack(side="left", padx=(0, 4))
        self.compare_before = ctk.CTkComboBox(controls, values=ids, width=80, height=28)
        self.compare_before.set(ids[-1])
        self.compare_before.pack(side="left", padx=4)

        label(controls, "→ Newer ID:", 10, SECONDARY).pack(side="left", padx=(8, 4))
        self.compare_after = ctk.CTkComboBox(controls, values=ids, width=80, height=28)
        self.compare_after.set(ids[0])
        self.compare_after.pack(side="left", padx=4)

        button(controls, "Compare", self.run_comparison, True, 85, 28).pack(side="left", padx=8)
        button(controls, "Export Diff CSV", self.export_comparison_view, False, 110, 28).pack(side="left", padx=4)

        # Snapshot rows table
        tbl_head = ctk.CTkFrame(card, fg_color="transparent")
        tbl_head.pack(fill="x", padx=18, pady=(4, 2))
        label(tbl_head, "ID", 9, MUTED, "bold").pack(side="left", padx=(6, 12))
        label(tbl_head, "TIMESTAMP", 9, MUTED, "bold").pack(side="left", padx=10)
        label(tbl_head, "TARGET & MODE", 9, MUTED, "bold").pack(side="left", padx=35)
        label(tbl_head, "COVERAGE", 9, MUTED, "bold").pack(side="right", padx=(10, 16))
        label(tbl_head, "SIZE", 9, MUTED, "bold").pack(side="right", padx=30)
        label(tbl_head, "FILES / DIRS", 9, MUTED, "bold").pack(side="right", padx=55)

        for row in rows[:10]:
            r_box = ctk.CTkFrame(card, fg_color=ELEVATED, corner_radius=4)
            r_box.pack(fill="x", padx=16, pady=2)
            label(r_box, f"#{row[0]}", 10, GOLD, "bold").pack(side="left", padx=(12, 10), pady=6)
            label(r_box, row[1][:19].replace("T", " "), 10, TEXT).pack(side="left", padx=10)

            # Target & Mode badge
            target_frame = ctk.CTkFrame(r_box, fg_color="transparent")
            target_frame.pack(side="left", padx=15)
            label(target_frame, row[2], 10, SECONDARY).pack(side="left", padx=(0, 6))
            is_quick = (row[3] == "Quick Scan")
            mode_badge_text = "QUICK SCAN (PARTIAL)" if is_quick else "FULL SCAN"
            mode_badge_color = WARNING if is_quick else SUCCESS
            Badge(target_frame, mode_badge_text, color=mode_badge_color).pack(side="left")

            # Coverage status on right
            if row[9]:
                cov_text = "FULL COVERAGE"
                cov_color = SUCCESS
            elif is_quick:
                cov_text = "100k CAPPED"
                cov_color = WARNING
            else:
                cov_text = f"ERRORS ({row[8]})"
                cov_color = WARNING
            Badge(r_box, cov_text, color=cov_color).pack(side="right", padx=(10, 16))
            label(r_box, format_bytes(row[7]), 10, BRIGHT_GOLD, "bold").pack(side="right", padx=25)
            label(r_box, f"{row[5]:,} files · {row[6]:,} dirs", 10, SECONDARY).pack(side="right", padx=35)

        if self.compare_view:
            self._render_comparison(card, self.compare_view)

    def run_comparison(self):
        try:
            self.compare_view = self.history.compare(int(self.compare_before.get()), int(self.compare_after.get()))
            self.show_page("history")
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Comparison unavailable", str(exc))

    def export_comparison_view(self):
        if not self.compare_view:
            messagebox.showinfo("No comparison", "Run a comparison first.")
            return
        dest = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if dest:
            export_comparison(self.compare_view, dest)
            self.status.configure(text=f"Exported comparison to {dest}", text_color=SUCCESS)

    def _render_comparison(self, parent, comparison: ScanComparison):
        section = Card(parent, fg_color="#141920", border_color=BORDER_ACCENT, border_width=1, corner_radius=6)
        section.pack(fill="x", padx=16, pady=(14, 10))

        header_row = ctk.CTkFrame(section, fg_color="transparent")
        header_row.pack(fill="x", padx=16, pady=(12, 4))
        label(header_row, "Comparison Delta Results", 12, BRIGHT_GOLD, "bold").pack(side="left")

        # Check for mode incompatibility
        is_incompatible = comparison.warning and "Incompatible scan modes" in comparison.warning
        if is_incompatible:
            Badge(header_row, "INCOMPATIBLE MODES", color=ERROR).pack(side="left", padx=10)
        elif not comparison.compatible:
            Badge(header_row, "PARTIAL COVERAGE", color=WARNING).pack(side="left", padx=10)
        else:
            Badge(header_row, "COMPATIBLE COMPARISON", color=SUCCESS).pack(side="left", padx=10)

        if comparison.warning:
            warn_card = ctk.CTkFrame(section, fg_color="#261A1A" if is_incompatible else "#222115", corner_radius=4)
            warn_card.pack(fill="x", padx=16, pady=6)
            warn_icon = "🛑 " if is_incompatible else "⚠ "
            label(warn_card, warn_icon + comparison.warning, 10, ERROR if is_incompatible else WARNING, wraplength=800, justify="left").pack(anchor="w", padx=12, pady=8)

        delta = comparison.after
        f_diff = delta.files - comparison.before.files
        s_diff = delta.bytes_total - comparison.before.bytes_total
        label(
            section,
            f"Files: {comparison.before.files:,} ({comparison.before.mode}) → {delta.files:,} ({delta.mode}) [{f_diff:+,} files]   |   Size: {format_bytes(comparison.before.bytes_total)} → {format_bytes(delta.bytes_total)} [{s_diff:+,} B]",
            10,
            TEXT,
        ).pack(anchor="w", padx=16, pady=3)

        label(
            section,
            f"New files: {len(comparison.added or []):,} · Removed: {len(comparison.removed or []):,} · Modified sizes: {len(comparison.changed or []):,}",
            10,
            SECONDARY,
        ).pack(anchor="w", padx=16, pady=3)

        for folder, amount in (comparison.folder_growth or [])[:5]:
            label(section, f"Growth · +{format_bytes(amount)} · {folder}", 10, SUCCESS).pack(anchor="w", padx=25, pady=2)
        ctk.CTkFrame(section, height=8, fg_color="transparent").pack()

    # -------------------------------------------------------------------------
    # 10. SETTINGS PAGE
    # -------------------------------------------------------------------------
    def page_settings(self):
        card = Card(self.content)
        card.pack(fill="x", padx=5, pady=5)
        SectionTitle(card, "Settings & Preferences", subtitle="Configure application preferences and scan defaults").pack(fill="x", padx=18, pady=16)

        rows = [
            ("Default Scan Mode", "Preferred scanning depth on application launch", ["Quick Scan (100k files)", "Full Scan (Uncapped)"]),
            ("File Size Display Units", "Choose between decimal (GB = 1,000 MB) or binary (GiB = 1,024 MiB)", ["Decimal (GB)", "Binary (GiB)"]),
            ("Deletion Safety Mode", "Files are sent to Windows Recycle Bin with confirmation", ["Recycle Bin (Send2Trash)", "Strict Revalidation"]),
        ]

        for title, desc, opts in rows:
            r = ctk.CTkFrame(card, fg_color=ELEVATED, corner_radius=6)
            r.pack(fill="x", padx=16, pady=4)
            left = ctk.CTkFrame(r, fg_color="transparent")
            left.pack(side="left", padx=14, pady=10)
            label(left, title, 11, TEXT, "bold").pack(anchor="w")
            label(left, desc, 9, MUTED).pack(anchor="w", pady=(1, 0))

            combo = ctk.CTkComboBox(r, values=opts, width=190, height=28)
            combo.set(opts[0])
            combo.pack(side="right", padx=14)
        ctk.CTkFrame(card, height=12, fg_color="transparent").pack()
