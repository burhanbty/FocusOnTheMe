"""Düşünce Park Alanı (Ctrl+Alt+P) hızlı not kutusu (ThoughtModal).

Çalışırken akla gelen dikkat dağıtıcı düşünceleri hızlıca dışsallaştırıp
ders sonuna park etmek için kullanılır. Enter'a basınca kaydedilir ve kapanır.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QGuiApplication, QKeyEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import POPOVER_FADE_MS, TOP_BAR_RADIUS
from app.ui.styles import (
    ACCENT_HEX,
    GLOBAL_STYLESHEET,
    TEXT_SECONDARY,
    apply_window_liquid_glass_effect,
    paint_liquid_glass_surface,
)


class ThoughtModal(QWidget):
    """Ctrl+Alt+P veya üst çubuk butonu ile açılan küçük Liquid Glass düşünce park kutusu."""

    thought_submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Düşünce Park Alanı")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(GLOBAL_STYLESHEET)
        self.setFixedSize(480, 128)

        apply_window_liquid_glass_effect(self)

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(min(120, POPOVER_FADE_MS))
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 14, 18, 14)
        root_layout.setSpacing(8)

        top_row = QHBoxLayout()
        title_lbl = QLabel("Düşünce Park Alanı")
        title_lbl.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {ACCENT_HEX};")
        hint_lbl = QLabel("Enter: Kaydet ve Kapat  •  Esc: İptal")
        hint_lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        top_row.addWidget(title_lbl)
        top_row.addStretch()
        top_row.addWidget(hint_lbl)
        root_layout.addLayout(top_row)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Aklınıza takılan düşünceyi yazın (ders bitince listelenecek)...")
        self.input_edit.returnPressed.connect(self._submit)
        input_row.addWidget(self.input_edit, 1)

        self.save_btn = QPushButton("Park Et")
        self.save_btn.setObjectName("PrimaryAccentButton")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self._submit)
        input_row.addWidget(self.save_btn)
        root_layout.addLayout(input_row)

        sub_lbl = QLabel("Park edilen düşünceler dikkatinizi dağıtmamak için gün sonunda gösterilir.")
        sub_lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        root_layout.addWidget(sub_lbl)

    def open_modal(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            sgeom = screen.geometry()
            x = sgeom.x() + (sgeom.width() - self.width()) // 2
            y = sgeom.y() + int(sgeom.height() * 0.22)
            self.move(x, y)

        self.input_edit.clear()
        self._fade_anim.stop()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        self.input_edit.setFocus()
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def _submit(self) -> None:
        text = self.input_edit.text().strip()
        if text:
            self.thought_submitted.emit(text)
        self.input_edit.clear()
        self.hide()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.input_edit.clear()
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        paint_liquid_glass_surface(
            painter,
            QRectF(self.rect()),
            radius=float(TOP_BAR_RADIUS),
            bg_alpha_top=228,
            bg_alpha_bottom=214,
        )
