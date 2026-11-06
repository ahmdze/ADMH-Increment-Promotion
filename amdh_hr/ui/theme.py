"""الثيمان (فاتح/داكن) وتوليد QSS."""

from __future__ import annotations

from pathlib import Path
from string import Template

from ..config import app_root

DARK = {
    "name": "dark",
    "label": "داكن",
    "bg": "#0B1220",
    "surface": "#111C2E",
    "surface_alt": "#16233A",
    "border": "#22314A",
    "text": "#E6EEF8",
    "muted": "#93A4BC",
    "primary": "#14B8A6",
    "primary_hover": "#0FA396",
    "on_primary": "#04211F",
    "sidebar": "#0E1726",
    "sidebar_text": "#C7D5E8",
    "sidebar_active": "#173249",
    "hover": "#1B2B44",
    "selection": "#1E3A5F",
    "table_header": "#152238",
    "danger": "#F87171",
    "warning": "#FBBF24",
    "success": "#34D399",
}

LIGHT = {
    "name": "light",
    "label": "فاتح",
    "bg": "#EEF2F7",
    "surface": "#FFFFFF",
    "surface_alt": "#F6F8FB",
    "border": "#DCE3EC",
    "text": "#0F172A",
    "muted": "#5B6B81",
    "primary": "#0F766E",
    "primary_hover": "#0D9488",
    "on_primary": "#FFFFFF",
    "sidebar": "#FFFFFF",
    "sidebar_text": "#334155",
    "sidebar_active": "#E3F3F0",
    "hover": "#F1F5F9",
    "selection": "#D9F2EE",
    "table_header": "#F1F5F9",
    "danger": "#DC2626",
    "warning": "#B45309",
    "success": "#047857",
}

PALETTES = {"dark": DARK, "light": LIGHT}

_QSS = Template("""
* { font-family: "Segoe UI", "Tahoma", "Arial"; }

QMainWindow, QDialog { background: $bg; }
QWidget { color: $text; font-size: 10.5pt; }
QLabel { background: transparent; }
QLabel#Title { font-size: 19pt; font-weight: 700; color: $text; }
QLabel#PageTitle { font-size: 16pt; font-weight: 700; color: $text; }
QLabel#Subtitle { color: $muted; font-size: 10pt; }
QLabel#Muted { color: $muted; font-size: 9.5pt; }
QLabel#Chip { background: $surface_alt; border: 1px solid $border; border-radius: 12px;
              padding: 4px 12px; color: $muted; font-size: 9.5pt; }
QLabel#Error { color: $danger; font-size: 9.5pt; }
QLabel#Success { color: $success; font-size: 9.5pt; }
QLabel#Brand { font-size: 13pt; font-weight: 700; color: $text; }
QLabel#Badge { background: $primary; color: $on_primary; border-radius: 18px;
               font-size: 15pt; font-weight: 800; }

QFrame#Sidebar { background: $sidebar; border-left: 1px solid $border; }
QFrame#Card { background: $surface; border: 1px solid $border; border-radius: 12px; }
QFrame#Header { background: $surface; border-bottom: 1px solid $border; }
QFrame#Divider { background: $border; max-height: 1px; min-height: 1px; border: none; }

QPushButton { background: $surface_alt; color: $text; border: 1px solid $border;
              border-radius: 8px; padding: 8px 14px; }
QPushButton:hover { background: $hover; }
QPushButton:pressed { background: $selection; }
QPushButton:disabled { color: $muted; background: $surface_alt; border-color: $border; }
QPushButton#Accent { background: $primary; color: $on_primary; border: none; font-weight: 700; }
QPushButton#Accent:hover { background: $primary_hover; }
QPushButton#Ghost { background: transparent; border: 1px solid $border; color: $text; }
QPushButton#Ghost:hover { background: $hover; }
QPushButton#Danger { background: transparent; color: $danger; border: 1px solid $danger; }
QPushButton#Danger:hover { background: rgba(220, 38, 38, 0.10); }
QPushButton#Nav { background: transparent; color: $sidebar_text; border: none;
                  border-radius: 9px; padding: 11px 8px; text-align: center;
                  font-size: 10.8pt; }
QPushButton#Nav:hover { background: $hover; color: $text; }
QPushButton#Nav:checked { background: $sidebar_active; color: $primary; font-weight: 700; }
QPushButton#Link { background: transparent; border: none; color: $primary; padding: 2px; }

QLineEdit, QComboBox, QSpinBox, QDateEdit, QTextEdit, QPlainTextEdit {
    background: $surface_alt; border: 1px solid $border; border-radius: 8px;
    padding: 7px 10px; selection-background-color: $primary; selection-color: $on_primary;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus, QTextEdit:focus {
    border: 1px solid $primary;
}
QLineEdit:disabled, QComboBox:disabled { color: $muted; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: url("$assets/chevron_down.png"); width: 10px; height: 7px; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border;
                              selection-background-color: $selection; selection-color: $text; }
QSpinBox, QDoubleSpinBox { padding-left: 28px; }
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top left; width: 24px;
    background: transparent; border: none; border-left: 1px solid $border;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom left; width: 24px;
    background: transparent; border: none; border-left: 1px solid $border;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background: $hover; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url("$assets/chevron_up.png"); width: 10px; height: 7px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url("$assets/chevron_down.png"); width: 10px; height: 7px;
}

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid $border;
                       border-radius: 4px; background: $surface_alt; }
QCheckBox::indicator:checked { background: $primary; border-color: $primary;
                               image: url("$assets/check.png"); }

QTableWidget { background: $surface; border: 1px solid $border; border-radius: 10px;
               gridline-color: $border; selection-background-color: $selection;
               alternate-background-color: $surface_alt; }
QTableWidget::item { padding: 6px; border: none; }
QTableWidget::item:selected { background: $selection; color: $text; }
QHeaderView::section { background: $table_header; color: $muted; border: none;
                       border-bottom: 1px solid $border; padding: 8px 6px;
                       font-weight: 700; font-size: 9.5pt; }
QTableCornerButton::section { background: $table_header; border: none; }

QTabWidget::pane { border: 1px solid $border; border-radius: 10px; background: $surface;
                   top: -1px; }
QTabBar::tab { background: transparent; color: $muted; padding: 9px 18px;
               border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: $primary; border-bottom: 2px solid $primary;
                        font-weight: 700; }

QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: $border; border-radius: 6px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: $border; border-radius: 6px; min-width: 30px; }

QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 5px; }
QMessageBox { background: $surface; }
QTextBrowser { background: $surface; border: 1px solid $border; border-radius: 10px; }
QGroupBox { border: 1px solid $border; border-radius: 10px; margin-top: 12px;
            padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; right: 12px; padding: 0 4px; color: $muted; }
""")


def palette(name: str) -> dict:
    return PALETTES.get(name, DARK)


def resolve(name: str) -> str:
    """يحوّل «تلقائي» إلى ثيم النظام الفعلي."""
    if name in PALETTES:
        return name
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            scheme = app.styleHints().colorScheme()
            return "light" if scheme == Qt.ColorScheme.Light else "dark"
    except Exception:  # pragma: no cover - إصدارات Qt الأقدم
        pass
    return "dark"


def stylesheet(name: str, assets_dir: Path | str | None = None) -> str:
    if assets_dir:
        folder = Path(assets_dir)
    else:
        folder = app_root() / "amdh_hr" / "assets"
        if not folder.exists():
            folder = app_root() / "_internal" / "amdh_hr" / "assets"
    return _QSS.substitute(assets=folder.as_posix(), **palette(resolve(name)))


def next_theme(name: str) -> str:
    return "light" if resolve(name) == "dark" else "dark"
