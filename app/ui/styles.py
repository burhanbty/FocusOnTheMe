"""Liquid Glass görsel dili, DWM Acrylic/Backdrop API sarmalayıcısı ve QSS tema tanımları."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

from app.config import TOP_BAR_RADIUS

# Tek vurgu rengi (Sakin, odak dostu buz mavisi)
ACCENT_HEX = "#38BDF8"
ACCENT_COLOR = QColor(56, 189, 248)
TEXT_PRIMARY = "#F1F5F9"
TEXT_SECONDARY = "#94A3B8"
DANGER_HEX = "#F87171"

# Windows DWM ve Composition sabitleri
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38

DWMWCP_ROUND = 2
DWMSBT_TRANSIENTWINDOW = 3  # Acrylic

WCA_ACCENT_POLICY = 19
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4


class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int),
    ]


class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.POINTER(ACCENT_POLICY)),
        ("SizeOfData", ctypes.c_size_t),
    ]


class MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


def apply_window_liquid_glass_effect(widget: QWidget) -> str:
    """Pencereye sırasıyla:
    1) Windows 11 DWMWA_SYSTEMBACKDROP_TYPE (Acrylic),
    2) SetWindowCompositionAttribute (Acrylic/Blur),
    3) QPainter yarı saydam koyu degrade + 1px üst parlak kenar çizgisi
    uygular. Uygulanan yöntemin adını döndürür.
    """
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    hwnd = int(widget.winId())
    if not hwnd:
        return "qpainter_fallback"

    # Koyu mod özniteliği
    try:
        dwmapi = ctypes.windll.dwmapi
        dark_val = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(dark_val),
            ctypes.sizeof(dark_val),
        )
    except Exception:
        pass

    # 1. Öncelik: Windows 11 DWM System Backdrop (DWMWA_SYSTEMBACKDROP_TYPE = 38)
    try:
        dwmapi = ctypes.windll.dwmapi
        margins = MARGINS(-1, -1, -1, -1)
        dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(margins))

        corner_pref = ctypes.c_int(DWMWCP_ROUND)
        dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(corner_pref),
            ctypes.sizeof(corner_pref),
        )

        backdrop_type = ctypes.c_int(DWMSBT_TRANSIENTWINDOW)
        hr = dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(backdrop_type),
            ctypes.sizeof(backdrop_type),
        )
        if hr == 0:
            return "dwm_systembackdrop_acrylic"
    except Exception:
        pass

    # 2. Öncelik: SetWindowCompositionAttribute (Acrylic Blur)
    try:
        user32 = ctypes.windll.user32
        set_wca = getattr(user32, "SetWindowCompositionAttribute", None)
        if set_wca is not None:
            policy = ACCENT_POLICY()
            policy.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
            policy.AccentFlags = 2
            # ABGR biçiminde yarı saydam koyu cam rengi (A=0xB8, B=0x24, G=0x19, R=0x12)
            policy.GradientColor = 0xB8241912
            policy.AnimationId = 0

            data = WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute = WCA_ACCENT_POLICY
            data.Data = ctypes.pointer(policy)
            data.SizeOfData = ctypes.sizeof(policy)

            res = set_wca(wintypes.HWND(hwnd), ctypes.byref(data))
            if res:
                return "wca_acrylic"
    except Exception:
        pass

    # 3. Öncelik: QPainter yarı saydam koyu degrade + 1px üst parlak kenar çizgisi
    return "qpainter_fallback"


def paint_liquid_glass_surface(
    painter: QPainter,
    rect: QRectF,
    radius: float = float(TOP_BAR_RADIUS),
    bg_alpha_top: int = 212,
    bg_alpha_bottom: int = 196,
) -> None:
    """Liquid Glass yüzeyini çizer:
    - 14 px köşe yuvarlaklığı
    - Yarı saydam koyu degrade
    - İnce açık kenarlık (rgba 255, 255, 255, 0.18)
    - 1 px üst parlak kenar çizgisi (specular highlight)
    """
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    inner = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    path = QPainterPath()
    path.addRoundedRect(inner, radius, radius)

    # Koyu yarı saydam cam degradesi
    grad = QLinearGradient(inner.topLeft(), inner.bottomLeft())
    grad.setColorAt(0.0, QColor(24, 32, 48, bg_alpha_top))
    grad.setColorAt(0.5, QColor(17, 23, 35, int((bg_alpha_top + bg_alpha_bottom) / 2)))
    grad.setColorAt(1.0, QColor(12, 17, 27, bg_alpha_bottom))

    painter.fillPath(path, grad)

    # İnce açık kenarlık: rgba(255, 255, 255, 0.18) -> alpha ~46
    border_pen = QPen(QColor(255, 255, 255, 46), 1.0)
    painter.setPen(border_pen)
    painter.drawPath(path)

    # 1 px üst parlak kenar çizgisi (liquid glass specular highlight)
    highlight_pen = QPen(QColor(255, 255, 255, 82), 1.0)
    painter.setPen(highlight_pen)
    x1 = inner.left() + radius * 0.75
    x2 = inner.right() - radius * 0.75
    y_top = inner.top() + 0.6
    if x2 > x1:
        painter.drawLine(int(x1), int(y_top), int(x2), int(y_top))

    painter.restore()


def get_app_font(size: int = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Segoe UI Variable (yoksa Segoe UI) yazı tipini döndürür."""
    font = QFont("Segoe UI Variable Text", size)
    if not font.exactMatch():
        font = QFont("Segoe UI Variable", size)
    if not font.exactMatch():
        font = QFont("Segoe UI", size)
    font.setWeight(weight)
    return font


GLOBAL_STYLESHEET: str = f"""
QWidget {{
    font-family: "Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", sans-serif;
    color: {TEXT_PRIMARY};
    font-size: 13px;
}}

QLineEdit, QSpinBox, QTextEdit {{
    background-color: rgba(15, 23, 36, 200);
    border: 1px solid rgba(255, 255, 255, 46);
    border-radius: 10px;
    padding: 7px 11px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT_HEX};
}}

QLineEdit:focus, QSpinBox:focus, QTextEdit:focus {{
    border: 1px solid {ACCENT_HEX};
}}

QPushButton {{
    background-color: rgba(255, 255, 255, 16);
    border: 1px solid rgba(255, 255, 255, 42);
    border-radius: 9px;
    padding: 6px 13px;
    color: {TEXT_PRIMARY};
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: rgba(255, 255, 255, 28);
    border: 1px solid rgba(255, 255, 255, 70);
}}

QPushButton:pressed {{
    background-color: rgba(56, 189, 248, 45);
}}

QPushButton:disabled {{
    background-color: rgba(255, 255, 255, 8);
    color: rgba(148, 163, 184, 100);
    border: 1px solid rgba(255, 255, 255, 18);
}}

QPushButton# PrimaryAccentButton {{
    background-color: rgba(56, 189, 248, 48);
    border: 1px solid rgba(56, 189, 248, 140);
    color: #F8FAFC;
    font-weight: 600;
}}

QPushButton#PrimaryAccentButton:hover {{
    background-color: rgba(56, 189, 248, 72);
}}

QPushButton#DangerButton {{
    background-color: rgba(248, 113, 113, 28);
    border: 1px solid rgba(248, 113, 113, 95);
    color: #FECACA;
}}

QPushButton#DangerButton:hover {{
    background-color: rgba(248, 113, 113, 50);
}}

QCheckBox {{
    spacing: 8px;
    color: {TEXT_PRIMARY};
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid rgba(255, 255, 255, 65);
    background-color: rgba(15, 23, 36, 180);
}}

QCheckBox::indicator:checked {{
    background-color: {ACCENT_HEX};
    border: 1px solid {ACCENT_HEX};
}}

QListWidget {{
    background-color: rgba(12, 18, 28, 175);
    border: 1px solid rgba(255, 255, 255, 38);
    border-radius: 10px;
    padding: 4px;
    outline: none;
}}

QListWidget::item {{
    padding: 7px 10px;
    border-radius: 7px;
    margin-bottom: 2px;
}}

QListWidget::item:selected {{
    background-color: rgba(56, 189, 248, 42);
    color: #FFFFFF;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 7px;
    margin: 2px;
}}

QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 55);
    min-height: 24px;
    border-radius: 3px;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""
