"""İzinsiz uygulama algılandığında gösterilen 5 saniyelik geri sayım uyarısı (WarningToast)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app import config
from app.ui.styles import (
    DANGER_HEX,
    GLOBAL_STYLESHEET,
    apply_window_liquid_glass_effect,
    paint_liquid_glass_surface,
)


class WarningToast(QWidget):
    """Üst çubuğun hemen altında beliren, odak çalmayan 5 sn geri sayım uyarısı."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(GLOBAL_STYLESHEET)
        self.setFixedSize(540, 46)

        apply_window_liquid_glass_effect(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(10)

        self.badge_lbl = QLabel("İZİNSİZ UYGULAMA")
        self.badge_lbl.setStyleSheet(
            f"background-color: rgba(248, 113, 113, 45);"
            f"border: 1px solid {DANGER_HEX};"
            f"border-radius: 6px;"
            f"padding: 2px 8px;"
            f"color: #FECACA;"
            f"font-size: 11px;"
            f"font-weight: 700;"
        )
        layout.addWidget(self.badge_lbl, 0)

        self.msg_lbl = QLabel("")
        self.msg_lbl.setStyleSheet("color: #F8FAFC; font-size: 13px; font-weight: 600;")
        layout.addWidget(self.msg_lbl, 1)

    def update_warnings(self, warnings: list[dict[str, Any]]) -> None:
        if not warnings:
            if self.isVisible():
                self.hide()
            return

        first = warnings[0]
        exe_name = str(first.get("exe_name") or "Uygulama")
        rem = int(first.get("remaining_seconds") or 0)
        stage = str(first.get("stage") or "countdown")

        if stage == "closing" or rem <= 0:
            self.msg_lbl.setText(f"{exe_name} kapatılıyor...")
        else:
            self.msg_lbl.setText(f"{exe_name} izinli listede değil — {rem} sn içinde kapatılacak")

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            sgeom = screen.geometry()
            x = sgeom.x() + (sgeom.width() - self.width()) // 2
            y = sgeom.y() + config.WORK_AREA_TOP_OFFSET + 8
            self.move(x, y)

        if not self.isVisible():
            self.show()
        self.raise_()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        paint_liquid_glass_surface(
            painter,
            QRectF(self.rect()),
            radius=12.0,
            bg_alpha_top=230,
            bg_alpha_bottom=215,
        )
