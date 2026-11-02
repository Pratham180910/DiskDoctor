from __future__ import annotations

import customtkinter as ctk

from .theme import BORDER, CARD, ELEVATED, GOLD, MUTED, SECONDARY, TEXT


class Card(ctk.CTkFrame):
    def __init__(self, master, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=8, **kwargs):
        super().__init__(master, fg_color=fg_color, border_color=border_color, border_width=border_width, corner_radius=corner_radius, **kwargs)


class StatCard(Card):
    """Refined metric card with title, icon badge, primary value, and metadata subtitle."""
    def __init__(self, master, title: str, value: str, meta: str, icon: str = "", accent_color: str | None = None, **kwargs):
        super().__init__(master, **kwargs)
        top_row = ctk.CTkFrame(self, fg_color="transparent")
        top_row.pack(fill="x", padx=16, pady=(14, 4))
        label(top_row, title.upper(), 9, MUTED, "bold").pack(side="left")
        if icon:
            label(top_row, icon, 12, accent_color or GOLD).pack(side="right")
        label(self, value, 21, TEXT, "bold").pack(anchor="w", padx=16)
        label(self, meta, 10, accent_color or SECONDARY).pack(anchor="w", padx=16, pady=(3, 14))


class Badge(ctk.CTkFrame):
    """Small pill badge for file extensions or statuses."""
    def __init__(self, master, text: str, color: str = GOLD, **kwargs):
        super().__init__(master, fg_color=ELEVATED, border_color=BORDER, border_width=1, corner_radius=4, **kwargs)
        label(self, text, 9, color, "bold").pack(padx=6, pady=2)


class SectionTitle(ctk.CTkFrame):
    def __init__(self, master, title: str, action: str | None = None, command=None, subtitle: str | None = None):
        super().__init__(master, fg_color="transparent")
        left_box = ctk.CTkFrame(self, fg_color="transparent")
        left_box.pack(side="left", fill="y")
        ctk.CTkLabel(left_box, text=title, text_color=TEXT, font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
        if subtitle:
            label(left_box, subtitle, 10, MUTED).pack(anchor="w", pady=(1, 0))
        if action:
            ctk.CTkButton(self, text=action, width=88, height=26, corner_radius=5, fg_color="transparent", hover_color=ELEVATED, text_color=GOLD, font=ctk.CTkFont(size=11), command=command).pack(side="right")


def label(master, text: str, size: int = 11, color: str = SECONDARY, weight: str = "normal", **kwargs):
    return ctk.CTkLabel(master, text=text, text_color=color, font=ctk.CTkFont(size=size, weight=weight), **kwargs)


def button(master, text: str, command=None, primary: bool = False, width: int = 110, height: int = 32, **kwargs):
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        width=width,
        height=height,
        corner_radius=6,
        fg_color=GOLD if primary else ELEVATED,
        hover_color="#F1C968" if primary else "#242A32",
        text_color="#101114" if primary else TEXT,
        font=ctk.CTkFont(size=11, weight="bold" if primary else "normal"),
        **kwargs
    )


def format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    number = float(value)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:.1f} {unit}" if unit != "B" else f"{int(number)} B"
        number /= 1024
    return "0 B"
