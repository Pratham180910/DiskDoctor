import customtkinter as ctk

BG = "#080A0D"
SIDEBAR = "#090B0F"
SURFACE = "#0D1015"
CARD = "#11151B"
CARD_HOVER = "#161B22"
ELEVATED = "#171B22"
BORDER = "#292A2D"
BORDER_ACCENT = "#3E3B32"
GOLD = "#E8B84D"
BRIGHT_GOLD = "#FFD778"
MUTED_GOLD = "#9D7B38"
GOLD_BG = "#2A2110"
TEXT = "#F5F4F0"
SECONDARY = "#A4A7AF"
MUTED = "#6D737D"
SUCCESS = "#49C99A"
WARNING = "#F2A84B"
ERROR = "#F06464"

# Category palette for charts & treemaps
CHART_COLORS = [
    "#E8B84D",  # Gold
    "#49C99A",  # Mint Green
    "#5D8FE8",  # Sky Blue
    "#E86B38",  # Coral / Amber
    "#9B5DE5",  # Purple
    "#3195CF",  # Cyan
    "#D65A5A",  # Crimson
    "#64748B",  # Slate (Other)
]


def configure() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
