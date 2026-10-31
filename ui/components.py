from __future__ import annotations

import customtkinter as ctk

from .theme import BORDER, CARD, ELEVATED, GOLD, MUTED, SECONDARY, TEXT


class Card(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=8, **kwargs)


class SectionTitle(ctk.CTkFrame):
    def __init__(self, master, title: str, action: str | None = None, command=None):
        super().__init__(master, fg_color="transparent")
        ctk.CTkLabel(self, text=title, text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        if action:
            ctk.CTkButton(self, text=action, width=82, height=26, fg_color="transparent", hover_color=ELEVATED, text_color=GOLD, command=command).pack(side="right")


def label(master, text: str, size: int = 11, color: str = SECONDARY, weight: str = "normal", **kwargs):
    return ctk.CTkLabel(master, text=text, text_color=color, font=ctk.CTkFont(size=size, weight=weight), **kwargs)


def button(master, text: str, command=None, primary: bool = False, width: int = 110, **kwargs):
    return ctk.CTkButton(master, text=text, command=command, width=width, height=32, corner_radius=6, fg_color=GOLD if primary else ELEVATED, hover_color="#F1C968" if primary else "#242A32", text_color="#101114" if primary else TEXT, **kwargs)


def format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    number = float(value)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:.1f} {unit}" if unit != "B" else f"{int(number)} B"
        number /= 1024
    return "0 B"
